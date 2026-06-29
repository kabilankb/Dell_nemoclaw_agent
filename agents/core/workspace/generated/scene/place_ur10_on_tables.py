#!/usr/bin/env python3
"""
Layer-1 asset placement: 4x UR10 arms, each seated on a SeattleLabTable.

Idempotent: re-running clears /World/Tables and /World/Robots first, then
re-authors them, and saves the stage in place.

Run from the user's own terminal (the harness cannot spawn Kit):

    $ISAAC_SIM_DIR/python.sh \
        agent_orchestrator/workspace/generated/scene/place_ur10_on_tables.py

Assets are resolved from the common catalog (agent_orchestrator/assets/catalog.yaml).
{ISAAC_NUCLEUS_DIR} is resolved at runtime via Isaac Sim's assets root, and the
tabletop height is measured from the live bbox so the arm bases sit exactly on
the table surface (no hardcoded clearances).
"""

import math
import os
import sys

# --- SimulationApp must come first (headless; no renderer needed for authoring) ---
from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

import omni.usd
from pxr import Gf, Usd, UsdGeom, UsdPhysics

# Resolve the Nucleus assets root used to expand {ISAAC_NUCLEUS_DIR}.
try:
    from isaacsim.storage.native import get_assets_root_path
except ImportError:  # older Isaac Sim layout
    from omni.isaac.nucleus import get_assets_root_path


# --------------------------------------------------------------------------- #
# Catalog resolution (single source of truth for asset paths)
# --------------------------------------------------------------------------- #
def _repo_root():
    p = os.path.abspath(__file__)
    while p != "/":
        p = os.path.dirname(p)
        if os.path.isfile(os.path.join(p, "agent_orchestrator", "assets", "catalog.yaml")):
            return p
    raise RuntimeError("could not locate repo root (catalog.yaml)")


REPO_ROOT = _repo_root()
sys.path.insert(0, REPO_ROOT)
from agent_orchestrator import catalog  # noqa: E402

ASSETS_ROOT = get_assets_root_path()
if not ASSETS_ROOT:
    raise RuntimeError("get_assets_root_path() returned None — Nucleus unreachable")


def resolve(name):
    """Friendly catalog name -> concrete USD path ({ISAAC_NUCLEUS_DIR} expanded)."""
    usd = catalog.get(name).resolved_usd()
    return usd.replace("{ISAAC_NUCLEUS_DIR}", ASSETS_ROOT)


STAGE_PATH = catalog.get("warehouse_local").resolved_usd()  # absolute local path
TABLE_USD = resolve("table")
UR10_USD = resolve("ur10")

# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
COUNT = 4
SPACING = 2.5          # m, >= 1.5x UR10 reach (~1.3 m -> 1.95 m min) + table footprint
COLS = math.ceil(math.sqrt(COUNT))
UR10_START_Z = float(catalog.get("ur10").attrs.get("start_z", 0.0))  # base offset, = 0.0

TABLES_ROOT = "/World/Tables"
ROBOTS_ROOT = "/World/Robots"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def grid_xy(i):
    row, col = divmod(i, COLS)
    x = (col - (COLS - 1) / 2.0) * SPACING
    y = (row - (math.ceil(COUNT / COLS) - 1) / 2.0) * SPACING
    return float(x), float(y)


def reset_group(stage, path):
    if stage.GetPrimAtPath(path):
        stage.RemovePrim(path)
    UsdGeom.Xform.Define(stage, path)


def set_trs(prim, translate, scale=None):
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(*translate))      # T
    xf.AddOrientOp().Set(Gf.Quatf(1.0, 0.0, 0.0, 0.0))  # R (identity)
    if scale is not None:
        xf.AddScaleOp().Set(Gf.Vec3f(*scale))          # S


def measure_ref(stage, ref_usd):
    """Reference an asset under a temp prim, step, return aligned bbox (min,max)."""
    tmp = "/World/__bbox_probe"
    p = stage.DefinePrim(tmp, "Xform")
    p.GetReferences().AddReference(ref_usd)
    for _ in range(5):
        simulation_app.update()
    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    rng = bc.ComputeWorldBound(p).ComputeAlignedRange()
    mn, mx = rng.GetMin(), rng.GetMax()
    stage.RemovePrim(tmp)
    if mn[0] > 1e30:
        raise RuntimeError(f"invalid bbox for {ref_usd}")
    return mn, mx


# --------------------------------------------------------------------------- #
# Author the scene
# --------------------------------------------------------------------------- #
ctx = omni.usd.get_context()
ctx.open_stage(STAGE_PATH)
stage = ctx.get_stage()

reset_group(stage, TABLES_ROOT)
reset_group(stage, ROBOTS_ROOT)

# Measure the table once: footprint center offset (XY) and top surface (Z).
t_min, t_max = measure_ref(stage, TABLE_USD)
table_cx = (t_min[0] + t_max[0]) / 2.0
table_cy = (t_min[1] + t_max[1]) / 2.0
table_base_z = t_min[2]   # ground the table base to z=0
table_top_z = t_max[2] - t_min[2]   # tabletop height above its own base
print(f"[place] table footprint {t_max[0]-t_min[0]:.3f} x {t_max[1]-t_min[1]:.3f} m, "
      f"top at z={table_top_z:.3f} m")

added = []
for i in range(COUNT):
    x, y = grid_xy(i)

    # --- Table (grounded; XY offset-corrected so its center lands on (x, y)) ---
    table_path = f"{TABLES_ROOT}/Table_{i}"
    tprim = stage.OverridePrim(table_path)
    tprim.GetReferences().AddReference(TABLE_USD)
    set_trs(tprim, (x - table_cx, y - table_cy, -table_base_z))

    # --- UR10 (seated on the tabletop) ---
    arm_path = f"{ROBOTS_ROOT}/ur10_{i}"
    aprim = stage.OverridePrim(arm_path)
    aprim.GetReferences().AddReference(UR10_USD)
    set_trs(aprim, (x, y, table_top_z + UR10_START_Z))
    # Fixed-base arm: ensure an articulation root is present on the referencing prim.
    if not aprim.HasAPI(UsdPhysics.ArticulationRootAPI):
        UsdPhysics.ArticulationRootAPI.Apply(aprim)

    added.append((table_path, arm_path, (x, y)))

# Save in place.
ctx.save_stage()

print("\n[place] saved stage:", STAGE_PATH)
print(f"[place] table USD : {TABLE_USD}")
print(f"[place] ur10  USD : {UR10_USD}")
for tp, ap, (x, y) in added:
    print(f"  {ap}  +  {tp}   @ (x={x:+.2f}, y={y:+.2f})")

simulation_app.close()
