#!/usr/bin/env python3
"""3D-printability check for a STEP or STL file (FDM defaults).

    img2cad printcheck model.step
    img2cad printcheck model.stl --build-volume 220,220,250 --min-wall 0.8 --overhang 45

Checks, each with a status of pass, warn or fail:

* `watertight`   every mesh edge is shared by exactly two triangles (no holes, no non-manifold edges)
* `solids`       one connected shell per printed part (a STEP with several parts is checked per part
                 by the kernel; loose shells in a mesh are reported)
* `build_volume` the bounding box fits the printer, in the orientation given (Z up)
* `overhangs`    area of downward faces steeper than the overhang angle that do not sit on the bed;
                 these need supports
* `bed_contact`  area touching the bed (z = min); a tiny footprint tips over or detaches
* `thin_walls`   sampled wall thickness along inward normals below `--min-wall`

The mesh is the same tessellation the exports use, so results describe what a
slicer will receive. Thickness is sampled (ray casts from up to 4000 triangle
centres), so treat it as a warning, not a proof.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct
from typing import Any

import numpy as np


def load_parts(path: Path, tolerance: float | None = None) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """[(name, vertices N x 3, triangles M x 3)] in millimetres; one entry per STEP part, one for an STL."""
    if path.suffix.lower() == ".stl":
        return [(path.stem, *read_stl(path))]
    from build123d import import_step

    from inspect_step import leaf_parts
    from mesh_export import default_tolerance

    shape = import_step(str(path))
    tolerance = tolerance or default_tolerance(shape)
    parts = []
    for index, part in enumerate(leaf_parts(shape)):
        vertices, triangles = part.tessellate(tolerance, 0.2)
        if not triangles:
            continue
        corners = np.array([(v.X, v.Y, v.Z) for v in vertices], dtype=float)[np.array(triangles, dtype=np.int64)].reshape(-1, 3)
        parts.append((getattr(part, "label", "") or f"part {index + 1}", *weld(corners)))
    return parts


def read_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    if len(data) >= 84 and 84 + 50 * struct.unpack_from("<I", data, 80)[0] == len(data):
        count = struct.unpack_from("<I", data, 80)[0]
        records = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=count, offset=84)
        corners = records["v"].reshape(-1, 3).astype(float)
    else:
        corners = np.array([[float(value) for value in line.split()[1:4]] for line in data.decode("utf-8", "replace").splitlines()
                            if line.strip().startswith("vertex")], dtype=float)
    return weld(corners)


def weld(corners: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Merge identical triangle corners (faces are tessellated separately) so shared edges match."""
    unique, inverse = np.unique(np.round(corners, 4), axis=0, return_inverse=True)
    triangles = inverse.reshape(-1, 3)
    keep = (triangles[:, 0] != triangles[:, 1]) & (triangles[:, 1] != triangles[:, 2]) & (triangles[:, 0] != triangles[:, 2])
    return unique, triangles[keep]


def triangle_geometry(vertices: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    a, b, c = (vertices[triangles[:, i]] for i in range(3))
    cross = np.cross(b - a, c - a)
    area2 = np.linalg.norm(cross, axis=1)
    normals = cross / np.maximum(area2, 1e-12)[:, None]
    return normals, area2 / 2, (a + b + c) / 3


def edge_report(triangles: np.ndarray) -> dict[str, int]:
    edges = np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1)
    counts = Counter(map(tuple, edges.tolist()))
    return {"open_edges": sum(1 for n in counts.values() if n == 1), "non_manifold_edges": sum(1 for n in counts.values() if n > 2)}


def shell_count(vertex_count: int, triangles: np.ndarray) -> int:
    parent = list(range(vertex_count))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, c in triangles.tolist():
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    return len({find(v) for v in set(triangles.ravel().tolist())})


def ray_hits(origins: np.ndarray, directions: np.ndarray, vertices: np.ndarray, triangles: np.ndarray, chunk: int = 64) -> np.ndarray:
    """Distance to the nearest triangle along each ray (inf if none), Möller-Trumbore."""
    a, b, c = (vertices[triangles[:, i]] for i in range(3))
    e1, e2 = b - a, c - a
    best = np.full(len(origins), np.inf)
    for start in range(0, len(origins), chunk):
        o = origins[start:start + chunk, None, :]
        d = directions[start:start + chunk, None, :]
        p = np.cross(d, e2[None])
        det = np.einsum("rtk,tk->rt", p, e1)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = o - a[None]
        u = np.einsum("rtk,rtk->rt", s, p) * inv
        q = np.cross(s, e1[None])
        v = np.einsum("rtk,rtk->rt", np.broadcast_to(d, q.shape), q) * inv
        t = np.einsum("tk,rtk->rt", e2, q) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
        best[start:start + chunk] = np.where(hit, t, np.inf).min(axis=1)
    return best


