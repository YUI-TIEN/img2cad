"""Fit the photo's camera to the two rims (circles at known/unknown heights).

Saucer rim: radius 60 mm at z = 12 around the origin (assumed size: sets the scale).
Cup rim: unknown radius R at unknown height H around (xc, yc).
Unknowns: elevation, camera distance, mm/px, origin pixel, xc, yc, R, H.
"""
import json, math, sys
import numpy as np
from scipy.optimize import least_squares
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "scripts"))
from img2cad_lib import ImageFrame

RIM_PX = [(173,100),(290,18),(408,100),(195,47),(385,47),(300,207),(220,190),(380,185)]
FOOT_PX = [(255, 280), (275, 283), (293, 284), (312, 283), (330, 281)]  # visible front arc of the cup foot (z = 4)
SAUCER_PX = [(76,225),(150,88),(172,75),(425,108),(465,165),(479,230),(440,325),(380,370),(280,389),(88,290)]
T = np.linspace(0, 2 * math.pi, 720, endpoint=False)

def frame(p):
    elev, dist, s, ox, oy = p[:5]
    e = math.radians(elev)
    return ImageFrame(mm_per_px=s, origin_px=(ox, oy), view=(0, -math.cos(e), math.sin(e)), distance=dist)

def curve(f, cx, cy, r, z):
    return np.array([f.project(cx + r * math.cos(t), cy + r * math.sin(t), z) for t in T])

def residuals(p):
    f = frame(p)
    xc, yc, R, H, RF = p[5:]
    out = []
    foot = curve(f, xc, yc, RF, 4.0)
    foot = foot[[i for i, t in enumerate(T) if math.sin(t) < -0.5]]  # front arc only
    for pts, c in ((SAUCER_PX, curve(f, 0, 0, 60, 12)), (RIM_PX, curve(f, xc, yc, R, H)), (FOOT_PX, foot)):
        for q in pts:
            out.append(np.min(np.hypot(c[:, 0] - q[0], c[:, 1] - q[1])))
    return out

p0 = [55, 400, 0.3, 275, 250, 5, 0, 35, 65, 18]
fit = least_squares(residuals, p0, bounds=([30, 120, 0.15, 200, 150, -20, -20, 25, 30, 8], [80, 5000, 0.5, 350, 350, 20, 30, 45, 100, 30]))
names = ["elevation", "distance", "mm_per_px", "origin_x", "origin_y", "cup_x", "cup_y", "rim_r", "rim_z", "foot_r"]
result = dict(zip(names, [round(float(v), 3) for v in fit.x]))
result["rms_px"] = round(float(np.sqrt(np.mean(np.square(fit.fun)))), 2)
result["max_px"] = round(float(np.max(fit.fun)), 2)
print(json.dumps(result, indent=1))
# orthographic comparison
fit_o = least_squares(lambda q: residuals([q[0], 1e7, *q[1:]]), [55, 0.3, 275, 250, 5, 0, 35, 65, 18])
print("orthographic rms_px", round(float(np.sqrt(np.mean(np.square(fit_o.fun)))), 2), [round(float(v), 2) for v in fit_o.x])
