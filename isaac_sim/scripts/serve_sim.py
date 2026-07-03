"""Persistent headless Isaac Sim for isaac-claw.

Unlike launch_warehouse.py (a one-shot that screenshots then exits), this one:
  1. boots a headless Isaac Sim,
  2. enables the `isaacsim.code_editor.python_server` bridge (TCP :8226) from the
     in-repo extension under isaac_sim/source,
  3. opens the requested scene,
  4. STAYS ALIVE, pumping the app so the socket keeps serving.

That is what lets the control server's /scene/load, /robot/spawn and /exec drive a
live sim — i.e. "open the warehouse with a G1" works from a single OpenClaw prompt.

    python.sh serve_sim.py [--scene warehouse.usd|/abs/path.usd] [--gui]

Paths come from $ISAAC_CLAW_DIR (defaults to this repo).
"""
import os
import sys
from pathlib import Path

CLAW_DIR = Path(os.environ.get("ISAAC_CLAW_DIR", Path(__file__).resolve().parents[2]))
SIM_DIR = CLAW_DIR / "isaac_sim"
EXT_FOLDER = SIM_DIR / "source"          # folder CONTAINING the extension dir
SCENES = SIM_DIR / "scenes"
EXT_NAME = "isaacsim.code_editor.python_server"

argv = sys.argv[1:]
headless = "--gui" not in argv
scene = os.environ.get("ISAAC_SCENE", "warehouse.usd")
if "--scene" in argv:
    scene = argv[argv.index("--scene") + 1]

# ---------------------------------------------------------------------------
# 1. Boot Isaac Sim.
# ---------------------------------------------------------------------------
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": headless, "renderer": "RayTracedLighting"})

import carb  # noqa: E402
import omni.kit.app  # noqa: E402

# ---------------------------------------------------------------------------
# 2. Register the in-repo ext folder and enable the python_server bridge.
# ---------------------------------------------------------------------------
try:
    _settings = carb.settings.get_settings()
    _settings.set(f"/exts/{EXT_NAME}/host", "127.0.0.1")
    _settings.set(f"/exts/{EXT_NAME}/port", 8226)
    mgr = omni.kit.app.get_app().get_extension_manager()
    mgr.add_path(str(EXT_FOLDER))
    mgr.set_extension_enabled_immediate(EXT_NAME, True)
    for _ in range(10):
        simulation_app.update()
    print(f"[serve_sim] enabled {EXT_NAME} on 127.0.0.1:8226")
except Exception as e:
    print(f"[serve_sim] WARNING could not enable {EXT_NAME}: {e}")

# ---------------------------------------------------------------------------
# 3. Open the scene (or start empty if it's missing).
# ---------------------------------------------------------------------------
import isaacsim.core.experimental.utils.stage as stage_utils  # noqa: E402
import omni.usd  # noqa: E402


def _resolve_scene(s):
    """Resolve a scene reference to an openable path/URL. Returns (target, remote).

    Handles three forms so `claw open --env <name>` works for cloud OR local envs:
      * Nucleus token paths ({ISAAC_NUCLEUS_DIR}/...) and omniverse:// / http(s)://
        URLs  -> resolve tokens against the in-sim asset root; open as remote.
      * absolute local path                      -> open as-is.
      * bare filename or repo-relative path       -> isaac_sim/scenes/<f>, else
                                                     $ISAAC_CLAW_DIR/<path>.
    """
    low = s.lower()
    if "{" in s or low.startswith(("omniverse://", "http://", "https://")):
        try:
            from isaacsim.storage.native import get_assets_root_path
        except Exception:
            try:
                from omni.isaac.nucleus import get_assets_root_path
            except Exception:
                get_assets_root_path = lambda: None  # noqa: E731
        root = get_assets_root_path() or ""
        s = (s.replace("{ISAACLAB_NUCLEUS_DIR}", root + "/Isaac/IsaacLab")
              .replace("{ISAAC_NUCLEUS_DIR}", root + "/Isaac")
              .replace("{NUCLEUS_ASSET_ROOT_DIR}", root))
        return s, True
    if os.path.isabs(s):
        return s, False
    local = str(SCENES / s)
    if not os.path.exists(local):
        alt = str(CLAW_DIR / s)            # repo-relative (e.g. local asset store)
        if os.path.exists(alt):
            return alt, False
    return local, False


def _wait_for_load(max_frames=2000, settle=60):
    """Version-robust 'is the stage done streaming' wait (no is_stage_loading)."""
    ctx = omni.usd.get_context()
    for _ in range(max_frames):
        try:
            status = ctx.get_stage_loading_status()   # (message, files_loaded, total_files)
            loaded, total = status[1], status[2]
            if not total or loaded >= total:
                break
        except Exception:
            break
        simulation_app.update()
    for _ in range(settle):                            # settle frames regardless
        simulation_app.update()


scene_target, scene_remote = _resolve_scene(scene)
if scene_remote or os.path.exists(scene_target):
    where = "remote" if scene_remote else "local"
    print(f"[serve_sim] opening {where} scene {scene_target} ...")
    stage_utils.open_stage(scene_target)
    _wait_for_load()
    print("[serve_sim] scene loaded")
else:
    print(f"[serve_sim] scene not found ({scene_target}); serving an empty stage")
    for _ in range(10):
        simulation_app.update()

# ---------------------------------------------------------------------------
# 4. Stay alive so the bridge keeps serving (this is the whole point).
# ---------------------------------------------------------------------------
print("[serve_sim] READY — python_server bridge live on :8226. "
      "Drive it via the control server (/scene/load, /robot/spawn, /exec). Ctrl-C to stop.")
try:
    while simulation_app.is_running():
        simulation_app.update()
except KeyboardInterrupt:
    print("[serve_sim] shutting down")
finally:
    simulation_app.close()
