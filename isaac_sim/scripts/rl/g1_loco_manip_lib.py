# Copyright (c) 2026.
# SPDX-License-Identifier: BSD-3-Clause
"""Shared helpers for the hierarchical G1 walk + pick-place demo.

This module is imported by ``hierarchical_pick_place.py`` AFTER the Isaac Sim
app has been created (so importing torch / isaaclab here is safe). It provides:

* :class:`LocomotionPolicy`   - loads the exported rsl_rl velocity policy
                                (TorchScript ``policy.pt``) and reconstructs the
                                exact observation vector of
                                ``Isaac-Velocity-Flat-G1-v0``.
* :class:`ArmIK`              - a thin wrapper around Isaac Lab's
                                ``DifferentialIKController`` that handles the
                                floating-base Jacobian indexing for the G1 arm.
* :class:`AttachGrasp`        - the "simplified attach grasp": creates / removes a
                                ``UsdPhysics.FixedJoint`` between a hand link and
                                the cube.
* scene-building helpers for a lightweight flat-ground + two-tables + cube scene.

All API symbols used here were verified against the local Isaac Lab checkout at
/home/dgx-destro/IsaacLab (see INVESTIGATION.md for exact file/line references).
"""

from __future__ import annotations

import os
import torch

import isaaclab.sim as sim_utils
import isaaclab.utils.math as math_utils
from isaaclab.assets import Articulation, ArticulationCfg, RigidObject, RigidObjectCfg
from isaaclab.controllers import DifferentialIKController, DifferentialIKControllerCfg

from isaaclab_assets.robots.unitree import G1_MINIMAL_CFG

# pxr is available once the Kit app is running.
from pxr import Gf, Usd, UsdPhysics


def find_prim_by_name(stage: Usd.Stage, root_path: str, name: str) -> str | None:
    """Return the path of the first prim named ``name`` under ``root_path``."""
    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        return None
    for prim in Usd.PrimRange(root):
        if prim.GetName() == name:
            return prim.GetPath().pathString
    return None


# ---------------------------------------------------------------------------
# Observation layout of Isaac-Velocity-Flat-G1-v0 (height_scan disabled on flat).
# Verified: source/isaaclab_tasks/.../locomotion/velocity/velocity_env_cfg.py
#   PolicyCfg order  -> base_lin_vel(3), base_ang_vel(3), projected_gravity(3),
#                       velocity_commands(3), joint_pos_rel(N), joint_vel_rel(N),
#                       last_action(N)
#   ActionsCfg       -> JointPositionAction(joint_names=[".*"], scale=0.5,
#                       use_default_offset=True)
#     => applied target = default_joint_pos + 0.5 * raw_action
# The exported policy.pt embeds the empirical normalizer, so we feed RAW obs.
# ---------------------------------------------------------------------------

ACTION_SCALE = 0.5  # JointPositionActionCfg.scale for the velocity task


def make_g1_cfg(prim_path: str = "/World/Robot") -> ArticulationCfg:
    """G1 articulation cfg identical to the one the locomotion policy trained on.

    Using ``G1_MINIMAL_CFG`` guarantees the physics-view joint ordering matches
    the training env, so ``robot.data.joint_pos`` lines up 1:1 with the policy's
    expected obs/action ordering (no manual re-indexing needed).
    """
    return G1_MINIMAL_CFG.replace(prim_path=prim_path)


class LocomotionPolicy:
    """Runs the exported velocity-tracking policy and produces joint targets."""

    def __init__(self, robot: Articulation, jit_path: str, device: str):
        if not os.path.isfile(jit_path):
            raise FileNotFoundError(
                f"Exported locomotion policy not found: {jit_path}\n"
                "Run the rsl_rl play.py export step first (see README.md)."
            )
        self.robot = robot
        self.device = device
        self.policy = torch.jit.load(jit_path, map_location=device).eval()
        self.num_joints = robot.num_joints
        # Persistent raw action (fed back into the obs as `last_action`).
        self.last_action = torch.zeros((robot.num_instances, self.num_joints), device=device)

    @torch.no_grad()
    def _build_obs(self, cmd: torch.Tensor) -> torch.Tensor:
        """Reconstruct the flat-G1 policy observation. ``cmd`` = [vx, vy, wz]."""
        d = self.robot.data
        base_lin_vel = d.root_lin_vel_b
        base_ang_vel = d.root_ang_vel_b
        proj_g = d.projected_gravity_b
        joint_pos_rel = d.joint_pos - d.default_joint_pos
        joint_vel_rel = d.joint_vel - d.default_joint_vel
        return torch.cat(
            [base_lin_vel, base_ang_vel, proj_g, cmd, joint_pos_rel, joint_vel_rel, self.last_action],
            dim=-1,
        )

    @torch.no_grad()
    def compute_targets(self, cmd: torch.Tensor) -> torch.Tensor:
        """Return absolute joint-position targets for ALL joints for this step."""
        obs = self._build_obs(cmd)
        action = self.policy(obs)
        self.last_action = action.clone()
        return self.robot.data.default_joint_pos + ACTION_SCALE * action


