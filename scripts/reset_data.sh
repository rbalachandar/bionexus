#!/usr/bin/env sh
# Back up, then wipe, local provenance + workbench state (fresh start).
# Keeps benchmark/reference data (bench_*.json, chembl/esol/hiv csvs, flywheel.db).
set -eu
cd "$(dirname "$0")/.."
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p .data
ITEMS=""
for f in proef.db proef.db-wal proef.db-shm .data/wizard.db .data/wizard.db-wal \
         .data/wizard.db-shm .data/anchors.json .data/approvals.jsonl .data/campaigns \
         .data/analyses .data/exports .data/demo.db; do
  [ -e "$f" ] && ITEMS="$ITEMS $f"
done
for d in .data/inbox*; do [ -e "$d" ] && ITEMS="$ITEMS $d"; done
if [ -z "$ITEMS" ]; then echo "nothing to reset"; exit 0; fi
tar czf ".data/backup-pre-reset-$TS.tar.gz" $ITEMS
echo "backup: .data/backup-pre-reset-$TS.tar.gz"
# shellcheck disable=SC2086
rm -rf $ITEMS
echo "reset done"
