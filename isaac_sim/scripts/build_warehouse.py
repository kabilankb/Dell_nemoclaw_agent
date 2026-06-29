"""
Build a textured, lit warehouse USD set up for a future humanoid pick-and-place task.

Layout:
  - Larger hall (32 m x 9 m), wide central aisle.
  - Tall pallet racking on both sides (some bays intentionally left EMPTY).
  - A pick-and-place workstation in the aisle:
        SOURCE rack (small graspable boxes, dynamic rigid bodies) at y = -1.2
        DEST   rack (empty decks, placement targets)            at y = +1.2
  - Dome + ceiling rect lights + key distant light.

Runs inside Isaac Sim via the python_server. Pure pxr USD. Z-up, meters.
All boxes are origin-centered meshes positioned by an xformOp:translate, so
rigid bodies have a proper local frame (rotate about their own center).
Floor top surface is at z = 0.
"""
import os
from pxr import Usd, UsdGeom, UsdShade, UsdLux, UsdPhysics, Sdf, Gf

SCENE_DIR = "/home/dgx-destro/warehouse_nemoclaw/warehouse_scene"
TEX_DIR = os.path.join(SCENE_DIR, "textures")
REAL_DIR = os.path.join(TEX_DIR, "real")          # photographic CC0 PBR (ambientCG)
OUT_USD = os.path.join(SCENE_DIR, "warehouse.usd")


def texpath(base, suffix):
    """Prefer real photo texture; fall back to procedural. Returns abs path or None."""
    real = os.path.join(REAL_DIR, f"{base}_{suffix}.png")
    if os.path.exists(real):
        return real
    proc = os.path.join(TEX_DIR, f"{base}_{suffix}.png")
    return proc if os.path.exists(proc) else None

# ----------------------------------------------------------------------------
# Stage
# ----------------------------------------------------------------------------
stage = Usd.Stage.CreateInMemory()
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
world = UsdGeom.Xform.Define(stage, "/World")
stage.SetDefaultPrim(world.GetPrim())

LOOKS = "/World/Looks"
UsdGeom.Scope.Define(stage, LOOKS)

# ----------------------------------------------------------------------------
# Physics scene
# ----------------------------------------------------------------------------
scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
scene.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
scene.CreateGravityMagnitudeAttr(9.81)

