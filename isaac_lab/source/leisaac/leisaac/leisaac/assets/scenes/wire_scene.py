from pathlib import Path

import isaaclab.sim as sim_utils
from isaaclab.assets import AssetBaseCfg
from leisaac.utils.constant import ASSETS_ROOT

"""Configuration for the Wire Scene"""
SCENES_ROOT = Path(ASSETS_ROOT) / "scenes"

WIRE_SCENE_V2_USD_PATH = str(SCENES_ROOT / "wire_scene_v2" / "scene.usd")

WIRE_SCENE_V2_CFG = AssetBaseCfg(
    spawn=sim_utils.UsdFileCfg(
        usd_path=WIRE_SCENE_V2_USD_PATH,
    )
)
