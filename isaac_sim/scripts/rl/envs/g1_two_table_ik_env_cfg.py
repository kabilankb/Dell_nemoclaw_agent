# Copyright (c) 2026.
# SPDX-License-Identifier: BSD-3-Clause
"""Manager-based DIFFERENTIAL-IK pick-place env for the G1 right arm.

This is the manager-based counterpart of the standalone manipulation low level.
It mirrors the structure of the stock
``FixedBaseUpperBodyIKG1EnvCfg``
(source/isaaclab_tasks/.../locomanipulation/pick_place/fixed_base_upper_body_ik_g1_env_cfg.py)
but swaps the Pink-IK / OpenXR-teleop action for Isaac Lab's native
``DifferentialInverseKinematicsAction`` on the right arm, and replaces the
steering-wheel prop with OUR layout (0.16 m cube on a table whose top is at
z = 0.62).

Why fixed base + single reachable table here?
    A standing G1 arm reaches ~0.5-0.7 m. The two warehouse tables are 1.2 m
    apart in y, which is OUT of arm reach without locomotion. So this env
    validates the low-level diff-IK + scene only; the 1.2 m table-to-table
    traverse is handled by the hierarchical walking script
    (warehouse_scene/rl/hierarchical_pick_place.py).

Registered as ``Isaac-Reach-PickPlace-DiffIK-G1-Abs-v0`` (see envs/__init__.py).
"""

from __future__ import annotations

import isaaclab.envs.mdp as base_mdp
import isaaclab.sim as sim_utils
from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
from isaaclab.controllers import DifferentialIKControllerCfg
from isaaclab.envs import ManagerBasedRLEnvCfg
from isaaclab.envs.mdp.actions.actions_cfg import DifferentialInverseKinematicsActionCfg
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.managers import TerminationTermCfg as DoneTerm
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sim.spawners.from_files.from_files_cfg import GroundPlaneCfg
from isaaclab.utils import configclass

from isaaclab_assets.robots.unitree import G1_29DOF_CFG

# Reachable forward placement (in front of the robot, +x). Table top at z=0.62.
TABLE_TOP_Z = 0.62
CUBE_SIZE = 0.16
TABLE_X = 0.45  # metres in front of the (fixed) pelvis -> within arm reach


@configclass
class G1TwoTableIKSceneCfg(InteractiveSceneCfg):
    """Fixed-base G1 with one reachable table and a graspable cube."""

    ground = AssetBaseCfg(prim_path="/World/GroundPlane", spawn=GroundPlaneCfg())

    light = AssetBaseCfg(
        prim_path="/World/light",
        spawn=sim_utils.DomeLightCfg(color=(0.75, 0.75, 0.75), intensity=3000.0),
    )

    # Source table (kinematic box). Top face at z = TABLE_TOP_Z.
    source_table = AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/SourceTable",
        init_state=AssetBaseCfg.InitialStateCfg(pos=(TABLE_X, 0.0, TABLE_TOP_Z / 2.0)),
        spawn=sim_utils.CuboidCfg(
            size=(0.8, 0.8, TABLE_TOP_Z),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(kinematic_enabled=True),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.4, 0.3, 0.2)),
        ),
    )

    # 0.16 m graspable cube sitting on the source table.
    object = RigidObjectCfg(
        prim_path="{ENV_REGEX_NS}/Object",
        init_state=RigidObjectCfg.InitialStateCfg(pos=(TABLE_X, 0.0, TABLE_TOP_Z + CUBE_SIZE / 2.0)),
        spawn=sim_utils.CuboidCfg(
            size=(CUBE_SIZE, CUBE_SIZE, CUBE_SIZE),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(mass=0.5),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.1, 0.5, 0.9)),
        ),
    )

    robot: ArticulationCfg = G1_29DOF_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")

    def __post_init__(self):
        # Fixed base: only the arm moves under IK; legs/torso hold their default pose.
        self.robot.spawn.articulation_props.fix_root_link = True


@configclass
class ActionsCfg:
    """Differential IK on the right arm (absolute pose command)."""

    right_arm_ik = DifferentialInverseKinematicsActionCfg(
        asset_name="robot",
        joint_names=["right_shoulder_.*_joint", "right_elbow_.*_joint", "right_wrist_.*_joint"],
        body_name="right_wrist_yaw_link",
        controller=DifferentialIKControllerCfg(command_type="pose", use_relative_mode=False, ik_method="dls"),
        scale=1.0,
    )


@configclass
class ObservationsCfg:
    @configclass
    class PolicyCfg(ObsGroup):
        joint_pos = ObsTerm(func=base_mdp.joint_pos_rel)
        joint_vel = ObsTerm(func=base_mdp.joint_vel_rel)
        object_pos = ObsTerm(func=base_mdp.root_pos_w, params={"asset_cfg": SceneEntityCfg("object")})
        actions = ObsTerm(func=base_mdp.last_action)

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True

    policy: PolicyCfg = PolicyCfg()


@configclass
class TerminationsCfg:
    time_out = DoneTerm(func=base_mdp.time_out, time_out=True)
    object_dropping = DoneTerm(
        func=base_mdp.root_height_below_minimum,
        params={"minimum_height": 0.3, "asset_cfg": SceneEntityCfg("object")},
    )


@configclass
class G1TwoTableIKEnvCfg(ManagerBasedRLEnvCfg):
    """Fixed-base differential-IK reach/pick env on our cube+table layout."""

    scene: G1TwoTableIKSceneCfg = G1TwoTableIKSceneCfg(num_envs=1, env_spacing=3.0, replicate_physics=True)
    observations: ObservationsCfg = ObservationsCfg()
    actions: ActionsCfg = ActionsCfg()
    terminations: TerminationsCfg = TerminationsCfg()

    # Unused managers (no learned reward here; control is scripted IK).
    commands = None
    rewards = None
    curriculum = None
    events = None

    def __post_init__(self):
        self.decimation = 4
        self.episode_length_s = 20.0
        self.sim.dt = 1.0 / 200.0
        self.sim.render_interval = self.decimation
