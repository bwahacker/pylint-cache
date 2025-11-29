#!/usr/bin/env python3
"""
pylint-cache.py - A caching wrapper for pylint

This tool caches pylint results based on file content (MD5) and modification time.
Files that haven't changed since the last run will use cached results instead of
re-running pylint.

Usage:
    pylint-cache.py <file1> <file2> ... -- <pylint args>
    pylint-cache.py <file1> <file2> ... --args='<pylint args>'
"""

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple


class PylintCache:
    """Manages pylint result caching using SQLite."""
    
    def __init__(self, db_path: str = None):
        """Initialize the cache with a SQLite database."""
        if db_path is None:
            # Check environment variable first, then default to home directory
            db_path = os.environ.get('PYLINT_CACHE_DB')
            if db_path is None:
                home = Path.home()
                db_path = str(home / ".pylint-cache.db")
        
        self.db_path = db_path
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """Initialize the SQLite database with the required schema."""
        self.conn = sqlite3.connect(self.db_path)
        
        # Table 1: File content metadata (keyed by MD5)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_content (
                md5_hash TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                first_seen REAL NOT NULL
            )
        """)
        
        # Table 2: File paths and their current state
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_paths (
                file_path TEXT PRIMARY KEY,
                md5_hash TEXT NOT NULL,
                mod_time REAL NOT NULL,
                last_checked REAL NOT NULL,
                FOREIGN KEY (md5_hash) REFERENCES file_content(md5_hash)
            )
        """)
        
        # Table 3: Pylint results (keyed by MD5 + args)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pylint_results (
                md5_hash TEXT NOT NULL,
                pylint_args TEXT NOT NULL,
                pylint_output TEXT,
                exit_code INTEGER,
                duration REAL NOT NULL,
                timestamp REAL NOT NULL,
                PRIMARY KEY (md5_hash, pylint_args),
                FOREIGN KEY (md5_hash) REFERENCES file_content(md5_hash)
            )
        """)
        
        # Table 4: Statistics tracking
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp REAL NOT NULL,
                files_checked INTEGER NOT NULL,
                files_cached INTEGER NOT NULL,
                files_ran INTEGER NOT NULL,
                time_saved REAL NOT NULL,
                cumulative_time_saved REAL NOT NULL
            )
        """)
        
        self.conn.commit()
    
    def get_file_metadata(self, file_path: str) -> Tuple[str, float, int]:
        """
        Get file metadata: MD5 hash, modification time, and size.
        
        Returns:
            Tuple of (md5_hash, mod_time, file_size)
        """
        stat = os.stat(file_path)
        mod_time = stat.st_mtime
        file_size = stat.st_size
        
        # Compute MD5 hash
        md5_hash = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5_hash.update(chunk)
        
        return md5_hash.hexdigest(), mod_time, file_size
    
    def check_cache(self, file_path: str, pylint_args: str) -> Optional[dict]:
        """
        Check if we have a valid cached result for this file.
        
        Uses MD5 hash as the primary lookup - if we've ever pylinted this exact
        content before (even at a different path or time), we reuse that result.
        
        Args:
            file_path: Path to the file to check
            pylint_args: The pylint arguments being used
            
        Returns:
            Cached result dict if valid, None otherwise
        """
        # Get current file metadata
        try:
            current_md5, current_mtime, current_size = self.get_file_metadata(file_path)
        except (OSError, IOError) as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            return None
        
        # Query pylint results by MD5 hash
        # If we've seen this exact file content before, reuse the result
        cursor = self.conn.execute("""
            SELECT pylint_output, exit_code, duration
            FROM pylint_results
            WHERE md5_hash = ? AND pylint_args = ?
        """, (current_md5, pylint_args))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        pylint_output, exit_code, duration = row
        
        # Check if this content was previously seen at a different path
        cached_from = None
        path_cursor = self.conn.execute("""
            SELECT file_path FROM file_paths 
            WHERE md5_hash = ? AND file_path != ?
            LIMIT 1
        """, (current_md5, file_path))
        path_row = path_cursor.fetchone()
        if path_row:
            cached_from = path_row[0]
        
        # Found a match! The MD5 and args match, so we can reuse the result
        return {
            'output': pylint_output,
            'exit_code': exit_code,
            'duration': duration,
            'cached': True,
            'cached_from': cached_from,
            'md5': current_md5
        }
    
    def store_result(self, file_path: str, pylint_args: str, 
                    output: str, exit_code: int, duration: float,
                    md5_hash: str = None):
        """
        Store a pylint result in the cache.
        
        The cache is keyed by (md5_hash, pylint_args) so the same file content
        will reuse the cached result regardless of path or modification time.
        
        Args:
            file_path: Path to the file
            pylint_args: The pylint arguments used
            output: The pylint output
            exit_code: The pylint exit code
            duration: How long pylint took to run (seconds)
            md5_hash: Optional pre-computed MD5 hash
        """
        try:
            if md5_hash is None:
                md5_hash, mod_time, file_size = self.get_file_metadata(file_path)
            else:
                stat = os.stat(file_path)
                mod_time = stat.st_mtime
                file_size = stat.st_size
        except (OSError, IOError) as e:
            print(f"Error storing cache for {file_path}: {e}", file=sys.stderr)
            return
        
        import time
        timestamp = time.time()
        
        # Store file content metadata (if new)
        self.conn.execute("""
            INSERT OR IGNORE INTO file_content (md5_hash, file_size, first_seen)
            VALUES (?, ?, ?)
        """, (md5_hash, file_size, timestamp))
        
        # Store/update file path mapping
        self.conn.execute("""
            INSERT OR REPLACE INTO file_paths 
            (file_path, md5_hash, mod_time, last_checked)
            VALUES (?, ?, ?, ?)
        """, (file_path, md5_hash, mod_time, timestamp))
        
        # Store pylint result
        self.conn.execute("""
            INSERT OR REPLACE INTO pylint_results
            (md5_hash, pylint_args, pylint_output, exit_code, duration, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (md5_hash, pylint_args, output, exit_code, duration, timestamp))
        
        self.conn.commit()
    
    def record_run_stats(self, files_checked: int, files_cached: int, 
                        files_ran: int, time_saved: float):
        """
        Record statistics for this run.
        
        Args:
            files_checked: Total files checked
            files_cached: Files that used cache
            files_ran: Files that ran pylint
            time_saved: Time saved in seconds
        """
        import time
        timestamp = time.time()
        
        # Get cumulative time saved
        cursor = self.conn.execute("""
            SELECT COALESCE(SUM(time_saved), 0.0) FROM cache_stats
        """)
        cumulative = cursor.fetchone()[0] + time_saved
        
        # Record this run
        self.conn.execute("""
            INSERT INTO cache_stats 
            (run_timestamp, files_checked, files_cached, files_ran, 
             time_saved, cumulative_time_saved)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (timestamp, files_checked, files_cached, files_ran, 
              time_saved, cumulative))
        
        self.conn.commit()
        
        return cumulative
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()


