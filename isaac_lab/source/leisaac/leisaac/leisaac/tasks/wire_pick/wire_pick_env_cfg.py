from isaaclab.assets import AssetBaseCfg
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import TerminationTermCfg as DoneTerm
from isaaclab.utils import configclass
from leisaac.assets.scenes.wire_scene import WIRE_SCENE_V2_CFG, WIRE_SCENE_V2_USD_PATH
from leisaac.utils.general_assets import parse_usd_and_create_subassets

from ..template import (
    SingleArmObservationsCfg,
    SingleArmTaskEnvCfg,
    SingleArmTaskSceneCfg,
    SingleArmTerminationsCfg,
)
from . import mdp


@configclass
class WirePickSceneCfg(SingleArmTaskSceneCfg):
    """Scene configuration for the wire pick task."""

    scene: AssetBaseCfg = WIRE_SCENE_V2_CFG.replace(prim_path="{ENV_REGEX_NS}/Scene")


@configclass
class ObservationsCfg(SingleArmObservationsCfg):
    pass


@configclass
class TerminationsCfg(SingleArmTerminationsCfg):
    pass


@configclass
class WirePickEnvCfg(SingleArmTaskEnvCfg):
    """Configuration for the wire pick environment."""

    scene: WirePickSceneCfg = WirePickSceneCfg(env_spacing=8.0)

    observations: ObservationsCfg = ObservationsCfg()

    terminations: TerminationsCfg = TerminationsCfg()

    task_description: str = "Pick the wire/cable from the table."

    def __post_init__(self) -> None:
        super().__post_init__()

        parse_usd_and_create_subassets(
            WIRE_SCENE_V2_USD_PATH,
            self,
            exclude_name_list=["SO101", "so101", "Robot"],
        )
