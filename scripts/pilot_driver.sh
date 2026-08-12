#!/bin/bash
# SunLine EC2 pilot driver — runs ON the instance, as root, cwd /opt/sunline.
#
# Contract with the launcher:
#   - $BUCKET is set (S3 bucket for results)
#   - a dead-man `shutdown -h +150` is already scheduled by user-data, so this
#     script cannot leave the instance running past the cost ceiling no matter
#     how it fails; on clean completion we shut down immediately instead.
#   - spot InstanceInterruptionBehavior=terminate + DeleteOnTermination=true
#     mean shutdown == full teardown of compute; only S3 objects persist.
#
# Everything is timed and uploaded, success or failure — the pilot's entire
# point is the measurements.

set -uo pipefail
cd /opt/sunline
export PYTHONPATH=src
PY=.venv/bin/python
# Parametrized so later waves reuse this unchanged: wave 1 used the defaults,
# wave 2 runs REGIONS_LIST="north" S3_PREFIX=pilot2 on a smaller instance.
S3="s3://${BUCKET}/${S3_PREFIX:-pilot}"
read -r -a REGIONS <<< "${REGIONS_LIST:-west northwest}"
STAMP() { date -u +%H:%M:%S; }

upload_logs() {
  aws s3 cp /var/log/pilot-driver.log "${S3}/logs/" --only-show-errors || true
  aws s3 cp /var/log/pilot-boot.log "${S3}/logs/" --only-show-errors || true
  [ -f timings.tsv ] && aws s3 cp timings.tsv "${S3}/results/" --only-show-errors
}
fail() {
  echo "PILOT FAILED at $(STAMP): $1"
  echo "$1" | aws s3 cp - "${S3}/FAILED" --only-show-errors || true
  upload_logs
  shutdown -h now
  exit 1
}

echo -e "stage\tregion\tseconds" > timings.tsv
t() {  # t <stage> <region> <cmd...>
  local s=$1 r=$2; shift 2
  local t0=$SECONDS
  "$@" || fail "$s/$r exited $?"
  echo -e "${s}\t${r}\t$((SECONDS - t0))" >> timings.tsv
  echo "=== ${s}/${r} took $((SECONDS - t0))s ==="
}

# Gate: the analytic test suite must be green on this box before any money
# is spent sweeping. Catches wheel/arch/library surprises immediately.
t pytest all $PY -m pytest tests/ -q || true

nproc; free -g | sed -n 2p; df -h /opt | tail -1

for R in "${REGIONS[@]}"; do
  CFG="configs/${R}.yaml"
  OUT="configs/data_${R}"

  t fetch     "$R" $PY -m sunline.cli fetch       -c "$CFG"
  t composite "$R" $PY -m sunline.cli composite   -c "$CFG" --workers 45
  t publish   "$R" $PY -m sunline.cli publish     -c "$CFG"
  t publimax  "$R" $PY -m sunline.cli publish-max -c "$CFG"

  # Results out immediately per region, so a later failure loses nothing.
  aws s3 cp "${OUT}/${R}.pmtiles"          "${S3}/results/${R}/" --only-show-errors || fail "upload ${R}.pmtiles"
  aws s3 cp "${OUT}/${R}_max.pmtiles"      "${S3}/results/${R}/" --only-show-errors || true
  aws s3 cp "${OUT}/visible_fraction.tif"  "${S3}/results/${R}/" --only-show-errors || true
  aws s3 cp "${OUT}/visible_at_max.tif"    "${S3}/results/${R}/" --only-show-errors || true
  upload_logs
done

echo "PILOT DONE at $(STAMP)"
cat timings.tsv
echo done | aws s3 cp - "${S3}/DONE" --only-show-errors
upload_logs
shutdown -h now
