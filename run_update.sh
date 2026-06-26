#!/usr/bin/env bash
set -euo pipefail

# Configure these via environment variables or edit before first use.
CONDA_BASE="${CONDA_BASE:-$(conda info --base 2>/dev/null || echo "")}"
CONDA_ENV="${CONDA_ENV:-osl_forecast}"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/cron_update.log}"

exec >> "${LOG_FILE}" 2>&1
echo "===== $(date) ====="

if [ -n "${CONDA_BASE}" ] && [ -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]; then
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
    conda activate "${CONDA_ENV}"
fi

cd "${PROJECT_DIR}"

python3 app/update_actual_prices.py

git add data/oslo_actual_prices.csv
git commit -m "Updated actual price $(date +%F)" || echo "Nothing to commit"
git push

