# NemoClaw + LeIsaac Pick Orange Workflow

Control a simulated SO101 robot arm for pick-and-place operations using NemoClaw (`robotcontrol` sandbox) as the AI controller, replacing manual OpenClaw teleoperation.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          HOST MACHINE (DGX)                         │
│                                                                      │
│  ┌─────────────────────────┐      ZMQ (5557/5558)     ┌────────────┐│
│  │  NemoClaw Sandbox       │◄────────────────────────►│  LeIsaac   ││
│  │  "robotcontrol"         │                          │  Simulator ││
│  │                         │   JSON commands ──►      │            ││
│  │  Nemotron-3-Super:120b  │   ◄── status feedback    │  IsaacLab  ││
│  │  (Ollama local)         │                          │  SO101 Arm ││
│  │                         │                          │            ││
│  │  OpenClaw Agent         │                          │  PickOrange││
│  │  + isaaclab-robot-ctrl  │                          │  Task      ││
│  │    skill                │                          │            ││
│  └─────────────────────────┘                          └────────────┘│
│        ▲                                                             │
│        │ Dashboard: http://127.0.0.1:18790/                         │
│        │ Terminal:  nemoclaw robotcontrol connect                    │
│        ▼                                                             │
│  ┌─────────────────────────┐                                        │
│  │  User (You)             │                                        │
│  │  "Pick the orange and   │                                        │
│  │   place it on the plate"│                                        │
│  └─────────────────────────┘                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **User** types a natural language command in NemoClaw chat
2. **NemoClaw Agent** (Nemotron-3-Super 120B) interprets the command using the `isaaclab-robot-control` skill
3. **Agent** executes `isaaclab-send` commands inside the sandbox, which send JSON over ZMQ to the host
4. **LeIsaac OpenClawDevice** receives the ZMQ messages and converts them to delta-pose actions
5. **IsaacLab Simulation** applies the actions to the SO101 robot arm at 60 Hz
6. **Status feedback** flows back over ZMQ port 5558 to the agent

---

## Prerequisites

- NemoClaw `robotcontrol` sandbox running and healthy
- LeIsaac installed with IsaacLab (conda env `leisaac`)
- Kitchen with Orange scene assets downloaded into `assets/`
- GPU available (CUDA)

Verify NemoClaw is ready:
```bash
nemoclaw robotcontrol status
```

---

## Quick Start (Automated)

The launcher script handles all setup and starts the simulation:

```bash
cd ~/leisaac
./launch_nemoclaw_pickorange.sh
```

With data recording:
```bash
./launch_nemoclaw_pickorange.sh --record
```

With high-quality rendering:
```bash
./launch_nemoclaw_pickorange.sh --quality
```

Then open the NemoClaw dashboard at `http://127.0.0.1:18790/` and start chatting with the agent.

---

## Manual Step-by-Step Setup

### Step 1: Add ZMQ Network Policy

The NemoClaw sandbox needs network access to reach the host's ZMQ ports (5557 for commands, 5558 for status).

Create the policy file:
```bash
cat > /tmp/isaaclab-zmq.yaml << 'EOF'
name: isaaclab-zmq
description: "Allow ZMQ communication with LeIsaac simulation on host ports 5557-5558"
endpoints:
  - host: host.openshell.internal
    port: 5557
    tls: skip
    access: full
  - host: host.openshell.internal
    port: 5558
    tls: skip
    access: full
binaries:
  - path: /usr/bin/python3*
  - path: /usr/local/bin/python3*
  - path: /usr/local/bin/node*
  - path: /usr/bin/node*
  - path: /sandbox/.venv/bin/python*
EOF
```

Apply it:
```bash
nemoclaw robotcontrol policy-add --from-file /tmp/isaaclab-zmq.yaml --yes
```

Verify:
```bash
nemoclaw robotcontrol policy-list
```

### Step 2: Install the Robot Control Skill

The skill teaches the NemoClaw agent how to send robot commands:

```bash
nemoclaw robotcontrol skill install ~/leisaac/nemoclaw-skill-isaaclab
```

### Step 3: Deploy Helper Scripts into Sandbox

Install `pyzmq` and copy the helper scripts:

