"""Run the Isaac Lab 3 `isaaclab` CLI with isaac-claw's runtime tweaks.

Used by isaac_control_server.py for tasks registered with "launcher": "isaaclab3"
(run with $ISAAC_LAB3_DIR/.venv/bin/python). Arguments pass straight through to
`isaaclab`, e.g.  isaaclab3_launch.py train --rl_library rsl_rl --task=... --viz=viser

Tweaks:
  * the viser web viewer binds $ISAAC_VISER_PORT (default 8012) instead of 8080,
    so it can sit in the web console's iframe next to other local services.
"""
import os
import sys

VISER_PORT = int(os.environ.get("ISAAC_VISER_PORT", "8012"))


def _patch_viser_port():
    from isaaclab_visualizers.viser import viser_visualizer as vv

    orig_init = vv.ViserVisualizer.__init__

    def __init__(self, cfg, *args, **kwargs):
        cfg.backend.port = VISER_PORT
        orig_init(self, cfg, *args, **kwargs)

    vv.ViserVisualizer.__init__ = __init__


if __name__ == "__main__":
    try:
        _patch_viser_port()
    except ImportError:  # viser extra not installed — other visualizers still work
        pass
    from isaaclab.cli import cli

    sys.argv[0] = "isaaclab"
    sys.exit(cli())
