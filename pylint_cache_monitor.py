#!/usr/bin/env python3
"""
pylint-cache-monitor.py - Monitor registered projects for changes

This script maintains a registry of projects to monitor. When run (e.g., via cron),
it checks each registered project for changes and triggers full re-analysis if needed.

Usage:
    # Register a project to monitor
    pylint-cache-monitor.py add /path/to/project --dirs src,lib --args "-E"
    
    # List monitored projects
    pylint-cache-monitor.py list
    
    # Remove a project
    pylint-cache-monitor.py remove /path/to/project
    
    # Run the monitor (check all projects for changes)
    pylint-cache-monitor.py run
    
    # Add to crontab to run every 15 minutes:
    */15 * * * * /usr/local/bin/pylint-cache-monitor.py run
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional


class MonitorRegistry:
    """Manages the registry of monitored projects."""
    
    def __init__(self, registry_path: str = None):
        """Initialize the registry."""
        if registry_path is None:
            home = Path.home()
            registry_dir = home / ".cache" / "pylint-cache-monitor"
            registry_dir.mkdir(parents=True, exist_ok=True)
            self.registry_path = registry_dir / "projects.json"
            self.log_dir = registry_dir / "logs"
            self.log_dir.mkdir(exist_ok=True)
            self.lock_dir = registry_dir / "locks"
            self.lock_dir.mkdir(exist_ok=True)
        else:
            self.registry_path = Path(registry_path)
            self.log_dir = self.registry_path.parent / "logs"
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.lock_dir = self.registry_path.parent / "locks"
            self.lock_dir.mkdir(parents=True, exist_ok=True)
        
        self.projects = self._load_registry()
    
    def _load_registry(self) -> Dict:
        """Load the registry from disk."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load registry: {e}", file=sys.stderr)
                return {}
        return {}
    
    def _save_registry(self):
        """Save the registry to disk."""
        with open(self.registry_path, 'w') as f:
            json.dump(self.projects, f, indent=2)
    
    def add_project(self, project_dir: str, source_dirs: List[str], 
                   pylint_args: str = "-E"):
        """
        Add or update a project in the registry.
        
        Args:
            project_dir: Path to project root
            source_dirs: List of source directories to monitor (relative to project_dir)
            pylint_args: Arguments to pass to pylint
        """
        project_dir = str(Path(project_dir).resolve())
        
        if not Path(project_dir).exists():
            raise ValueError(f"Project directory does not exist: {project_dir}")
        
        self.projects[project_dir] = {
            "source_dirs": source_dirs,
            "pylint_args": pylint_args,
            "last_run": 0,  # Epoch time
            "last_check": 0,  # Last time we checked for changes
            "added": time.time()
        }
        
        self._save_registry()
        print(f"✓ Added project: {project_dir}")
        print(f"  Source dirs: {', '.join(source_dirs)}")
        print(f"  Pylint args: {pylint_args}")
    
    def remove_project(self, project_dir: str) -> bool:
        """Remove a project from the registry."""
        project_dir = str(Path(project_dir).resolve())
        
        if project_dir in self.projects:
            del self.projects[project_dir]
            self._save_registry()
            print(f"✓ Removed project: {project_dir}")
            return True
        else:
            print(f"✗ Project not found: {project_dir}", file=sys.stderr)
            return False
    
    def list_projects(self):
        """List all monitored projects."""
        if not self.projects:
            print("No projects registered for monitoring.")
            print("\nAdd a project with:")
            print("  pylint-cache-monitor.py add /path/to/project --dirs src,lib")
            return
        
        print(f"Monitored projects ({len(self.projects)}):")
        print("-" * 80)
        
        for project_dir, config in self.projects.items():
            print(f"\n📁 {project_dir}")
            print(f"   Source dirs: {', '.join(config['source_dirs'])}")
            print(f"   Pylint args: {config['pylint_args']}")
            
            if config['last_run'] > 0:
                last_run = time.strftime('%Y-%m-%d %H:%M:%S', 
                                        time.localtime(config['last_run']))
                print(f"   Last run: {last_run}")
            else:
                print(f"   Last run: Never")
    
    def update_last_run(self, project_dir: str):
        """Update the last run timestamp for a project."""
        project_dir = str(Path(project_dir).resolve())
        
        if project_dir in self.projects:
            self.projects[project_dir]['last_run'] = time.time()
            self._save_registry()
    
    def update_last_check(self, project_dir: str):
        """Update the last check timestamp for a project."""
        project_dir = str(Path(project_dir).resolve())
        
        if project_dir in self.projects:
            self.projects[project_dir]['last_check'] = time.time()
            self._save_registry()


