# syntax=docker/dockerfile:1.7
#
# sanctum-terminal — roguelike TUI + brain_server + GPU renderers.
# FROM sanctum-base.
#
# Three runnable things share this image:
#   - `sanctum`            roguelike ASCII TUI (no display needed)
#   - brain_server.py      TCP daemon on :9877 (no display needed)
#   - renderer_bridge.py   panda3d/wgpu 3D renderer (needs xvfb + GL)
#
# GPU caveat: Docker has no GPU passthrough here. The renderer runs
# against xvfb + Mesa software rasterization (llvmpipe / lavapipe) —
# functional but slow. The TUI and brain daemon are unaffected.
FROM sanctum-base:latest

# X / GL / Vulkan libs for the software-rendered renderer.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        libgl1 \
        libglu1-mesa \
        libgl1-mesa-dri \
        mesa-vulkan-drivers \
        libxext6 \
        libxrender1 \
        libsm6 \
        libxi6 \
    && rm -rf /var/lib/apt/lists/*
USER app

COPY --chown=app:app . /workspaces/sanctum-terminal

# sanctum-terminal is a flat-layout app, not a clean installable package
# — core/ uses implicit-namespace subpackages that don't survive a
# `pip install -e .` editable finder. So install its deps directly and
# run modules straight from the source dir (the way brain_server runs).
# The spaCy model is baked in — never downloaded at runtime.
RUN pip install --no-cache-dir \
        "panda3d>=1.10.14" \
        "rich>=13.0.0" \
        "spacy>=3.7,<4.0" \
        "wgpu>=0.15" \
 && python -m spacy download en_core_web_sm

WORKDIR /workspaces/sanctum-terminal

# Bare entry = the roguelike TUI. The compose `brain` service overrides
# this to run brain_server.py; the renderer runs under xvfb-run.
CMD ["python", "sanctum_terminal.py"]
