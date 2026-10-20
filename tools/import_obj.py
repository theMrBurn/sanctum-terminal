"""tools/import_obj.py — ingest a raw vendor OBJ into a registered mesh.

Persona E of `docs/spec_open_source_primitive_pipeline.md` (D5). Turns a
raw, untouched vendor OBJ (Kenney / Quaternius / NASA / …) into an
art-directed, validated, engine-ready wireframe mesh the vector terminal
+ kitbash parts provider consume by NAME.

    .venv/bin/python tools/import_obj.py \
        --source "assets/kenney/nature-kit/Models/OBJ format/tree_pineTallA.obj" \
        --name spire \
        --recenter bottom_center \
        --rescale-height 4.0 \
        --axis-swap y_up \
        --merge-vertices 1e-6 \
        --max-edges 200

Writes (all under the repo):
  - assets/derived/<name>/mesh.obj        cleaned OBJ (v + l), committed
  - assets/derived/<name>/provenance.json D2 sidecar (source + edits +
                                          stats{…, sha256} + imported_at)
  - config/wireframe_meshes.json          atomic, sorted-keys registry update

Determinism: mesh.obj is byte-identical across re-runs of the same flags
(the sha256 in provenance is over mesh.obj bytes only — never the sidecar,
which carries the wall-clock `imported_at`). The clock is supplied by the
CLI wrapper; `run_ingest()` takes `imported_at` as a parameter so no clock
is called inside the hashable/reproducible path. Air-gapped: no network,
no LLM.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import sys
from pathlib import Path

# Ensure the repo root is importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.systems import wireframe_ingest_edits as ie
from core.systems.wireframe_mesh import (
    PROVENANCE_FILENAME,
    WireframeMesh,
    load_obj,
    load_wireframe_obj,
    mesh_file_sha256,
    registry_path,
    write_obj,
)

# ── Named tunables (AGENTS: no hardcoded literals controlling behavior) ──
IMPORT_TOOL_VERSION: str = "1.0.0"
DERIVED_DIR: str = "assets/derived"
DERIVED_MESH_FILENAME: str = "mesh.obj"
LICENSE_FILENAME: str = "License.txt"

DEFAULT_MAX_EDGES: int = 500        # D6 hard-fail ceiling
EDGE_BUDGET_WARN: int = 200         # D6 soft-warn rendering budget
VERTEX_BUDGET_WARN: int = 100       # D6 soft-warn
ASPECT_RATIO_WARN: float = 10.0     # D6 soft-warn (axis_swap likely wrong)

# Best-effort SPDX-ish detection + canonical URLs for the common vendors.
_LICENSE_URLS: dict[str, str] = {
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA": "https://creativecommons.org/licenses/by-sa/4.0/",
    "MIT": "https://opensource.org/licenses/MIT",
}


class IngestError(Exception):
    """Hard-fail during ingest (D6). Aborts without writing artifacts."""


# ── License discovery ────────────────────────────────────────────────────


def _detect_license_token(text: str) -> str:
    """Best-effort license token from a License.txt body."""
    upper = text.upper()
    if "CC0" in upper or "PUBLIC DOMAIN" in upper:
        return "CC0"
    if "CC-BY-SA" in upper or "ATTRIBUTION-SHAREALIKE" in upper:
        return "CC-BY-SA"
    if "CC-BY" in upper or "ATTRIBUTION" in upper:
        return "CC-BY"
    if "MIT LICENSE" in upper:
        return "MIT"
    return "custom"


def _find_license(source: Path) -> Path | None:
    """Walk up from the source OBJ toward the repo root looking for a
    pack-root License.txt (case-insensitive)."""
    cur = source.resolve().parent
    stop = _REPO_ROOT.resolve()
    while True:
        for child in cur.iterdir() if cur.exists() else []:
            if child.is_file() and child.name.lower() == LICENSE_FILENAME.lower():
                return child
        if cur == stop or cur.parent == cur:
            return None
        cur = cur.parent


def _resolve_license(
    source: Path,
    license_override: str | None,
    license_url: str | None,
) -> tuple[str, str]:
    """Return (license, license_url). Hard-fail if neither an explicit
    --license nor a discoverable License.txt is available (D6)."""
    if license_override:
        token = license_override
    else:
        lic_file = _find_license(source)
        if lic_file is None:
            raise IngestError(
                f"no license: pass --license or place a {LICENSE_FILENAME} at "
                f"the vendor pack root above {source}"
            )
        token = _detect_license_token(lic_file.read_text(errors="replace"))
    url = license_url or _LICENSE_URLS.get(token, "")
    return token, url


# ── Edit pipeline ────────────────────────────────────────────────────────


def _build_edits(
    recenter: str | None,
    rescale_height: float | None,
    axis_swap_from: str | None,
    merge_epsilon: float | None,
    decimate_target: int | None,
    bounds_min: tuple[float, float, float] | None,
    bounds_max: tuple[float, float, float] | None,
) -> list[dict]:
    """Assemble the provenance `edits` log in canonical INGEST_EDIT_ORDER.
    Only ops the caller requested are included."""
    edits: list[dict] = []
    if recenter is not None:
        edits.append({"op": "recenter", "mode": recenter})
    if rescale_height is not None:
        edits.append({"op": "rescale", "target_height": rescale_height})
    if axis_swap_from is not None:
        edits.append({"op": "axis_swap", "from": axis_swap_from, "to": ie.UP_AXIS})
    if merge_epsilon is not None:
        edits.append({"op": "merge_vertices", "epsilon": merge_epsilon})
    if decimate_target is not None:
        edits.append({"op": "decimate_edges", "target_count": decimate_target})
    if bounds_min is not None and bounds_max is not None:
        edits.append({"op": "bounds_clip", "min": list(bounds_min),
                      "max": list(bounds_max)})
    return edits


def apply_edits(mesh: WireframeMesh, edits: list[dict]) -> WireframeMesh:
    """Replay the ingest edit log against a mesh. Deterministic: same
    mesh + same log → same geometry. Ops dispatch to
    `core.systems.wireframe_ingest_edits`."""
    for op in edits:
        name = op.get("op")
        if name == "recenter":
            mesh = ie.recenter(mesh, mode=op["mode"])
        elif name == "rescale":
            mesh = ie.rescale(
                mesh,
                target_height=op.get("target_height"),
                target_diag=op.get("target_diag"),
                factor=op.get("factor"),
            )
        elif name == "axis_swap":
            mesh = ie.axis_swap(mesh, from_up=op["from"], to_up=op["to"])
        elif name == "merge_vertices":
            mesh = ie.merge_vertices(mesh, epsilon=op["epsilon"])
        elif name == "decimate_edges":
            mesh = ie.decimate_edges(mesh, target_count=op["target_count"])
        elif name == "bounds_clip":
            mesh = ie.bounds_clip(
                mesh, min=tuple(op["min"]), max=tuple(op["max"])
            )
        else:
            raise IngestError(f"unknown edit op {name!r}")
    return mesh


# ── Validation (D6) ──────────────────────────────────────────────────────


def _validate(mesh: WireframeMesh, max_edges: int) -> list[str]:
    """Hard-fail (raise IngestError) on the abort conditions; return the
    list of soft-warning strings for the caller to print/record."""
    (minx, miny, minz), (maxx, maxy, maxz) = ie._bounds(mesh.vertices)
    span_x, span_y, span_z = maxx - minx, maxy - miny, maxz - minz

    if span_x <= 0.0 and span_y <= 0.0 and span_z <= 0.0:
        raise IngestError("degenerate mesh: zero bounds on every axis")
    if mesh.edge_count() > max_edges:
        raise IngestError(
            f"edge count {mesh.edge_count()} exceeds --max-edges {max_edges}"
        )

    warnings: list[str] = []
    if mesh.edge_count() > EDGE_BUDGET_WARN:
        warnings.append(
            f"edge count {mesh.edge_count()} > render budget {EDGE_BUDGET_WARN}"
        )
    if mesh.vertex_count() > VERTEX_BUDGET_WARN:
        warnings.append(
            f"vertex count {mesh.vertex_count()} > {VERTEX_BUDGET_WARN}"
        )
    spans = [s for s in (span_x, span_y, span_z) if s > 0.0]
    if spans and (max(spans) / min(spans)) > ASPECT_RATIO_WARN:
        warnings.append(
            f"bounds aspect ratio {max(spans) / min(spans):.1f}:1 > "
            f"{ASPECT_RATIO_WARN:.0f}:1 (axis_swap may be wrong)"
        )
    return warnings


# ── Registry (atomic, sorted-keys) ───────────────────────────────────────


def _update_registry(name: str, rel_path: str) -> None:
    path = registry_path()
    registry: dict = {}
    if path.exists():
        registry = json.loads(path.read_text())
    registry[name] = {"path": rel_path}
    ordered = {k: registry[k] for k in sorted(registry)}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ordered, indent=2) + "\n")
    os.replace(tmp, path)  # atomic on POSIX


# ── Ingest entry point ───────────────────────────────────────────────────


def run_ingest(
    *,
    source: str | Path,
    name: str,
    imported_at: str,
    recenter: str | None = None,
    rescale_height: float | None = None,
    axis_swap_from: str | None = None,
    merge_epsilon: float | None = None,
    decimate_target: int | None = None,
    bounds_min: tuple[float, float, float] | None = None,
    bounds_max: tuple[float, float, float] | None = None,
    max_edges: int = DEFAULT_MAX_EDGES,
    license: str | None = None,
    license_url: str | None = None,
    credit: str = "",
    vendor: str = "",
    pack: str = "",
) -> dict:
    """Core ingest — pure of the clock (`imported_at` is passed in).

    Returns a result dict: {name, mesh_path, provenance_path, registry_path,
    stats, warnings}. Raises IngestError on any D6 hard-fail (before any
    artifact is written).
    """
    source = Path(source)
    if not source.exists():
        raise IngestError(f"source not found: {source}")

    # License gate FIRST — no point cleaning geometry we can't ship.
    lic, lic_url = _resolve_license(source, license, license_url)

    try:
        raw = load_obj(source)  # faces → edges (vendor OBJs are f-faced)
    except (ValueError, OSError) as exc:
        raise IngestError(f"malformed source {source}: {exc}") from exc
    if not raw.vertices:
        raise IngestError(f"source {source} has no vertices")

    edits = _build_edits(
        recenter, rescale_height, axis_swap_from, merge_epsilon,
        decimate_target, bounds_min, bounds_max,
    )
    cleaned = apply_edits(raw, edits)
    warnings = _validate(cleaned, max_edges)

    # Write mesh, then read it BACK and derive stats from the reread mesh so
    # provenance stats match exactly what resolve_mesh() will later load
    # (float round-trip fidelity — advisor point 3).
    out_dir = _REPO_ROOT / DERIVED_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = out_dir / DERIVED_MESH_FILENAME
    write_obj(cleaned, mesh_path)
    reread = load_wireframe_obj(mesh_path)
    (lo, hi) = ie._bounds(reread.vertices)
    stats = {
        "vertex_count": reread.vertex_count(),
        "edge_count": reread.edge_count(),
        "bounds": [list(lo), list(hi)],
        "sha256": mesh_file_sha256(mesh_path),
    }

    try:
        src_rel = str(source.resolve().relative_to(_REPO_ROOT.resolve()))
    except ValueError:
        src_rel = str(source)
    provenance = {
        "name": name,
        "source": {
            "vendor": vendor,
            "pack": pack,
            "path": src_rel,
            "license": lic,
            "license_url": lic_url,
            "credit": credit,
        },
        "edits": edits,
        "stats": stats,
        "imported_at": imported_at,
        "import_tool_version": IMPORT_TOOL_VERSION,
    }
    (out_dir / PROVENANCE_FILENAME).write_text(
        json.dumps(provenance, indent=2) + "\n"
    )

    rel_mesh = f"{DERIVED_DIR}/{name}/{DERIVED_MESH_FILENAME}"
    _update_registry(name, rel_mesh)

    return {
        "name": name,
        "mesh_path": mesh_path,
        "provenance_path": out_dir / PROVENANCE_FILENAME,
        "registry_path": registry_path(),
        "stats": stats,
        "warnings": warnings,
    }


# ── CLI ──────────────────────────────────────────────────────────────────


def _triple(value: str) -> tuple[float, float, float]:
    parts = value.replace(",", " ").split()
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected 3 numbers 'x y z'")
    return (float(parts[0]), float(parts[1]), float(parts[2]))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="import_obj",
        description="Ingest a raw vendor OBJ into a registered wireframe mesh.",
    )
    p.add_argument("--source", required=True, help="path to the raw vendor OBJ")
    p.add_argument("--name", required=True, help="canonical registered mesh name")
    p.add_argument("--recenter", choices=ie.RECENTER_MODES, default=None)
    p.add_argument("--rescale-height", type=float, default=None,
                   help="uniform-scale so the Y extent equals this")
    p.add_argument("--axis-swap", dest="axis_swap_from", default=None,
                   help="source up-axis (e.g. z_up | y_up); converted to y_up")
    p.add_argument("--merge-vertices", dest="merge_epsilon", type=float,
                   default=None, help="collapse verts within this epsilon")
    p.add_argument("--decimate-edges", dest="decimate_target", type=int,
                   default=None, help="drop shortest edges down to this count")
    p.add_argument("--bounds-clip-min", dest="bounds_min", type=_triple,
                   default=None, help="clip box min 'x y z'")
    p.add_argument("--bounds-clip-max", dest="bounds_max", type=_triple,
                   default=None, help="clip box max 'x y z'")
    p.add_argument("--max-edges", type=int, default=DEFAULT_MAX_EDGES,
                   help=f"hard-fail ceiling (default {DEFAULT_MAX_EDGES})")
    p.add_argument("--license", default=None,
                   help="license override (else discovered from License.txt)")
    p.add_argument("--license-url", default=None)
    p.add_argument("--credit", default="")
    p.add_argument("--vendor", default="")
    p.add_argument("--pack", default="")
    p.add_argument("--imported-at", default=None,
                   help="ISO timestamp override (default: now)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    imported_at = args.imported_at or _datetime.datetime.now().astimezone().isoformat()
    try:
        result = run_ingest(
            source=args.source,
            name=args.name,
            imported_at=imported_at,
            recenter=args.recenter,
            rescale_height=args.rescale_height,
            axis_swap_from=args.axis_swap_from,
            merge_epsilon=args.merge_epsilon,
            decimate_target=args.decimate_target,
            bounds_min=args.bounds_min,
            bounds_max=args.bounds_max,
            max_edges=args.max_edges,
            license=args.license,
            license_url=args.license_url,
            credit=args.credit,
            vendor=args.vendor,
            pack=args.pack,
        )
    except IngestError as exc:
        print(f"ingest FAILED: {exc}", file=sys.stderr)
        return 1

    s = result["stats"]
    print(f"ingested {result['name']!r}:")
    print(f"  mesh:       {result['mesh_path']}")
    print(f"  provenance: {result['provenance_path']}")
    print(f"  registry:   {result['registry_path']}")
    print(f"  stats:      {s['vertex_count']} verts, {s['edge_count']} edges")
    print(f"  bounds:     {s['bounds']}")
    for w in result["warnings"]:
        print(f"  WARN: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
