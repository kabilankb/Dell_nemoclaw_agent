"""Single-command launcher for the warehouse scene.

Builds warehouse.usd (pure-pxr authoring), opens it in a headless Isaac Sim,
warms up the RTX renderer, and writes a viewport screenshot — all in one
process. No python_server / socket needed.

Run:
    cd /home/dgx-destro/warehouse_nemoclaw
    DISPLAY=:0 ~/IsaacSim/_build/linux-aarch64/release/python.sh \
        warehouse_scene/launch_warehouse.py

Flags (optional):
    --no-build     skip regeneration, just open the existing warehouse.usd
    --shot PATH    screenshot output path (default /tmp/warehouse.png)
    --gui          run with a window instead of headless
"""
import os
import sys
import runpy

# isaac-claw layout: scripts live in isaac_sim/scripts, scenes in isaac_sim/scenes.
_CLAW = os.environ.get("ISAAC_CLAW_DIR", os.path.expanduser("~/isaac-claw"))
SCENE_DIR = os.path.join(_CLAW, "isaac_sim", "scripts")
SCENES_DIR = os.path.join(_CLAW, "isaac_sim", "scenes")
BUILD_SCRIPT = os.path.join(SCENE_DIR, "build_warehouse.py")
OUT_USD = os.path.join(SCENES_DIR, "warehouse.usd")

# --- tiny arg parse (avoid argparse colliding with Kit's argv) ---
argv = sys.argv[1:]
do_build = "--no-build" not in argv
headless = "--gui" not in argv
pt = "--pt" in argv                       # Path Tracing hero render (GI, soft shadows)
shot = "/tmp/warehouse.png"
if "--shot" in argv:
    shot = argv[argv.index("--shot") + 1]
if "--scene" in argv:                      # honor an explicit scene name/path
    _sc = argv[argv.index("--scene") + 1]
    OUT_USD = _sc if os.path.isabs(_sc) else os.path.join(SCENES_DIR, _sc)

# ---------------------------------------------------------------------------
# 1. Boot Isaac Sim FIRST so the USD runtime is the Kit one.
# ---------------------------------------------------------------------------
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp(
    {"headless": headless, "renderer": "RayTracedLighting", "width": 2560, "height": 1440}
)

import carb  # noqa: E402
import isaacsim.core.experimental.utils.app as app_utils  # noqa: E402
import isaacsim.core.experimental.utils.stage as stage_utils  # noqa: E402

# --- Render quality: ACES tonemap (the single biggest quality lever) ---
_s = carb.settings.get_settings()
_s.set("/rtx/post/tonemap/op", 4)            # 4 = ACES filmic
_s.set("/rtx/post/tonemap/filmIso", 600.0)   # warehouse-calibrated
_s.set("/rtx/post/tonemap/whitepoint", 6500.0)
_s.set("/rtx/post/tonemap/enabled", True)
_s.set("/rtx/reflections/enabled", True)
_s.set("/rtx/ambientOcclusion/enabled", True)
_s.set("/rtx/indirectDiffuse/enabled", True)
# Light atmospheric fog for depth down the aisle
_s.set("/rtx/fog/enabled", True)
_s.set("/rtx/fog/fogDensity", 0.0035)
_s.set("/rtx/fog/fogColor", (0.85, 0.87, 0.92))

if pt:
    # Path Tracing: real global illumination, soft shadows, accurate reflections.
    # Slow but photoreal — accumulates samples over many app updates.
    _s.set("/rtx/rendermode", "PathTracing")
    _s.set("/rtx/pathtracing/spp", 1)
    _s.set("/rtx/pathtracing/totalSpp", 256)
    _s.set("/rtx/pathtracing/maxBounces", 6)
    _s.set("/rtx/pathtracing/maxSpecularAndTransmissionBounces", 6)
    _s.set("/rtx/pathtracing/clampSpp", 0)
    _SETTLE = 320
    print("[launch] PATH TRACING mode (256 spp) — slower, photoreal")
else:
    _s.set("/rtx/rendermode", "RayTracedLighting")   # RT2 — fast
    _s.set("/rtx/post/aa/op", 3)                      # TAA
    _s.set("/rtx/directLighting/sampledLighting/enabled", True)
    _SETTLE = 200

# ---------------------------------------------------------------------------
# 2. Build the USD (pure pxr; build_warehouse.py exports OUT_USD on import).
# ---------------------------------------------------------------------------
if do_build:
    print(f"[launch] building {OUT_USD} ...")
    runpy.run_path(BUILD_SCRIPT, run_name="__main__")
else:
    print("[launch] --no-build: opening existing stage")

