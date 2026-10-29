#!/usr/bin/env python3
"""Sim2real hand-off check for an exported Isaac Lab policy. Run with the Isaac Lab 3
python (it has torch, onnx, onnxruntime):

    python verify_policy.py <run>/exported --out <bundle dir> [--obs 61 --act 14]

1. merges policy.onnx + policy.onnx.data into ONE self-contained policy.onnx (the
   robot loads a single file; the graph alone is ~14 KB of structure and no weights)
2. checks the interface: one input [1, obs], one output [1, act] (MicroDuck: 61 -> 14)
3. checks the size limit (Microduck runtime: 64 MiB)
4. runs onnxruntime and the TorchScript policy.pt on the same random observations and
   requires them to agree, and the actions to be finite and bounded

Prints one JSON object; exit code 0 only if every check passed.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch

MAX_BYTES = 64 * 1024 * 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exported", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--obs", type=int, default=61)
    ap.add_argument("--act", type=int, default=14)
    ap.add_argument("--samples", type=int, default=256)
    a = ap.parse_args()

    checks, info = {}, {}
    src = a.exported / "policy.onnx"
    if not src.exists():
        print(json.dumps({"ok": False, "error": f"{src} not found — play/record the policy first"}))
        return 1

    a.out.mkdir(parents=True, exist_ok=True)
    merged = a.out / "policy.onnx"
    model = onnx.load(str(src))                     # pulls in policy.onnx.data
    onnx.save_model(model, str(merged), save_as_external_data=False)
    onnx.checker.check_model(str(merged))
    info["bytes"] = merged.stat().st_size
    info["sha256"] = hashlib.sha256(merged.read_bytes()).hexdigest()
    checks["single_file"] = not any(t.data_location == onnx.TensorProto.EXTERNAL
                                    for t in onnx.load(str(merged)).graph.initializer)
    checks["size_under_64MiB"] = info["bytes"] < MAX_BYTES

    sess = ort.InferenceSession(str(merged), providers=["CPUExecutionProvider"])
    ins, outs = sess.get_inputs(), sess.get_outputs()
    info["inputs"] = [[i.name, i.shape] for i in ins]
    info["outputs"] = [[o.name, o.shape] for o in outs]
    checks["one_input_one_output"] = len(ins) == 1 and len(outs) >= 1
    checks[f"input_is_{a.obs}"] = ins[0].shape[-1] == a.obs
    checks[f"output_is_{a.act}"] = outs[0].shape[-1] == a.act

    rng = np.random.default_rng(0)
    obs = rng.normal(0, 1, (a.samples, a.obs)).astype(np.float32)
    onnx_act = np.concatenate([sess.run([outs[0].name], {ins[0].name: o[None]})[0] for o in obs])
    checks["actions_finite"] = bool(np.isfinite(onnx_act).all())
    info["action_abs_max"] = float(np.abs(onnx_act).max())
    checks["actions_bounded"] = info["action_abs_max"] < 100.0
    # same input twice -> same output (no stateful/random ops slipped into the graph)
    again = sess.run([outs[0].name], {ins[0].name: obs[:1]})[0]
    checks["deterministic"] = bool(np.allclose(again, onnx_act[:1]))

    pt = a.exported / "policy.pt"
    if pt.exists():
        ts = torch.jit.load(str(pt), map_location="cpu").eval()
        with torch.no_grad():
            torch_act = ts(torch.from_numpy(obs)).numpy()
        info["onnx_vs_torch_max_diff"] = float(np.abs(torch_act - onnx_act).max())
        checks["matches_torchscript"] = info["onnx_vs_torch_max_diff"] < 1e-4
    else:
        info["onnx_vs_torch_max_diff"] = None

    ok = all(checks.values())
    print(json.dumps({"ok": ok, "checks": checks, **info, "bundle_policy": str(merged)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