def printcheck(parts: list[tuple[str, np.ndarray, np.ndarray]], build_volume: tuple[float, float, float] = (220, 220, 250),
               min_wall: float = 0.8, overhang_deg: float = 45, samples: int = 4000) -> dict[str, Any]:
    """Watertightness and shells are checked per part (parts touch each other); the rest on the whole model."""
    checks: list[dict[str, Any]] = []

    def check(name: str, status: str, detail: str, **values: Any) -> None:
        checks.append({"check": name, "status": status, "detail": detail, **values})

    offsets = np.cumsum([0] + [len(vertices) for _, vertices, _ in parts])
    vertices = np.concatenate([part[1] for part in parts])
    triangles = np.concatenate([part[2] + offset for part, offset in zip(parts, offsets)])
    normals, areas, centres = triangle_geometry(vertices, triangles)
    total_area = float(areas.sum())
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    size = high - low

    leaky = []
    loose = []
    edges = {"open_edges": 0, "non_manifold_edges": 0}
    for name, part_vertices, part_triangles in parts:
        part_edges = edge_report(part_triangles)
        edges = {key: edges[key] + part_edges[key] for key in edges}
        if any(part_edges.values()):
            leaky.append(name)
        if shell_count(len(part_vertices), part_triangles) > 1:
            loose.append(name)
    check("watertight", "fail" if leaky else "pass",
          f"open or non-manifold edges in {', '.join(leaky[:8])}; slicers may fill or drop them" if leaky
          else f"every part ({len(parts)}) is a closed, manifold mesh", **edges)
    check("solids", "warn" if loose else "pass",
          f"parts with loose pieces: {', '.join(loose[:8])}; they print separately or fall over" if loose
          else f"each of {len(parts)} part(s) is one connected shell", parts=len(parts))

    fits = all(size[i] <= build_volume[i] for i in range(3))
    check("build_volume", "pass" if fits else "fail",
          f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm in {build_volume[0]:g} x {build_volume[1]:g} x {build_volume[2]:g} mm"
          + ("" if fits else "; scale down, split, or reorient"), size_mm=[round(float(v), 3) for v in size])

    bed_band = max(0.05, float(size[2]) * 1e-3)
    on_bed = (normals[:, 2] < -0.99) & (centres[:, 2] < low[2] + bed_band)
    bed_area = float(areas[on_bed].sum())
    footprint = float(size[0] * size[1]) or 1.0
    bed_ratio = bed_area / footprint
    check("bed_contact", "pass" if bed_ratio >= 0.05 else "warn",
          f"{bed_area:.1f} mm² on the bed ({bed_ratio:.0%} of the XY footprint)"
          + ("" if bed_ratio >= 0.05 else "; add a flat base, a brim, or reorient"), area_mm2=round(bed_area, 2))

    limit = np.cos(np.radians(overhang_deg))
    overhang = (normals[:, 2] < -limit) & ~on_bed
    overhang_area = float(areas[overhang].sum())
    share = overhang_area / total_area if total_area else 0.0
    check("overhangs", "pass" if share < 0.02 else "warn",
          f"{overhang_area:.1f} mm² ({share:.1%} of the surface) faces down steeper than {overhang_deg:g}° from vertical"
          + ("" if share < 0.02 else "; needs supports, or reorient / add chamfers"), area_mm2=round(overhang_area, 2), share=round(share, 4))

    # Thickness inside each part (rays from one part would hit paint layers embedded in another).
    rng = np.random.default_rng(0)
    found = []
    for _, part_vertices, part_triangles in parts:
        part_normals, part_areas, part_centres = triangle_geometry(part_vertices, part_triangles)
        count = int(round(samples * part_areas.sum() / total_area)) if total_area else 0
        if count == 0:
            continue
        picks = rng.choice(len(part_triangles), size=count, p=part_areas / part_areas.sum())
        origins = part_centres[picks] - part_normals[picks] * 1e-4
        found.append(ray_hits(origins, -part_normals[picks], part_vertices, part_triangles))
    thickness = np.concatenate(found) if found else np.array([])
    finite = thickness[np.isfinite(thickness)]
    thin = finite[finite < min_wall]
    thin_share = len(thin) / len(finite) if len(finite) else 0.0
    status = "pass" if thin_share < 0.01 else ("warn" if thin_share < 0.1 else "fail")
    minimum = float(finite.min()) if len(finite) else None
    check("thin_walls", status,
          (f"min sampled wall {minimum:.2f} mm; {thin_share:.1%} of samples under {min_wall:g} mm" if minimum is not None else "no wall samples")
          + ("" if status == "pass" else "; thicken, or print with a finer nozzle"),
          min_mm=None if minimum is None else round(minimum, 3), thin_share=round(thin_share, 4))

    worst = "fail" if any(c["status"] == "fail" for c in checks) else ("warn" if any(c["status"] == "warn" for c in checks) else "pass")
    return {"status": worst, "triangles": int(len(triangles)), "checks": checks}


def check_file(path: Path, build_volume: tuple[float, float, float] = (220, 220, 250), min_wall: float = 0.8,
               overhang_deg: float = 45, tolerance: float | None = None) -> dict[str, Any]:
    return {"file": str(path), **printcheck(load_parts(path, tolerance), build_volume, min_wall, overhang_deg)}


def parse_triple(raw: str) -> tuple[float, float, float]:
    values = tuple(float(item) for item in raw.split(","))
    if len(values) != 3:
        raise argparse.ArgumentTypeError("expected x,y,z")
    return values  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="STEP or STL file, oriented as it will print (Z up)")
    parser.add_argument("--build-volume", type=parse_triple, default=(220, 220, 250), help="printer build volume x,y,z in mm")
    parser.add_argument("--min-wall", type=float, default=0.8, help="thinnest printable wall in mm (about 2 nozzle widths)")
    parser.add_argument("--overhang", type=float, default=45, help="steepest unsupported overhang, degrees from vertical")
    parser.add_argument("--tolerance", type=float, help="STEP tessellation tolerance in mm")
    args = parser.parse_args()
    result = check_file(args.file, args.build_volume, args.min_wall, args.overhang, args.tolerance)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
