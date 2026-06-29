"""Gradio dashboard to orchestrate the 4-layer Isaac Sim / Isaac Lab agents.

Run:  python -m agent_orchestrator.app   (or  python agent_orchestrator/app.py)
"""
from __future__ import annotations

import asyncio
import warnings

# gradio 6 + starlette 1.x emit a StarletteDeprecationWarning on every request
# (HTTP_422_UNPROCESSABLE_ENTITY → ..._CONTENT). It's harmless; silence the flood.
warnings.filterwarnings("ignore", message=r".*HTTP_422_UNPROCESSABLE_ENTITY.*")
warnings.filterwarnings("ignore", message=r".*UNPROCESSABLE_ENTITY.*deprecated.*")

import gradio as gr

from . import catalog, router
from .config import SETTINGS
from .state import OrchestratorState

from .orchestrate import orchestrate

STATE = OrchestratorState()

FORCE_CHOICES = ["auto-route"] + [f"L{n} · {t}" for n, (_k, t, _a) in router.LAYERS.items()]
_LAYER_COLOR = {1: "#a78bfa", 2: "#34d399", 3: "#f472b6", 4: "#fbbf24"}

CSS = """
.gradio-container{max-width:1380px !important;}
#orch-hero{background:linear-gradient(120deg,#0f172a,#1e1b4b 55%,#312e81);
 border:1px solid #4338ca;border-radius:18px;padding:20px 26px;margin-bottom:4px;}
#orch-hero h1{margin:0;font-size:1.7rem;color:#ede9fe;letter-spacing:.3px;}
#orch-hero p{margin:7px 0 0;color:#a5b4fc;font-size:.92rem;}
#orch-hero .lp{display:inline-block;margin-top:12px;margin-right:8px;font-size:.74rem;
 padding:3px 11px;border-radius:999px;border:1px solid #4f46e5;color:#c7d2fe;background:#4338ca22;}
.route-bar{display:flex;gap:14px;align-items:center;flex-wrap:wrap;
 border:1px solid #334155;border-radius:12px;padding:10px 14px;font-size:.85rem;}
.route-idle{color:#64748b;}
.route-chip{font-weight:700;padding:3px 12px;border-radius:999px;font-size:.82rem;}
.route-why{color:#cbd5e1;}
.route-scores{color:#64748b;font-family:ui-monospace,monospace;margin-left:auto;}
.layer-card{border-radius:14px;padding:14px 16px;min-height:140px;border:1px solid #334155;
 background:linear-gradient(180deg,#0b1220,#0e1526);transition:all .25s ease;}
.layer-card .lc-title{font-weight:600;font-size:.92rem;color:#e2e8f0;display:flex;align-items:center;gap:8px;}
.layer-card .lc-badge{font-size:.74rem;padding:2px 10px;border-radius:999px;display:inline-block;margin-top:10px;font-weight:600;}
.layer-card .lc-cmd{font-family:ui-monospace,monospace;font-size:.72rem;color:#64748b;margin-top:10px;word-break:break-word;}
.layer-card .lc-detail{font-size:.76rem;color:#94a3b8;margin-top:8px;max-height:98px;overflow:auto;white-space:pre-wrap;}
.dot{height:10px;width:10px;border-radius:50%;display:inline-block;flex:none;}
.st-running{border-color:#22c55e;box-shadow:0 0 0 1px #22c55e33,0 0 26px #22c55e1f;}
.st-done{border-color:#16a34a;}
.st-error{border-color:#ef4444;box-shadow:0 0 0 1px #ef444433;}
.st-rerouted{border-color:#3b82f6;}
.pulse{animation:pulse 1.1s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
#orch-log textarea{font-family:ui-monospace,Menlo,monospace !important;font-size:.78rem !important;
 background:#0b1220 !important;color:#cbd5e1 !important;line-height:1.45 !important;}
.cat-stats{color:#94a3b8;font-size:.84rem;margin:2px 0 6px;}
.cat-stats b{color:#c7d2fe;}
"""


def _forced_from_choice(choice: str) -> int | None:
    if not choice or choice.startswith("auto"):
        return None
    return int(choice[1])


def _render():
    return (
        STATE.panel_html(0),
        STATE.panel_html(1), STATE.panel_html(2),
        STATE.panel_html(3), STATE.panel_html(4),
        STATE.log_text(),
    )


