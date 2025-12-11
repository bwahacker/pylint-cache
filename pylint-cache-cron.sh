#!/usr/bin/env bash
#
# pylint-cache-cron.sh - Cron job helper for pre-warming pylint cache
#
# This script runs pylint-cache on your project(s) during off-hours to
# pre-populate the cache. When developers run pylint-cache later, they
# get instant results from the cache.
#
# Usage:
#   1. Edit this script to configure your projects and pylint args
#   2. Make it executable: chmod +x pylint-cache-cron.sh
#   3. Add to crontab (see examples below)
#

set -e

# ============================================================================
# CONFIGURATION - Edit this section for your projects
# ============================================================================

# Projects to cache (space-separated list of directories)
PROJECTS=(
    "/home/user/projects/myproject1/src"
    "/home/user/projects/myproject2"
)

# Pylint arguments to use (optional)
PYLINT_ARGS="--disable=C0111,R0903 --max-line-length=100"

# Path to pylint-cache command (auto-detect or specify)
PYLINT_CACHE_CMD="${PYLINT_CACHE_CMD:-$(command -v pylint-cache 2>/dev/null || echo './pylint_cache.py')}"

# Log file location
LOG_DIR="${HOME}/.cache/pylint-cache-cron"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/pylint-cache-$(date +%Y%m%d).log"

# ============================================================================
# Script Logic - No need to edit below this line
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Starting pylint-cache cron job ==="
log "Using pylint-cache: $PYLINT_CACHE_CMD"

# Check if pylint-cache is available
if [ ! -x "$PYLINT_CACHE_CMD" ] && ! command -v "$PYLINT_CACHE_CMD" &>/dev/null; then
    log "ERROR: pylint-cache not found at: $PYLINT_CACHE_CMD"
    exit 1
fi

total_projects=${#PROJECTS[@]}
success_count=0
error_count=0

# Process each project
for project_dir in "${PROJECTS[@]}"; do
    if [ ! -d "$project_dir" ]; then
        log "WARNING: Project directory not found: $project_dir"
        ((error_count++))
        continue
    fi
    
    log "Processing: $project_dir"
    
    # Run pylint-cache
    if [ -n "$PYLINT_ARGS" ]; then
        if $PYLINT_CACHE_CMD "$project_dir" --args="$PYLINT_ARGS" >> "$LOG_FILE" 2>&1; then
            log "✓ Success: $project_dir"
            ((success_count++))
        else
            exit_code=$?
            log "✗ Completed with issues (exit $exit_code): $project_dir"
            # Don't count pylint issues as errors - we're just caching
            ((success_count++))
        fi
    else
        if $PYLINT_CACHE_CMD "$project_dir" >> "$LOG_FILE" 2>&1; then
            log "✓ Success: $project_dir"
            ((success_count++))
        else
            exit_code=$?
            log "✗ Completed with issues (exit $exit_code): $project_dir"
            ((success_count++))
        fi
    fi
done

log "=== Cron job complete ==="
log "Summary: $success_count/$total_projects projects processed, $error_count errors"
log "Log saved to: $LOG_FILE"

# Clean up old logs (keep last 30 days)
find "$LOG_DIR" -name "pylint-cache-*.log" -mtime +30 -delete 2>/dev/null || true

exit 0




