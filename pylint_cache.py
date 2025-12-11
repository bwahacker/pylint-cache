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
import ast
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def extract_imports(file_path: str, all_files: Set[str] = None) -> Set[str]:
    """
    Extract import statements from a Python file and resolve them to actual file paths.
    
    Args:
        file_path: Path to the Python file to analyze
        all_files: Optional set of all Python files in the project (for resolving local imports)
        
    Returns:
        Set of resolved file paths that this file imports
    """
    imports = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except (OSError, IOError):
        return imports
    
    # Try AST parsing first (more accurate)
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])  # Get top-level module
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])  # Get top-level module
                elif node.level > 0:
                    # Relative import - we'll handle this below
                    pass
    except SyntaxError:
        # Fall back to regex-based parsing for files with syntax errors
        import_pattern = re.compile(
            r'^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))', 
            re.MULTILINE
        )
        for match in import_pattern.finditer(content):
            module = match.group(1) or match.group(2)
            if module:
                imports.add(module.split('.')[0])
    
    # Now resolve module names to actual file paths
    if all_files is None:
        return imports
    
    # Build a mapping of module names to file paths
    resolved = set()
    file_path_obj = Path(file_path).resolve()
    file_dir = file_path_obj.parent
    
    # Create a module-to-file mapping from all_files
    module_to_file: Dict[str, str] = {}
    for f in all_files:
        f_path = Path(f).resolve()
        # Get the module name (filename without .py)
        module_name = f_path.stem
        # Also track the full path for exact matching
        module_to_file[module_name] = str(f_path)
        
        # Also add parent-relative paths for package imports
        # e.g., featrix.input_data_set -> input_data_set.py
        parts = f_path.parts
        for i in range(len(parts) - 1, 0, -1):
            if parts[i].endswith('.py'):
                partial_path = '.'.join(parts[i:]).replace('.py', '')
                module_to_file[partial_path] = str(f_path)
    
    for import_name in imports:
        # Check if this import corresponds to a local file
        # 1. Direct module name match
        if import_name in module_to_file:
            resolved.add(module_to_file[import_name])
            continue
        
        # 2. Check for relative path from current file's directory
        potential_file = file_dir / f"{import_name}.py"
        if potential_file.exists() and str(potential_file) in all_files:
            resolved.add(str(potential_file))
            continue
        
        # 3. Check for package (directory with __init__.py)
        potential_pkg = file_dir / import_name / "__init__.py"
        if potential_pkg.exists() and str(potential_pkg) in all_files:
            resolved.add(str(potential_pkg))
    
    return resolved


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
        
        # In-memory import graphs for current run
        self.import_graph: Dict[str, Set[str]] = {}  # file → files it imports
        self.reverse_graph: Dict[str, Set[str]] = {}  # file → files that import it
    
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
        
        # Table 5: Import dependencies (for smart cache invalidation)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS import_dependencies (
                importer_path TEXT NOT NULL,
                imported_path TEXT NOT NULL,
                importer_md5 TEXT NOT NULL,
                last_updated REAL NOT NULL,
                PRIMARY KEY (importer_path, imported_path)
            )
        """)
        
        # Index for reverse lookups (finding files that import a given file)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_imported_path 
            ON import_dependencies(imported_path)
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
    
    def build_import_graph(self, python_files: List[str]) -> None:
        """
        Build the import graph for all Python files.
        
        This creates:
        - import_graph: file → files it imports
        - reverse_graph: file → files that import it
        
        Args:
            python_files: List of Python file paths to analyze
        """
        import time
        
        # Convert to set and resolve paths for efficient lookup
        all_files_set = {str(Path(f).resolve()) for f in python_files}
        
        self.import_graph = {}
        self.reverse_graph = {}
        timestamp = time.time()
        
        for file_path in python_files:
            resolved_path = str(Path(file_path).resolve())
            
            # Extract imports and resolve to actual files
            imported_files = extract_imports(file_path, all_files_set)
            
            # Store in memory
            self.import_graph[resolved_path] = imported_files
            
            # Build reverse graph
            for imported in imported_files:
                if imported not in self.reverse_graph:
                    self.reverse_graph[imported] = set()
                self.reverse_graph[imported].add(resolved_path)
            
            # Get MD5 for tracking changes
            try:
                md5_hash, _, _ = self.get_file_metadata(file_path)
            except (OSError, IOError):
                continue
            
            # Store in database (clear old entries first, then insert new ones)
            self.conn.execute(
                "DELETE FROM import_dependencies WHERE importer_path = ?",
                (resolved_path,)
            )
            
            for imported in imported_files:
                self.conn.execute("""
                    INSERT OR REPLACE INTO import_dependencies
                    (importer_path, imported_path, importer_md5, last_updated)
                    VALUES (?, ?, ?, ?)
                """, (resolved_path, imported, md5_hash, timestamp))
        
        self.conn.commit()
    
    def get_files_importing(self, file_path: str) -> Set[str]:
        """
        Get all files that import the given file (one layer).
        
        Args:
            file_path: Path to the file
            
        Returns:
            Set of file paths that import this file
        """
        resolved_path = str(Path(file_path).resolve())
        
        # First check in-memory graph
        if resolved_path in self.reverse_graph:
            return self.reverse_graph[resolved_path]
        
        # Fall back to database
        cursor = self.conn.execute("""
            SELECT importer_path FROM import_dependencies
            WHERE imported_path = ?
        """, (resolved_path,))
        
        return {row[0] for row in cursor.fetchall()}
    
    def get_files_to_invalidate(self, changed_files: Set[str]) -> Set[str]:
        """
        Get all files that need to be invalidated (re-linted) based on changes.
        
        This includes:
        1. The changed files themselves
        2. Files that import the changed files (one layer of dependencies)
        
        Args:
            changed_files: Set of file paths that have changed
            
        Returns:
            Set of file paths that need to be re-linted
        """
        to_invalidate = set()
        
        for changed_file in changed_files:
            resolved = str(Path(changed_file).resolve())
            to_invalidate.add(resolved)
            
            # Add files that import this file
            importers = self.get_files_importing(resolved)
            to_invalidate.update(importers)
        
        return to_invalidate
    
    def has_file_changed(self, file_path: str, pylint_args: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a file has changed since last cache entry.
        
        Args:
            file_path: Path to check
            pylint_args: Pylint args string
            
        Returns:
            Tuple of (has_changed, current_md5)
        """
        try:
            current_md5, _, _ = self.get_file_metadata(file_path)
        except (OSError, IOError):
            return True, None
        
        # Check if we have a cached result for this MD5
        cursor = self.conn.execute("""
            SELECT 1 FROM pylint_results
            WHERE md5_hash = ? AND pylint_args = ?
        """, (current_md5, pylint_args))
        
        has_cached = cursor.fetchone() is not None
        return not has_cached, current_md5
    
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
        print("\nFeatures:")
        print("  - Smart dependency-based cache invalidation")
        print("  - When a file changes, dependent files (importers) are also re-linted")
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
    
    # Show what we're checking
    print(f"Found {total_files} Python file(s) to check")
    print(f"Pylint args: {pylint_args_str or '(none)'}")
    print(f"Cache database: {cache.db_path}")
    if force_rebuild:
        print(f"Mode: FORCE REBUILD (ignoring cache)")
    
    # =========================================================================
    # SMART DEPENDENCY-BASED CACHE INVALIDATION
    # =========================================================================
    
    # Step 1: Build import graph for all files
    print(f"Building import graph...")
    cache.build_import_graph(python_files)
    
    # Step 2: Identify files that have actually changed (content differs)
    changed_files: Set[str] = set()
    file_md5_cache: Dict[str, str] = {}  # Store MD5s for later
    
    for file_path in python_files:
        has_changed, current_md5 = cache.has_file_changed(file_path, pylint_args_str)
        if current_md5:
            file_md5_cache[file_path] = current_md5
        if has_changed:
            changed_files.add(str(Path(file_path).resolve()))
    
    # Step 3: Use smart invalidation - get files to re-lint
    # This includes changed files + files that import them
    if force_rebuild:
        files_to_lint = {str(Path(f).resolve()) for f in python_files}
        invalidated_dependents: Set[str] = set()
    else:
        files_to_lint = cache.get_files_to_invalidate(changed_files)
        # Track which files are being invalidated due to dependencies
        invalidated_dependents = files_to_lint - changed_files
    
    # Create a mapping from resolved paths back to original paths
    resolved_to_original = {str(Path(f).resolve()): f for f in python_files}
    
    # Show smart invalidation info
    if changed_files and not force_rebuild:
        print(f"\n🔍 Smart Dependency Analysis:")
        print(f"   Files with content changes: {len(changed_files)}")
        if invalidated_dependents:
            print(f"   Dependent files to re-lint: {len(invalidated_dependents)}")
            for dep in sorted(invalidated_dependents)[:5]:  # Show first 5
                original_path = resolved_to_original.get(dep, dep)
                print(f"      → {os.path.basename(original_path)} (imports changed file)")
            if len(invalidated_dependents) > 5:
                print(f"      ... and {len(invalidated_dependents) - 5} more")
        print(f"   Total files to lint: {len(files_to_lint)}")
        print(f"   Files using cache: {total_files - len(files_to_lint)}")
    
    print("-" * 80)
    
    # =========================================================================
    # RUN PYLINT
    # =========================================================================
    
    cached_count = 0
    ran_count = 0
    max_exit_code = 0
    time_saved = 0.0
    
    for file_path in python_files:
        resolved_path = str(Path(file_path).resolve())
        needs_lint = resolved_path in files_to_lint
        
        if not needs_lint and not force_rebuild:
            # File doesn't need linting - use cache
            cached_result = cache.check_cache(file_path, pylint_args_str)
            
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
                time_saved += cached_result['duration']
                
                # Update the file_paths table even for cached results
                cache.store_result(file_path, pylint_args_str, 
                                 cached_result['output'], cached_result['exit_code'],
                                 cached_result['duration'],
                                 md5_hash=cached_result['md5'])
            else:
                # No cache available, need to run
                needs_lint = True
        
        if needs_lint or force_rebuild:
            # Determine reason for linting
            if force_rebuild:
                reason = "FORCE"
            elif resolved_path in changed_files:
                reason = "CHANGED"
            elif resolved_path in invalidated_dependents:
                reason = "DEPENDENCY"
            else:
                reason = "RUNNING"
            
            print(f"[{reason}] {file_path}")
            output, exit_code, duration = run_pylint(file_path, pylint_args)
            if output:
                print(output)
            
            # Store in cache
            md5_hash = file_md5_cache.get(file_path)
            cache.store_result(file_path, pylint_args_str, output, exit_code, duration, 
                             md5_hash=md5_hash)
            ran_count += 1
            max_exit_code = max(max_exit_code, exit_code)
    
    # Record statistics for this run
    cumulative_saved = cache.record_run_stats(total_files, cached_count, ran_count, time_saved)
    
    cache.close()
    
    print("-" * 80)
    print(f"📊 Summary:")
    print(f"   Total files in scope: {total_files}")
    print(f"   ✅ Cached (skipped): {cached_count}")
    print(f"   🔄 Newly analyzed: {ran_count}")
    if invalidated_dependents and not force_rebuild:
        print(f"   🔗 Re-linted due to dependencies: {len(invalidated_dependents)}")
    
    if time_saved > 0:
        print(f"   ⚡ Time saved this run: {time_saved:.2f}s")
        print(f"   🎯 Cumulative time saved: {cumulative_saved:.2f}s ({cumulative_saved/60:.1f} min)")
    
    # Also output in a parseable format for scripts
    print(f"\n[STATS] files={total_files} cached={cached_count} ran={ran_count} "
          f"deps_invalidated={len(invalidated_dependents)} saved={time_saved:.2f}s "
          f"cumulative={cumulative_saved:.2f}s")
    
    sys.exit(max_exit_code)


if __name__ == '__main__':
    main()