def find_changed_files(project_dir: str, source_dirs: List[str], 
                      since_time: float) -> int:
    """
    Find Python files that changed since the given time.
    
    Args:
        project_dir: Project root directory
        source_dirs: List of source directories to check
        since_time: Unix timestamp
        
    Returns:
        Number of changed files found
    """
    changed_count = 0
    project_path = Path(project_dir)
    
    for src_dir in source_dirs:
        src_path = project_path / src_dir
        
        if not src_path.exists():
            continue
        
        # Find all .py files
        for py_file in src_path.rglob('*.py'):
            try:
                if py_file.stat().st_mtime > since_time:
                    changed_count += 1
            except OSError:
                continue
    
    return changed_count


def run_pylint_cache(project_dir: str, source_dirs: List[str], 
                    pylint_args: str, log_file: Path) -> int:
    """
    Run pylint-cache on the project.
    
    Args:
        project_dir: Project root directory
        source_dirs: List of source directories
        pylint_args: Pylint arguments
        log_file: Path to log file
        
    Returns:
        Exit code from pylint-cache
    """
    # Find pylint-cache command
    pylint_cache = os.environ.get('PYLINT_CACHE_CMD')
    if not pylint_cache:
        # Try to find it in PATH
        import shutil
        pylint_cache = shutil.which('pylint-cache')
        if not pylint_cache:
            # Try local installation
            pylint_cache = './pylint_cache.py'
    
    # Build command
    paths = [str(Path(project_dir) / src_dir) for src_dir in source_dirs]
    cmd = [pylint_cache] + paths + ['--args=' + pylint_args]
    
    # Run command
    try:
        with open(log_file, 'a') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"Running: {' '.join(cmd)}\n")
            f.write(f"{'='*80}\n")
            
            result = subprocess.run(
                cmd,
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            f.write(result.stdout)
            f.write(result.stderr)
            
            return result.returncode
    except subprocess.TimeoutExpired:
        print(f"ERROR: pylint-cache timed out for {project_dir}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: Failed to run pylint-cache: {e}", file=sys.stderr)
        return 1


class ProjectLock:
    """Lock file context manager to prevent concurrent runs on same project."""
    
    def __init__(self, lock_file: Path, project_dir: str):
        """
        Initialize the lock.
        
        Args:
            lock_file: Path to lock file
            project_dir: Project directory (for error messages)
        """
        self.lock_file = lock_file
        self.project_dir = project_dir
        self.lock_fd = None
        self.acquired = False
    
    def __enter__(self):
        """Acquire the lock."""
        try:
            # Create lock file if it doesn't exist
            self.lock_fd = open(self.lock_file, 'w')
            
            # Try to acquire exclusive lock (non-blocking)
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # Write PID to lock file
            self.lock_fd.write(f"{os.getpid()}\n")
            self.lock_fd.flush()
            
            self.acquired = True
            return self
            
        except (IOError, OSError) as e:
            # Lock is already held
            if self.lock_fd:
                self.lock_fd.close()
                self.lock_fd = None
            self.acquired = False
            return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release the lock."""
        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
                self.lock_fd.close()
            except (IOError, OSError):
                pass
            finally:
                self.lock_fd = None
        
        # Try to remove lock file
        try:
            if self.acquired and self.lock_file.exists():
                self.lock_file.unlink()
        except OSError:
            pass


def get_project_lock_file(registry: MonitorRegistry, project_dir: str) -> Path:
    """
    Get the lock file path for a project.
    
    Args:
        registry: MonitorRegistry instance
        project_dir: Project directory path
        
    Returns:
        Path to lock file
    """
    # Create a safe filename from project path
    import hashlib
    project_hash = hashlib.md5(project_dir.encode()).hexdigest()
    return registry.lock_dir / f"project_{project_hash}.lock"


def run_monitor(registry: MonitorRegistry, verbose: bool = False):
    """
    Run the monitor - check all projects for changes.
    
    Args:
        registry: MonitorRegistry instance
        verbose: Print verbose output
    """
    if not registry.projects:
        if verbose:
            print("No projects registered for monitoring.")
        return
    
    log_file = registry.log_dir / f"monitor-{time.strftime('%Y%m%d')}.log"
    
    for project_dir, config in registry.projects.items():
        project_path = Path(project_dir)
        
        if not project_path.exists():
            print(f"⚠ Skipping (not found): {project_dir}")
            continue
        
        # Try to acquire lock for this project
        lock_file = get_project_lock_file(registry, project_dir)
        
        with ProjectLock(lock_file, project_dir) as lock:
            if not lock.acquired:
                print(f"🔒 Skipping {project_dir} (already running)")
                continue
            
            # Check for changes since last run
            last_run = config.get('last_run', 0)
            changed_count = find_changed_files(
                project_dir, 
                config['source_dirs'], 
                last_run
            )
            
            # Update last check time
            registry.update_last_check(project_dir)
            
            if changed_count > 0:
                print(f"🔄 Changes detected in {project_dir}")
                print(f"   {changed_count} file(s) modified - triggering full analysis")
                
                # Run pylint-cache
                exit_code = run_pylint_cache(
                    project_dir,
                    config['source_dirs'],
                    config['pylint_args'],
                    log_file
                )
                
                # Update last run time
                registry.update_last_run(project_dir)
                
                if exit_code == 0:
                    print(f"   ✓ Analysis completed successfully")
                else:
                    print(f"   ⚠ Analysis completed with exit code: {exit_code}")
            else:
                if verbose:
                    print(f"○ No changes in {project_dir}")
    
    # Clean up old logs (keep 30 days)
    cutoff = time.time() - (30 * 24 * 3600)
    for log in registry.log_dir.glob("monitor-*.log"):
        try:
            if log.stat().st_mtime < cutoff:
                log.unlink()
        except OSError:
            pass
    
    # Clean up stale lock files (older than 1 hour)
    stale_cutoff = time.time() - 3600
    for lock in registry.lock_dir.glob("project_*.lock"):
        try:
            if lock.stat().st_mtime < stale_cutoff:
                lock.unlink()
        except OSError:
            pass


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor registered projects for changes and trigger pylint re-analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Register a project
  %(prog)s add /home/user/myproject --dirs src,lib --args "-E"
  
  # List monitored projects
  %(prog)s list
  
  # Run the monitor (checks all projects)
  %(prog)s run
  
  # Remove a project
  %(prog)s remove /home/user/myproject
  
  # Add to crontab (run every 15 minutes):
  */15 * * * * %(prog)s run
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a project to monitor')
    add_parser.add_argument('project_dir', help='Project directory path')
    add_parser.add_argument('--dirs', required=True, 
                          help='Comma-separated source directories (e.g., src,lib)')
    add_parser.add_argument('--args', default='-E',
                          help='Pylint arguments (default: -E)')
    
    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove a project from monitoring')
    remove_parser.add_argument('project_dir', help='Project directory path')
    
    # List command
    subparsers.add_parser('list', help='List monitored projects')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run the monitor (check for changes)')
    run_parser.add_argument('-v', '--verbose', action='store_true',
                          help='Verbose output')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Initialize registry
    registry = MonitorRegistry()
    
    # Execute command
    if args.command == 'add':
        source_dirs = [d.strip() for d in args.dirs.split(',')]
        registry.add_project(args.project_dir, source_dirs, args.args)
    
    elif args.command == 'remove':
        if not registry.remove_project(args.project_dir):
            sys.exit(1)
    
    elif args.command == 'list':
        registry.list_projects()
    
    elif args.command == 'run':
        run_monitor(registry, verbose=args.verbose)


if __name__ == '__main__':
    main()

