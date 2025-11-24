# Setting Up Automated Cache Pre-warming

Running `pylint-cache` periodically on your projects means developers get instant results from the cache instead of waiting for pylint to run.

## Quick Setup

### 1. Configure the Cron Script

Edit `pylint-cache-cron.sh` and set your projects:

```bash
PROJECTS=(
    "/home/user/projects/myproject1/src"
    "/home/user/projects/myproject2"
)

PYLINT_ARGS="--disable=C0111 --max-line-length=100"
```

### 2. Add to Crontab

```bash
# Edit your crontab
crontab -e
```

Add one of these lines:

```cron
# Run every hour (every day at :00)
0 * * * * /path/to/pylint-cache-cron.sh

# Run every night at 2 AM
0 2 * * * /path/to/pylint-cache-cron.sh

# Run every 6 hours
0 */6 * * * /path/to/pylint-cache-cron.sh

# Run every weekday at 6 AM (before work starts)
0 6 * * 1-5 /path/to/pylint-cache-cron.sh

# Run twice a day (8 AM and 8 PM)
0 8,20 * * * /path/to/pylint-cache-cron.sh
```

### 3. Verify It's Working

Check the logs:

```bash
ls -la ~/.cache/pylint-cache-cron/
cat ~/.cache/pylint-cache-cron/pylint-cache-$(date +%Y%m%d).log
```

## Cron Schedule Examples

```
# Minute Hour Day Month Weekday Command
# (0-59) (0-23) (1-31) (1-12) (0-7, 0=Sun)

0 * * * *          # Every hour
*/30 * * * *       # Every 30 minutes
0 */2 * * *        # Every 2 hours
0 9 * * *          # Daily at 9 AM
0 0 * * *          # Daily at midnight
0 2 * * 0          # Weekly on Sunday at 2 AM
0 3 1 * *          # Monthly on the 1st at 3 AM
```

## How It Works

1. **Cron runs the script** at scheduled times
2. **Script runs pylint-cache** on all configured projects
3. **Cache is populated** with fresh results
4. **Developers run pylint-cache** later and get instant results from cache
5. **Logs are saved** to `~/.cache/pylint-cache-cron/`

## Benefits

- ✅ **Faster CI/CD**: Pre-warmed cache means faster build times
- ✅ **Fresh results**: Regular runs keep cache up-to-date
- ✅ **Developer experience**: Instant feedback from cache
- ✅ **Shared cache**: If cache DB is on shared storage, everyone benefits

## Advanced: Shared Team Cache

By default, the cache is stored in `~/.pylint-cache.db` (each user has their own).

For a shared team cache on a network drive:

```bash
# Set cache location via environment variable
export PYLINT_CACHE_DB="/shared/cache/pylint-cache.db"
pylint-cache src/ --args="..."

# Add this to your pylint-cache-cron.sh before running
export PYLINT_CACHE_DB="/shared/cache/pylint-cache.db"
```

This way, the entire team shares the same cache:
- ✅ One person runs pylint on a file, everyone benefits
- ✅ Cron job pre-warms cache for the whole team
- ✅ CI/CD can also use the shared cache

## Troubleshooting

### Cron job not running?

```bash
# Check cron service is running
systemctl status cron  # Linux
# or
sudo launchctl list | grep cron  # macOS

# Check cron logs
grep CRON /var/log/syslog  # Linux
tail -f /var/log/system.log | grep cron  # macOS
```

### Script errors?

```bash
# Run manually to see errors
./pylint-cache-cron.sh

# Check the log file
tail -f ~/.cache/pylint-cache-cron/pylint-cache-$(date +%Y%m%d).log
```

### Permission issues?

Make sure the cron job runs as the correct user and has access to:
- The project directories
- The cache database location
- Python/pylint installation

## Cache Location

By default, the cache is stored in `~/.pylint-cache.db` in your home directory, not in the project directory. This means:

- No need to add it to `.gitignore` (it's not in the project)
- Single cache shared across all your projects
- Easy to clear: `rm ~/.pylint-cache.db`

To check cache statistics:

```bash
sqlite3 ~/.pylint-cache.db "SELECT SUM(cumulative_time_saved) FROM cache_stats"
```