# ----------------------------------------------------------------------------
# Materials
# ----------------------------------------------------------------------------
def _uv_tex(mpath, slot, abspath, st_out, colorspace="auto", scale=None, bias=None):
    """A UsdUVTexture sampler bound to the shared st reader, repeat-wrapped."""
    tex = UsdShade.Shader.Define(stage, f"{mpath}/{slot}")
    tex.CreateIdAttr("UsdUVTexture")
    tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(abspath)
    tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st_out)
    tex.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
    tex.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
    tex.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set(colorspace)
    if scale is not None:
        tex.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*scale))
    if bias is not None:
        tex.CreateInput("bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*bias))
    return tex


def make_textured_material(name, base, roughness=0.6, metallic=0.0, tint=(1, 1, 1),
                           normal=True, rough_map=True):
    """Full-PBR UsdPreviewSurface: albedo + normal + roughness + AO maps.

    Headless-safe (NOT MDL — MDL renders black on headless arm64). Prefers real
    photographic textures in textures/real/, falls back to procedural. Tiling is
    carried by the mesh `st` primvar (tiles_per_m); textures just repeat.
    """
    mpath = f"{LOOKS}/{name}"
    mat = UsdShade.Material.Define(stage, mpath)
    pbr = UsdShade.Shader.Define(stage, f"{mpath}/Shader")
    pbr.CreateIdAttr("UsdPreviewSurface")
    pbr.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
    pbr.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)

    st_reader = UsdShade.Shader.Define(stage, f"{mpath}/stReader")
    st_reader.CreateIdAttr("UsdPrimvarReader_float2")
    st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    st_out = st_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    # Albedo (sRGB), tintable
    p_alb = texpath(base, "albedo")
    if p_alb:
        alb = _uv_tex(mpath, "albedoTex", p_alb, st_out, colorspace="sRGB",
                      scale=(tint[0], tint[1], tint[2], 1.0))
        pbr.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
            alb.CreateOutput("rgb", Sdf.ValueTypeNames.Float3))

    # Normal map (raw, remap 0..1 -> -1..1)
    p_nrm = texpath(base, "normal")
    if normal and p_nrm:
        nrm = _uv_tex(mpath, "normalTex", p_nrm, st_out, colorspace="raw",
                      scale=(2.0, 2.0, 2.0, 1.0), bias=(-1.0, -1.0, -1.0, 0.0))
        pbr.CreateInput("normal", Sdf.ValueTypeNames.Normal3f).ConnectToSource(
            nrm.CreateOutput("rgb", Sdf.ValueTypeNames.Float3))

    # Roughness map (raw, .r), else scalar fallback
    p_rgh = texpath(base, "roughness")
    if rough_map and p_rgh:
        rgh = _uv_tex(mpath, "roughTex", p_rgh, st_out, colorspace="raw")
        pbr.CreateInput("roughness", Sdf.ValueTypeNames.Float).ConnectToSource(
            rgh.CreateOutput("r", Sdf.ValueTypeNames.Float))
    else:
        pbr.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)

    # Ambient occlusion (raw, .r) -> contact-shadow realism (real sets only)
    p_ao = texpath(base, "ao")
    if p_ao:
        ao = _uv_tex(mpath, "aoTex", p_ao, st_out, colorspace="raw")
        pbr.CreateInput("occlusion", Sdf.ValueTypeNames.Float).ConnectToSource(
            ao.CreateOutput("r", Sdf.ValueTypeNames.Float))

    mat.CreateSurfaceOutput().ConnectToSource(pbr.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    return mat


def make_emissive_material(name, color=(1.0, 0.96, 0.85), intensity=1.0):
    mpath = f"{LOOKS}/{name}"
    mat = UsdShade.Material.Define(stage, mpath)
    pbr = UsdShade.Shader.Define(stage, f"{mpath}/Shader")
    pbr.CreateIdAttr("UsdPreviewSurface")
    pbr.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    pbr.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(color[0]*intensity, color[1]*intensity, color[2]*intensity))
    pbr.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.4)
    mat.CreateSurfaceOutput().ConnectToSource(pbr.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    return mat


def make_color_material(name, color, roughness=0.7, metallic=0.0):
    mpath = f"{LOOKS}/{name}"
    mat = UsdShade.Material.Define(stage, mpath)
    pbr = UsdShade.Shader.Define(stage, f"{mpath}/Shader")
    pbr.CreateIdAttr("UsdPreviewSurface")
    pbr.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    pbr.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    pbr.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
    mat.CreateSurfaceOutput().ConnectToSource(pbr.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    return mat


MAT = {
    "floor":  make_textured_material("Concrete", "concrete_floor"),
    "card":   make_textured_material("Cardboard", "cardboard"),
    "card2":  make_textured_material("Cardboard2", "cardboard", tint=(0.82, 0.74, 0.62)),
    "steel":  make_textured_material("PaintedSteel", "painted_steel", metallic=0.5),
    "rack":   make_textured_material("RackSteel", "rack_steel", metallic=0.35),
    "wall":   make_textured_material("WallPanel", "wall_panel", metallic=0.3),
    "wood":   make_textured_material("PalletWood", "pallet_wood"),
    "lamp":   make_emissive_material("LampPanel", color=(1.0, 0.97, 0.9), intensity=1.0),
    "ceil":   make_color_material("Ceiling", (0.30, 0.32, 0.36), roughness=0.85),
    "lane":   make_color_material("LaneYellow", (0.88, 0.72, 0.10), roughness=0.55),
    "plastic":make_color_material("Shrinkwrap", (0.72, 0.74, 0.77), roughness=0.20, metallic=0.1),
}
# Bright, distinct colors for the small pickable boxes
SMALL_MATS = [
    make_color_material("Pick_Red",    (0.75, 0.12, 0.12), roughness=0.6),
    make_color_material("Pick_Blue",   (0.12, 0.28, 0.72), roughness=0.6),
    make_color_material("Pick_Green",  (0.13, 0.55, 0.22), roughness=0.6),
    make_color_material("Pick_Yellow", (0.85, 0.7, 0.1),   roughness=0.6),
    make_color_material("Pick_Orange", (0.85, 0.4, 0.1),   roughness=0.6),
    make_color_material("Pick_Teal",   (0.1, 0.6, 0.6),    roughness=0.6),
]

# ----------------------------------------------------------------------------
# Origin-centered box mesh with per-face UVs + normals; positioned by translate.
# ----------------------------------------------------------------------------
_FACES = [
    ((0, 0, 1),  [(-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)], (0, 1)),
    ((0, 0,-1),  [(-.5,.5,-.5),(.5,.5,-.5),(.5,-.5,-.5),(-.5,-.5,-.5)], (0, 1)),
    ((1, 0, 0),  [(.5,-.5,-.5),(.5,.5,-.5),(.5,.5,.5),(.5,-.5,.5)], (1, 2)),
    ((-1,0, 0),  [(-.5,.5,-.5),(-.5,-.5,-.5),(-.5,-.5,.5),(-.5,.5,.5)], (1, 2)),
    ((0, 1, 0),  [(.5,.5,-.5),(-.5,.5,-.5),(-.5,.5,.5),(.5,.5,.5)], (0, 2)),
    ((0,-1, 0),  [(-.5,-.5,-.5),(.5,-.5,-.5),(.5,-.5,.5),(-.5,-.5,.5)], (0, 2)),
]

def make_box(path, center, size, material, tiles_per_m=0.5, collider=None,
             dynamic=False, mass=2.0):
    sx, sy, sz = size
    pts, nrm, st, counts, idx = [], [], [], [], []
    vi = 0
    dims = (sx, sy, sz)
    for normal, corners, (ua, va) in _FACES:
        for (ox, oy, oz) in corners:
            pts.append(Gf.Vec3f(ox * sx, oy * sy, oz * sz))   # origin-centered
            nrm.append(Gf.Vec3f(*normal))
        ud, vd = dims[ua] * tiles_per_m, dims[va] * tiles_per_m
        st += [Gf.Vec2f(0, 0), Gf.Vec2f(ud, 0), Gf.Vec2f(ud, vd), Gf.Vec2f(0, vd)]
        counts.append(4)
        idx += [vi, vi + 1, vi + 2, vi + 3]
        vi += 4

    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(pts)
    mesh.CreateFaceVertexCountsAttr(counts)
    mesh.CreateFaceVertexIndicesAttr(idx)
    mesh.CreateNormalsAttr(nrm)
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    mesh.CreateExtentAttr([Gf.Vec3f(-sx/2, -sy/2, -sz/2), Gf.Vec3f(sx/2, sy/2, sz/2)])
    pv = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    pv.Set(st)
    UsdGeom.Xformable(mesh).AddTranslateOp().Set(Gf.Vec3d(*center))
    UsdShade.MaterialBindingAPI(mesh).Bind(material)

    if collider:
        UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        mca = UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim())
        mca.CreateApproximationAttr().Set(collider)
        if dynamic:
            UsdPhysics.RigidBodyAPI.Apply(mesh.GetPrim())
            UsdPhysics.MassAPI.Apply(mesh.GetPrim()).CreateMassAttr().Set(float(mass))
    return mesh

# ----------------------------------------------------------------------------
# Hall dimensions (bigger)
# ----------------------------------------------------------------------------
env = UsdGeom.Xform.Define(stage, "/World/Warehouse")
X0, X1 = -2.0, 30.0          # 32 m long
YW = 4.5                      # 9 m wide (half = 4.5)
CEIL_Z = 6.8
stats = {"big_boxes": 0, "small_boxes": 0, "empty_bays": 0, "empty_decks": 0}

# Floor (top at z=0)
make_box("/World/Warehouse/Floor", ((X0+X1)/2, 0.0, -0.1), (X1 - X0, YW * 2, 0.2),
         MAT["floor"], tiles_per_m=0.35, collider="boundingCube")

# Yellow aisle guide lines
for sgn in (1, -1):
    make_box(f"/World/Warehouse/Lane_{'p' if sgn>0 else 'n'}", ((X0+X1)/2, sgn * 2.45, 0.005),
             (X1 - X0 - 1.0, 0.08, 0.012), MAT["lane"], tiles_per_m=1.0)

# Ceiling + walls
make_box("/World/Warehouse/Ceiling", ((X0+X1)/2, 0.0, CEIL_Z + 0.1), (X1 - X0, YW * 2, 0.2),
         MAT["ceil"], tiles_per_m=0.5)
make_box("/World/Warehouse/EndWall", (X1, 0.0, CEIL_Z/2), (0.2, YW * 2, CEIL_Z),
         MAT["wall"], tiles_per_m=0.5, collider="boundingCube")
make_box("/World/Warehouse/BackWall", (X0, 0.0, CEIL_Z/2), (0.2, YW * 2, CEIL_Z),
         MAT["wall"], tiles_per_m=0.5, collider="boundingCube")
for sgn in (1, -1):
    make_box(f"/World/Warehouse/SideWall_{'p' if sgn>0 else 'n'}",
             ((X0+X1)/2, sgn * (YW - 0.05), CEIL_Z/2), (X1 - X0, 0.1, CEIL_Z),
             MAT["wall"], tiles_per_m=0.5, collider="boundingCube")

# ----------------------------------------------------------------------------
# Tall pallet racking (with intentionally empty bays / shelves)
# ----------------------------------------------------------------------------
N_BAYS = 9
BAY_W = 3.0
RACK_H = 6.0
DEPTH = 1.05
FRONT_Y = 2.6
UPRIGHT = 0.12
LEVELS = [0.15, 1.95, 3.6, 5.25]
EMPTY_BAYS = {2, 5, 7}        # whole bays kept clear
box_palette = ["card", "card2", "card", "plastic"]

def build_rack(side):
    sgn = side
    tag = "L" if side > 0 else "R"
    y_center = sgn * (FRONT_Y + DEPTH / 2)
    UsdGeom.Xform.Define(stage, f"/World/Warehouse/Rack_{tag}")
    for b in range(N_BAYS + 1):
        x = b * BAY_W
        for dy in (-DEPTH/2, DEPTH/2):
            make_box(f"/World/Warehouse/Rack_{tag}/Up_{b}_{'f' if dy<0 else 'b'}",
                     (x, y_center + dy, RACK_H/2), (UPRIGHT, UPRIGHT, RACK_H),
                     MAT["rack"], tiles_per_m=1.0, collider="boundingCube")
    for b in range(N_BAYS):
        xc = b * BAY_W + BAY_W / 2
        for li, lz in enumerate(LEVELS):
            for dy in (-DEPTH/2, DEPTH/2):
                make_box(f"/World/Warehouse/Rack_{tag}/Beam_{b}_{int(lz*100)}_{'f' if dy<0 else 'b'}",
                         (xc, y_center + dy, lz), (BAY_W, 0.10, 0.12),
                         MAT["rack"], tiles_per_m=1.0, collider="boundingCube")
            make_box(f"/World/Warehouse/Rack_{tag}/Deck_{b}_{int(lz*100)}",
                     (xc, y_center, lz + 0.07), (BAY_W - 0.12, DEPTH, 0.05),
                     MAT["wood"], tiles_per_m=0.8, collider="boundingCube")
            # Leave whole bays empty, and the top shelf empty on odd bays -> empty racks
            empty = (b in EMPTY_BAYS) or (li == len(LEVELS) - 1 and b % 2 == 1)
            if empty:
                if b in EMPTY_BAYS and li == 0:
                    stats["empty_bays"] += 1
                stats["empty_decks"] += 1
                continue
            deck_top = lz + 0.07 + 0.025
            for i, fx in enumerate((-0.62, 0.0, 0.62)):
                bw, bd, bh = 0.78, 0.85, 0.62
                mat = MAT[box_palette[(b + i + (0 if side > 0 else 2)) % len(box_palette)]]
                make_box(f"/World/Warehouse/Rack_{tag}/Box_{b}_{int(lz*100)}_{i}",
                         (xc + fx * (BAY_W/3), y_center, deck_top + bh/2),
                         (bw, bd, bh), mat, tiles_per_m=0.8, collider="boundingCube")
                stats["big_boxes"] += 1

build_rack(+1)
build_rack(-1)

# ----------------------------------------------------------------------------
# Pick-and-place workstation (humanoid stands at y=0 between the two racks)
# ----------------------------------------------------------------------------
PICK = UsdGeom.Xform.Define(stage, "/World/PickPlace")
WS_X = 6.0                      # workstation center along the aisle
SHELF_W, SHELF_D = 1.6, 0.6     # small rack footprint (X, Y)
SHELF_LEVELS = [0.38, 0.62]     # waist/low-chest height — reachable by the G1 (~1.3 m tall)
SMALL = (0.16, 0.16, 0.14)      # graspable box size

def make_small_rack(name, cx, cy):
    base = f"/World/PickPlace/{name}"
    UsdGeom.Xform.Define(stage, base)
    H = SHELF_LEVELS[-1] + 0.2
    for ox in (-SHELF_W/2, SHELF_W/2):
        for oy in (-SHELF_D/2, SHELF_D/2):
            make_box(f"{base}/leg_{'p' if ox>0 else 'n'}{'p' if oy>0 else 'n'}",
                     (cx + ox, cy + oy, H/2), (0.06, 0.06, H),
                     MAT["steel"], tiles_per_m=1.0, collider="boundingCube")
    for lz in SHELF_LEVELS:
        make_box(f"{base}/deck_{int(lz*100)}", (cx, cy, lz),
                 (SHELF_W, SHELF_D, 0.04), MAT["wood"], tiles_per_m=1.0,
                 collider="boundingCube")
    return base

# SOURCE rack with small graspable boxes (dynamic rigid bodies)
src = make_small_rack("SourceRack", WS_X, -1.2)
n = 0
for lz in SHELF_LEVELS:
    deck_top = lz + 0.02
    for i, fx in enumerate((-0.5, -0.1, 0.3, 0.62)):
        mat = SMALL_MATS[n % len(SMALL_MATS)]
        z = deck_top + SMALL[2] / 2 + 0.003
        make_box(f"/World/PickPlace/SourceRack/pick_{n:02d}",
                 (WS_X + fx, -1.2, z), SMALL, mat, tiles_per_m=2.0,
                 collider="convexHull", dynamic=True, mass=0.3)
        stats["small_boxes"] += 1
        n += 1

# DESTINATION rack: empty decks = placement targets
make_small_rack("DestRack", WS_X, 1.2)
# thin visual target pads on the dest decks (static, no collision conflict)
for j, lz in enumerate(SHELF_LEVELS):
    make_box(f"/World/PickPlace/DestRack/target_{j}", (WS_X, 1.2, lz + 0.021 + 0.001),
             (0.5, 0.5, 0.002), SMALL_MATS[2], tiles_per_m=1.0)

# ----------------------------------------------------------------------------
# Lights
# ----------------------------------------------------------------------------
# Calibrated for ACES tonemap (filmIso 600) per isaac-sim-rendering skill.
# Previous values (dome 2400, rect 60000) were ~16x too hot -> pure-white clip.
UsdGeom.Xform.Define(stage, "/World/Lights")
dome = UsdLux.DomeLight.Define(stage, "/World/Lights/Dome")
dome.CreateIntensityAttr(180.0)                       # low ambient; let fixtures work
dome.CreateColorAttr(Gf.Vec3f(0.82, 0.86, 0.95))      # cool fill
dome.CreateExposureAttr(0.0)

# Two staggered rows of ceiling fixtures for even aisle coverage + light pools.
n_lamps = 10
for i in range(n_lamps):
    lx = 1.5 + i * ((X1 - 2.0) / n_lamps)
    for row, ly in enumerate((-1.6, 1.6)):
        make_box(f"/World/Warehouse/Lamp_{i}_{row}", (lx, ly, CEIL_Z - 0.15),
                 (1.4, 0.5, 0.10), MAT["lamp"], tiles_per_m=1.0)
        rect = UsdLux.RectLight.Define(stage, f"/World/Lights/Rect_{i}_{row}")
        rect.CreateWidthAttr(1.4)
        rect.CreateHeightAttr(0.5)
        rect.CreateIntensityAttr(14000.0)             # bright pools, not floods
        rect.CreateColorAttr(Gf.Vec3f(0.98, 0.97, 0.92))  # warm fixture
        rect.CreateExposureAttr(0.0)
        UsdLux.ShapingAPI.Apply(rect.GetPrim())
        UsdGeom.Xformable(rect.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(lx, ly, CEIL_Z - 0.30))

# Soft key for directional shading (mostly skylight-style fill on upper structure).
dist = UsdLux.DistantLight.Define(stage, "/World/Lights/Key")
dist.CreateIntensityAttr(900.0)
dist.CreateColorAttr(Gf.Vec3f(0.95, 0.93, 0.85))
dist.CreateAngleAttr(1.5)
UsdGeom.Xformable(dist.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3d(-55, 0, 20))

# ----------------------------------------------------------------------------
# Unitree G1 humanoid — referenced from the NVIDIA asset root (streams meshes +
# materials at load). Resolves the configured root at runtime; falls back to the
# verified S3 URL. Stands in the aisle at the pick-and-place workstation.
# ----------------------------------------------------------------------------
def _assets_root():
    try:
        from isaacsim.storage.native import get_assets_root_path
        r = get_assets_root_path()
        if r:
            return r.rstrip("/")
    except Exception:
        pass
    return "https://omniverse-content-staging.s3.us-west-2.amazonaws.com/Assets/Isaac/6.0"


G1_USD = f"{_assets_root()}/Isaac/Robots/Unitree/G1/g1.usd"
UsdGeom.Xform.Define(stage, "/World/Robots")
_g1 = stage.OverridePrim("/World/Robots/G1")          # 'over' lets the ref supply the type/articulation
_g1.GetReferences().AddReference(G1_USD)
_g1x = UsdGeom.Xformable(_g1)
_g1x.ClearXformOpOrder()
_g1x.AddTranslateOp().Set(Gf.Vec3d(WS_X, 0.0, 0.74))  # feet on floor (pelvis ~0.74 m)
_g1x.AddRotateZOp().Set(-90.0)                         # face the SOURCE rack (y = -1.2)
print(f"G1 referenced from {G1_USD}")

# ----------------------------------------------------------------------------
# Save
# ----------------------------------------------------------------------------
stage.Export(OUT_USD)
total = len(list(stage.Traverse()))
print(f"SAVED {OUT_USD}")
print(f"PRIMS {total}  BIG_BOXES {stats['big_boxes']}  SMALL_PICK_BOXES {stats['small_boxes']}")
print(f"EMPTY_BAYS {stats['empty_bays']}  EMPTY_DECKS {stats['empty_decks']}  LAMPS {n_lamps}")
print(f"WORKSTATION at x={WS_X}: SourceRack y=-1.2 (boxes), DestRack y=+1.2 (empty)")
print("DONE_BUILD")
