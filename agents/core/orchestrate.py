"""The orchestration loop: classify → run a worker layer → let the Master
Supervisor (Atlas, L0) validate it → accept / retry / reroute.

`orchestrate()` is an async generator that mutates the shared OrchestratorState
and yields after each event so the Gradio UI can re-render live.

Control flow per worker turn:
  1. run the worker layer (L1-L4) and collect its output + any @@REROUTE it asks for
  2. Atlas validates that output (deterministic Isaac/Lab checks + optional LLM)
  3. act on the verdict:
       PASS/WARN    → accept; follow the worker's own reroute if it emitted one
       FAIL+retry   → re-run the SAME layer with Atlas's reason as feedback
       FAIL+reroute → hand off to the layer Atlas says owns the fix
Retries are bounded by `max_retries` (per layer) and reroutes by `max_hops`.
"""
from __future__ import annotations

from typing import AsyncIterator

from . import router, state as state_mod
from .config import SETTINGS
from .runner import get_executor, Event
from .validator import Supervisor, FAIL, WARN, PASS, RETRY, REROUTE


def _supervisor_status(verdict) -> str:
    return {PASS: state_mod.STATUS_PASS, WARN: state_mod.STATUS_WARN,
            FAIL: state_mod.STATUS_FAIL}.get(verdict.status, state_mod.STATUS_DONE)


