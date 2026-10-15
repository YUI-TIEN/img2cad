#!/usr/bin/env python3
"""Export a STEP file to GLB, STL and 3MF meshes.

* GLB keeps every part's name and colour (glTF materials), for viewers and the web.
* 3MF keeps every part as its own object with its colour (`basematerials`), for slicers.
* STL is a single uncoloured mesh, for tools that only read STL.

Exports read the saved STEP, so the meshes always match the checked B-rep.
The tessellation tolerance scales with the model size unless given.

    .venv-cad/bin/python scripts/mesh_export.py model.step out_dir --formats glb,stl,3mf
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import zipfile
from xml.sax.saxutils import escape

FORMATS = ("glb", "stl", "3mf")


def default_tolerance(shape: Any) -> float:
    """About 1/2000 of the model's diagonal, at least 0.01 mm."""
    box = shape.bounding_box()
    diagonal = (box.size.X ** 2 + box.size.Y ** 2 + box.size.Z ** 2) ** 0.5
    return max(0.01, diagonal / 2000)


def write_3mf(parts: list[Any], path: Path, tolerance: float) -> None:
    """3MF core spec: one mesh object per part, coloured through a basematerials group."""
    from inspect_step import color_rgba

    materials = []
    objects = []
    build_items = []
    for index, part in enumerate(parts):
        vertices, triangles = part.tessellate(tolerance, 0.2)
        if not vertices or not triangles:
            continue
        rgba = color_rgba(part) or [0.79, 0.61, 0.4, 1.0]
        materials.append(f'<base name="{escape(getattr(part, "label", "") or f"part {index + 1}")}" '
                         f'displaycolor="#{"".join(f"{round(channel * 255):02X}" for channel in rgba[:4])}" />')
        object_id = len(objects) + 2  # id 1 is the material group
        vertex_xml = "".join(f'<vertex x="{v.X:.4f}" y="{v.Y:.4f}" z="{v.Z:.4f}" />' for v in vertices)
        triangle_xml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}" />' for a, b, c in triangles)
        name = escape(getattr(part, "label", "") or f"part {index + 1}")
        objects.append(f'<object id="{object_id}" name="{name}" type="model" pid="1" pindex="{len(materials) - 1}">'
                       f'<mesh><vertices>{vertex_xml}</vertices><triangles>{triangle_xml}</triangles></mesh></object>')
        build_items.append(f'<item objectid="{object_id}" />')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources><basematerials id="1">{"".join(materials)}</basematerials>{"".join(objects)}</resources>'
             f'<build>{"".join(build_items)}</build></model>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />'
                     '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml" /></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" /></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model)


def export_meshes(step_path: Path, out_dir: Path, formats: tuple[str, ...] = FORMATS, stem: str = "model",
                  tolerance: float | None = None) -> dict[str, Path]:
    from build123d import export_gltf, export_stl, import_step

    from inspect_step import leaf_parts

    unknown = [name for name in formats if name not in FORMATS]
    if unknown:
        raise ValueError(f"unknown mesh formats {unknown}; choose from {', '.join(FORMATS)}")
    shape = import_step(str(step_path))
    tolerance = tolerance or default_tolerance(shape)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    if "glb" in formats:
        written["glb"] = out_dir / f"{stem}.glb"
        export_gltf(shape, str(written["glb"]), binary=True, linear_deflection=tolerance, angular_deflection=0.2)
    if "stl" in formats:
        written["stl"] = out_dir / f"{stem}.stl"
        export_stl(shape, str(written["stl"]), tolerance=tolerance, angular_tolerance=0.2)
    if "3mf" in formats:
        written["3mf"] = out_dir / f"{stem}.3mf"
        write_3mf(leaf_parts(shape), written["3mf"], tolerance)
    return written


def parse_formats(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() in ("", "none"):
        return ()
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--formats", default=",".join(FORMATS), help="comma-separated: glb,stl,3mf")
    parser.add_argument("--stem", default=None, help="output file name stem (default: the STEP file's stem)")
    parser.add_argument("--tolerance", type=float, help="linear tessellation tolerance in mm (default: scaled to the model)")
    args = parser.parse_args()
    written = export_meshes(args.step, args.out_dir, parse_formats(args.formats), args.stem or args.step.stem, args.tolerance)
    print(json.dumps({name: str(path) for name, path in written.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
