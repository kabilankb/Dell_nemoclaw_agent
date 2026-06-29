"""Download real CC0 photographic PBR texture sets from ambientCG and rename
them into our convention: textures/real/<base>_{albedo,normal,roughness,ao}.png

ambientCG is CC0 (public domain). Each asset zip ships Color / NormalGL /
Roughness / AmbientOcclusion / Displacement PNGs. We keep the first four.
Run with system python3 (CPU only):  python3 warehouse_scene/fetch_real_textures.py
"""
import io
import os
import sys
import zipfile
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures", "real")
os.makedirs(OUT, exist_ok=True)

# base name -> ordered list of candidate ambientCG asset IDs (first that works wins)
ASSETS = {
    "concrete_floor": ["Concrete034", "Concrete033", "Concrete016"],
    "pallet_wood":    ["Planks011", "Planks016", "WoodFloor043"],
    "cardboard":      ["Cardboard004", "Cardboard003", "Cardboard001"],
    "wall_panel":     ["CorrugatedSteel005", "CorrugatedSteel007", "Metal032"],
    "painted_steel":  ["Metal032", "MetalPlates006", "Metal027"],
    "rack_steel":     ["Metal032", "MetalPlates006", "Metal027"],  # tinted orange in shader
}
RES = "2K-PNG"
MAP_KEYS = {  # ambientCG suffix -> our suffix
    "_Color.": "albedo",
    "_NormalGL.": "normal",
    "_Roughness.": "roughness",
    "_AmbientOcclusion.": "ao",
}


def fetch(asset_id):
    url = f"https://ambientcg.com/get?file={asset_id}_{RES}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def extract(base, asset_id, blob):
    got = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            for acg, ours in MAP_KEYS.items():
                if acg in name and name.lower().endswith(".png"):
                    data = z.read(name)
                    dst = os.path.join(OUT, f"{base}_{ours}.png")
                    with open(dst, "wb") as f:
                        f.write(data)
                    got[ours] = len(data)
    return got


def main():
    results = {}
    for base, candidates in ASSETS.items():
        ok = None
        for aid in candidates:
            try:
                print(f"[{base}] trying {aid} ...", flush=True)
                blob = fetch(aid)
                if len(blob) < 1000:
                    print(f"  {aid}: tiny response, skip")
                    continue
                got = extract(base, aid, blob)
                if "albedo" in got:
                    print(f"  OK {aid}: {sorted(got)}")
                    ok = (aid, got)
                    break
                print(f"  {aid}: no Color map in zip")
            except Exception as e:
                print(f"  {aid}: {type(e).__name__}: {e}")
        results[base] = ok
    print("\n=== SUMMARY ===")
    fails = 0
    for base, ok in results.items():
        if ok:
            print(f"  {base:16s} <- {ok[0]:18s} maps={sorted(ok[1])}")
        else:
            print(f"  {base:16s} <- FAILED")
            fails += 1
    print("DONE" if fails == 0 else f"DONE with {fails} failures")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
