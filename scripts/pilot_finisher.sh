#!/bin/bash
# Self-running end-of-pilot finisher. Survives every Claude session closing —
# plain bash + the project venv, nohup'd, logs to data/finisher.log.
#
# Sequence, each step hard-gated:
#   1. wait for all three waves' DONE markers (or FAILED / 2.5 h timeout)
#   2. install Prague into web/ IFF the archive passes completeness checks:
#      header bounds cover the full AOI AND a north-edge tile decodes non-empty
#      (blocks write south-to-north, so a partial archive truncates the north —
#      this exact failure shipped once today; never trust "the file exists")
#   3. pull every wave's timings.tsv into data/pilot_timings/ for the record
#   4. after ALL instances self-terminate: run the teardown (bucket kept),
#      leaving AWS exactly as pre-pilot + one S3 bucket — the user's requirement
#
# Idempotent; safe to re-run.

set -uo pipefail
cd /home/tded/P/solarme
B=s3://sunline-pilot-774672614717
STAGED="/tmp/claude-1000/-home-tded-P-solarme/51597636-ad85-4218-8d44-ecd02a7309c3/scratchpad/staged"
PY=.venv/bin/python
log() { echo "[$(date +%H:%M:%S)] $*"; }

log "waiting for wave completion markers"
for i in $(seq 1 95); do
  D=0
  for p in pilot pilot2 pilot3; do
    aws s3 ls $B/$p/DONE >/dev/null 2>&1 && D=$((D+1))
    aws s3 ls $B/$p/FAILED >/dev/null 2>&1 && { log "WAVE $p FAILED — see $B/$p/logs/"; D=$((D+1)); }
  done
  [ "$D" -ge 3 ] && break
  sleep 100
done
log "markers done (or timeout) — syncing any stragglers"

for p in pilot pilot2; do
  aws s3 sync "$B/$p/results/" web/ --exclude "*" --include "*.pmtiles" --only-show-errors 2>/dev/null
done
for f in web/*/*.pmtiles; do [ -f "$f" ] && mv -f "$f" web/; done 2>/dev/null
rmdir web/west web/northwest web/north 2>/dev/null
aws s3 sync "$B/pilot3/results/" "$STAGED/" --exclude "*" --include "*.pmtiles" --only-show-errors 2>/dev/null

log "gating Prague install"
PRG=$(find "$STAGED" -name "prague.pmtiles" | head -1)
PRGM=$(find "$STAGED" -name "prague_max.pmtiles" | head -1)
if [ -n "$PRG" ]; then
  if $PY scripts/check_pmtiles_complete.py "$PRG" 14.26 49.93 14.67 50.20; then
    cp -f "$PRG" web/visibility.pmtiles
    log "INSTALLED web/visibility.pmtiles (fresh Prague, gate passed)"
    if [ -n "$PRGM" ] && $PY scripts/check_pmtiles_complete.py "$PRGM" 14.26 49.93 14.67 50.20; then
      cp -f "$PRGM" web/visibility_max.pmtiles
      log "INSTALLED web/visibility_max.pmtiles"
    fi
  else
    log "PRAGUE GATE FAILED — stopgap stays live; archive kept at $PRG"
  fi
else
  log "no prague archive staged — stopgap stays live"
fi

log "collecting timings"
mkdir -p data/pilot_timings
for p in pilot pilot2 pilot3; do
  aws s3 cp "$B/$p/results/timings.tsv" "data/pilot_timings/${p}.tsv" --only-show-errors 2>/dev/null
done

log "waiting for instances to self-terminate before teardown"
for i in $(seq 1 40); do
  LEFT=$(aws ec2 describe-instances --region eu-central-1 \
    --filters "Name=tag:Name,Values=sunline-pilot" \
              "Name=instance-state-name,Values=pending,running,stopping,shutting-down" \
    --query 'Reservations[].Instances[].InstanceId' --output text)
  [ -z "$LEFT" ] && break
  log "still up: $LEFT"
  sleep 120
done

log "running teardown (bucket kept, per user requirement)"
bash scripts/aws_pilot_teardown.sh
log "FINISHER COMPLETE — see data/pilot_timings/ and web/*.pmtiles"