def run_pylint(file_path: str, pylint_args: List[str]) -> Tuple[str, int, float]:
    """
    Run pylint on a file with the given arguments.
    
    Args:
        file_path: Path to the file to check
        pylint_args: List of additional pylint arguments
        
    Returns:
        Tuple of (output, exit_code, duration)
    """
    import time
    
    cmd = ['pylint'] + pylint_args + [file_path]
    
    try:
        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        duration = time.time() - start_time
        output = result.stdout + result.stderr
        return output, result.returncode, duration
    except subprocess.TimeoutExpired:
        return f"ERROR: pylint timed out for {file_path}", 1, 300.0
    except Exception as e:
        return f"ERROR: Failed to run pylint: {e}", 1, 0.0


def parse_arguments() -> Tuple[List[str], List[str], bool]:
    """
    Parse command line arguments.
    
    Returns:
        Tuple of (file_paths, pylint_args, force_rebuild)
    """
    args = sys.argv[1:]
    force_rebuild = False
    
    # Check for --force or -f flag
    if '--force' in args:
        force_rebuild = True
        args = [a for a in args if a != '--force']
    elif '-f' in args:
        force_rebuild = True
        args = [a for a in args if a != '-f']
    
    # Check for --args= style
    for i, arg in enumerate(args):
        if arg.startswith('--args='):
            args_str = arg[7:]  # Remove '--args='
            file_paths = args[:i]
            pylint_args = args_str.split() if args_str else []
            return file_paths, pylint_args, force_rebuild
    
    # Check for -- separator style
    if '--' in args:
        separator_idx = args.index('--')
        file_paths = args[:separator_idx]
        pylint_args = args[separator_idx + 1:]
        return file_paths, pylint_args, force_rebuild
    
    # No pylint args, all arguments are file paths
    return args, [], force_rebuild


