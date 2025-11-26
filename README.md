# pylint-cache

A smart caching wrapper for pylint that avoids re-running checks on unchanged files.

## Why Bother?

Pylint has a built-in caching mechanism, but it does **not** skip work on subsequent runs. Even with caching enabled, Pylint will:

- re-open every file
- re-parse the AST
- re-run its full suite of checks
- re-evaluate imports and module relationships

As a result, Pylint performance remains largely proportional to the number of files being analyzed—no matter how often you run it.

This project provides a pragmatic alternative: **content-based caching of entire Pylint results.** If a file's contents have not changed since the previous run, its prior lint output is reused immediately, and Pylint is never invoked for that file.

The impact is significant:

- First run: Pylint performs full analysis.
- Subsequent runs: Unchanged files are resolved directly from cache.

This produces dramatic, measurable speedups—often reducing multi-second runs to just tens of milliseconds—without altering lint results or behavior.

In short:

- **Stock Pylint caches *internals*, not results.**
- **This tool caches results, not internals.**
- **Only this approach eliminates unnecessary work.**

It's a simple optimization that makes repeated linting practical, fast, and pleasant—especially in large codebases or workflows where rapid iteration matters.


## Demo

When we run pylint-cache and the files have not been prcossed before, we get the same experience as running `pylint` on its own, except that each file is shown with a [RUNNING] prefix:
```
admin baconator (527) >> time pylint-cache . --args="-E"
Found 168 Python file(s) to check
Pylint args: -E
--------------------------------------------------------------------------------
[RUNNING] test_cluster_routing.py
[RUNNING] walk_sessions.py
************* Module walk_sessions
walk_sessions.py:799:35: E0601: Using variable 'json' before assignment (used-before-assignment)

[RUNNING] test_density_weighted_embedding.py
[RUNNING] repair_all_sessions_batch.py
[RUNNING] analyze_geometric_compression.py
[RUNNING] visualize_results.py
[RUNNING] system_monitor.py
************* Module system_monitor
system_monitor.py:506:12: E1123: Unexpected keyword argument 'throttle' in function call (unexpected-keyword-arg)
system_monitor.py:506:12: E1123: Unexpected keyword argument 'skip_hostname_prefix' in function call (unexpected-keyword-arg)
system_monitor.py:971:8: E0401: Unable to import 'lib.featrix_debug' (import-error)
system_monitor.py:971:8: E0611: No name 'featrix_debug' in module 'lib' (no-name-in-module)

[RUNNING] test_list_permutations.py
[RUNNING] debug_masking.py
[RUNNING] demo_cluster_routing.py
[RUNNING] test_credit_full_dataset.py

--------------------------------------------------------------------------------
Summary: 168 files total, 0 cached, 168 ran

real	5m31.171s
user	5m32.309s
sys	4m32.291s
```

