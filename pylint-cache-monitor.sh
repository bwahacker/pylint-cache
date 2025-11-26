#!/usr/bin/env bash
#
# pylint-cache-monitor.sh - Monitor for changes and trigger full re-analysis
#
# This script checks if any Python files have changed since the last run.
# If changes are detected, it forces a full re-analysis of the entire tree
# to catch cross-file dependency issues that caching might hide.
#
# Designed to run as a cron job every 15-30 minutes.
#
# Usage:
#   1. Edit CONFIGURATION section below
#   2. Make executable: chmod +x pylint-cache-monitor.sh
#   3. Add to crontab:
#      */15 * * * * /path/to/pylint-cache-monitor.sh
#

set -e

# ============================================================================
# CONFIGURATION - Edit this section
# ============================================================================

# Project directory to monitor
PROJECT_DIR="${PROJECT_DIR:-/path/to/your/project}"

# Source directories to check (relative to PROJECT_DIR)
SOURCE_DIRS=(
    "src"
    "lib"
)

# Pylint arguments
PYLINT_ARGS="${PYLINT_ARGS:--E}"

# Path to pylint-cache command
PYLINT_CACHE_CMD="${PYLINT_CACHE_CMD:-$(command -v pylint-cache 2>/dev/null || echo './pylint_cache.py')}"

# State directory (tracks last run time)
STATE_DIR="${HOME}/.cache/pylint-cache-monitor"
mkdir -p "$STATE_DIR"

# Log directory
LOG_DIR="${HOME}/.cache/pylint-cache-monitor/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/monitor-$(date +%Y%m%d).log"

# State file for this project (use hash of project path to avoid conflicts)
PROJECT_HASH=$(echo -n "$PROJECT_DIR" | md5sum 2>/dev/null | cut -d' ' -f1 || echo -n "$PROJECT_DIR" | md5 | cut -d' ' -f1)
STATE_FILE="$STATE_DIR/last_run_${PROJECT_HASH}.state"

# ============================================================================
# Functions
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

get_last_run_time() {
    if [ -f "$STATE_FILE" ]; then
        cat "$STATE_FILE"
    else
        echo "0"
    fi
}

update_last_run_time() {
    date +%s > "$STATE_FILE"
}

find_changed_files() {
    local last_run_time=$1
    local changed=0
    
    for src_dir in "${SOURCE_DIRS[@]}"; do
        local full_path="$PROJECT_DIR/$src_dir"
        
        if [ ! -d "$full_path" ]; then
            log "WARNING: Directory not found: $full_path"
            continue
        fi
        
        # Find Python files modified since last run
        local files=$(find "$full_path" -name "*.py" -type f -newermt "@$last_run_time" 2>/dev/null | wc -l)
        
        if [ "$files" -gt 0 ]; then
            log "Found $files changed Python file(s) in $src_dir/"
            changed=1
        fi
    done
    
    return $changed
}

# ============================================================================
# Main Logic
# ============================================================================

log "=========================================="
log "Starting pylint-cache monitor"
log "Project: $PROJECT_DIR"
log "Source dirs: ${SOURCE_DIRS[*]}"
log "State file: $STATE_FILE"

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    log "ERROR: Project directory not found: $PROJECT_DIR"
    exit 1
fi

# Check if pylint-cache is available
if [ ! -x "$PYLINT_CACHE_CMD" ] && ! command -v "$PYLINT_CACHE_CMD" &>/dev/null; then
    log "ERROR: pylint-cache not found at: $PYLINT_CACHE_CMD"
    exit 1
fi

# Get last run time
last_run=$(get_last_run_time)
log "Last run: $(date -r $last_run 2>/dev/null || date -d @$last_run 2>/dev/null || echo 'never')"

# Check for changes
if find_changed_files "$last_run"; then
    log "✓ Changes detected - triggering full re-analysis"
    log "This ensures cross-file dependency issues are caught"
    
    # Change to project directory
    cd "$PROJECT_DIR"
    
    # Build paths to check
    paths=()
    for src_dir in "${SOURCE_DIRS[@]}"; do
        if [ -d "$src_dir" ]; then
            paths+=("$src_dir")
        fi
    done
    
    if [ ${#paths[@]} -eq 0 ]; then
        log "ERROR: No valid source directories found"
        exit 1
    fi
    
    # Run pylint-cache (which will update cache with fresh results)
    log "Running: $PYLINT_CACHE_CMD ${paths[*]} --args='$PYLINT_ARGS'"
    
    if $PYLINT_CACHE_CMD "${paths[@]}" --args="$PYLINT_ARGS" >> "$LOG_FILE" 2>&1; then
        log "✓ Analysis completed successfully"
        exit_code=0
    else
        exit_code=$?
        log "⚠ Analysis completed with exit code: $exit_code"
    fi
    
    # Update last run time
    update_last_run_time
    log "Updated last run timestamp"
    
    # Extract stats from output
    stats=$(tail -20 "$LOG_FILE" | grep "^\[STATS\]" | tail -1)
    if [ -n "$stats" ]; then
        log "Stats: $stats"
    fi
    
else
    log "○ No changes detected - skipping analysis"
    log "Next check will run per cron schedule"
fi

log "Monitor run complete"
log "=========================================="

# Clean up old logs (keep last 30 days)
find "$LOG_DIR" -name "monitor-*.log" -mtime +30 -delete 2>/dev/null || true

exit 0

