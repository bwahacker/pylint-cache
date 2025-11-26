# Background Monitoring Setup

The monitor runs in the background to detect file changes and trigger full re-analysis. This helps catch cross-file dependency issues that caching might hide.

## Why Use the Monitor?

`pylint-cache` is extremely fast because it caches results per-file. However, this means:

- If `file_a.py` imports `file_b.py` and only `file_b.py` changes, `file_a.py` won't be re-analyzed
- Cross-file issues (import errors, type mismatches, etc.) might not be detected

**The monitor solves this:**
- Maintains a registry of projects to monitor in `~/.cache/pylint-cache-monitor/projects.json`
- Runs every 15-30 minutes via cron (configurable)
- Checks if ANY Python file changed since last run
- If changes detected → runs pylint on ENTIRE tree
- Results are cached, so developers get instant feedback
- Uses lock files to prevent concurrent runs on the same project

## Quick Setup

### 1. Register Your Project(s)

```bash
# Register a project to monitor
pylint-cache-monitor add /path/to/project --dirs src,lib --args "-E"

# Register another project
pylint-cache-monitor add /another/project --dirs app --args "--disable=C0111"

# List all registered projects
pylint-cache-monitor list
```

### 2. Test the Monitor

```bash
# Run manually to test
pylint-cache-monitor run

# Run with verbose output
pylint-cache-monitor run -v
```

### 3. Configure Cron (OLD - Shell Script Approach)

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
# Every 15 minutes (recommended)
*/15 * * * * pylint-cache-monitor run

# Every 30 minutes
*/30 * * * * pylint-cache-monitor run

# Every hour
0 * * * * pylint-cache-monitor run

# Every 15 minutes during work hours (8am-6pm, weekdays)
*/15 8-18 * * 1-5 pylint-cache-monitor run
```

**That's it!** All registered projects will be checked automatically.

## Registry Management

### Add a Project

```bash
pylint-cache-monitor add /path/to/project --dirs src,lib --args "-E"
```

### Remove a Project

```bash
pylint-cache-monitor remove /path/to/project
```

### List Monitored Projects

```bash
pylint-cache-monitor list
```

Output:
```
Monitored projects (2):
--------------------------------------------------------------------------------

📁 /home/user/project1
   Source dirs: src, lib
   Pylint args: -E
   Last run: 2025-11-24 14:30:15

📁 /home/user/project2
   Source dirs: app
   Pylint args: --disable=C0111
   Last run: 2025-11-24 14:31:42
```

## How It Works

1. **Registry**: Stores project list and config in `~/.cache/pylint-cache-monitor/projects.json`
2. **State Tracking**: Stores last run timestamp per project in the registry
3. **Lock Files**: Creates lock files in `~/.cache/pylint-cache-monitor/locks/` to prevent concurrent runs
4. **Change Detection**: Checks file modification times since last run
5. **Full Re-analysis**: If changes found, runs `pylint-cache` on entire tree
6. **Cache Update**: Results are stored in the cache database
7. **Developer Benefit**: When you run `pylint-cache` while coding, you get cached results from the latest full analysis

### Concurrency Protection

- If cron triggers while a project is already being analyzed, the new job **exits immediately**
- Uses `fcntl` file locking (Linux/macOS) for reliable concurrency control
- Lock files are automatically cleaned up after analysis completes
- Stale locks (>1 hour old) are automatically removed

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

### Check Registry

```bash
# List all registered projects
pylint-cache-monitor list

# View registry file directly
cat ~/.cache/pylint-cache-monitor/projects.json
```

### Check Monitor Logs

```bash
# Today's log
tail -f ~/.cache/pylint-cache-monitor/logs/monitor-$(date +%Y%m%d).log

# All logs
ls -lh ~/.cache/pylint-cache-monitor/logs/

# Recent activity
tail -50 ~/.cache/pylint-cache-monitor/logs/monitor-$(date +%Y%m%d).log
```

### Check Lock Files

```bash
# See if any projects are currently running
ls -lh ~/.cache/pylint-cache-monitor/locks/
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
# Register a test project
pylint-cache-monitor add /path/to/project --dirs src --args "-E"

# Run the monitor
pylint-cache-monitor run -v

# Touch a file to trigger re-analysis
touch /path/to/project/src/somefile.py

# Run again - should detect change and re-analyze
pylint-cache-monitor run -v
```

### Simulate Concurrent Run

```bash
# Terminal 1: Start long-running analysis
pylint-cache-monitor run

# Terminal 2: Try to run again (should be skipped)
pylint-cache-monitor run
# Output: 🔒 Skipping /path/to/project (already running)
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

