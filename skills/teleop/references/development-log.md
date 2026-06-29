# NemoClaw + LeIsaac Vision-Guided Pick & Place -- Development Log

> **Platform:** DGX Spark | **Date:** 2026-05-25  
> **Goal:** Build a vision-guided robotic pick-and-place data collection pipeline  
> **Stack:** NemoClaw (nemotron-3-super:120b via Ollama) + LeIsaac (IsaacLab) + YOLO + ZMQ/HTTP

---

## 1. Architecture Overview

```
NemoClaw Sandbox ("robotcontrol")
  |
  |  HTTP POST (commands)          HTTP GET (detections)
  |  /sandbox/bin/isaaclab-send     /sandbox/bin/isaaclab-detect
  |        |                              |
  v        v                              v
+-------------------------------------------------------------+
|  VisionPublisher HTTP Server (port 5560)                     |
|    POST -> queue.Queue -> main loop -> OpenClawDevice        |
|    GET  -> latest JSON detection payload                     |
+-------------------------------------------------------------+
         |                                    |
         v                                    v
  OpenClawDevice (ZMQ SUB :5557)     YOLO Inference (front cam)
    -> delta-pose @ 60Hz               -> orange detection
    -> env.step()                       -> ground-truth positions
         |                                    |
         v                                    v
  IsaacLab SO101 Simulation          ZMQ PUB :5559 (detections)
    -> PickOrange-v0 task              -> JSON with positions,
    -> HDF5 data recording                distances, subtask status
```

### Port Map

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 5557 | ZMQ SUB  | bind      | Robot commands (OpenClawDevice) |
| 5558 | ZMQ PUB  | bind      | Execution status feedback |
| 5559 | ZMQ PUB  | bind      | Vision detections (raw) |
| 5560 | HTTP     | bind      | HTTP bridge for sandbox (GET detect, POST commands) |

### Action Vector Mapping (8-element delta-pose)

```
Index:  [dx, dy, dz, droll, dpitch, dyaw, d_shoulder_pan, d_gripper]

Action       -> Vector                              -> World Effect
forward      -> [0, 0, -1, 0, 0, 0, 0, 0]          -> mostly +Z (up)
backward     -> [0, 0, +1, 0, 0, 0, 0, 0]          -> mostly -Z (down)
up           -> [+1, 0, 0, 0, 0, 0, 0, 0]           -> +Z (up)
down         -> [-1, 0, 0, 0, 0, 0, 0, 0]           -> -Z (down)
left         -> [0, 0, 0, 0, 0, 0, -1, 0]           -> -X (shoulder pan)
right        -> [0, 0, 0, 0, 0, 0, +1, 0]           -> +X (shoulder pan)
turn_left    -> [0, 0, 0, 0, 0, +1, 0, 0]           -> +yaw rotation
turn_right   -> [0, 0, 0, 0, 0, -1, 0, 0]           -> -yaw rotation
gripper_open -> [0, 0, 0, 0, 0, 0, 0, +1]           -> open gripper
gripper_close-> [0, 0, 0, 0, 0, 0, 0, -1]           -> close gripper
```

**Important:** The `_convert_delta_from_frame()` in `device_base.py` transforms deltas from the end-effector frame to the robot base frame using quaternion rotation. This means the world effect of `forward`/`backward` varies with the current EE orientation. `up`/`down` map directly to world Z because the transform skips when `delta[:3]` and `delta[3:6]` are all zero (indices 6 and 7 pass through untransformed).

---

## 2. Key Files Modified

### `source/leisaac/leisaac/devices/openclaw/openclaw_device.py`

The core device that receives commands and converts them to timed delta-pose trajectories.

**Changes made:**

1. **Auto-start on first command** -- The device was not starting because `_started=False` in `device_base.py` and `advance()` returns `None` when not started. Previously required pressing keyboard 'B' to start.
   ```python
   def _process_command(self, cmd):
       if not self._started:
           self._started = True
   ```

2. **Gripper hold latch** -- Gripper was releasing between movement commands because `_remaining_steps` hit zero and delta reset to zeros. Added `_gripper_hold` to maintain close state.
   ```python
   self._gripper_hold = -0.05 if action == "gripper_close" else 0.0
   # Applied in get_device_state when idle:
   if self._remaining_steps <= 0 and self._gripper_hold != 0.0:
       delta[7] = self._gripper_hold
   ```

