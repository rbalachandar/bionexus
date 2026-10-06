#!/usr/bin/env bash
# Provision a 4090 pod for CS08 step 2. Idempotent; re-run after resume.
set -euo pipefail
docker pull ghcr.io/microsoft/BindCraft:latest 2>/dev/null || \
  { git clone https://github.com/mis-tikala/BindCraft.git ~/BindCraft && \
    echo "NOTE: verify BindCraft repo/weights license & source before run"; }
pip install boltz  2>/dev/null || \
  { git clone https://github.com/jwohlprob/boltz ~/boltz && \
    echo "NOTE: verify boltz repo/weights license & source before run"; }
mkdir -p work weights
echo "weights download (ESM2 650M, RFdiffusion, Boltz-1) happens on first" \
     "job run; expect ~6 GB and a one-time ~20 min"
