"""Cup side radii from silhouette edges, through the fitted perspective frame."""
import math, sys
import numpy as np
from scipy.optimize import least_squares
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "scripts"))
from img2cad_lib import ImageFrame

E, D, S, OX, OY, XC, YC = 57.153, 629.504, 0.301, 276.009, 235.405, 4.418, 7.625
F = ImageFrame(mm_per_px=S, origin_px=(OX, OY), view=(0, -math.cos(math.radians(E)), math.sin(math.radians(E))), distance=D)
EDGES = {120: (175, 406), 150: (181, 400), 180: (187, 394), 200: (199, 389), 220: (209, None)}

def silhouette_x(r, z, side):
    """Extreme image x of the circle (radius r, height z) on one side."""
    xs = [F.project(XC + r * math.cos(t), YC + r * math.sin(t), z) for t in np.linspace(0, 2 * math.pi, 360)]
    pick = max if side > 0 else min
    return pick(xs, key=lambda q: q[0])

for row, (left, right) in EDGES.items():
    for side, px in ((-1, left), (1, right)):
        if px is None:
            continue
        fit = least_squares(lambda v: [silhouette_x(v[0], v[1], side)[0] - px, silhouette_x(v[0], v[1], side)[1] - row], [30, 30])
        print(row, "left " if side < 0 else "right", "r=%.1f z=%.1f" % tuple(fit.x))
# lowest front point of the foot
fit = least_squares(lambda v: [F.project(XC, YC - v[0], v[1])[0] - 293, F.project(XC, YC - v[0], v[1])[1] - 285], [18, 4], bounds=([5, 3.9], [30, 4.1]))
print("foot front at z=4: r=%.1f" % fit.x[0])
print("crema far edge (287, 95): ", [round(v, 1) for v in F.on_plane_z(287, 95, 40)])
for z in (36, 38, 40, 42):
    far = F.on_plane_z(287, 95, z); left = F.on_plane_z(203, 150, z); right = F.on_plane_z(371, 150, z)
    print(z, "far r", round(math.hypot(far[0] - XC, far[1] - YC), 1), "left r", round(math.hypot(left[0] - XC, left[1] - YC), 1), "right r", round(math.hypot(right[0] - XC, right[1] - YC), 1))