3. **Left/right action vectors** -- Attempted changing left/right from shoulder pan to Cartesian Y (`dy`), but reverted because `_convert_delta_from_frame()` makes local Y useless for consistent world-Y control. Shoulder pan provides reliable lateral movement.

### `source/leisaac/leisaac/devices/openclaw/vision_publisher.py`

Publishes YOLO-based orange detections and provides the HTTP bridge for sandbox communication.

**Changes made:**

1. **HTTP server on port 5560** -- Added `_start_http_server()` with GET (detections) and POST (commands) endpoints. Required because the NemoClaw sandbox blocks raw TCP/ZMQ traffic through its OpenShell proxy.

2. **HTTP/1.1 compliance** -- Added `Content-Length`, `Connection: close`, `protocol_version = "HTTP/1.1"`, and `wfile.flush()`. Without these, the OpenShell proxy stripped response bodies.

3. **YOLO class expansion** -- Changed from single class 49 ("orange") to `[32, 47, 49]` because simulated oranges are classified as class 32 ("sports ball") by YOLO11n. Added size filter (`w > 100 or h > 100`) to exclude the plate from detections.

4. **Fingertip position fix** -- Changed `_get_gripper_pos()` from `target_pos_w[0, 0]` (wrist) to `target_pos_w[0, 1]` (fingertip) to match the pick detection threshold check in `observations.py`.

5. **Command queue (latest fix)** -- Replaced broken ZMQ PUB forwarding with `queue.Queue()`. The anonymous `zmq.Context()` in the HTTP handler was getting garbage collected, silently killing the socket. Commands from HTTP POST are now queued and drained in the main simulation loop.

### `scripts/environments/teleoperation/teleop_se3_agent.py`

Main teleop loop that ties everything together.

**Changes made:**

1. **Vision publisher update moved** -- Moved `vision_publisher.update()` outside the `else` block so it runs every frame, not only when actions are non-None.

2. **Command queue drain** -- Added loop to drain pending HTTP commands from VisionPublisher and forward to OpenClawDevice's `_process_command()`:
   ```python
   for cmd in vision_publisher.drain_commands():
       teleop_interface._process_command(cmd)
   ```

### `nemoclaw-skill-isaaclab/` (all helper scripts)

All four helper scripts were rewritten from ZMQ to HTTP:

| Script | Purpose | Protocol Change |
|--------|---------|-----------------|
| `isaaclab-detect` | Get vision detections | ZMQ SUB -> HTTP GET `:5560/detect` |
| `isaaclab-send` | Send robot command | ZMQ PUB -> HTTP POST `:5560/command` |
| `isaaclab-pick` | Compound: down + close + up | ZMQ -> HTTP POST sequence |
| `isaaclab-place` | Compound: down + open + up | ZMQ -> HTTP POST sequence |

All scripts use `urllib.request` (stdlib) targeting `http://host.openshell.internal:5560/`.

### `nemoclaw-skill-isaaclab/SKILL.md`

Updated to instruct NemoClaw agent to use `exec` tool with full paths (`/sandbox/bin/isaaclab-*`). Added explicit instruction not to use Read/Write/file tools.

### `launch_nemoclaw_vision_pick.sh`

Launch script for the full pipeline.

**Changes made:**
- Deploy scripts to `/sandbox/bin/` (writable) instead of `/usr/local/bin/` (read-only)
- Fixed multi-line bash commands that NemoClaw exec rejected (newlines not allowed)
- Added `--resume` flag and auto-detection of existing HDF5 dataset
- Updated network policy to include port 5560 with REST protocol, GET and POST rules
- Added LeRobot recording format support (`--lerobot`, `--lerobot-repo`, `--lerobot-fps`)

---

## 3. Bugs Found & Fixed (Chronological)

### Bug 1: Script deployment -- permission denied
- **Symptom:** `/usr/local/bin/isaaclab-send: Permission denied` inside sandbox
- **Cause:** Sandbox user cannot write to `/usr/local/bin/`
- **Fix:** Deploy to `/sandbox/bin/` and use full paths in SKILL.md

