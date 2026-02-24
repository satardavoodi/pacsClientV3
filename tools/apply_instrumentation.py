"""
Instrumentation Helper for Mode B Performance Testing

This script adds performance logging instrumentation to key methods
without modifying application logic.

Usage:
    python apply_instrumentation.py --check     # Dry run, show what would be added
    python apply_instrumentation.py --apply     # Apply instrumentation
    python apply_instrumentation.py --remove    # Remove instrumentation (restore backups)
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Tuple


class Instrumentation:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.backup_dir = self.root_dir / "backups" / f"pre_instrumentation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.changes = []
    
    def backup_file(self, file_path: Path):
        """Create backup of file before modification."""
        if not self.backup_dir.exists():
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        relative_path = file_path.relative_to(self.root_dir)
        backup_path = self.backup_dir / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(file_path, backup_path)
        print(f"[✓] Backed up: {relative_path}")
    
    def add_imports(self, file_path: Path) -> str:
        """Add required imports to file if not present."""
        content = file_path.read_text(encoding='utf-8')
        
        imports_to_add = []
        
        if 'import time' not in content:
            imports_to_add.append('import time')
        if 'import os' not in content:
            imports_to_add.append('import os')
        if 'import threading' not in content:
            imports_to_add.append('import threading')
        
        if imports_to_add:
            # Find first import statement
            lines = content.split('\n')
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('import ') or line.strip().startswith('from '):
                    insert_idx = i
                    break
            
            # Insert after existing imports
            for imp in reversed(imports_to_add):
                lines.insert(insert_idx + 1, imp)
            
            content = '\n'.join(lines)
        
        return content
    
    def instrument_vtk_widget_set_slice(self, dry_run: bool = True) -> Tuple[bool, str]:
        """Instrument vtk_widget.py set_slice method."""
        file_path = self.root_dir / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget.py"
        
        if not file_path.exists():
            return False, f"File not found: {file_path}"
        
        content = file_path.read_text(encoding='utf-8')
        
        # Check if already instrumented
        if '[PERF][VIEWER]' in content and 'set_slice ENTRY' in content:
            return False, "Already instrumented"
        
        # Find set_slice method
        target = 'def set_slice(self, slice_index):'
        if target not in content:
            return False, "set_slice method not found"
        
        instrumented_method = '''def set_slice(self, slice_index):
        import time
        import os
        import threading
        t_start = time.perf_counter()
        corr_id = f"{int(time.time()*1000)}_VIEWER_SET_SLICE_{id(self) % 10000}"
        
        # [PERF LOG] Entry
        if hasattr(self, 'logger') and self.logger:
            self.logger.info(
                f"[PERF][VIEWER][{corr_id}] set_slice ENTRY | "
                f"slice={slice_index} | pid={os.getpid()} | tid={threading.get_ident()}"
            )
        
        try:'''
        
        # Find method body and wrap with timing
        lines = content.split('\n')
        new_lines = []
        in_set_slice = False
        indent_level = 0
        method_start_idx = None
        
        for i, line in enumerate(lines):
            if target in line:
                in_set_slice = True
                method_start_idx = i
                indent_level = len(line) - len(line.lstrip())
                
                # Add instrumented method signature
                new_lines.append(line)
                # Add timing setup
                new_lines.append(' ' * (indent_level + 4) + 'import time')
                new_lines.append(' ' * (indent_level + 4) + 'import os')
                new_lines.append(' ' * (indent_level + 4) + 'import threading')
                new_lines.append(' ' * (indent_level + 4) + 't_start = time.perf_counter()')
                new_lines.append(' ' * (indent_level + 4) + 'corr_id = f"{int(time.time()*1000)}_VIEWER_SET_SLICE_{id(self) % 10000}"')
                new_lines.append('')
                new_lines.append(' ' * (indent_level + 4) + '# [PERF LOG] Entry')
                new_lines.append(' ' * (indent_level + 4) + 'if hasattr(self, \'logger\') and self.logger:')
                new_lines.append(' ' * (indent_level + 8) + 'self.logger.info(')
                new_lines.append(' ' * (indent_level + 12) + 'f"[PERF][VIEWER][{corr_id}] set_slice ENTRY | "')
                new_lines.append(' ' * (indent_level + 12) + 'f"slice={slice_index} | pid={os.getpid()} | tid={threading.get_ident()}"')
                new_lines.append(' ' * (indent_level + 8) + ')')
                new_lines.append('')
                new_lines.append(' ' * (indent_level + 4) + 'try:')
                continue
            
            if in_set_slice:
                # Check if we're at next method (dedent)
                if line.strip() and not line.strip().startswith('#'):
                    current_indent = len(line) - len(line.lstrip())
                    if current_indent <= indent_level and line.strip().startswith('def '):
                        # End of set_slice method, add finally block
                        in_set_slice = False
                        
                        new_lines.append(' ' * (indent_level + 4) + 'finally:')
                        new_lines.append(' ' * (indent_level + 8) + 't_end = time.perf_counter()')
                        new_lines.append(' ' * (indent_level + 8) + 'duration_ms = (t_end - t_start) * 1000')
                        new_lines.append(' ' * (indent_level + 8) + '# [PERF LOG] Exit')
                        new_lines.append(' ' * (indent_level + 8) + 'if hasattr(self, \'logger\') and self.logger:')
                        new_lines.append(' ' * (indent_level + 12) + 'self.logger.info(')
                        new_lines.append(' ' * (indent_level + 16) + 'f"[PERF][VIEWER][{corr_id}] set_slice EXIT | "')
                        new_lines.append(' ' * (indent_level + 16) + 'f"duration_ms={duration_ms:.2f} | slice={slice_index}"')
                        new_lines.append(' ' * (indent_level + 12) + ')')
                        new_lines.append(' ' * (indent_level + 12) + 'if duration_ms > 50:')
                        new_lines.append(' ' * (indent_level + 16) + 'self.logger.warning(')
                        new_lines.append(' ' * (indent_level + 20) + 'f"[PERF][VIEWER][{corr_id}] SLOW set_slice | "')
                        new_lines.append(' ' * (indent_level + 20) + 'f"duration_ms={duration_ms:.2f} | threshold=50ms"')
                        new_lines.append(' ' * (indent_level + 16) + ')')
                        new_lines.append('')
                
                # Add extra indent for existing code (now inside try block)
                if line.strip():
                    new_lines.append(' ' * 4 + line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        new_content = '\n'.join(new_lines)
        
        if not dry_run:
            self.backup_file(file_path)
            file_path.write_text(new_content, encoding='utf-8')
            print(f"[✓] Instrumented: set_slice in vtk_widget.py")
        
        self.changes.append(('vtk_widget.py', 'set_slice', 'instrumented'))
        return True, "Instrumentation prepared"
    
    def add_simple_logging_decorator(self, dry_run: bool = True):
        """Add a simple logging decorator to common module."""
        decorator_code = '''
# Performance logging decorator (added for Mode B testing)
import time
import os
import threading
import functools

def perf_log(component: str, threshold_ms: float = 50.0):
    """Decorator to log function performance."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t_start = time.perf_counter()
            corr_id = f"{int(time.time()*1000)}_{component}_{func.__name__}_{id(args[0]) % 10000 if args else 0}"
            
            # Try to get logger from self
            logger = None
            if args and hasattr(args[0], 'logger'):
                logger = args[0].logger
            
            if logger:
                logger.debug(
                    f"[PERF][{component}][{corr_id}] {func.__name__} ENTRY | "
                    f"pid={os.getpid()} | tid={threading.get_ident()}"
                )
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                t_end = time.perf_counter()
                duration_ms = (t_end - t_start) * 1000
                
                if logger:
                    log_level = logger.warning if duration_ms > threshold_ms else logger.info
                    log_level(
                        f"[PERF][{component}][{corr_id}] {func.__name__} EXIT | "
                        f"duration_ms={duration_ms:.2f}"
                    )
        
        return wrapper
    return decorator