def _route_badge(layer: int, title: str, matched, scores) -> str:
    col = _LAYER_COLOR.get(layer, "#94a3b8")
    why = ", ".join(matched) if matched else "no strong keywords → default"
    sc = " ".join(f"L{l}:{s:.1f}" for l, s in sorted(scores.items(), key=lambda x: -x[1]) if s > 0)
    return (
        f'<div class="route-bar" style="border-color:{col}66;background:{col}14">'
        f'<span class="route-chip" style="background:{col};color:#0b1220">→ L{layer} · {title}</span>'
        f'<span class="route-why">matched: {why}</span>'
        f'<span class="route-scores">{sc}</span></div>'
    )


def _routing_preview(command: str) -> str:
    if not command.strip():
        return ('<div class="route-bar route-idle">⌨️  Type a command — the '
                'router previews which layer it goes to, live.</div>')
    r = router.classify(command)
    return _route_badge(r.layer, r.title, r.matched, r.scores)


_BACKEND_MAP = {
    "Dry-run (no API)": "dryrun",
    "Claude Agent SDK": "sdk",
    "OpenClaw runtime": "openclaw",
    "NemoClaw sandbox": "nemoclaw",
}
# Seed the UI's default backend from orchestrator.yaml (runtime.backend).
_LABEL_BY_BACKEND = {v: k for k, v in _BACKEND_MAP.items()}
_DEFAULT_BACKEND_LABEL = _LABEL_BY_BACKEND.get(
    SETTINGS.backend or "dryrun", "Dry-run (no API)")


async def on_run(command, force_choice, backend_choice, allow_exec, supervise):
    command = (command or "").strip()
    if not command:
        yield (_routing_preview(""), *_render())
        return
    backend = _BACKEND_MAP.get(backend_choice, "sdk")
    dry_run = backend == "dryrun"
    forced = _forced_from_choice(force_choice)
    if forced is None:
        head = _routing_preview(command)
    else:
        col = _LAYER_COLOR.get(forced, "#94a3b8")
        head = (f'<div class="route-bar" style="border-color:{col}66;background:{col}14">'
                f'<span class="route-chip" style="background:{col};color:#0b1220">'
                f'→ forced {force_choice}</span></div>')
    yield (head, *_render())

    # Long agent turns (SDK/OpenClaw) leave gaps between events; without a yield
    # the browser's SSE stream goes idle and reports "connection lost". Run the
    # orchestration in a background task and drain it with a periodic heartbeat
    # so the UI keeps refreshing even while the agent is thinking.
    queue: asyncio.Queue = asyncio.Queue()

    async def _produce():
        try:
            async for _ev in orchestrate(
                command, STATE, dry_run=dry_run, allow_execution=allow_exec,
                forced_layer=forced, backend=backend, supervise=supervise,
            ):
                await queue.put(True)
        except Exception as e:  # surface, don't kill the UI
            STATE.append_log(f"✗ orchestrator crashed: {type(e).__name__}: {e}")
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(_produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.5)
            except asyncio.TimeoutError:
                yield (head, *_render())  # heartbeat keeps SSE warm
                continue
            if item is None:
                break
            yield (head, *_render())
    finally:
        if not task.done():
            task.cancel()
    yield (head, *_render())


def _catalog_rows(category, search):
    if search and search.strip():
        ents = catalog.find(search, n=50)
        if category and category != "all":
            ents = [e for e in ents if e.category == category]
    else:
        ents = catalog.entries(None if category in (None, "all") else category)
    return [
        [e.name, e.category, ", ".join(e.attrs.get("tags", [])), e.usd]
        for e in ents
    ]


def _catalog_stats() -> str:
    parts = [f"<b>{len(catalog.entries())}</b> assets"]
    for c in catalog.categories():
        parts.append(f"{c}: <b>{len(catalog.entries(c))}</b>")
    return '<div class="cat-stats">' + "  ·  ".join(parts) + "</div>"


HERO = """
<div id="orch-hero">
  <h1>🤖 Isaac Sim / Lab — Multi-Layer Robot Orchestration</h1>
  <p>One command → routed to the right slave agent · the <b>Master Agent</b>
     validates every slave's execution and retries / reroutes on failure.</p>
  <span class="lp">🛰️ L0 Isaac Robot Orchestrator · Master</span>
  <span class="lp">📦 L1 Asset Placement</span>
  <span class="lp">🧠 L2 RL Authoring</span>
  <span class="lp">🎭 L3 Imitation Learning</span>
  <span class="lp">⚙️ L4 Execution + reroute</span>
</div>
"""