def resolve_arm(robot: Articulation, side: str = "right") -> tuple[list[int], str, int]:
    """Resolve the arm joint ids and an end-effector body for ``side``.

    G1's two USDs differ: the locomotion ``g1_minimal.usd`` exposes shoulder /
    elbow joints (and finger joints), while the 29-dof manip USD adds wrist
    pitch/roll/yaw. We therefore try EE-body candidates from most to least
    specific so the same code works on either asset. The script PRINTS the
    resolved names on startup -- confirm them on first run.
    """
    joint_ids, joint_names = robot.find_joints(
        [f"{side}_shoulder_.*_joint", f"{side}_elbow_.*_joint", f"{side}_wrist_.*_joint"],
        preserve_order=False,
    )
    if not joint_ids:
        raise RuntimeError(f"No arm joints matched for side={side}. joints={robot.joint_names}")

    ee_candidates = [
        f"{side}_wrist_yaw_link",
        f"{side}_wrist_.*_link",
        f"{side}_rubber_hand",
        f"{side}_elbow_roll_link",
        f"{side}_elbow_.*_link",
    ]
    ee_name = None
    ee_body_idx = None
    for pat in ee_candidates:
        ids, names = robot.find_bodies(pat, preserve_order=False)
        if ids:
            ee_body_idx = ids[-1]
            ee_name = names[-1]
            break
    if ee_body_idx is None:
        raise RuntimeError(f"Could not resolve a {side} arm EE body. bodies={robot.body_names}")
    return joint_ids, ee_name, ee_body_idx


class ArmIK:
    """Differential IK for one G1 arm, floating-base aware.

    Mirrors the Jacobian indexing used by Isaac Lab's
    ``DifferentialInverseKinematicsAction`` for a floating-base articulation:
        jacobi_body_idx  = body_idx
        jacobi_joint_ids = [j + 6 for j in joint_ids]   # first 6 cols are base
    (verified: source/isaaclab/.../envs/mdp/actions/task_space_actions.py:75-82)
    """

    def __init__(self, robot: Articulation, side: str = "right", command_type: str = "pose", device: str = "cuda"):
        self.robot = robot
        self.device = device
        self.joint_ids, self.ee_name, self.body_idx = resolve_arm(robot, side)
        self.command_type = command_type

        cfg = DifferentialIKControllerCfg(command_type=command_type, use_relative_mode=False, ik_method="dls")
        self.controller = DifferentialIKController(cfg, num_envs=robot.num_instances, device=device)

        if robot.is_fixed_base:
            self.jacobi_body_idx = self.body_idx - 1
            self.jacobi_joint_ids = self.joint_ids
        else:
            self.jacobi_body_idx = self.body_idx
            self.jacobi_joint_ids = [j + 6 for j in self.joint_ids]

    # -- pose helpers ------------------------------------------------------
    def _ee_pose_b(self):
        """EE pose expressed in the robot root frame."""
        d = self.robot.data
        root_pos_w = d.root_pos_w
        root_quat_w = d.root_quat_w
        ee_pos_w = d.body_pos_w[:, self.body_idx]
        ee_quat_w = d.body_quat_w[:, self.body_idx]
        ee_pos_b, ee_quat_b = math_utils.subtract_frame_transforms(root_pos_w, root_quat_w, ee_pos_w, ee_quat_w)
        return ee_pos_b, ee_quat_b

    def _jacobian_b(self):
        jac_w = self.robot.root_physx_view.get_jacobians()[:, self.jacobi_body_idx, :, self.jacobi_joint_ids]
        base_rot = math_utils.matrix_from_quat(math_utils.quat_inv(self.robot.data.root_quat_w))
        jac_b = jac_w.clone()
        jac_b[:, :3, :] = torch.bmm(base_rot, jac_w[:, :3, :])
        jac_b[:, 3:, :] = torch.bmm(base_rot, jac_w[:, 3:, :])
        return jac_b

    # -- public API --------------------------------------------------------
    def set_target_b(self, pos_b: torch.Tensor, quat_b: torch.Tensor | None = None):
        """Set the desired EE target (in the robot root frame)."""
        ee_pos_b, ee_quat_b = self._ee_pose_b()
        if self.command_type == "position":
            self.controller.set_command(pos_b, ee_pos_b, ee_quat_b)
        else:
            cmd = torch.cat([pos_b, quat_b], dim=-1)
            self.controller.set_command(cmd, ee_pos_b, ee_quat_b)

    def compute_joint_targets(self) -> torch.Tensor:
        """Return desired joint positions for the arm joints only."""
        ee_pos_b, ee_quat_b = self._ee_pose_b()
        jac_b = self._jacobian_b()
        joint_pos = self.robot.data.joint_pos[:, self.joint_ids]
        return self.controller.compute(ee_pos_b, ee_quat_b, jac_b, joint_pos)

    def ee_pos_w(self) -> torch.Tensor:
        return self.robot.data.body_pos_w[:, self.body_idx]