You see here this took over 5 minutes on my Mac Studio M2 Ultra.  When we run the next time through, we will see all the same errors (if we haven't fixed them) and [CACHED] before each file.  You will also note the time savings at the end.

```
[taco-fixes] ~/Desktop/tetra-ws/featrix/taco-fixes 
admin baconator (528) >> time pylint-cache . --args="-E"
Found 168 Python file(s) to check
Pylint args: -E
--------------------------------------------------------------------------------
[CACHED] test_cluster_routing.py
[CACHED] walk_sessions.py
************* Module walk_sessions
walk_sessions.py:799:35: E0601: Using variable 'json' before assignment (used-before-assignment)

[CACHED] test_density_weighted_embedding.py
[CACHED] repair_all_sessions_batch.py
[CACHED] analyze_geometric_compression.py
[CACHED] visualize_results.py
[CACHED] system_monitor.py
************* Module system_monitor
system_monitor.py:506:12: E1123: Unexpected keyword argument 'throttle' in function call (unexpected-keyword-arg)
system_monitor.py:506:12: E1123: Unexpected keyword argument 'skip_hostname_prefix' in function call (unexpected-keyword-arg)
system_monitor.py:971:8: E0401: Unable to import 'lib.featrix_debug' (import-error)
system_monitor.py:971:8: E0611: No name 'featrix_debug' in module 'lib' (no-name-in-module)

--------------------------------------------------------------------------------
📊 Summary:
   Total files checked: 168
   ✅ Cached (skipped): 168
   🔄 Newly analyzed: 0
   ⚡ Time saved this run: 331.17s
   🎯 Cumulative time saved: 331.17s (5.5 min)

[STATS] files=168 cached=168 ran=0 saved=331.17s cumulative=331.17s

real	0m0.199s
user	0m0.047s
sys	0m0.096s
(base) 
[taco-fixes] ~/Desktop/tetra-ws/featrix/taco-fixes 
admin baconator (529) >> 


```



## Installation

### Option 1: Install with pip (recommended)

```bash
# Install from local directory
pip install .

# Or install in development/editable mode
pip install -e .

# Uninstall
pip uninstall pylint-cache
```

### Option 2: System-wide installation

```bash
# Install system-wide (requires sudo)
sudo ./install.sh

# This will:
# - Copy pylint_cache.py to /opt/pylint-cache/
# - Create a symlink at /usr/local/bin/pylint-cache
# - Make it available in your PATH

# Uninstall
sudo ./install.sh uninstall
```

## Features

- **Intelligent Caching**: Tracks file MD5 hash, modification time, and size
- **SQLite Backend**: Stores results in a local `.pylint-cache.db` database
- **Argument Tracking**: Caches results per unique set of pylint arguments
- **Fast**: Only re-runs pylint when files actually change
- **Easy to Use**: Drop-in replacement for pylint with the same arguments

## Usage

After installation:

```bash
# Check a single file
pylint-cache myfile.py

# Check multiple files
pylint-cache file1.py file2.py file3.py

# Check with pylint arguments (using --)
pylint-cache src/*.py -- --disable=C0111 --max-line-length=100

# Check with pylint arguments (using --args=)
pylint-cache src/ --args='--disable=C0111 --max-line-length=100'

# Check entire directory (recursively finds .py files)
pylint-cache src/
```

Or run directly without installation:

```bash
./pylint_cache.py myfile.py
```

### Directory Recursion

When given a directory, `pylint-cache` recursively finds all `.py` files **while automatically ignoring** common non-code directories:

**Ignored directories:**
- Virtual environments: `venv/`, `env/`, `.venv/`, `virtualenv/`
- Version control: `.git/`, `.svn/`, `.hg/`
- Build artifacts: `build/`, `dist/`, `*.egg-info/`
- Cache directories: `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`
- Dependencies: `node_modules/`, `site-packages/`
- IDE: `.idea/`, `.vscode/`

This matches typical `pylint` behavior and prevents scanning 57,000+ files in large projects!

## Time Savings Tracking

Every time you run `pylint-cache`, it tracks:
- How long each pylint invocation took
- How much time was saved by using cached results
- Cumulative time saved across all runs

Example output:

```
--------------------------------------------------------------------------------
📊 Summary:
   Total files checked: 247
   ✅ Cached (skipped): 245
   🔄 Newly analyzed: 2
   ⚡ Time saved this run: 45.23s
   🎯 Cumulative time saved: 1847.56s (30.8 min)

[STATS] files=247 cached=245 ran=2 saved=45.23s cumulative=1847.56s
```

This shows you the real-world impact of caching - how many minutes/hours you've saved by not re-running pylint on unchanged files!

The `[STATS]` line is machine-parseable for scripts and CI integration.



### Use in Makefiles

```makefile
.PHONY: lint
lint:
	@echo "🔍 Running pylint error checks..."
	@pylint-cache src/ --args="-E" || exit 1
	@echo "✅ Pylint check completed"

.PHONY: test
test: lint
	pytest

.PHONY: build
build: lint
	python setup.py build
```

The tool exits with the highest pylint exit code from all files, so make will properly fail if any file has issues.

### Parsing Output in Scripts

The `[STATS]` line provides machine-parseable output:

```bash
#!/bin/bash
output=$(pylint-cache src/ --args="-E" 2>&1)
stats=$(echo "$output" | grep "^\[STATS\]")

# Extract values
files=$(echo "$stats" | grep -o 'files=[0-9]*' | cut -d= -f2)
cached=$(echo "$stats" | grep -o 'cached=[0-9]*' | cut -d= -f2)
ran=$(echo "$stats" | grep -o 'ran=[0-9]*' | cut -d= -f2)
saved=$(echo "$stats" | grep -o 'saved=[0-9.]*s' | cut -d= -f2 | tr -d 's')

echo "Checked $files files, $cached from cache, $ran newly analyzed"
echo "Saved ${saved}s this run"
```

## Background Monitoring (Recommended)

**Problem:** Caching per-file is fast but might miss cross-file dependency issues.

**Solution:** Run a background monitor that detects changes and triggers full re-analysis.

```bash
# 1. Register your project(s)
pylint-cache-monitor add /path/to/project --dirs src,lib --args "-E"

# 2. Test it
pylint-cache-monitor run -v

# 3. Add to crontab
crontab -e
# Add: */15 * * * * pylint-cache-monitor run
```

See `MONITOR_SETUP.md` for detailed instructions.

**How it works:**
- Monitor wakes up every 15-30 minutes
- Checks if ANY Python file changed since last run
- If changes detected → runs pylint on ENTIRE tree
- Results are cached → developers get instant feedback with cross-file analysis

**Benefits:**
- 🔍 Catches import errors and cross-file issues
- ⚡ Developers still get instant cache hits
- 🔄 Automatic full re-analysis when needed
- 🎯 Best of both worlds: speed + accuracy

## Automated Cache Pre-warming (Optional)

Pre-populate the cache for multiple projects:

```bash
# Run every night at 2 AM
0 2 * * * /path/to/pylint-cache-cron.sh
```

See `CRON_SETUP.md` for detailed instructions.

## How It Works

1. For each Python file, computes MD5 hash and gets modification time
2. Checks SQLite database for cached results using **MD5 hash** as the primary key:
   - If we've ever seen this exact file content before (even at a different path or time), reuse that result!
   - Cache lookup is based on: MD5 hash + pylint arguments
3. If cache hit: displays cached output (marked as `[CACHED]` or `[CACHED from other/path.py]`)
4. If cache miss: runs pylint and stores result (marked as `[RUNNING]`)

### Smart Content-Based Caching

The cache uses MD5 as the primary lookup key, which means:
- ✅ Moving a file to a different location? Still cached!
- ✅ Copying a file? Reuses the existing result!
- ✅ Touching a file (updating mtime) without changing content? Still cached!
- ✅ Same file analyzed in different projects? Reuses results across projects!

## Cache Location

The cache is stored in `~/.pylint-cache.db` in your home directory by default.

This means:
- ✅ Single shared cache across all your projects
- ✅ If you've linted a file in project A, the same file in project B reuses the result
- ✅ No `.pylint-cache.db` files cluttering your project directories
- ✅ Easy to back up or clear: just delete `~/.pylint-cache.db`

You can override the location by setting the `PYLINT_CACHE_DB` environment variable:

```bash
export PYLINT_CACHE_DB=/path/to/custom.db
pylint-cache src/
```

## Database Schema

The cache uses a normalized three-table design:

### Table 1: `file_content`
Tracks unique file content by MD5 hash:
- `md5_hash` (PRIMARY KEY) - Content hash
- `file_size` - Size in bytes
- `first_seen` - Timestamp when first encountered

### Table 2: `file_paths`
Maps file paths to their content:
- `file_path` (PRIMARY KEY) - Full file path
- `md5_hash` (FOREIGN KEY) - Links to file_content
- `mod_time` - Last modification time
- `last_checked` - When we last checked this path

### Table 3: `pylint_results`
Stores pylint results per content + args:
- `md5_hash` (PRIMARY KEY part 1) - Links to file_content
- `pylint_args` (PRIMARY KEY part 2) - Pylint arguments used
- `pylint_output` - Full output from pylint
- `exit_code` - Return code from pylint
- `duration` - How long pylint took to run (seconds)
- `timestamp` - When this result was generated

### Table 4: `cache_stats`
Tracks cumulative time savings:
- `id` - Auto-increment ID
- `run_timestamp` - When this run occurred
- `files_checked` - Total files in this run
- `files_cached` - Files that used cache
- `files_ran` - Files that ran pylint
- `time_saved` - Time saved this run (seconds)
- `cumulative_time_saved` - Total time saved ever (seconds)

This design allows multiple file paths to reference the same content, efficiently tracks which files we've seen, and shows you exactly how much time the cache has saved you.

## Exit Codes

The tool exits with the highest exit code from all pylint runs (cached or fresh).

## Limitations & Future Ideas

### Current Limitations

- **No automatic cross-file dependency tracking**: If `file_a.py` imports `file_b.py` and `file_b.py` changes, we won't automatically re-check `file_a.py` unless you use the monitor script.
  - **Solution**: Use `pylint-cache-monitor.sh` to periodically trigger full re-analysis
- **Single-threaded**: Files are checked sequentially (though this is still faster than pylint due to caching)

### Potential Future Enhancements

Want to help extend this? Here are some ideas:

- 🔗 **Detect changed transitive imports** - Track import graphs and invalidate cache when dependencies change
- ⚡ **Parallel execution** - Check multiple files simultaneously  
- 📊 **Track errors over time** - Historical tracking of what errors changed
- 📄 **HTML reports** - Generate browsable reports of issues
- 🔧 **Multi-tool caching** - Unified cache for `ruff` + `pylint` + `mypy`
- 🌐 **Shared team cache** - Central cache server for CI/CD

Pull requests welcome!
Cache pylint results.