EXAMPLES = [
    ["place 6 nova carters in the warehouse aisle"],
    ["import the unitree g1 humanoid into warehouse_local"],
    ["write a PPO reward to balance the cartpole"],
    ["create a lerobot behavior-cloning task for the franka"],
    ["train the franka lift task for 500 iterations headless"],
    ["collect a teleop dataset by recording demos"],
]


def build():
    with gr.Blocks(title="Isaac Agent Orchestrator") as demo:
        gr.HTML(HERO)
        with gr.Accordion("⚙️ Environment contract", open=False):
            gr.Code(SETTINGS.summary(), label="resolved paths")

        with gr.Tab("🚀 Orchestrator"):
            command = gr.Textbox(
                label="Command", lines=2, autofocus=True,
                placeholder="e.g. place 6 nova carters in the warehouse aisle  ·  "
                            "write a PPO reward to balance the cartpole  ·  "
                            "train the franka lift task for 500 iterations",
            )
            with gr.Row():
                force = gr.Dropdown(FORCE_CHOICES, value="auto-route",
                                    label="Layer", scale=2)
                backend = gr.Dropdown(
                    ["Dry-run (no API)", "Claude Agent SDK", "OpenClaw runtime",
                     "NemoClaw sandbox"],
                    value=_DEFAULT_BACKEND_LABEL, label="Backend", scale=2)
                allow_exec = gr.Checkbox(
                    SETTINGS.allow_execution_default, label="Allow L4 exec (Bash)",
                    scale=1)
                supervise = gr.Checkbox(
                    SETTINGS.supervise_default, label="🛰️ Master supervise",
                    scale=1)
                run = gr.Button("Dispatch ▶", variant="primary", scale=1, size="lg")
            routing = gr.HTML(_routing_preview(""))
            gr.Examples(EXAMPLES, inputs=[command], label="Try one →")

            gr.Markdown("#### 🛰️ Master Supervisor")
            with gr.Row():
                p0 = gr.HTML(STATE.panel_html(0))
            gr.Markdown("#### Worker layers")
            with gr.Row():
                p1 = gr.HTML(STATE.panel_html(1))
                p2 = gr.HTML(STATE.panel_html(2))
                p3 = gr.HTML(STATE.panel_html(3))
                p4 = gr.HTML(STATE.panel_html(4))
            log = gr.Textbox(label="📜 Orchestration log", lines=16, max_lines=16,
                             autoscroll=True, elem_id="orch-log")

            outs = [routing, p0, p1, p2, p3, p4, log]
            inputs = [command, force, backend, allow_exec, supervise]
            command.change(_routing_preview, command, routing)
            run.click(on_run, inputs, outs)
            command.submit(on_run, inputs, outs)

        with gr.Tab("📦 Asset Catalog (L1 store)"):
            gr.Markdown(
                "Common categorized asset store the **Layer-1 placement agent** "
                "resolves names from. Edit `agent_orchestrator/assets/catalog.yaml` "
                "to extend it.")
            gr.HTML(_catalog_stats())
            with gr.Row():
                cat = gr.Dropdown(["all"] + catalog.categories(), value="all",
                                  label="Category")
                search = gr.Textbox(label="Search (name / tag)", scale=2,
                                    placeholder="humanoid · arm · warehouse · lidar")
            table = gr.Dataframe(
                headers=["name", "category", "tags", "usd"],
                value=_catalog_rows("all", ""), wrap=True, interactive=False,
                column_widths=["18%", "13%", "29%", "40%"],
            )
            cat.change(_catalog_rows, [cat, search], table)
            search.change(_catalog_rows, [cat, search], table)

        gr.Markdown(
            "L4 reroutes to **L2** (RL), **L3** (IL), or **L1** (USD/articulation) "
            "as the task demands · backends: Dry-run · Claude Agent SDK · OpenClaw "
            "· NemoClaw")
    return demo


def main():
    # Belt-and-suspenders: also silence by category in case filters get reset.
    try:
        from starlette.exceptions import StarletteDeprecationWarning
        warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
    except Exception:
        warnings.filterwarnings("ignore", message=r".*UNPROCESSABLE_ENTITY.*")
    SETTINGS.ensure_workspace()
    build().queue().launch(
        server_name="0.0.0.0", server_port=7860, show_error=True,
        css=CSS, theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="violet"),
    )


if __name__ == "__main__":
    main()