'''
        
        # Add to utils/logging_utils.py or create new file
        utils_dir = self.root_dir / "PacsClient" / "utils"
        target_file = utils_dir / "perf_logging.py"
        
        if target_file.exists() and not dry_run:
            print(f"[!] {target_file.name} already exists, skipping")
            return
        
        if not dry_run:
            target_file.write_text(decorator_code, encoding='utf-8')
            print(f"[✓] Created: {target_file}")
        
        self.changes.append(('perf_logging.py', 'decorator', 'created'))
    
    def check(self):
        """Dry run - show what would be changed."""
        print("=" * 80)
        print("INSTRUMENTATION CHECK (Dry Run)")
        print("=" * 80)
        print("")
        
        print("[*] Checking files that would be instrumented...")
        print("")
        
        # Check each instrumentation
        self.add_simple_logging_decorator(dry_run=True)
        self.instrument_vtk_widget_set_slice(dry_run=True)
        
        print("")
        print("Summary of changes:")
        print("-" * 80)
        for file_name, method, action in self.changes:
            print(f"  [{action.upper()}] {file_name} -> {method}")
        
        print("")
        print(f"Total changes: {len(self.changes)}")
        print("")
        print("To apply these changes, run:")
        print("  python apply_instrumentation.py --apply")
        print("")
    
    def apply(self):
        """Apply instrumentation to files."""
        print("=" * 80)
        print("APPLYING INSTRUMENTATION")
        print("=" * 80)
        print("")
        
        print(f"[*] Backups will be saved to: {self.backup_dir}")
        print("")
        
        self.add_simple_logging_decorator(dry_run=False)
        self.instrument_vtk_widget_set_slice(dry_run=False)
        
        print("")
        print("=" * 80)
        print("INSTRUMENTATION COMPLETE")
        print("=" * 80)
        print("")
        print(f"Applied {len(self.changes)} changes")
        print(f"Backups saved to: {self.backup_dir}")
        print("")
        print("Next steps:")
        print("  1. Test application to verify instrumentation works")
        print("  2. Run performance test: tools\\run_performance_test.ps1 -Scenario mode_b")
        print("  3. Analyze logs: python tools\\performance_log_analyzer.py <log_file>")
        print("")
    
    def remove(self):
        """Remove instrumentation by restoring from most recent backup."""
        backup_dirs = sorted((self.root_dir / "backups").glob("pre_instrumentation_*"))
        
        if not backup_dirs:
            print("[!] No backup found. Cannot remove instrumentation.")
            return
        
        latest_backup = backup_dirs[-1]
        print(f"[*] Restoring from: {latest_backup}")
        print("")
        
        for backup_file in latest_backup.rglob("*"):
            if backup_file.is_file():
                relative_path = backup_file.relative_to(latest_backup)
                target_file = self.root_dir / relative_path
                
                shutil.copy2(backup_file, target_file)
                print(f"[✓] Restored: {relative_path}")
        
        print("")
        print("[✓] Instrumentation removed")
        print("")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python apply_instrumentation.py --check     # Dry run")
        print("  python apply_instrumentation.py --apply     # Apply changes")
        print("  python apply_instrumentation.py --remove    # Remove changes")
        sys.exit(1)
    
    mode = sys.argv[1]
    root_dir = Path(__file__).parent.parent
    
    instr = Instrumentation(root_dir)
    
    if mode == '--check':
        instr.check()
    elif mode == '--apply':
        instr.apply()
    elif mode == '--remove':
        instr.remove()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == '__main__':
    main()
