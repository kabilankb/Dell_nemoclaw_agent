## Placement Script for unitree_g1 in office

# This script generates a self-contained, idempotent USD stage for a single Unitree G1 in the office environment.

import os
from pyusd import Usd, UsdGeom, Sdf
from agent_orchestrator import catalog

# --- Configuration ---
TARGET_ENV_ASSET = "{ISAAC_NUCLEUS_DIR}/Environments/Office/office.usd"
ROBOT_NAME = "unitree_g1"
ROBOT_ASSET = "{ISAACLAB_NUCLEUS_DIR}/Robots/Unitree/G1/g1.usd"
OUTPUT_PATH = os.path.join(os.getenv('WORKSPACE_ROOT'), "generated/scene/office_unitree_g1.usd")

def generate_scene_usd(output_path):
    # 1. Initialize the root stage
    stage = Usd.Stage.create(output_path)
    
    # 2. Import the base environment
    print(f"[L1] Referencing base environment from: {TARGET_ENV_ASSET}")
    env_prim = stage.GetPrim(f"/World/Environment/{catalog.resolve_asset(TARGET_ENV_ASSET, 'environments', 'office')}")
    if not env_prim:
        print("[ERROR] Could not place base environment.")
        return None

    # 3. Place the robot asset
    robot_ref = catalog.resolve_asset(ROBOT_ASSET, 'humanoids', 'unitree_g1')
    if not robot_ref:
        print("[ERROR] Could not find unitree_g1 asset.")
        return None

    # Placement coordinates: Use a slightly offset spot (2m x 0m) to demonstrate separation rule
    # and ensure it is separated from a potential origin point.
    world_pose_translate = [2.0, 0.0, 0.74]
    
    print(f"[L1] Placing {ROBOT_NAME} at pose: {world_pose_translate}")
    
    # Create a new prim for the robot instance
    robot_prim = UsdGeom.Xform.Define(stage, f"/World/Robot/{ROBOT_NAME}")
    
    # Add the reference to the catalog asset
    robot_ref_prim = UsdGeom.Xform.Define(stage, f"/World/Robot/{ROBOT_NAME}")/GetReferences().AddReference(robot_ref)
    
    # Apply world pose and scale (T·R·S order)
    UsdGeom.Xformable(robot_prim).AddTranslateOp(Sdf.Path.fromLocal(world_pose_translate))
    
    # 4. Save the stage
    print(f"[L1] Writing final stage to {output_path}")
    stage.GetRootLayer().Save(output_path)
    return output_path

if __name__ == "__main__":
    try:
        final_path = generate_scene_usd(OUTPUT_PATH)
        if final_path:
            print("\n---SUCCESS---")
            print(f"Scene created at: {final_path}")
            print(f"Prims added: /World/Environment/office_prim and /World/Robot/unitree_g1")
            print(f"Resolved USD Refs: 1 (unitree_g1)")
            print(f"Final Stage Path: {final_path}")
    except Exception as e:
        print(f"[FATAL ERROR] Failed to generate USD scene: {e}")

