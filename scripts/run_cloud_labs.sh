#!/usr/bin/env bash
# =============================================================================
# 🚀 Cloud Lab Runner — ai-gateway
# =============================================================================
# terraform apply → run all labs → terraform destroy
#
# Usage:
#   ./scripts/run_cloud_labs.sh --provider aws --email you@email.com
#   ./scripts/run_cloud_labs.sh --provider azure --email you@email.com
#   ./scripts/run_cloud_labs.sh --provider aws --email you@email.com --cost-limit 15
#   ./scripts/run_cloud_labs.sh --dry-run --provider aws
#
# Author: Ketan (private — personal use only)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
REPO_NAME="ai-gateway"
PORT=8100
EXPECTED_LABS=8

PROVIDER=""; EMAIL=""; BUDGET=5; TIMEOUT_MINUTES=120; DRY_RUN=false; SKIP_DESTROY=false

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[✅ $(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[⚠️  $(date +%H:%M:%S)]${NC} $*"; }
fail() { echo -e "${RED}[❌ $(date +%H:%M:%S)]${NC} $*"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --provider)     PROVIDER="$2";        shift 2 ;;
        --email)        EMAIL="$2";           shift 2 ;;
        --budget)       BUDGET="$2";          shift 2 ;;
        --cost-limit)   BUDGET="$2";          shift 2 ;;
        --timeout)      TIMEOUT_MINUTES="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true;         shift ;;
        --skip-destroy) SKIP_DESTROY=true;    shift ;;
        *) fail "Unknown flag: $1"; exit 1 ;;
    esac
done

[[ -z "$PROVIDER" ]] && { fail "Usage: $0 --provider <aws|azure> --email <you@email.com>"; exit 1; }
[[ "$PROVIDER" != "aws" && "$PROVIDER" != "azure" ]] && { fail "Provider must be 'aws' or 'azure'"; exit 1; }
[[ -z "$EMAIL" ]] && warn "No --email provided."

INFRA_DIR="$REPO_DIR/infra/$PROVIDER"
RESULTS_DIR="$SCRIPT_DIR/lab_results/$PROVIDER"
REPORT_FILE="$RESULTS_DIR/cloud-lab-report.txt"

check_cost() {
    local cost="0"
    if [[ "$PROVIDER" == "aws" ]]; then
        cost=$(aws ce get-cost-and-usage --time-period "Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d)" \
            --granularity MONTHLY --metrics BlendedCost \
            --query 'ResultsByTime[0].Total.BlendedCost.Amount' --output text 2>/dev/null || echo "0")
    else
        cost=$(az consumption usage list --start-date "$(date +%Y-%m-01)" --end-date "$(date +%Y-%m-%d)" \
            --query "sum([].pretaxCost)" --output tsv 2>/dev/null || echo "0")
    fi
    local exceeded; exceeded=$(awk "BEGIN { print ($cost >= $BUDGET) ? 1 : 0 }")
    [[ "$exceeded" == "1" ]] && { fail "💰 BUDGET EXCEEDED! €$cost >= €$BUDGET"; return 1; }
    log "💰 Budget: €$cost / €$BUDGET ($(awk "BEGIN { printf \"%.0f\", ($cost/$BUDGET)*100 }")%)"
}

tf_apply() {
    log "🏗️  Terraform init + apply ($PROVIDER)..."
    if $DRY_RUN; then log "[DRY RUN] terraform apply"; return 0; fi
    terraform -chdir="$INFRA_DIR" init -input=false -no-color
    terraform -chdir="$INFRA_DIR" apply -auto-approve -input=false -no-color \
        -var="alert_email=${EMAIL:-noop@example.com}" -var="cost_limit_eur=$BUDGET"
    ok "Infrastructure deployed"
}

tf_destroy() {
    if $SKIP_DESTROY; then warn "⚠️ --skip-destroy: resources STILL RUNNING!"; return; fi
    log "💣 Terraform destroy ($PROVIDER)..."
    if $DRY_RUN; then log "[DRY RUN] terraform destroy"; return 0; fi
    terraform -chdir="$INFRA_DIR" destroy -auto-approve -input=false -no-color \
        -var="alert_email=${EMAIL:-noop@example.com}" -var="cost_limit_eur=$BUDGET" || true
    ok "Infrastructure destroyed"
}

trap tf_destroy EXIT INT TERM

# ---------------------------------------------------------------------------
# App server management
# ---------------------------------------------------------------------------
APP_PID=""