class AttachGrasp:
    """Simplified attach grasp via a runtime UsdPhysics.FixedJoint.

    On grasp: author a FixedJoint whose body0 is the hand link and body1 is the
    object. On release: deactivate / remove that joint. This avoids contact-rich
    dexterous grasping entirely.
    """

    def __init__(self, stage: Usd.Stage, robot_root_path: str, hand_link_name: str, object_path: str):
        self.stage = stage
        # The link rigid-body prim can be nested deep in the robot USD; resolve it
        # by name within the robot subtree rather than assuming a flat path.
        self.hand_link_path = find_prim_by_name(stage, robot_root_path, hand_link_name)
        if self.hand_link_path is None:
            raise RuntimeError(
                f"Could not find hand link prim '{hand_link_name}' under {robot_root_path}."
            )
        self.object_path = object_path
        self.joint_path = f"{self.hand_link_path}/AttachGraspJoint"
        self.attached = False

    def grasp(self):
        if self.attached:
            return
        joint = UsdPhysics.FixedJoint.Define(self.stage, self.joint_path)
        joint.CreateBody0Rel().SetTargets([self.hand_link_path])
        joint.CreateBody1Rel().SetTargets([self.object_path])
        # Keep the object exactly where it is at grasp time -> identity local poses
        # so PhysX locks the current relative transform.
        joint.CreateLocalPos0Attr().Set(Gf.Vec3f(0.0, 0.0, 0.0))
        joint.CreateLocalPos1Attr().Set(Gf.Vec3f(0.0, 0.0, 0.0))
        self.attached = True

    def release(self):
        if not self.attached:
            return
        prim = self.stage.GetPrimAtPath(self.joint_path)
        if prim and prim.IsValid():
            # Disable then remove so PhysX drops the constraint cleanly.
            UsdPhysics.Joint(prim).CreateJointEnabledAttr().Set(False)
            self.stage.RemovePrim(self.joint_path)
        self.attached = False


# ---------------------------------------------------------------------------
# Lightweight scene assets (no Nucleus dependency -> fine for many parallel envs).
# ---------------------------------------------------------------------------

def make_table_cfg(prim_path: str, pos: tuple[float, float, float], top_z: float = 0.62) -> RigidObjectCfg:
    """A simple kinematic box table; ``top_z`` is the world height of its top face."""
    half_h = top_z / 2.0
    return RigidObjectCfg(
        prim_path=prim_path,
        spawn=sim_utils.CuboidCfg(
            size=(0.8, 0.8, top_z),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(kinematic_enabled=True),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(mass=50.0),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.4, 0.3, 0.2)),
        ),
        init_state=RigidObjectCfg.InitialStateCfg(pos=(pos[0], pos[1], half_h)),
    )


def make_cube_cfg(prim_path: str, pos: tuple[float, float, float], size: float = 0.16) -> RigidObjectCfg:
    """A 0.16 m graspable cube (dynamic rigid body)."""
    return RigidObjectCfg(
        prim_path=prim_path,
        spawn=sim_utils.CuboidCfg(
            size=(size, size, size),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(disable_gravity=False),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(mass=0.5),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.1, 0.5, 0.9)),
        ),
        init_state=RigidObjectCfg.InitialStateCfg(pos=pos),
    )
