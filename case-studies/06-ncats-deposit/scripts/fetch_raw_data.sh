#!/usr/bin/env bash
# CS06 — reproducible fetch of the NCATS qHTS ALDH3A1 confirmatory reassay
# (AID 2061307, deposited 2025-09-13): 2,427 retested compounds with raw
# per-concentration %Activity curves + NCATS' own AI-fit answer columns.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p ../../.data/cs06_raw
tries=0
until curl -fsSL --retry 4 --retry-delay 10 \
  -H "User-Agent: bionexus-cs06 (deposit pilot)" \
  "https://pubchem.ncbi.nlm.nih.gov/rest/pug/assay/aid/2061307/CSV" \
  -o ../../.data/cs06_raw/aid_2061307.csv; do
  tries=$((tries+1)); [ $tries -ge 5 ] && exit 1; sleep $((tries*15)); done
echo "fetched -> .data/cs06_raw/aid_2061307.csv ; then freeze:"
echo "  python -c 'from bionexus.fixtures import freeze; \
  freeze(\"case-studies/06-ncats-deposit\", [(\"aid_2061307.csv\", __import__(\"pathlib\").Path(\".data/cs06_raw/aid_2061307.csv\"))])'"