# ---------------------------------------------------------------------------
# 3. Open the stage and wait for it to finish loading.
# ---------------------------------------------------------------------------
print(f"[launch] opening {OUT_USD} ...")
stage_utils.open_stage(OUT_USD)
while stage_utils.is_stage_loading():
    simulation_app.update()

# --- Snap the G1's feet exactly to the floor (z=0) via its world bounding box ---
# The robot's USD origin isn't at its soles, so a fixed Z guess sinks/floats it.
# Measure instead: lift the prim so its min-Z sits on the floor.
try:
    from pxr import Usd, UsdGeom, Gf
    import omni.usd
    _stage = omni.usd.get_context().get_stage()
    _g1 = _stage.GetPrimAtPath("/World/Robots/G1")
    if _g1 and _g1.IsValid():
        for _ in range(40):                       # let streamed meshes finish loading
            simulation_app.update()
        _bb = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy])
        _minz = _bb.ComputeWorldBound(_g1).ComputeAlignedRange().GetMin()[2]
        for _op in UsdGeom.Xformable(_g1).GetOrderedXformOps():
            if _op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                _t = _op.Get()
                _op.Set(Gf.Vec3d(_t[0], _t[1], _t[2] - _minz))   # min_z -> 0
                print(f"[launch] G1 floor-snap: min_z={_minz:.3f} m -> z {_t[2]:.3f}->{_t[2]-_minz:.3f}")
                break
        if do_build:
            _stage.GetRootLayer().Save()          # persist corrected pose into warehouse.usd
except Exception as _e:
    print(f"[launch] G1 floor-snap skipped: {_e}")

# ---------------------------------------------------------------------------
# 4. Frame the camera on the warehouse, then warm up the RTX renderer.
#    Hall runs along +X (0..32 m), aisle centered at y=0, floor at z=0.
#    Default cam sits at origin staring at a wall -> overexposed white frame.
# ---------------------------------------------------------------------------
from isaacsim.core.rendering_manager import ViewportManager  # noqa: E402

# INTERIOR 3/4 view: stand inside the aisle (|y|<2.6, between the racks),
# near the back wall, looking down the aisle past the workstation (x=6).
# Previous eye y=-9 was OUTSIDE the building (hall half-width 4.5) -> only the
# exterior wall was visible. Eye must be inside the open aisle.
ViewportManager.set_camera_view(
    "/OmniverseKit_Persp", eye=[-1.2, -2.1, 2.6], target=[12.0, 0.6, 1.1]
)

for _ in range(_SETTLE):      # settle/denoise (RT2 ~200, PathTracing ~320)
    simulation_app.update()

# ---------------------------------------------------------------------------
# 5. Capture a viewport screenshot.
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402

# Remove any stale file so existence == fresh success.
if os.path.exists(shot):
    os.remove(shot)

# Enable the headless-capable capture helper, if present.
try:
    app_utils.enable_extension("isaacsim.test.utils")
    for _ in range(5):
        simulation_app.update()
except Exception:
    pass


async def _capture(path):
    # Preferred: headless-safe hydra-texture capture used by the repo.
    try:
        from isaacsim.test.utils.image_capture import capture_viewport_screenshot_async
        await capture_viewport_screenshot_async(path)
        return "test.utils"
    except Exception as e:
        # Fallback: viewport utility (await its result object if returned).
        from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file
        cap = capture_viewport_to_file(get_active_viewport(), path)
        if hasattr(cap, "wait_for_result"):
            await cap.wait_for_result(completion_frames=60)
        return f"viewport.utility (fallback: {e})"


_task = asyncio.ensure_future(_capture(shot))
for _ in range(600):                     # pump app until capture completes
    if _task.done():
        break
    simulation_app.update()
for _ in range(30):                      # extra flush to disk
    simulation_app.update()

method = _task.result() if _task.done() else "TIMEOUT"
ok = os.path.exists(shot)
print(f"[launch] screenshot -> {shot}  written={ok}  via={method}")

# ---------------------------------------------------------------------------
# 6. Done. (Drop sys.exit / keep app open if you passed --gui and want to look.)
# ---------------------------------------------------------------------------
if not headless:
    # Only idle-loop if a real window actually came up; otherwise GLFW failed
    # (e.g. no X11 auth on :0) and we'd spin forever with nothing to see.
    import carb.windowing  # noqa: E402

    has_window = False
    try:
        has_window = carb.windowing.acquire_windowing_interface() is not None
    except Exception:
        has_window = False
    if has_window:
        print("[launch] GUI mode: close the window to exit")
        while simulation_app.is_running():
            simulation_app.update()
    else:
        print("[launch] no window (X11 unavailable) — screenshot saved, exiting")

simulation_app.close()
