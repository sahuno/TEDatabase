#!/usr/bin/env bash
# Author: Samuel Ahuno
# Date:   2026-04-20
# Purpose: Local full-pipeline runner for development and manual runs.
#          Executes all 6 pipeline stages sequentially, with optional seed step.
#          Stops on first failure. Prints elapsed wall time on completion.
#
# Usage:
#   bash scripts/run_pipeline.sh           # run all 6 stages
#   bash scripts/run_pipeline.sh --seed    # run seed_l1base2.py first, then all 6 stages

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
RUN_SEED=0

for arg in "$@"; do
    case "${arg}" in
        --seed)
            RUN_SEED=1
            ;;
        -h|--help)
            grep '^# ' "$0" | sed 's/^# //'
            exit 0
            ;;
        *)
            echo "Unknown argument: ${arg}" >&2
            echo "Usage: $0 [--seed]" >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
SCRIPT_NAME="$(basename "$0" .sh)"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="logs/${SCRIPT_NAME}_${TIMESTAMP}.log"
mkdir -p logs

# Tee all stdout+stderr to the log file for the rest of the script
exec > >(tee -a "${LOG_FILE}") 2>&1

log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ---------------------------------------------------------------------------
# Session header
# ---------------------------------------------------------------------------
log_msg "=== ${SCRIPT_NAME} started ==="
log_msg "Working directory : $(pwd)"
log_msg "Log file          : ${LOG_FILE}"
log_msg "Python            : $(python3 --version 2>&1)"
log_msg "Run seed stage    : ${RUN_SEED}"

START_EPOCH=$(date +%s)

# ---------------------------------------------------------------------------
# Helper: run a numbered pipeline stage
# ---------------------------------------------------------------------------
run_stage() {
    local LABEL="$1"
    local CMD="$2"

    log_msg "--- Stage: ${LABEL} ---"
    log_msg "Command: ${CMD}"
    eval "${CMD}"
    log_msg "Stage complete: ${LABEL}"
}

# ---------------------------------------------------------------------------
# Optional seed stage
# ---------------------------------------------------------------------------
if (( RUN_SEED )); then
    run_stage "Seed — L1Base2 import" \
        "python3 pipeline/seed_l1base2.py --log_dir logs"
fi

# ---------------------------------------------------------------------------
# Core pipeline stages
# ---------------------------------------------------------------------------
run_stage "Stage 1 — PubMed search" \
    "python3 pipeline/01_pubmed_search.py --log_dir logs"

run_stage "Stage 2 — Download papers" \
    "python3 pipeline/02_paper_fetch.py --log_dir logs"

run_stage "Stage 3 — LLM extraction" \
    "python3 pipeline/03_llm_extract.py --log_dir logs"

run_stage "Stage 4 — Liftover" \
    "python3 pipeline/04_liftover.py --log_dir logs"

run_stage "Stage 5 — Dedup and merge" \
    "python3 pipeline/05_dedup_merge.py --log_dir logs"

run_stage "Stage 6 — Build site data" \
    "python3 pipeline/06_build_site_data.py --log_dir logs"

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
log_msg "--- Running output validation ---"
bash scripts/validate_data.sh

# ---------------------------------------------------------------------------
# Elapsed time
# ---------------------------------------------------------------------------
END_EPOCH=$(date +%s)
ELAPSED=$(( END_EPOCH - START_EPOCH ))
ELAPSED_MIN=$(( ELAPSED / 60 ))
ELAPSED_SEC=$(( ELAPSED % 60 ))
log_msg "Completed in ${ELAPSED_MIN}m ${ELAPSED_SEC}s"

log_msg "=== DONE: ${SCRIPT_NAME} completed successfully ==="