```bash
# Install pyzmq in sandbox
nemoclaw robotcontrol exec -- pip install pyzmq -q

# Deploy isaaclab-send (single command sender)
cat ~/leisaac/nemoclaw-skill-isaaclab/isaaclab-send | \
    nemoclaw robotcontrol exec -- bash -c "cat > /usr/local/bin/isaaclab-send && chmod +x /usr/local/bin/isaaclab-send"

# Deploy isaaclab-pick (compound pick action)
cat ~/leisaac/nemoclaw-skill-isaaclab/isaaclab-pick | \
    nemoclaw robotcontrol exec -- bash -c "cat > /usr/local/bin/isaaclab-pick && chmod +x /usr/local/bin/isaaclab-pick"

# Deploy isaaclab-place (compound place action)
cat ~/leisaac/nemoclaw-skill-isaaclab/isaaclab-place | \
    nemoclaw robotcontrol exec -- bash -c "cat > /usr/local/bin/isaaclab-place && chmod +x /usr/local/bin/isaaclab-place"
```

Verify they work:
```bash
nemoclaw robotcontrol exec -- isaaclab-send --help
```

### Step 4: Start the LeIsaac Simulation

In a **separate terminal**, activate your leisaac conda env and start the simulation:

```bash
conda activate leisaac
cd ~/leisaac

python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=openclaw \
    --openclaw_endpoint="tcp://0.0.0.0:5557" \
    --step_hz=60 \
    --num_envs=1 \
    --device=cuda \
    --enable_cameras
```

Wait for the Isaac Lab simulator window to appear and the `[OpenClawDevice] Listening for commands on tcp://0.0.0.0:5557` message.

### Step 5: Connect NemoClaw and Control the Robot

**Option A — Browser Dashboard:**
```
http://127.0.0.1:18790/
```

**Option B — Terminal TUI:**
```bash
nemoclaw robotcontrol connect
# Inside sandbox:
openclaw tui
```

**Option C — Direct CLI commands from host:**
```bash
# Test a single command
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "forward", "params": {"distance": 0.2}}'

# Run a pick sequence
nemoclaw robotcontrol exec -- isaaclab-pick

# Run a place sequence
nemoclaw robotcontrol exec -- isaaclab-place
```

---

## Controlling the Robot

### Natural Language (via NemoClaw Chat)

In the NemoClaw dashboard or TUI, type commands like:

```
Pick up the orange and place it on the plate
Move forward 0.3 meters
Turn left 30 degrees
Open the gripper
Move down slowly
Pick the object
Place it on the plate
```

The Nemotron-3-Super agent uses the `isaaclab-robot-control` skill to translate these into ZMQ commands.

### Direct JSON Commands (via isaaclab-send)

For precise control, send JSON commands directly:

```bash
# Movement
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "forward", "params": {"distance": 0.3}}'
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "backward", "params": {"distance": 0.2}}'
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "left", "params": {"distance": 0.3}}'
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "right", "params": {"distance": 0.3}}'
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "up", "params": {"distance": 0.15}}'
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "down", "params": {"distance": 0.15}}'

# Rotation
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "turn_left", "params": {"angle": 45}}'
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "turn_right", "params": {"angle": 30}}'

# Gripper
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "gripper_open", "params": {}}'
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "gripper_close", "params": {}}'

# Emergency stop
nemoclaw robotcontrol exec -- isaaclab-send '{"action": "stop", "params": {}}'
```

### Compound Actions

```bash
# Pick: lower arm, close gripper, lift
nemoclaw robotcontrol exec -- isaaclab-pick

# Place: lower arm, open gripper, lift
nemoclaw robotcontrol exec -- isaaclab-place
```

---

## Command Reference

| Command | Parameters | Default | Description |
|---------|-----------|---------|-------------|
| `forward` | `distance` (m) | 1.0 | Move gripper forward toward objects |
| `backward` | `distance` (m) | 1.0 | Move gripper backward |
| `left` | `distance` (m) | 0.5 | Rotate arm base left |
| `right` | `distance` (m) | 0.5 | Rotate arm base right |
| `up` | `distance` (m) | 0.3 | Lift gripper up |
| `down` | `distance` (m) | 0.3 | Lower gripper down |
| `turn_left` | `angle` (deg) | 45 | Yaw gripper left |
| `turn_right` | `angle` (deg) | 45 | Yaw gripper right |
| `gripper_open` | — | — | Open gripper to release |
| `gripper_close` | — | — | Close gripper to grasp |
| `stop` | — | — | Stop all motion |

### Robot Speeds

| Motion Type | Speed |
|------------|-------|
| Position (translation) | 0.15 m/s |
| Rotation | 0.5 rad/s |
| Gripper open/close | 1.0 s duration |
| Simulation rate | 60 Hz |

