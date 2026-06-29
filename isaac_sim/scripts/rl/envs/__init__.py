# Copyright (c) 2026.
# SPDX-License-Identifier: BSD-3-Clause
"""Gym registration for the custom two-table differential-IK G1 env.

Import this module (``import envs``) before calling ``gym.make`` so the id is
registered. It is intentionally standalone (does not touch the Isaac Lab task
package) so it can live under the project tree.
"""

import gymnasium as gym

from . import g1_two_table_ik_env_cfg

gym.register(
    id="Isaac-Reach-PickPlace-DiffIK-G1-Abs-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": g1_two_table_ik_env_cfg.G1TwoTableIKEnvCfg,
    },
)
