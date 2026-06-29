# isaac_lab/scripts — canonical entrypoints

Stable, model-friendly names. Each forwards to the real (framework-specific or
leisaac) script so skills and the control server can rely on one name.

| Canonical | Forwards to | Notes |
|---|---|---|
| `train.py` | `reinforcement_learning/<backend>/train.py` | `--backend rsl_rl\|cusrl\|skrl` (default rsl_rl) |
| `play.py` | `reinforcement_learning/<backend>/play.py` | watch a trained policy; `--checkpoint` |
| `eval.py` | `reinforcement_learning/<backend>/play.py` | evaluation == play with a checkpoint |
| `teleop.py` | `leisaac/environments/teleoperation/teleop_se3_agent.py` | `--teleop_device`, `--record` |
| `annotate.py` | `leisaac/mimic/annotate_demos.py` | label recorded demos |
| `inference.py` | `leisaac/evaluation/policy_inference.py` | LeRobot/GR00T/OpenPI policy inference |

Underlying trees (unchanged from source repos):
- `reinforcement_learning/{rsl_rl,cusrl,skrl}/` — RL train/play + `cli_args.py`
- `tools/` — `training_server.py` (legacy; superseded by
  `../../isaac_sim/scripts/isaac_control_server.py`), `list_envs.py`, converters
- `leisaac/` — teleop, mimic (annotate/generate), convert (hdf5↔lerobot), evaluation

Hyperparameters for any backend: [`../../policies/policy_skill.md`](../../policies/policy_skill.md).
