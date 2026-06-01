#!/usr/bin/env bash
# =============================================================================
# run_113.sh — Sweep RepairAgent over the canonical Defects4J 113-bug list.
#
# - Sequential (parallel would corrupt the shared ai_settings.yaml file).
# - Resumable: a bug with a non-empty plausible_patches_<P>_<N>.json in any
#   prior experiment dir is skipped on rerun.
# - Tolerant: a per-bug crash logs the error and continues to the next bug.
# - Summary file: one line per bug → bug, status (OK|FAIL|SKIP), wall-time-s,
#   experiment dir, optional fix-line count.
#
# Usage:  bash run_113.sh                 # full sweep
#         BUGS=path/to/bugs.txt bash run_113.sh   # custom bug list
#         MAX_CYCLES=40 MODEL=deepseek-v4-flash bash run_113.sh
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

BUGS="${BUGS:-bugs_113.txt}"
MODEL="${MODEL:-deepseek-v4-flash}"
MAX_CYCLES="${MAX_CYCLES:-40}"
SUMMARY="${SUMMARY:-/tmp/sweep_113.summary}"
EXP_ROOT="experimental_setups"

# Load DEEPSEEK_API_KEY from shared .env; unset stale OpenAI vars and the
# .env's DEFECTS4J_URL (which still points at the documented default 8090 even
# though our service lives on 8091).  Set our 8091 default AFTER the source.
set -a; . /data/wangjian/wj_code/defects4c_dirs/.env; set +a
unset OPENAI_API_KEY OPENAI_API_BASE_URL OPENAI_BASE_URL
unset DEFECTS4J_URL
export DEFECTS4J_URL="${D4J_URL_OVERRIDE:-http://localhost:8092}"
export TEMPERATURE=0

# Pre-flight checks
if ! curl -fs --max-time 5 "$DEFECTS4J_URL/health" >/dev/null; then
  echo "FATAL: $DEFECTS4J_URL not healthy — bring up defects4j_docker_web first" >&2
  exit 1
fi
if [ ! -x "./venv/bin/python" ]; then
  echo "FATAL: ./venv/bin/python missing — see ra-d4j-run-recipe" >&2
  exit 1
fi

# True if a plausible patch for $1=Project $2=Index already exists.
has_plausible() {
  local p="$1" i="$2"
  # match the casing repairagent.py uses: lower-cased project name
  find "$EXP_ROOT" -maxdepth 3 -type f \
    \( -name "plausible_patches_${p}_${i}.json" -o -name "plausible_patches_$(echo "$p"|tr A-Z a-z)_${i}.json" \) \
    -size +2c 2>/dev/null | head -1
}

total=$(grep -cE '\S' "$BUGS")
echo "SWEEP_START $(date +%F\ %T)  total=$total bugs  model=$MODEL  c$MAX_CYCLES  url=$DEFECTS4J_URL"
mkdir -p logs_113
i=0
ok=0; fail=0; skip=0
fast_fail_streak=0   # consecutive bugs failing in <30s = infra issue
while IFS= read -r line || [ -n "$line" ]; do
  [ -z "${line// }" ] && continue
  i=$((i+1))
  proj=$(echo "$line" | awk '{print $1}')
  idx=$(echo "$line" | awk '{print $2}')
  bug="$proj $idx"

  exist=$(has_plausible "$proj" "$idx")
  if [ -n "$exist" ]; then
    skip=$((skip+1))
    line_out="$(date +%T) [$i/$total] $bug  SKIP  (already plausible: $exist)"
    echo "$line_out"; echo "$line_out" >> "$SUMMARY"
    continue
  fi

  log="logs_113/${proj}_${idx}.log"
  t0=$SECONDS
  ./venv/bin/python repairagent.py run --bugs "$bug" --model "$MODEL" \
       --max-cycles "$MAX_CYCLES" > "$log" 2>&1
  rc=$?
  dt=$((SECONDS - t0))

  new_exp=$(ls -dt "$EXP_ROOT"/experiment_* 2>/dev/null | head -1)
  if [ -n "$(has_plausible "$proj" "$idx")" ]; then
    ok=$((ok+1)); status="OK"; fast_fail_streak=0
  elif [ $rc -ne 0 ]; then
    fail=$((fail+1)); status="FAIL(rc=$rc)"
    if [ "$dt" -lt 30 ]; then fast_fail_streak=$((fast_fail_streak+1)); else fast_fail_streak=0; fi
  else
    fail=$((fail+1)); status="NOFIX"
    if [ "$dt" -lt 30 ]; then fast_fail_streak=$((fast_fail_streak+1)); else fast_fail_streak=0; fi
  fi
  line_out="$(date +%T) [$i/$total] $bug  $status  ${dt}s  $new_exp"
  echo "$line_out"; echo "$line_out" >> "$SUMMARY"

  # Infrastructure-failure circuit-breaker: a real cycle takes minutes; <30s
  # back-to-back failures mean the LLM endpoint, Docker, or workspace mount is
  # broken.  Bail before the whole bug list burns.
  if [ "$fast_fail_streak" -ge 3 ]; then
    msg="SWEEP_ABORT $(date +%F\ %T)  3 consecutive <30s failures — infra issue (mount? container? endpoint?). Fix and rerun (resume-safe)."
    echo "$msg"; echo "$msg" >> "$SUMMARY"
    exit 2
  fi
done < "$BUGS"

echo "SWEEP_END $(date +%F\ %T)  ok=$ok  nofix/fail=$fail  skip=$skip  / total=$total"
echo "SWEEP_END $(date +%F\ %T)  ok=$ok  nofix/fail=$fail  skip=$skip  / total=$total" >> "$SUMMARY"
