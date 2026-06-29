"""Generate tileable 2K PBR texture sets (albedo + normal + roughness) for the
warehouse. Pure numpy/PIL, no Isaac needed. Run with system python3:

    python3 warehouse_scene/gen_textures_pbr.py

Outputs to warehouse_scene/textures/<name>_{albedo,normal,roughness}.png.
All maps are seamlessly tileable (noise built from periodic FFT) so they repeat
cleanly across large floors/walls. UsdPreviewSurface-compatible (linear normal,
grayscale roughness). NOTE: MDL is avoided on purpose — it renders black on
headless arm64.
"""
import os
import numpy as np
from PIL import Image

RES = 2048
TEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures")
os.makedirs(TEX_DIR, exist_ok=True)
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------------------
# Tileable value noise via summed periodic sine grids (seamless by construction)
# ---------------------------------------------------------------------------
def tileable_noise(res, freqs=(2, 4, 8, 16, 32, 64), seed=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:res, 0:res].astype(np.float32) / res * 2.0 * np.pi
    out = np.zeros((res, res), np.float32)
    amp = 1.0
    for f in freqs:
        ph1, ph2 = rng.uniform(0, 2 * np.pi, 2)
        out += amp * (np.sin(f * x + ph1) * np.sin(f * y + ph2))
        out += amp * 0.7 * np.sin(f * (x + y) * 0.5 + rng.uniform(0, 6.28))
        amp *= 0.55
    out -= out.min()
    out /= out.max() + 1e-9
    return out


def fbm(res, octaves=6, seed=0, persistence=0.55):
    """Fractal Brownian motion from tileable octaves -> [0,1]."""
    acc = np.zeros((res, res), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        acc += amp * tileable_noise(res, freqs=(2 ** (o + 1),), seed=seed + o)
        tot += amp
        amp *= persistence
    acc /= tot
    acc -= acc.min()
    acc /= acc.max() + 1e-9
    return acc


def height_to_normal(height, strength=2.0):
    """Sobel-style gradient -> tangent-space normal map (RGB 0..255)."""
    h = height.astype(np.float32)
    gx = np.roll(h, -1, 1) - np.roll(h, 1, 1)
    gy = np.roll(h, -1, 0) - np.roll(h, 1, 0)
    nx = -gx * strength
    ny = -gy * strength
    nz = np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-9
    nx, ny, nz = nx / ln, ny / ln, nz / ln
    rgb = np.stack([(nx * 0.5 + 0.5), (ny * 0.5 + 0.5), (nz * 0.5 + 0.5)], -1)
    return (rgb * 255).astype(np.uint8)


def save(name, suffix, arr):
    p = os.path.join(TEX_DIR, f"{name}_{suffix}.png")
    Image.fromarray(arr).save(p)
    return p


def write_set(name, albedo, height, rough, normal_strength=2.0):
    albedo = np.clip(albedo, 0, 1)
    save(name, "albedo", (albedo * 255).astype(np.uint8))
    save(name, "normal", height_to_normal(height, normal_strength))
    save(name, "roughness", (np.clip(rough, 0, 1) * 255).astype(np.uint8))
    print(f"  {name}: albedo+normal+roughness")


def tint(base, noise, lo=0.85, hi=1.12):
    """Multiply a base RGB by a per-pixel brightness from noise."""
    b = (lo + (hi - lo) * noise)[..., None]
    return np.array(base, np.float32)[None, None, :] / 255.0 * b


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
def concrete_floor():
    n = fbm(RES, octaves=7, seed=11)
    stains = fbm(RES, octaves=4, seed=23) ** 2.2
    base = tint((150, 150, 154), n, 0.78, 1.06)
    base *= (1.0 - 0.25 * stains)[..., None]                 # darker stains
    # expansion-joint grid lines
    grid = np.zeros((RES, RES), np.float32)
    step = RES // 4
    for k in range(0, RES, step):
        grid[max(0, k - 2):k + 2, :] = 1.0
        grid[:, max(0, k - 2):k + 2] = 1.0
    base *= (1.0 - 0.45 * grid)[..., None]
    height = n * 0.6 + grid * -0.5 + 0.4
    rough = 0.72 + 0.18 * stains - 0.1 * grid
    write_set("concrete_floor", base, height, rough, normal_strength=1.4)


def pallet_wood():
    n = fbm(RES, octaves=6, seed=31)
    # vertical planks with grain
    plank_w = RES // 6
    col = (np.arange(RES) // plank_w)
    plank_shade = (0.85 + 0.15 * ((col % 2)))[None, :]
    grain = np.sin((np.arange(RES)[None, :] % plank_w) / plank_w * np.pi * 14
                   + n * 4.0) * 0.5 + 0.5
    grain = grain * 0.3 + n * 0.7
    base = tint((150, 105, 60), grain, 0.7, 1.15) * plank_shade[..., None]
    gap = np.zeros((RES, RES), np.float32)
    for k in range(0, RES, plank_w):
        gap[:, max(0, k - 2):k + 2] = 1.0
    base *= (1.0 - 0.6 * gap)[..., None]
    height = grain * 0.7 - gap * 0.8 + 0.4
    rough = 0.6 + 0.25 * grain
    write_set("pallet_wood", base, height, rough, normal_strength=2.2)


def cardboard():
    n = fbm(RES, octaves=6, seed=41)
    corr = np.sin(np.arange(RES)[None, :] / RES * np.pi * 2 * 90) * 0.5 + 0.5
    mix = corr * 0.25 + n * 0.75
    base = tint((178, 140, 96), mix, 0.82, 1.1)
    height = corr * 0.35 + n * 0.65
    rough = np.full((RES, RES), 0.85, np.float32) - 0.08 * n
    write_set("cardboard", base, height, rough, normal_strength=1.2)


def painted_steel():
    n = fbm(RES, octaves=5, seed=51)
    scratch = (fbm(RES, octaves=3, seed=67) > 0.82).astype(np.float32)
    base = tint((58, 86, 120), n, 0.92, 1.06)               # industrial blue
    base = base * (1 - 0.3 * scratch)[..., None] + 0.3 * scratch[..., None]
    height = n * 0.3 + 0.5
    rough = 0.35 + 0.1 * n + 0.4 * scratch
    write_set("painted_steel", base, height, rough, normal_strength=1.0)


def rack_steel():
    n = fbm(RES, octaves=5, seed=59)
    base = tint((196, 120, 40), n, 0.9, 1.08)               # safety-orange racking
    height = n * 0.3 + 0.5
    rough = np.full((RES, RES), 0.45, np.float32) + 0.15 * n
    write_set("rack_steel", base, height, rough, normal_strength=1.0)


def wall_panel():
    # corrugated steel: vertical ribs
    ribs = np.sin(np.arange(RES)[None, :] / RES * np.pi * 2 * 48) * 0.5 + 0.5
    ribs = np.repeat(ribs, RES, axis=0)
    n = fbm(RES, octaves=4, seed=71)
    base = tint((205, 208, 214), ribs * 0.6 + n * 0.4, 0.8, 1.05)
    height = ribs * 0.9 + n * 0.1
    rough = 0.4 + 0.15 * n
    write_set("wall_panel", base, height, rough, normal_strength=2.6)


if __name__ == "__main__":
    print(f"Generating {RES}px PBR sets -> {TEX_DIR}")
    concrete_floor()
    pallet_wood()
    cardboard()
    painted_steel()
    rack_steel()
    wall_panel()
    print("DONE")
