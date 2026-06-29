# sandbox — network policies + sandbox-side clients

Everything the NemoClaw/OpenClaw **sandbox** needs to reach the host and drive
Isaac. The host runs the [Isaac Control Server](../isaac_sim/scripts/isaac_control_server.py)
(port 5561); the sandbox runs these thin clients, and the **policies** decide
what egress is allowed (deny-by-default).

## clients/  — installed into the sandbox PATH (`/sandbox/bin`)
| Client | Talks to | Purpose |
|---|---|---|
| `isaaclab-train` | `:5561` REST | list envs / start / status / stop / logs for RL training |
| `isaaclab-send` | `:5560` `/command` | send one JSON delta-pose command to the SO101 arm |
| `isaaclab-pick` | `:5560` | compound: down → close gripper → up |
| `isaaclab-place` | `:5560` | compound: down → open gripper → up |
| `isaaclab-detect` | `:5560` `/detect` | fetch YOLO detections (orange positions, recommended move) |

> Migration note: `isaaclab-train` is the locomotion-training client; the
> `isaaclab-send/pick/place/detect` set is the SO101 manipulation client. The
> generalized control server now also exposes `/sim/launch`, `/scene/load`,
> `/robot/spawn`, `/play`, `/eval` — extend the clients (or just `curl`) to use
> them. They are kept as-is so existing skills keep working.

## policies/ — network egress allowlists (OpenShell / NemoClaw)
| Policy | Whitelists |
|---|---|
| `isaaclab-training-policy.yaml` | `host.openshell.internal:5561` GET/POST — the control server |
| `orchestrator-policy-additions.yaml` | Anthropic + NVIDIA NIM + PyPI + Omniverse for the orchestrator agent |

The leisaac ZMQ/vision policy (ports 5557–5560) is generated inline by the
launch scripts in the source repo; if you wire teleop through the sandbox, add an
equivalent allowlist here for 5557–5560.

## Ports (single source of truth)
| Port | Server | Direction |
|---|---|---|
| 5561 | Isaac Control Server (train/sim/scene/robot) | sandbox → host |
| 5560 | leisaac HTTP bridge (`/command`, `/detect`) | sandbox → host |
| 5557/5558 | leisaac ZMQ device cmd / status | sandbox ↔ host |
| 5559 | leisaac YOLO vision PUB | host internal |
| 8226 | isaacsim.code_editor.python_server (in-sim exec) | control server → running sim |
