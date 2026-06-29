from isaacsim import SimulationApp

# Start SimulationApp in headless mode
simulation_app = SimulationApp({"headless": True})

import omni.isaac.core.utils.stage as stage_utils
from omni.isaac.core import World

# Create a new world
world = World()

# Add a ground plane
stage_utils.add_default_ground_plane()

# Add a distant light
stage_utils.add_distant_light()

# Step the simulation once
world.step(render=False)

# Close the simulation
simulation_app.close()
