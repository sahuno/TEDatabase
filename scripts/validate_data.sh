#!/usr/bin/env bash
# Author: Samuel Ahuno
# Date:   2026-04-20
# Purpose: Validate that all required processed/site data files exist and are
#          well-formed after a pipeline run. Exits 1 if any check fails.

set -euo pipefail

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
LOG_FILE="logs/validate_data_$(date '+%Y%m%d_%H%M%S').log"
mkdir -p logs

log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# ---------------------------------------------------------------------------
# Session header
# ---------------------------------------------------------------------------
log_msg "=== validate_data.sh started ==="
log_msg "Working directory : $(pwd)"
log_msg "Log file          : ${LOG_FILE}"

# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------
FAILURES=0

pass() { log_msg "PASS  $*"; }
fail() { log_msg "FAIL  $*"; FAILURES=$(( FAILURES + 1 )); }
warn() { log_msg "WARN  $*"; }

# ---------------------------------------------------------------------------
# Check 1: data/processed/loci.json exists and is non-empty
# ---------------------------------------------------------------------------
TARGET="data/processed/loci.json"
log_msg "--- Check 1: ${TARGET} exists and is non-empty ---"
if [[ ! -f "${TARGET}" ]]; then
    fail "${TARGET} not found"
elif [[ ! -s "${TARGET}" ]]; then
    fail "${TARGET} exists but is empty"
else
    pass "${TARGET} exists ($(wc -c < "${TARGET}") bytes)"
fi

# ---------------------------------------------------------------------------
# Check 2: data/processed/loci.json is valid JSON
# ---------------------------------------------------------------------------
log_msg "--- Check 2: ${TARGET} is valid JSON ---"
if [[ -f "${TARGET}" ]]; then
    if python3 -c "import json, sys; json.load(open(sys.argv[1]))" "${TARGET}" 2>>"${LOG_FILE}"; then
        LOCI_COUNT=$(python3 -c "import json, sys; d=json.load(open(sys.argv[1])); print(len(d) if isinstance(d, list) else 'non-list')" "${TARGET}")
        pass "${TARGET} is valid JSON — ${LOCI_COUNT} top-level entries"
    else
        fail "${TARGET} contains invalid JSON"
    fi
else
    fail "${TARGET} missing — skipping JSON parse check"
fi

# ---------------------------------------------------------------------------
# Check 3: site/data/loci.json exists (the copy served to the browser)
# ---------------------------------------------------------------------------
SITE_LOCI="site/data/loci.json"
log_msg "--- Check 3: ${SITE_LOCI} exists ---"
if [[ ! -f "${SITE_LOCI}" ]]; then
    fail "${SITE_LOCI} not found — run pipeline/06_build_site_data.py"
elif [[ ! -s "${SITE_LOCI}" ]]; then
    fail "${SITE_LOCI} exists but is empty"
else
    pass "${SITE_LOCI} exists ($(wc -c < "${SITE_LOCI}") bytes)"
fi

# ---------------------------------------------------------------------------
# Check 4: site/data/stats.json exists
# ---------------------------------------------------------------------------
STATS_FILE="site/data/stats.json"
log_msg "--- Check 4: ${STATS_FILE} exists ---"
if [[ ! -f "${STATS_FILE}" ]]; then
    fail "${STATS_FILE} not found"
elif [[ ! -s "${STATS_FILE}" ]]; then
    fail "${STATS_FILE} exists but is empty"
else
    pass "${STATS_FILE} exists ($(wc -c < "${STATS_FILE}") bytes)"
fi

# ---------------------------------------------------------------------------
# Check 5: site/data/stats.json has total_loci > 0  (warn, don't fail)
# ---------------------------------------------------------------------------
log_msg "--- Check 5: ${STATS_FILE} total_loci > 0 ---"
if [[ -f "${STATS_FILE}" ]]; then
    TOTAL_LOCI=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get('total_loci', 0))
except Exception as e:
    print(0)
" "${STATS_FILE}" 2>>"${LOG_FILE}")

    if [[ "${TOTAL_LOCI}" =~ ^[0-9]+$ ]] && (( TOTAL_LOCI > 0 )); then
        pass "${STATS_FILE} total_loci = ${TOTAL_LOCI}"
    elif [[ "${TOTAL_LOCI}" == "0" ]]; then
        warn "${STATS_FILE} total_loci is 0 — database may be empty or key is missing"
    else
        warn "${STATS_FILE} could not parse total_loci (got: ${TOTAL_LOCI})"
    fi
else
    fail "${STATS_FILE} missing — skipping total_loci check"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log_msg "=== Validation summary: ${FAILURES} failure(s) ==="

if (( FAILURES > 0 )); then
    log_msg "=== DONE: validate_data.sh completed with FAILURES ==="
    exit 1
fi

log_msg "=== DONE: validate_data.sh completed successfully ==="