---

## Recording Demonstrations

To record the NemoClaw-controlled demonstrations for later training:

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=openclaw \
    --openclaw_endpoint="tcp://0.0.0.0:5557" \
    --step_hz=60 \
    --num_envs=1 \
    --device=cuda \
    --enable_cameras \
    --record \
    --dataset_file=./datasets/nemoclaw_pickorange.hdf5
```

Or record directly to LeRobot format:

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=openclaw \
    --openclaw_endpoint="tcp://0.0.0.0:5557" \
    --step_hz=60 \
    --num_envs=1 \
    --device=cuda \
    --enable_cameras \
    --record \
    --use_lerobot_recorder \
    --lerobot_dataset_repo_id=your-username/nemoclaw-pickorange \
    --lerobot_dataset_fps=30
```

### During Recording

| Key | Action |
|-----|--------|
| `N` | Mark episode as **success** and reset (saves demo) |
| `R` | Mark episode as **failed** and reset (discards demo) |

---

## Complete Pick Orange Sequence

Example step-by-step for picking one orange via NemoClaw:

```bash
SB="robotcontrol"

# 1. Position above the orange
nemoclaw $SB exec -- isaaclab-send '{"action": "forward", "params": {"distance": 0.25}}'
sleep 3

# 2. Open gripper
nemoclaw $SB exec -- isaaclab-send '{"action": "gripper_open", "params": {}}'
sleep 2

# 3. Lower to orange
nemoclaw $SB exec -- isaaclab-send '{"action": "down", "params": {"distance": 0.12}}'
sleep 2

# 4. Close gripper (grasp)
nemoclaw $SB exec -- isaaclab-send '{"action": "gripper_close", "params": {}}'
sleep 2

# 5. Lift up
nemoclaw $SB exec -- isaaclab-send '{"action": "up", "params": {"distance": 0.15}}'
sleep 2

# 6. Move to plate
nemoclaw $SB exec -- isaaclab-send '{"action": "right", "params": {"distance": 0.3}}'
sleep 3

# 7. Lower toward plate
nemoclaw $SB exec -- isaaclab-send '{"action": "down", "params": {"distance": 0.10}}'
sleep 2

# 8. Release orange
nemoclaw $SB exec -- isaaclab-send '{"action": "gripper_open", "params": {}}'
sleep 2

# 9. Lift away
nemoclaw $SB exec -- isaaclab-send '{"action": "up", "params": {"distance": 0.12}}'
sleep 2

# Repeat for remaining oranges...
```

---

## Troubleshooting

### NemoClaw can't reach the simulation

Check the ZMQ policy is applied:
```bash
nemoclaw robotcontrol policy-list | grep isaaclab-zmq
```

Test connectivity from inside the sandbox:
```bash
nemoclaw robotcontrol exec -- python3 -c "
import zmq
ctx = zmq.Context()
s = ctx.socket(zmq.PUB)
s.connect('tcp://host.openshell.internal:5557')
print('ZMQ connection OK')
s.close()
ctx.term()
"
```

### Simulation not responding to commands

Make sure the simulation is running and shows:
```
[OpenClawDevice] Listening for commands on tcp://0.0.0.0:5557
```

If it's stuck, press `B` in the Isaac Lab window to activate teleoperation mode.

### Helper scripts not found in sandbox

Redeploy them:
```bash
for script in isaaclab-send isaaclab-pick isaaclab-place; do
    cat ~/leisaac/nemoclaw-skill-isaaclab/$script | \
        nemoclaw robotcontrol exec -- bash -c "cat > /usr/local/bin/$script && chmod +x /usr/local/bin/$script"
done
```

### Port 5557 already in use

Change the ZMQ port:
```bash
ZMQ_PORT=5560 ./launch_nemoclaw_pickorange.sh
```

Or manually specify:
```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=openclaw \
    --openclaw_endpoint="tcp://0.0.0.0:5560" \
    ...
```

Update the helper scripts' HOST/PORT accordingly.

---

## Files Created

```
leisaac/
├── launch_nemoclaw_pickorange.sh          # One-command launcher
├── NEMOCLAW_PICKORANGE_WORKFLOW.md        # This document
└── nemoclaw-skill-isaaclab/
    ├── SKILL.md                           # NemoClaw agent skill definition
    ├── isaaclab-send                      # Single ZMQ command sender
    ├── isaaclab-pick                      # Compound pick action
    └── isaaclab-place                     # Compound place action
```
