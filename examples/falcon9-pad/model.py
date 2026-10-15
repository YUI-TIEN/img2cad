"""Falcon 9 v1.1 on the pad at dusk, from a real photo (scikit-image `rocket`, SpaceX, public domain).

Decompose, then measure the main bodies and use known sizes for the rest:

* Rocket: published Falcon 9 v1.1 dimensions (68.4 m tall, 3.66 m core,
  5.2 m fairing) set the scale: the rocket spans image rows 127 (fairing
  tip) to 405 (top of the launch mount) -> 246 mm/px. The camera is far
  away and level, so a front orthographic frame fits.
* Lightning towers: measured. Each is a tapered square lattice: base 8.6 m,
  top platform 3.7 m wide at 54 m, mast to 70 m; axes 32 m left and right of
  the rocket. Their lattice is one solid: a tapered shell with triangular
  windows cut through its faces (cheaper and more robust than fusing about a
  hundred struts).
* Transporter-erector strongback, launch mount and pad slab: simple boxes at
  their measured image extents.
"""

from build123d import *
from img2cad_lib import ImageFrame

S = 246.0  # mm per px
IMAGE_FRAME = ImageFrame(mm_per_px=S, origin_px=(321.5, 405.0))  # rocket base on the mount top

# Falcon 9 v1.1 (published dimensions, mm): (radius, z) half-profile from the base up.
CORE_R = 1830.0
FAIRING_R = 2600.0
STAGE1_TOP = 47000.0  # first stage + interstage
FAIRING_BASE = 55300.0
HEIGHT = 68400.0

TOWER_X = (-32300.0, 32800.0)  # measured axes: image x 190 and 455
MAST_X = (-30100.0, 30600.0)  # masts stand on the platforms' inner edges: image x 199 and 446
TOWER_BASE_HALF = 4300.0
TOWER_TOP_HALF = 1850.0
TOWER_TOP_Z = 53900.0  # platform, image row 186: (405 - 186) * S
MAST_TOP_Z = 70300.0  # image row 119
BAYS = 9
WALL = 450.0  # shell wall = strut depth
STRUT = 380.0  # strut width left between windows

MOUNT = (27500.0, 9000.0, 5400.0)  # launch mount: image x 268..380, rows 405..427
SLAB = (80000.0, 16000.0, 1000.0)

WHITE = Color(0.92, 0.92, 0.89)
STEEL = Color(0.45, 0.40, 0.33)
MAST = Color(0.70, 0.70, 0.68)
DARK = Color(0.22, 0.22, 0.24)
CONCRETE = Color(0.78, 0.66, 0.45)
GROUND = Color(0.42, 0.40, 0.36)


def rocket():
    with BuildPart() as part:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Line((0, 0), (CORE_R, 0))
                Line((CORE_R, 0), (CORE_R, FAIRING_BASE - 1500))
                Line((CORE_R, FAIRING_BASE - 1500), (FAIRING_R, FAIRING_BASE))
                Line((FAIRING_R, FAIRING_BASE), (FAIRING_R, FAIRING_BASE + 6500))
                Spline((FAIRING_R, FAIRING_BASE + 6500), (1700, HEIGHT - 1800), (0, HEIGHT),
                       tangents=((0, 1), (-1, 0)))
                Line((0, HEIGHT), (0, 0))
            make_face()
        revolve(axis=Axis.Z)
    body = part.part
    body.color, body.label = WHITE, "falcon 9"
    return body


def lattice_tower(x, mast_x, base_z):
    """Tapered square lattice from base_z up to the platform: a frustum shell with X-braced triangular windows."""
    height = TOWER_TOP_Z - base_z
    def square(z, half):
        return Plane.XY.offset(z) * Rectangle(2 * half, 2 * half)

    outer = loft([square(0, TOWER_BASE_HALF), square(height, TOWER_TOP_HALF)])
    inner = loft([square(-1, TOWER_BASE_HALF - WALL), square(height + 1, TOWER_TOP_HALF - WALL)])
    shell = outer - inner

    def half_at(z):
        return TOWER_BASE_HALF + (TOWER_TOP_HALF - TOWER_BASE_HALF) * z / height

    windows = []
    for bay in range(BAYS):
        z0, z1 = height * bay / BAYS, height * (bay + 1) / BAYS
        w0, w1 = half_at(z0), half_at(z1)
        quad = [(-w0, z0), (w0, z0), (w1, z1), (-w1, z1)]
        centre = (0.0, (z0 + z1) / 2)
        for i in range(4):
            a, b = quad[i], quad[(i + 1) % 4]
            tri = [a, b, centre]
            cx, cz = sum(p[0] for p in tri) / 3, sum(p[1] for p in tri) / 3
            # shrink toward the centroid so a strut of width STRUT remains on every edge
            size = max(abs(p[0] - cx) + abs(p[1] - cz) for p in tri)
            k = max(0.0, 1 - 2.2 * STRUT / size)
            windows.append([(cx + k * (p[0] - cx), cz + k * (p[1] - cz)) for p in tri])
    cutters = []
    for tri in windows:
        face = Polygon(*tri, align=None)
        # front/back faces: cut along Y; side faces: the same triangles along X
        cutters.append(extrude(Plane.XZ * face, amount=2 * TOWER_BASE_HALF, both=True))
        cutters.append(extrude(Plane.YZ * face, amount=2 * TOWER_BASE_HALF, both=True))
    lattice = shell - Compound(children=cutters)
    platform = Pos(0, 0, height) * Box(2 * TOWER_TOP_HALF + 600, 2 * TOWER_TOP_HALF + 600, 1500,
                                             align=(Align.CENTER, Align.CENTER, Align.MIN))
    tower = Pos(x, 0, base_z) * (lattice + platform)
    tower.color, tower.label = STEEL, f"lightning tower {'left' if x < 0 else 'right'}"
    mast = Pos(mast_x, 0, TOWER_TOP_Z + 1400) * Cone(700, 350, MAST_TOP_Z - TOWER_TOP_Z - 1400, align=(Align.CENTER, Align.CENTER, Align.MIN))
    mast.color, mast.label = MAST, f"lightning mast {'left' if x < 0 else 'right'}"
    return tower, mast


def build_model():
    body = rocket()
    # Strongback of the transporter-erector, standing just behind the rocket (dark edges in the photo).
    strongback = Pos(0, CORE_R + 700, 0) * Box(4400, 1400, STAGE1_TOP, align=(Align.CENTER, Align.CENTER, Align.MIN))
    strongback.color, strongback.label = DARK, "strongback"
    mount = Pos(0, 0, 0) * Box(*MOUNT, align=(Align.CENTER, Align.CENTER, Align.MAX))
    mount.color, mount.label = CONCRETE, "launch mount"
    slab = Pos(0, 0, -MOUNT[2]) * Box(*SLAB, align=(Align.CENTER, Align.CENTER, Align.MAX))
    slab.color, slab.label = GROUND, "pad"
    parts = [body, strongback, mount, slab]
    for x, mast_x in zip(TOWER_X, MAST_X):
        parts += list(lattice_tower(x, mast_x, -MOUNT[2]))
    return Compound(children=parts)
