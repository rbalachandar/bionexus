#!/usr/bin/env bash
# CS05 — reproducible fetch of the PUBLISHED RAW deposits of the paper-pilot:
# Jacobs et al., J. Med. Chem. 2013 (PMID 23231439; PMC3569073) — NIH MLPCN
# anti-SARS-CoV 3CLpro screening cascade. These CSVs are the lab's uploaded
# concentration-response / triplicate data AS DEPOSITED in PubChem (the REST
# export of each AID's data table). Run from the study directory:
#   ./scripts/fetch_raw_data.sh          # confirmatory + secondary (~0.4 MB)
#   ./scripts/fetch_raw_data.sh --primary # also the 290k-well primary (~35 MB)
set -euo pipefail
UA="bionexus-cs05 (research; paper-pilot reproduction)"
BASE="https://pubchem.ncbi.nlm.nih.gov/rest/pug/assay/aid"
cd "$(dirname "$0")/.."
fetch() { # aid outfile
  local tries=0
  until curl -fsSL -H "User-Agent: $UA" "$BASE/$1/CSV" -o "fixtures/$2.csv"; do
    tries=$((tries+1)); [ $tries -ge 5 ] && { echo "fetch failed: AID $1" >&2; exit 1; }
    sleep $((tries*15))   # PubChem throttle: >=5 req/s rule, back off politely
  done
  echo "fetched AID $1 -> fixtures/$2.csv"
}
fetch 1890 aid_1890   # confirmatory dose response: 101 cmpds, 6-10 pt CRCs
fetch 1879 aid_1879   # secondary confirmation: 380 cmpds, triplicate @ 6 uM
if [ "${1:-}" = "--primary" ]; then
  fetch 1706 aid_1706 # primary single-point: 290,893 cmpds (opt-in; large)
fi