async def orchestrate(
    command: str,
    state: state_mod.OrchestratorState,
    *,
    dry_run: bool,
    allow_execution: bool = True,
    forced_layer: int | None = None,
    backend: str | None = None,
    max_hops: int | None = None,
    supervise: bool | None = None,
    max_retries: int | None = None,
) -> AsyncIterator[Event]:
    executor = get_executor(dry_run, allow_execution=allow_execution, backend=backend)
    if max_hops is None:
        max_hops = SETTINGS.max_hops
    supervise = SETTINGS.supervise_default if supervise is None else supervise
    max_retries = SETTINGS.max_retries if max_retries is None else max_retries
    backend_name = "dryrun" if dry_run else (backend or SETTINGS.backend or "sdk").lower()
    # Atlas only calls the model when it can (real backend + LLM enabled).
    use_llm = supervise and SETTINGS.supervisor_use_llm and not dry_run
    supervisor = Supervisor()

    # Initial routing → Atlas (L0) dispatches to the entry worker.
    if forced_layer:
        layer = forced_layer
        state.append_log(f"▶ command: {command!r}  (forced → L{layer})")
    else:
        routing = router.classify(command, default_layer=SETTINGS.default_layer)
        layer = routing.layer
        state.append_log(f"▶ command: {command!r}")
        state.append_log("  " + routing.explain())
    if supervise:
        state.append_log("  🛰️ Master (L0) conducting"
                         + ("" if use_llm else " — deterministic only"))
        if not forced_layer:
            state.set_status(0, state_mod.STATUS_VALIDATING, command="dispatch",
                             detail="picking entry worker…")
            async for dev in supervisor.dispatch(command, routing, llm=use_llm,
                                                 executor=executor):
                if dev.kind == "dispatch":
                    layer = dev.payload.target_layer
                    state.set_status(0, state_mod.STATUS_VALIDATING,
                                     command="dispatch", detail=dev.payload.one_line())
                    state.append_log(f"  🛰️ Master dispatch: {dev.payload.one_line()}")
                elif dev.kind in ("tool", "text"):
                    state.append_log(f"  🛰️ {dev.text.strip()[:240]}")
                yield dev

    layer_base = command       # the canonical task for the current layer
    current_command = command  # what we feed the executor (may carry feedback)
    hops = 0                   # reroutes followed
    retries = 0                # retries of the CURRENT layer
    visited: list[int] = []
    max_iter = max_hops + (max_retries + 1) * 4 + 2  # safety bound on the loop

    for _ in range(max_iter):
        visited.append(layer)
        state.reset_idle(exclude=0)  # keep Atlas's last verdict on its panel
        state.set_status(layer, state_mod.STATUS_RUNNING, command=current_command,
                         detail="working…")
        _key, title, _ = router.LAYERS[layer]
        attempt = f" (retry {retries})" if retries else ""
        state.append_log(f"  ┌ L{layer} {title}{attempt} ◂ {current_command!r}")

        worker_reroute: tuple[str, str] | None = None
        final_text = ""
        async for ev in executor.run(layer, current_command):
            if ev.kind == "text":
                final_text = ev.text
                snippet = ev.text.strip().replace("\n", " ")
                if snippet:
                    state.append_log(f"  │ {snippet[:300]}")
                state.set_status(layer, state_mod.STATUS_RUNNING,
                                 detail=ev.text[-600:])
            elif ev.kind == "tool":
                state.append_log(f"  │ {ev.text}")
            elif ev.kind == "reroute":
                tgt = router.resolve_reroute(ev.target)
                if tgt and tgt != layer:
                    worker_reroute = (ev.target, ev.text)
                    state.append_log(f"  ├ ↪ worker reroute → {ev.target}: {ev.text}")
            elif ev.kind == "result":
                cost = f"  (${ev.cost_usd:.4f})" if ev.cost_usd else ""
                state.append_log(f"  └ L{layer} done{cost}")
            elif ev.kind == "error":
                state.set_status(layer, state_mod.STATUS_ERROR, detail=ev.text)
                state.append_log(f"  ✗ L{layer} error: {ev.text}")
            yield ev

        # ---- Master Supervisor (Atlas / L0) validates this layer -------------
        verdict = None
        if supervise:
            state.set_status(0, state_mod.STATUS_VALIDATING,
                             command=f"validate L{layer}", detail="inspecting output…")
            async for sev in supervisor.validate(
                layer, layer_base, final_text,
                llm=use_llm, executor=executor, backend=backend_name,
            ):
                if sev.kind == "verdict":
                    verdict = sev.payload
                elif sev.kind == "tool":
                    state.append_log(f"  🛰️ {sev.text}")
                elif sev.kind == "text":
                    state.append_log(f"  🛰️ {sev.text.strip()[:240]}")
                yield sev
            if verdict is not None:
                state.set_status(0, _supervisor_status(verdict),
                                 detail=verdict.one_line())
                state.append_log(f"  🛰️ Master: {verdict.one_line()}")

        # ---- Act on the verdict ---------------------------------------------
        # 1) FAIL + retry → re-run the same layer with Atlas's reason as feedback.
        if (verdict and verdict.status == FAIL and verdict.action == RETRY
                and retries < max_retries):
            retries += 1
            state.set_status(layer, state_mod.STATUS_REROUTED,
                             detail=f"↻ retry {retries}: {verdict.message}")
            state.append_log(f"  ↻ L{layer} retry {retries}/{max_retries}: "
                             f"{verdict.message}")
            current_command = (
                f"{layer_base}\n\n[Master REJECTED the previous "
                f"attempt — fix and redo]\nReason: {verdict.message}\n"
                f"Failed checks: {verdict.failed_summary()}\n"
                f"Previous output tail:\n{final_text[-800:]}"
            )
            continue

        # 2) Decide a reroute target: Atlas's verdict wins, else the worker's own.
        reroute_target_key: str | None = None
        reroute_reason = ""
        if verdict and verdict.action == REROUTE and verdict.target:
            reroute_target_key, reroute_reason = verdict.target, verdict.message
        elif worker_reroute and (verdict is None or verdict.ok):
            reroute_target_key, reroute_reason = worker_reroute

        tgt_layer = (router.resolve_reroute(reroute_target_key)
                     if reroute_target_key else None)
        if tgt_layer and tgt_layer != layer and hops < max_hops:
            src = layer
            state.set_status(layer, state_mod.STATUS_REROUTED,
                             detail=f"↪ {reroute_target_key}: {reroute_reason}")
            state.append_log(f"  ├ ↪ reroute → {reroute_target_key}: {reroute_reason}")
            hops += 1
            retries = 0
            layer = tgt_layer
            layer_base = (
                f"{reroute_reason}\n\n(Context from L{src}: original command was: "
                f"{command!r}. Previous layer output tail:\n{final_text[-800:]})"
            )
            current_command = layer_base
            continue

        # 3) Otherwise this layer is the end of the line.
        end_status = state_mod.STATUS_DONE
        if verdict and verdict.status == FAIL:
            end_status = state_mod.STATUS_ERROR
            if retries >= max_retries:
                state.append_log(f"  ! L{layer} still failing after "
                                 f"{max_retries} retries; stopping.")
        elif hops >= max_hops and (worker_reroute or (verdict and verdict.action == REROUTE)):
            state.append_log(f"  ! max reroute hops ({max_hops}) reached; stopping.")
        state.set_status(layer, end_status, detail=final_text[-600:])
        break
    else:
        state.append_log(f"  ! loop bound ({max_iter}) reached; stopping.")

    state.append_log(f"■ finished. path: {' → '.join(f'L{l}' for l in visited)}")
