# Background Monitoring Setup

The monitor script runs in the background to detect file changes and trigger full re-analysis. This helps catch cross-file dependency issues that caching might hide.

## Why Use the Monitor?

`pylint-cache` is extremely fast because it caches results per-file. However, this means:

- If `file_a.py` imports `file_b.py` and only `file_b.py` changes, `file_a.py` won't be re-analyzed
- Cross-file issues (import errors, type mismatches, etc.) might not be detected

**The monitor solves this:**
- Runs every 15-30 minutes (configurable)
- Checks if ANY Python file changed since last run
- If changes detected → runs pylint on ENTIRE tree
- Results are cached, so developers get instant feedback
- When you code and run `pylint-cache`, you see errors from the latest full analysis

## Quick Setup

### 1. Configure the Monitor Script

Edit `pylint-cache-monitor.sh`:

```bash
# Project directory to monitor
PROJECT_DIR="/path/to/your/project"

# Source directories to check (relative to PROJECT_DIR)
SOURCE_DIRS=(
    "src"
    "lib"
)

# Pylint arguments
PYLINT_ARGS="-E"  # Errors only, or customize
```

### 2. Test the Script

```bash
# Run manually first to verify it works
./pylint-cache-monitor.sh

# Check the logs
tail -f ~/.cache/pylint-cache-monitor/logs/monitor-$(date +%Y%m%d).log
```

### 3. Add to Crontab

```bash
crontab -e
```

Add one of these lines:

```cron
# Every 15 minutes
*/15 * * * * /path/to/pylint-cache-monitor.sh

# Every 30 minutes
*/30 * * * * /path/to/pylint-cache-monitor.sh

# Every hour
0 * * * * /path/to/pylint-cache-monitor.sh

# Every 15 minutes during work hours (8am-6pm, weekdays)
*/15 8-18 * * 1-5 /path/to/pylint-cache-monitor.sh
```

### 4. Monitor Multiple Projects

Create a wrapper script:

```bash
#!/bin/bash
# monitor-all.sh

export PROJECT_DIR="/home/user/project1"
export SOURCE_DIRS="src lib"
export PYLINT_ARGS="-E"
/path/to/pylint-cache-monitor.sh

export PROJECT_DIR="/home/user/project2"
export SOURCE_DIRS="app"
export PYLINT_ARGS="--disable=C0111"
/path/to/pylint-cache-monitor.sh
```

Then add to crontab:

```cron
*/30 * * * * /path/to/monitor-all.sh
```

## How It Works

1. **State Tracking**: Stores last run timestamp in `~/.cache/pylint-cache-monitor/last_run_<hash>.state`
2. **Change Detection**: Uses `find -newermt` to detect files modified since last run
3. **Full Re-analysis**: If changes found, runs `pylint-cache` on entire tree
4. **Cache Update**: Results are stored in the cache database
5. **Developer Benefit**: When you run `pylint-cache` while coding, you get cached results from the latest full analysis

## Workflow Example

### Without Monitor:
```
9:00 AM - Developer A changes file_a.py → runs pylint-cache → sees errors in file_a.py
9:30 AM - Developer B changes file_b.py (imported by file_a.py)
10:00 AM - Developer A edits file_c.py → runs pylint-cache
          → file_a.py shows cached (old) results
          → Misses new import error from file_b.py changes!
```

### With Monitor (runs every 30 min):
```
9:00 AM - Developer A changes file_a.py → runs pylint-cache → sees errors
9:30 AM - Developer B changes file_b.py
9:35 AM - Monitor detects change → re-analyzes entire tree → caches new results
10:00 AM - Developer A edits file_c.py → runs pylint-cache
          → file_a.py shows fresh cached results including file_b.py changes!
          → Sees import error immediately!
```

## Logs and Debugging

### Check Monitor Logs

```bash
# Today's log
tail -f ~/.cache/pylint-cache-monitor/logs/monitor-$(date +%Y%m%d).log

# All logs
ls -lh ~/.cache/pylint-cache-monitor/logs/

# Recent activity
tail -50 ~/.cache/pylint-cache-monitor/logs/monitor-$(date +%Y%m%d).log
```

### Verify Cron is Running

```bash
# Check cron service
systemctl status cron  # Linux
# or
sudo launchctl list | grep cron  # macOS

# View cron execution logs
grep CRON /var/log/syslog  # Linux
tail -f /var/log/system.log | grep cron  # macOS
```

### Manual Test

```bash
# Set a test project
export PROJECT_DIR="/path/to/project"
export SOURCE_DIRS="src"
export PYLINT_ARGS="-E"

# Run the monitor
./pylint-cache-monitor.sh

# Touch a file to trigger re-analysis
touch /path/to/project/src/somefile.py

# Run again - should detect change
./pylint-cache-monitor.sh
```

## Environment Variables

Override configuration via environment variables:

```bash
export PROJECT_DIR="/custom/path"
export SOURCE_DIRS="src lib tests"
export PYLINT_ARGS="--disable=C0111 --max-line-length=120"
export PYLINT_CACHE_CMD="/usr/local/bin/pylint-cache"

./pylint-cache-monitor.sh
```

## Performance Considerations

- **Monitor overhead**: Uses `find` to check modification times (very fast)
- **Re-analysis trigger**: Only runs full pylint when changes detected
- **Caching benefit**: Full analysis results are cached, so developer runs are instant
- **Frequency**: Every 15-30 minutes is reasonable for most projects
  - More frequent = faster cross-file error detection
  - Less frequent = less system load

## Advanced: Systemd Service (Linux)

Instead of cron, use systemd for automatic restart and logging:

### Create service file: `/etc/systemd/system/pylint-cache-monitor.service`

```ini
[Unit]
Description=Pylint Cache Monitor for Project
After=network.target

[Service]
Type=simple
User=youruser
Environment="PROJECT_DIR=/path/to/project"
Environment="SOURCE_DIRS=src lib"
Environment="PYLINT_ARGS=-E"
ExecStart=/usr/local/bin/pylint-cache-monitor.sh
Restart=on-failure
RestartSec=1800

[Install]
WantedBy=multi-user.target
```

### Create timer: `/etc/systemd/system/pylint-cache-monitor.timer`

```ini
[Unit]
Description=Run Pylint Cache Monitor every 30 minutes
Requires=pylint-cache-monitor.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable pylint-cache-monitor.timer
sudo systemctl start pylint-cache-monitor.timer
sudo systemctl status pylint-cache-monitor.timer
```

## Tips

1. **Start with longer intervals** (30-60 min) and adjust based on team size
2. **Monitor logs** for the first few days to ensure it's working
3. **Combine with pre-commit hooks** for comprehensive coverage
4. **Use different args** for monitor vs interactive (e.g., monitor runs all checks, interactive runs errors only)
5. **Share cache database** on network drive for team-wide benefit