start_server() {
    log "🖥️  Starting ai-gateway server on port $PORT..."
    if $DRY_RUN; then log "[DRY RUN] poetry run start"; return 0; fi
    (
        cd "$REPO_DIR"
        poetry run uvicorn src.main:app --host 0.0.0.0 --port "$PORT" \
            > "$RESULTS_DIR/server.log" 2>&1
    ) &
    APP_PID=$!

    local retries=30
    while (( retries > 0 )); do
        if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
            ok "Server is up (PID=$APP_PID)"
            return 0
        fi
        if ! kill -0 "$APP_PID" 2>/dev/null; then
            fail "Server process died. Check $RESULTS_DIR/server.log"
            tail -20 "$RESULTS_DIR/server.log"
            return 1
        fi
        sleep 2
        retries=$((retries - 1))
    done
    fail "Server did not start within 60s"
    return 1
}

stop_server() {
    if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
        log "Stopping server (PID=$APP_PID)..."
        kill "$APP_PID" 2>/dev/null || true
        wait "$APP_PID" 2>/dev/null || true
        APP_PID=""
    fi
}

cleanup() {
    stop_server
    tf_destroy
}
trap cleanup EXIT INT TERM

scan_results() {
    local results_dir="$1"
    local total=0 passed=0 failed=0

    echo ""
    echo "=========================================="
    echo "  📋 Lab Completion Report — $REPO_NAME"
    echo "  Provider: $PROVIDER"
    echo "  Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=========================================="
    echo ""

    # ai-gateway stores results in raw-results.json with experiment list
    local raw_json="$results_dir/raw-results.json"
    if [[ -f "$raw_json" ]]; then
        python3 -c "
import json
data = json.load(open('$raw_json'))
results = data if isinstance(data, list) else data.get('results', [])
passed = sum(1 for r in results if r.get('status') == 'success')
failed = sum(1 for r in results if r.get('status') == 'failed')
errors = sum(1 for r in results if r.get('status') == 'error')
skipped = sum(1 for r in results if r.get('status') in ('skipped', 'not_run'))
total = len(results)

for r in results:
    icon = '✅' if r['status'] == 'success' else '❌' if r['status'] in ('failed','error') else '⏭️'
    print(f\"  {icon} {r.get('experiment_id','?')}: {r.get('description','')}\")

print()
print(f'  ─────────────────────────────────')
print(f'  Total expected:  $EXPECTED_LABS')
print(f'  Ran:             {total}')
print(f'  Passed:          {passed}')
print(f'  Failed:          {failed}')
print(f'  Errors:          {errors}')
print(f'  Skipped/Not run: {skipped}')
not_run = $EXPECTED_LABS - total
if not_run > 0:
    print(f'  Not started:     {not_run}')
print(f'  ─────────────────────────────────')

if total == $EXPECTED_LABS and passed == total:
    print(f'\n  🎉 ALL $EXPECTED_LABS labs passed on $PROVIDER!')
elif failed > 0 or errors > 0:
    print(f'\n  ⚠️  {failed + errors} labs need attention.')
"
    else
        echo "  ⚠️  No raw-results.json found in $results_dir"
        echo "  Labs may not have run at all."
    fi

    echo ""
    echo "=========================================="
}

main() {
    echo ""
    echo "=========================================="
    echo "  🚀 Cloud Lab Runner — $REPO_NAME"
    echo "=========================================="
    echo "  Provider:   $PROVIDER"
    echo "  Budget:     €$BUDGET"
    echo "  Timeout:    ${TIMEOUT_MINUTES} min"
    echo "  Email:      ${EMAIL:-<none>}"
    echo "  Dry run:    $DRY_RUN"
    echo "  Labs:       $EXPECTED_LABS expected"
    echo "=========================================="
    echo ""

    local start_time=$SECONDS

    log "━━━ Phase 1: Deploy infrastructure ━━━"
    tf_apply
    if ! $DRY_RUN; then check_cost || exit 1; fi

    log "━━━ Starting application server ━━━"
    mkdir -p "$RESULTS_DIR"
    start_server || exit 1

    log "━━━ Phase 2: Run hands-on labs ━━━"
    local lab_exit=0
    if $DRY_RUN; then
        log "[DRY RUN] poetry run python scripts/run_all_labs.py --env $PROVIDER"
    else
        mkdir -p "$RESULTS_DIR"
        (cd "$REPO_DIR" && timeout $((TIMEOUT_MINUTES * 60)) \
            poetry run python scripts/run_all_labs.py --env "$PROVIDER" 2>&1 | tee "$RESULTS_DIR/run_output.log"
        ) || lab_exit=$?
        [[ $lab_exit -eq 124 ]] && warn "⏰ Timed out after ${TIMEOUT_MINUTES} min"
        [[ $lab_exit -ne 0 && $lab_exit -ne 124 ]] && warn "Labs exited with code $lab_exit"
        check_cost || true
    fi

    log "━━━ Phase 3: Cleanup (terraform destroy) ━━━"

    if ! $DRY_RUN; then
        scan_results "$RESULTS_DIR" | tee "$REPORT_FILE"
    fi

    log "Total time: $(( (SECONDS - start_time) / 60 )) minutes"
}

main
