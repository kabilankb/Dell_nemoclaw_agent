"""Generate tileable procedural textures for the warehouse scene (no external deps beyond PIL/numpy)."""
import numpy as np
from PIL import Image
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures")
os.makedirs(OUT, exist_ok=True)
RNG = np.random.default_rng(42)


def save(arr, name):
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    p = os.path.join(OUT, name)
    img.save(p)
    print("wrote", p, img.size)


def fbm(shape, octaves=5):
    """Simple fractal value noise in [0,1]."""
    h, w = shape
    out = np.zeros(shape, np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        step = 2 ** (o + 1)
        gh, gw = max(2, step), max(2, step)
        grid = RNG.random((gh, gw)).astype(np.float32)
        big = np.array(Image.fromarray((grid * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255.0
        out += amp * big
        norm += amp
        amp *= 0.5
    return out / norm


# --- Concrete floor: cool grey, subtle mottling, fine speckle ---
n = fbm((1024, 1024), 6)
base = 150 + (n - 0.5) * 38
speck = (RNG.random((1024, 1024)) > 0.985) * RNG.uniform(-25, 25, (1024, 1024))
g = base + speck
floor = np.stack([g * 0.97, g * 1.0, g * 1.04], -1)  # faint cool/blue tint
save(floor, "concrete_floor.png")

# --- Cardboard: tan/brown with horizontal fiber streaks ---
n = fbm((512, 512), 5)
fiber = np.sin(np.linspace(0, 60, 512))[None, :] * 4
b = 165 + (n - 0.5) * 30 + fiber
card = np.stack([b * 1.0, b * 0.82, b * 0.58], -1)
# packing-tape seam down the middle
card[:, 248:264] = card[:, 248:264] * 0.6 + np.array([150, 150, 150]) * 0.4
save(card, "cardboard.png")

# --- Painted steel rack: cool blue-grey, brushed vertical streaks ---
n = fbm((512, 512), 4)
streak = np.sin(np.linspace(0, 200, 512))[:, None] * 3
s = 120 + (n - 0.5) * 22 + streak
steel = np.stack([s * 0.86, s * 0.95, s * 1.08], -1)
save(steel, "painted_steel.png")

# --- Corrugated wall panel: light grey vertical ribs ---
x = np.linspace(0, np.pi * 32, 1024)
ribs = (np.sin(x) * 0.5 + 0.5)[None, :]
n = fbm((1024, 1024), 4)
w = 175 + ribs * 35 + (n - 0.5) * 12
wall = np.stack([w * 0.97, w * 1.0, w * 1.03], -1)
save(wall, "wall_panel.png")

# --- Pallet wood: warm planks ---
n = fbm((512, 512), 5)
plank = (np.floor(np.linspace(0, 6, 512)) % 2)[None, :] * 10
p = 150 + (n - 0.5) * 35 + plank
wood = np.stack([p * 1.0, p * 0.78, p * 0.5], -1)
save(wood, "pallet_wood.png")

print("done")
