"""
core/systems/kitbash_blender_backend.py

Persona D runner -- the Python side of the Blender->glTF backend
(spec_kitbash_greeble.md §4, Persona D). Shells out to the Blender BINARY
headless to run tools/kitbash_assemble.py, which consumes an AssemblyResult
(core/systems/kitbash_engine.py) and emits a .glb for the paused Godot client.

This module does NOT import bpy (that only runs inside Blender). It:
  * serializes an AssemblyResult to the assembly-JSON the bpy script expects,
  * invokes `<BLENDER> --background --factory-startup --python <script> -- \
    <assembly_json> <out_glb>`,
  * treats "output .glb exists and is non-empty" as the success signal (NOT the
    process return code alone -- Blender's exit code on a --python exception has
    been inconsistent across versions), and
  * raises RuntimeError with captured stderr on failure.

Air-gap / no-LLM: subprocess to a local binary + json + a filesystem check.
Deterministic, offline. No model, no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


# -- Constants (no hardcoded tunables -- AGENTS.md line 18) --------------------

# The verified Blender binary (4.5.12 LTS). Env override lets a different host
# (e.g. the Linux CI node) point at its own install without a code edit.
BLENDER_ENV_VAR  = "KITBASH_BLENDER"
DEFAULT_BLENDER_BIN = "/Applications/Blender.app/Contents/MacOS/Blender"

# The bpy script this runner drives, resolved relative to the repo root
# (this file lives at core/systems/, so root is two parents up).
_REPO_ROOT   = Path(__file__).resolve().parents[2]
ASSEMBLE_SCRIPT = _REPO_ROOT / "tools" / "kitbash_assemble.py"

# Blender invocation flags. --factory-startup guarantees a clean default scene
# (the bpy script also clears it) so no user startup file leaks objects in.
BLENDER_FLAGS = ("--background", "--factory-startup", "--python")
ARGV_SEPARATOR = "--"

# Marker the bpy script prints on a successful run (see tools/kitbash_assemble.py).
SUCCESS_MARKER = "KITBASH_ASSEMBLE_OK"

# Ceiling on a single headless assemble (seconds). Named, not bare.
BLENDER_TIMEOUT_S = 180

REPORT_SUFFIX = ".report.json"


def blender_bin() -> str:
    """The Blender binary path: env override (KITBASH_BLENDER) else the verified
    default."""
    return os.environ.get(BLENDER_ENV_VAR, DEFAULT_BLENDER_BIN)


def is_blender_available() -> bool:
    """True iff the Blender binary exists and is executable. Tests skip on False
    so the suite stays green on a host without Blender."""
    path = blender_bin()
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _assembly_to_dict(assembly) -> dict:
    """Serialize an AssemblyResult (or a plain dict) to the JSON shape the bpy
    script parses. Duck-typed: anything exposing base_id / bindings works, so
    the runner never has to import kitbash_engine."""
    if isinstance(assembly, dict):
        base_id = assembly.get("base_id")
        bindings = assembly.get("bindings", [])
        signal = assembly.get("signal_snapshot", {})
    else:
        base_id = assembly.base_id
        bindings = assembly.bindings
        signal = getattr(assembly, "signal_snapshot", {})
    return {
        "base_id": base_id,
        "bindings": [list(b) for b in bindings],   # tuples -> JSON arrays
        "signal_snapshot": signal,
    }


def assemble_to_glb(
    assembly,
    out_glb_path,
    *,
    assembly_json_path: Optional[str] = None,
    timeout_s: int = BLENDER_TIMEOUT_S,
) -> str:
    """
    Run the Blender headless backend on `assembly`, writing a .glb to
    `out_glb_path`. Returns the output path as a str.

    `assembly` is an AssemblyResult (from KitbashEngine) or an equivalent dict
    {base_id, bindings}. `assembly_json_path`, if given, is where the serialized
    assembly JSON is written (else a temp file next to the output).

    Raises:
      FileNotFoundError -- the Blender binary is not available.
      RuntimeError      -- the backend produced no (or an empty) .glb; the
                           message carries Blender's captured stderr/stdout tail.
    """
    if not is_blender_available():
        raise FileNotFoundError(
            f"Blender binary not available at {blender_bin()!r} "
            f"(set {BLENDER_ENV_VAR} to override)."
        )

    out_glb_path = str(out_glb_path)
    out_dir = os.path.dirname(os.path.abspath(out_glb_path)) or "."

    # Serialize the assembly to JSON for the bpy script.
    payload = _assembly_to_dict(assembly)
    if assembly_json_path is None:
        fd, assembly_json_path = tempfile.mkstemp(
            suffix=".assembly.json", dir=out_dir
        )
        os.close(fd)
    with open(assembly_json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)

    # A stale output from a prior run must not masquerade as success.
    if os.path.exists(out_glb_path):
        os.remove(out_glb_path)

    cmd = [
        blender_bin(),
        *BLENDER_FLAGS,
        str(ASSEMBLE_SCRIPT),
        ARGV_SEPARATOR,
        assembly_json_path,
        out_glb_path,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )

    # Success signal = the artifact exists and is non-empty. We do NOT trust the
    # return code alone (see module docstring). But surface diagnostics if not.
    if not (os.path.exists(out_glb_path) and os.path.getsize(out_glb_path) > 0):
        raise RuntimeError(
            "kitbash Blender backend produced no .glb.\n"
            f"cmd: {' '.join(cmd)}\n"
            f"returncode: {proc.returncode}\n"
            f"--- stderr tail ---\n{proc.stderr[-4000:]}\n"
            f"--- stdout tail ---\n{proc.stdout[-2000:]}"
        )

    return out_glb_path


def report_path_for(out_glb_path) -> str:
    """The sidecar report path the bpy script writes alongside the .glb
    (decimate before/after triangle counts + node manifest)."""
    return str(out_glb_path) + REPORT_SUFFIX