### Bug 2: NemoClaw agent using wrong tools
- **Symptom:** Agent tried `Read` tool to read script files instead of executing them
- **Cause:** SKILL.md didn't restrict tool usage
- **Fix:** Added explicit instruction: "Use the `exec` tool to run all commands"

### Bug 3: Multi-line command rejection
- **Symptom:** `command argument contains newline or carriage return characters`
- **Cause:** NemoClaw `exec` API rejects newlines in command strings
- **Fix:** Replaced all multi-line heredocs/scripts with single-line commands

### Bug 4: Dataset file already exists
- **Symptom:** `AssertionError` on second launch because HDF5 file exists
- **Cause:** No resume support for existing datasets
- **Fix:** Added `--resume` flag and auto-detection of existing files

### Bug 5: Vision publisher not updating
- **Symptom:** Detection endpoint returned stale data, frame counter not advancing
- **Cause:** `vision_publisher.update()` was inside `else` block, only called when `actions is not None`
- **Fix:** Moved `update()` call outside the if/else to run every frame

### Bug 6: ZMQ blocked by sandbox firewall
- **Symptom:** Scripts hung or timed out when connecting to ZMQ ports
- **Cause:** OpenShell proxy blocks raw TCP; only HTTP is allowed outbound from sandbox
- **Fix:** Added HTTP bridge server on port 5560 in VisionPublisher

### Bug 7: HTTP empty response body
- **Symptom:** Detection GET returned empty body despite server sending data
- **Cause:** OpenShell proxy stripped body from HTTP/1.0 responses without Content-Length
- **Fix:** Set HTTP/1.1, added Content-Length header, Connection: close, flush()

### Bug 8: YOLO not detecting oranges
- **Symptom:** `yolo_count: 0` even with oranges visible in camera
- **Cause:** Simulated oranges classified as class 32 "sports ball", not class 49 "orange"
- **Fix:** Expanded COCO classes to `[32, 47, 49]`, added size filter >100px to exclude plate

### Bug 9: Robot not moving on first command
- **Symptom:** Commands received and processed, but `advance()` returned None
- **Cause:** `_started = False` in device_base.py; `advance()` early-returns None when not started
- **Fix:** Added auto-start in `_process_command()`: set `_started = True` on first command

### Bug 10: Left/right not moving in world Y
- **Symptom:** Left/right commands produced unexpected world movement
- **Cause:** Changed left/right to Cartesian Y but `_convert_delta_from_frame()` transforms Y into EE-relative direction
- **Fix:** Reverted to shoulder pan (index 6), which reliably provides world-X lateral movement

### Bug 11: Orange dropped during transport
- **Symptom:** Gripper opened between movement commands after successful grasp
- **Cause:** Gripper delta only applied for 1s duration, then reset to zero
- **Fix:** Added `_gripper_hold` latch -- maintains -0.05 on gripper channel when idle after close

### Bug 12: Distance reporting mismatch
- **Symptom:** Reported distance to orange didn't match pick detection threshold
- **Cause:** VisionPublisher used `target_pos_w[0, 0]` (wrist) but pick detection uses `target_pos_w[:, 1, :]` (fingertip)
- **Fix:** Changed to `target_pos_w[0, 1]` (fingertip frame)

### Bug 13: HTTP commands not reaching robot
- **Symptom:** HTTP POST returned success but robot didn't move; direct ZMQ from host worked fine
- **Cause:** Anonymous `zmq.Context()` in `_start_http_server()` garbage collected, killing the PUB socket silently
- **Fix:** Replaced ZMQ forwarding with `queue.Queue()`. HTTP handler puts commands in queue, main loop drains and forwards to `_process_command()` directly

---

## 4. Pick Detection Thresholds

From `source/leisaac/leisaac/tasks/pick_orange/mdp/observations.py`:

```
Pick threshold:  diff_threshold = 0.05  (5cm between fingertip and orange center)
Grasp threshold: grasp_threshold = 0.60 (gripper joint position < 0.60 = closed)
EE frame used:   ee_frame.data.target_pos_w[:, 1, :]  (index 1 = fingertip)
```

**Grasped = (position_diff < 0.05m) AND (gripper_joint_pos < 0.60)**

---

## 5. Known Issues & Limitations

