# Isaac Agent Orchestrator — NemoClaw agent package

A **replication of the Hermes agent architecture** (`~/.nemoclaw/source/agents/hermes/`)
for this repo's 4-layer Isaac Sim/Lab orchestrator. Hermes is how NemoClaw
packages a third-party agent (Nous Research) as a first-class, deployable,
network-isolated sandbox agent. This package does the same for the orchestrator,
so it can be stamped out / replicated the same way.

## What "Hermes architecture" is

A NemoClaw agent is a directory under `agents/<name>/` declaring an **integration
contract** with the sandbox runtime. The control plane is:

```
onboard → build sandbox image → run sandbox (OpenShell gateway + L7 proxy)
        → gateway service (health-probed) → exec / skills → snapshot / rebuild
```

The agent itself is defined by a handful of declarative files. The runtime gives
it: an isolated OpenShell container, a gateway running as a separate user, an L7
egress proxy that enforces a deny-by-default network policy, gateway-token auth,
and host-side state snapshots.

## File-by-file mapping (Hermes → this agent)

| Hermes file (`agents/hermes/`) | This package | Role |
|---|---|---|
| `manifest.yaml` | `manifest.yaml` | **Integration contract** — binary, health probe, config dir, state dirs, auth, inference, phone-home hosts, package registry |
| `start.sh` | `start.sh` | Sandbox entrypoint — launches the always-on gateway service (here: the Gradio dashboard on :7860) |
| `policy-additions.yaml` | `policy-additions.yaml` | Deny-by-default network egress allowlist (here: Anthropic + NVIDIA NIM + Omniverse assets + PyPI) |
| `plugin/plugin.yaml` | `plugin/plugin.yaml` | In-sandbox tools/hooks the host agent can call |
| `nemoclaw-blueprint/blueprint.yaml` | `blueprint.yaml` | **Replication artifact** — sandbox image + inference profiles + policy; validates against `schemas/blueprint.schema.json` |

### What changed from Hermes (and why)

- **Service**: Hermes exposes an OpenAI-compatible API on :8642; this agent
  exposes a **Gradio web UI on :7860** (`manifest.dashboard.kind: ui`).
- **Binary**: Hermes is one installed binary; this agent is this repo's Python
  package run from its isolated `.venv` (gradio deps conflict with base lerobot).
- **Inference**: the orchestrator doesn't call inference directly — each layer
  runs through a pluggable backend (`sdk` / `openclaw` / `nemoclaw` / `dryrun`),
  reflected in `manifest.inference.provider_options` and the blueprint's 3
  profiles (`default` NVIDIA, `nim-local`, `claude`).
- **Egress**: Anthropic (`/v1/messages`), NVIDIA NIM, and the Omniverse content
  server (L1 resolves `{ISAAC_NUCLEUS_DIR}` assets) — instead of Nous Research +
  messaging-platform hosts.
- **Messaging**: none — this agent is driven by the dashboard/CLI, not chat.
- **State**: mirrors `WORKSPACE_DIR` (`generated/{rl,il,scene}`, `runs`,
  `datasets`, `logs`) so generated scripts and runs survive a rebuild.

## Replicate / deploy

The blueprint is the unit of replication. To stamp this agent out as a sandbox:

```bash
# 1. Validate the blueprint against NVIDIA's schema
python3 - <<'PY'
import json, yaml, jsonschema
s = json.load(open("/home/dgx-destro/.nemoclaw/source/schemas/blueprint.schema.json"))
jsonschema.validate(yaml.safe_load(open("blueprint.yaml")), s); print("ok")
PY

# 2. Deploy the control skill into a sandbox (separate from this package)
agent_orchestrator/nemoclaw/install_skill.sh <sandbox>

# 3. Mount the repo into the sandbox so $ORCHESTRATOR_DIR resolves
nemoclaw <sandbox> share mount /home/dgx-destro/warehouse_nemoclaw /sandbox/warehouse_nemoclaw

# 4. The sandbox runs start.sh as its gateway service; health-probe :7860
nemoclaw <sandbox> exec -- bash agent_orchestrator/nemoclaw/agent/isaac-orchestrator/start.sh
```

> The runtime hardening in Hermes' `start.sh` (gateway-user separation,
> config-hash verification, Landlock) is provided by NemoClaw's
> `sandbox-init.sh`; this package's `start.sh` is the thin service-launch step
> that runs after it. Pin `components.sandbox.image` to a digest at release time
> (see `nemoclaw-blueprint/blueprint.yaml`).