def expand_paths(paths: List[str]) -> List[str]:
    """
    Expand paths to include directories recursively.
    
    Ignores common non-code directories like venv, node_modules, .git, etc.
    
    Args:
        paths: List of file or directory paths
        
    Returns:
        List of Python file paths
    """
    # Directories to ignore (similar to pylint's default behavior)
    IGNORE_DIRS = {
        '__pycache__', '.git', '.svn', '.hg', '.bzr', '_darcs',
        'CVS', '.tox', '.nox', '.eggs', '*.egg-info', 'dist', 'build',
        'venv', 'env', '.venv', '.env', 'virtualenv',
        'node_modules', '.mypy_cache', '.pytest_cache', '.hypothesis',
        '.idea', '.vscode', 'htmlcov', 'cover', 'coverage',
        '__pypackages__', 'site-packages', 'lib', 'lib64',
    }
    
    python_files = []
    
    for path in paths:
        path_obj = Path(path)
        
        if path_obj.is_file():
            # Direct file reference - always include if it's .py
            if path_obj.suffix == '.py':
                python_files.append(str(path_obj))
        elif path_obj.is_dir():
            # Recursively find .py files, but skip ignored directories
            for py_file in path_obj.rglob('*.py'):
                # Check if any parent directory is in the ignore list
                skip = False
                for parent in py_file.parents:
                    if parent.name in IGNORE_DIRS or any(
                        parent.match(pattern) for pattern in IGNORE_DIRS if '*' in pattern
                    ):
                        skip = True
                        break
                    # Stop checking once we reach the original search path
                    if parent == path_obj:
                        break
                
                if not skip:
                    python_files.append(str(py_file))
    
    return python_files


def main():
    """Main entry point for pylint-cache."""
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help']:
        print(__doc__)
        print("\nExamples:")
        print("  pylint-cache myfile.py")
        print("  pylint-cache file1.py file2.py -- --disable=C0111")
        print("  pylint-cache src/ --args='--disable=C0111 --max-line-length=100'")
        print("  pylint-cache src/ --force  # Force rebuild, ignore cache")
        print("\nOptions:")
        print("  -f, --force    Force re-run pylint on all files, ignore cache")
        print("\nNote: When given directories, recursively finds .py files")
        print("      while ignoring common directories like venv/, .git/, etc.")
        sys.exit(0)
    
    # Parse arguments
    file_paths, pylint_args, force_rebuild = parse_arguments()
    
    if not file_paths:
        print("ERROR: No file paths provided", file=sys.stderr)
        sys.exit(1)
    
    # Expand paths to get all Python files
    python_files = expand_paths(file_paths)
    
    if not python_files:
        print("ERROR: No Python files found", file=sys.stderr)
        print("(Searched in: {})".format(', '.join(file_paths)), file=sys.stderr)
        sys.exit(1)
    
    # Initialize cache
    cache = PylintCache()
    
    # Convert pylint args to string for cache key
    pylint_args_str = ' '.join(pylint_args)
    
    total_files = len(python_files)
    cached_count = 0
    ran_count = 0
    max_exit_code = 0
    time_saved = 0.0
    
    # Show what we're checking
    print(f"Found {total_files} Python file(s) to check")
    print(f"Pylint args: {pylint_args_str or '(none)'}")
    print(f"Cache database: {cache.db_path}")
    if force_rebuild:
        print(f"Mode: FORCE REBUILD (ignoring cache)")
    print("-" * 80)
    
    for file_path in python_files:
        # Check cache first (unless force rebuild)
        cached_result = None if force_rebuild else cache.check_cache(file_path, pylint_args_str)
        
        if cached_result:
            cached_from = cached_result.get('cached_from')
            if cached_from:
                print(f"[CACHED from {cached_from}] {file_path}")
            else:
                print(f"[CACHED] {file_path}")
            if cached_result['output']:
                print(cached_result['output'])
            cached_count += 1
            max_exit_code = max(max_exit_code, cached_result['exit_code'])
            
            # Track time saved
            time_saved += cached_result['duration']
            
            # Update the file_paths table even for cached results
            cache.store_result(file_path, pylint_args_str, 
                             cached_result['output'], cached_result['exit_code'],
                             cached_result['duration'],
                             md5_hash=cached_result['md5'])
        else:
            print(f"[RUNNING] {file_path}")
            output, exit_code, duration = run_pylint(file_path, pylint_args)
            if output:
                print(output)
            
            # Store in cache
            cache.store_result(file_path, pylint_args_str, output, exit_code, duration)
            ran_count += 1
            max_exit_code = max(max_exit_code, exit_code)
    
    # Record statistics for this run
    cumulative_saved = cache.record_run_stats(total_files, cached_count, ran_count, time_saved)
    
    cache.close()
    
    print("-" * 80)
    print(f"📊 Summary:")
    print(f"   Total files checked: {total_files}")
    print(f"   ✅ Cached (skipped): {cached_count}")
    print(f"   🔄 Newly analyzed: {ran_count}")
    
    if time_saved > 0:
        print(f"   ⚡ Time saved this run: {time_saved:.2f}s")
        print(f"   🎯 Cumulative time saved: {cumulative_saved:.2f}s ({cumulative_saved/60:.1f} min)")
    
    # Also output in a parseable format for scripts
    print(f"\n[STATS] files={total_files} cached={cached_count} ran={ran_count} saved={time_saved:.2f}s cumulative={cumulative_saved:.2f}s")
    
    sys.exit(max_exit_code)


if __name__ == '__main__':
    main()