### SO101 Arm Workspace Limit
The SO101 arm cannot reliably reach below Z ~0.95-0.98 in the simulation. Oranges spawn at Z ~0.919. The pick threshold requires <5cm distance. This makes picking borderline -- the arm occasionally achieves `[PICKED]` status but it's unreliable. May need to:
- Raise the table/orange spawn height in the task config
- Lower the arm's base position
- Increase the pick threshold (but this reduces training data quality)

### Command Recommendations in isaaclab-detect
The `decompose_relative()` function in `isaaclab-detect` gives incorrect movement recommendations because it assumes world-aligned axes. The actual action-to-world mapping is complex due to the EE frame quaternion transform. The raw positions and distances are accurate; only the suggested commands are wrong.

### No Direct World-Y Control
There is no action that reliably moves the gripper in world-Y direction. `left`/`right` use shoulder pan (world-X). `forward`/`backward` involve the EE frame transform and mostly affect world-Z. For Y-axis positioning, the robot must rotate (turn) and then use forward/backward.

### YOLO Classification
Simulated oranges are detected as COCO class 32 "sports ball" (60-80% confidence) rather than class 49 "orange". The expanded class list `[32, 47, 49]` handles this, with a size filter excluding the plate.

---

## 6. Testing Checklist

```
[ ] Simulation launches without errors
[ ] YOLO detects oranges (check yolo_count > 0)
[ ] HTTP GET /detect returns valid JSON with positions
[ ] HTTP POST /command returns {"status":"sent"}
[ ] Robot moves after HTTP POST command
[ ] Gripper maintains close state between movements
[ ] Auto-start works (no keyboard 'B' press needed)
[ ] isaaclab-detect works from sandbox
[ ] isaaclab-send works from sandbox
[ ] isaaclab-pick executes compound sequence
[ ] isaaclab-place executes compound sequence
[ ] Recording captures episodes to HDF5
[ ] Episode marking: N=success, R=failed
```

---

## 7. Quick Reference Commands

```bash
# Launch full pipeline
./launch_nemoclaw_vision_pick.sh

# Launch with LeRobot recording
./launch_nemoclaw_vision_pick.sh --lerobot --lerobot-repo your-name/pick-orange

# Test detection from host
curl http://127.0.0.1:5560/detect | python3 -m json.tool

# Send command from host
curl -X POST http://127.0.0.1:5560/command \
  -H "Content-Type: application/json" \
  -d '{"action":"forward","params":{"distance":0.5}}'

# Direct ZMQ command from host
python3 -c "
import zmq, json, time
ctx = zmq.Context()
pub = ctx.socket(zmq.PUB)
pub.connect('tcp://127.0.0.1:5557')
time.sleep(0.5)
pub.send(json.dumps({'action':'up','params':{'distance':0.05}}).encode())
pub.close(); ctx.term()
"

# Test from NemoClaw sandbox
nemoclaw robotcontrol exec -- /sandbox/bin/isaaclab-detect
nemoclaw robotcontrol exec -- /sandbox/bin/isaaclab-send '{"action":"up","params":{"distance":0.05}}'
nemoclaw robotcontrol exec -- /sandbox/bin/isaaclab-pick
nemoclaw robotcontrol exec -- /sandbox/bin/isaaclab-place
```

---

## 8. Data Flow Summary

```
User/NemoClaw Agent
  |
  | "Pick the closest orange"
  v
SKILL.md (isaaclab-robot-control)
  |
  | exec isaaclab-detect  ->  HTTP GET :5560  ->  VisionPublisher._latest_json
  | exec isaaclab-send    ->  HTTP POST :5560 ->  queue.Queue -> _process_command()
  | exec isaaclab-pick    ->  3x HTTP POST    ->  down + close + up sequence
  v
OpenClawDevice
  |
  | delta-pose [dx,dy,dz,droll,dpitch,dyaw,d_shoulder_pan,d_gripper]
  | -> _convert_delta_from_frame() (EE quaternion rotation)
  | -> timed trajectory (N steps at scale/step)
  v
env.step(actions)
  |
  | IsaacLab Differential IK solver
  v
SO101 Robot Arm (simulation)
  |
  | Joint positions recorded to HDF5 / LeRobot dataset
  v
Training Data for Action/Policy Models
```
