#!/usr/bin/env python3
"""Check that Nebius Token Factory is reachable and the Nemotron models respond.

Usage:
    export NEBIUS_API_KEY=...        # from tokenfactory.nebius.com
    pip install openai
    python scripts/test_nebius.py
"""
import os
import sys
import time

from openai import OpenAI

BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
MODELS = [
    "nvidia/nemotron-3-super-120b-a12b",      # agent brain (tool calling)
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",  # fast, cheap calls
]

key = os.environ.get("NEBIUS_API_KEY")
if not key:
    sys.exit("Set NEBIUS_API_KEY first.")

client = OpenAI(base_url=BASE_URL, api_key=key)

# 1. List the NVIDIA models your key can see (confirms exact model IDs).
print(f"Token Factory: {BASE_URL}")
try:
    ids = sorted(m.id for m in client.models.list().data)
    nvidia = [i for i in ids if "nemotron" in i.lower() or i.lower().startswith("nvidia/")]
    print("NVIDIA models available:")
    for i in nvidia:
        print("  ", i)
except Exception as e:
    sys.exit(f"Could not list models: {e}")

# 2. Ask each model a robot-flavoured question.
prompt = ("You control a Unitree G1 humanoid in Isaac Sim. In one sentence, "
          "what would you do first to train it to walk on rough terrain?")
for model in MODELS:
    if model not in ids:
        print(f"\n[skip] {model} not in your model list — pick an ID from above.")
        continue
    t = time.time()
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,  # Super reasons before answering; 200 is used up by reasoning alone
    )
    print(f"\n[{model}] {time.time() - t:.1f}s, {r.usage.total_tokens} tokens")
    print(" ", (r.choices[0].message.content or "").strip())

print("\nOK — Token Factory works. Use NEBIUS_API_KEY with the 'nebius' profile.")
