---
name: "isaaclab-robot-control"
description: "Control a simulated SO101 robot arm in NVIDIA Isaac Lab for pick-and-place tasks. Use when the user asks to pick, place, grab, move the arm, open/close gripper, or manipulate objects in the simulation. Trigger keywords - pick orange, place, grab, move arm, gripper, forward, backward, left, right, up, down, robot control, pick and place, simulation, detect, vision, find orange."
---

# Isaac Lab Robot Control

You are connected to a simulated SO101 robot arm running in NVIDIA Isaac Lab (LeIsaac) via a ZMQ bridge.

IMPORTANT: Use the `exec` tool to run all commands below. Do NOT use Read, Write, or any file tools — they are not available. All interaction happens through shell commands via `exec`.

## How It Works

You send JSON commands over ZMQ to port 5557 on the host. The LeIsaac simulation receives them and moves the robot.
You receive status feedback on port 5558.
You can read YOLO vision detections on port 5559 using `/sandbox/bin/isaaclab-detect`.

## Available Commands

All commands are JSON objects: `{"action": "<name>", "params": {<optional>}}`

### Movement Commands (Cartesian space)

| Action | Params | Default | Description |
|--------|--------|---------|-------------|
| `forward` | `{"distance": <meters>}` | 1.0 | Move gripper forward (toward objects) |
| `backward` | `{"distance": <meters>}` | 1.0 | Move gripper backward (away from objects) |
| `left` | `{"distance": <meters>}` | 0.5 | Rotate arm base left |
| `right` | `{"distance": <meters>}` | 0.5 | Rotate arm base right |
| `up` | `{"distance": <meters>}` | 0.3 | Move gripper up |
| `down` | `{"distance": <meters>}` | 0.3 | Move gripper down |

### Rotation Commands

| Action | Params | Default | Description |
|--------|--------|---------|-------------|
| `turn_left` | `{"angle": <degrees>}` | 45 | Yaw gripper left |
| `turn_right` | `{"angle": <degrees>}` | 45 | Yaw gripper right |

### Gripper Commands

| Action | Params | Description |
|--------|--------|-------------|
| `gripper_open` | none | Open the gripper to release objects |
| `gripper_close` | none | Close the gripper to grasp objects |
| `stop` | none | Stop all motion immediately |

## How to Send Commands

```bash
/sandbox/bin/isaaclab-send '{"action": "forward", "params": {"distance": 0.3}}'
/sandbox/bin/isaaclab-send '{"action": "gripper_close", "params": {}}'
/sandbox/bin/isaaclab-send '{"action": "up", "params": {"distance": 0.15}}'
```

Compound helpers:

```bash
/sandbox/bin/isaaclab-pick    # down + gripper_close + up
/sandbox/bin/isaaclab-place   # down + gripper_open + up
```

## Vision-Guided Picking (YOLO)

When the simulation is running with `--enable_vision`, YOLO detects oranges in the camera and a vision publisher streams their world positions over ZMQ.

### Reading Detections

```bash
/sandbox/bin/isaaclab-detect
```

This prints a report showing:
- Each orange's world position and distance from gripper
- Recommended movement commands (forward/backward/left/right/up/down with distances)
- Which oranges are picked, on the plate, or still remaining
- YOLO detection confidence
- The next target (closest unpicked orange)

Example output:
```
=== Vision Detection Report ===
Gripper position: [+1.234, -0.456, +0.789]

--- Orange001 [NOT PICKED] ---
  World pos:  [+1.500, -0.300, +0.550]
  Distance:   0.350m
  Commands:   forward 0.25, left 0.10, down 0.12

--- Orange002 [NOT PICKED] ---
  World pos:  [+1.450, -0.600, +0.550]
  Distance:   0.300m
  Commands:   forward 0.20, right 0.15, down 0.12

--- Orange003 [ON PLATE] ---
  (completed)

--- Plate ---
  World pos:  [+1.600, -0.500, +0.520]
  Distance:   0.420m
  Commands:   forward 0.35, right 0.05, down 0.15

YOLO detections: 2 orange(s) visible in camera

Next target: Orange002 (closest unpicked, 0.300m away)
```

### Visual Servoing Workflow

Use this loop to pick oranges one by one:

1. **Detect**: Run `/sandbox/bin/isaaclab-detect` to see where oranges are
2. **Navigate**: Send the recommended commands one at a time to approach the target orange. Use small distances (0.05-0.15m) for precision. Send the lateral (left/right) command first, then forward, then down.
3. **Re-check**: Run `/sandbox/bin/isaaclab-detect` again to verify you are close (distance < 0.05m)
4. **Pick**: Open gripper, lower to orange, close gripper, lift up
5. **Navigate to plate**: Run `/sandbox/bin/isaaclab-detect` to get plate position, send commands to move above plate
6. **Place**: Lower to plate, open gripper, lift up
7. **Repeat**: Run `/sandbox/bin/isaaclab-detect` again for the next unpicked orange

### Example: Pick One Orange with Vision Guidance

```bash
# 1. Check where oranges are
/sandbox/bin/isaaclab-detect

# 2. Move laterally first (left/right), using the "Commands" line from the report
/sandbox/bin/isaaclab-send '{"action": "left", "params": {"distance": 0.10}}'
sleep 3

# 3. Move forward toward the orange
/sandbox/bin/isaaclab-send '{"action": "forward", "params": {"distance": 0.20}}'
sleep 3

# 4. Check position again
/sandbox/bin/isaaclab-detect

# 5. Fine-tune if needed, then pick
/sandbox/bin/isaaclab-send '{"action": "gripper_open", "params": {}}'
sleep 2
/sandbox/bin/isaaclab-send '{"action": "down", "params": {"distance": 0.12}}'
sleep 2
/sandbox/bin/isaaclab-send '{"action": "gripper_close", "params": {}}'
sleep 2
/sandbox/bin/isaaclab-send '{"action": "up", "params": {"distance": 0.15}}'
sleep 2

# 6. Check detection for plate position
/sandbox/bin/isaaclab-detect

# 7. Navigate to plate and place
/sandbox/bin/isaaclab-send '{"action": "right", "params": {"distance": 0.15}}'
sleep 3
/sandbox/bin/isaaclab-send '{"action": "forward", "params": {"distance": 0.10}}'
sleep 3
/sandbox/bin/isaaclab-send '{"action": "down", "params": {"distance": 0.10}}'
sleep 2
/sandbox/bin/isaaclab-send '{"action": "gripper_open", "params": {}}'
sleep 2
/sandbox/bin/isaaclab-send '{"action": "up", "params": {"distance": 0.12}}'
sleep 2
```

## Important Notes

- Use small distances (0.05-0.3m) for precise control
- The robot speed is 0.15 m/s for position, 0.5 rad/s for rotation
- Wait between commands for the motion to complete (commands are timed trajectories)
- The simulation runs at 60 Hz
- Always run `/sandbox/bin/isaaclab-detect` before and after movements to verify position
- The "Commands" line in the detect report gives you the exact commands and distances needed
- When distance to target is under 0.05m, you are close enough to pick/place
- Always open the gripper before lowering to pick an object

## Pick Orange Task

The `LeIsaac-SO101-PickOrange-v0` task has 3 oranges and a plate.
Goal: Pick each orange and place it on the plate.

Strategy:
1. Run `/sandbox/bin/isaaclab-detect` to find the closest unpicked orange
2. Use visual servoing (detect → move → detect → move) to approach it
3. Pick it up (gripper_open → down → gripper_close → up)
4. Navigate to plate using `/sandbox/bin/isaaclab-detect` for plate position
5. Place it (down → gripper_open → up)
6. Repeat for remaining oranges
