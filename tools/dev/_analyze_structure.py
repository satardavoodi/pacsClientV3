"""Extract class/function outline from large Python files."""
import os
import ast
import sys

TARGET_FILES = [
    r".\PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget_viewer_controller.py",
    r".\PacsClient\pacs\patient_tab\ui\patient_ui\patient_toolbar\toolbar_manager.py",
    r".\PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget.py",
    r".\modules\EchoMind\viewer_chat\ai_chat_pages.py",
    r".\modules\download_manager\ui\main_widget.py",
    r".\PacsClient\pacs\workstation_ui\home_ui\home_ui.py",
    r".\modules\mpr\zeta_mpr\standard_mpr_viewer.py",
    r".\modules\EchoMind\viewer_chat\ai_chat_widgets.py",
    r".\PacsClient\pacs\patient_tab\ui\patient_ui\widget_viewer.py",
    r".\modules\education\education_module_redesigned.py",
    r".\PacsClient\pacs\workstation_ui\home_ui\patient_table_widget.py",
    r".\database\core.py",
    r".\modules\viewer\advanced\viewer_2d.py",
    r".\modules\EchoMind\viewer_chat\openai_reporter.py",
    r".\modules\web_browser\widget.py",
    r".\modules\mpr\zeta_mpr\curved_mpr.py",
    r".\PacsClient\pacs\patient_tab\utils\thumbnail_manager.py",
    r".\PacsClient\pacs\workstation_ui\settings_ui\filter_config.py",
    r".\modules\printing\ui\printing_widget.py",
    r".\PacsClient\pacs\patient_tab\utils\utils.py",
    r".\PacsClient\pacs\patient_tab\utils\image_io.py",
]

def analyze_file(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
    except Exception as e:
        return f"  ERROR: {e}\n"

    lines = source.count('\n') + 1
    output = []

    # Top-level imports summary
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    output.append(f"  Imports: {len(imports)} total")

    # Classes with method counts and line ranges
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    output.append(f"  Classes: {len(classes)}")
    for cls in classes:
        methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        # approximate line count for class
        class_end = max((getattr(n, 'end_lineno', cls.lineno) for n in ast.walk(cls)), default=cls.lineno)
        class_lines = class_end - cls.lineno + 1
        output.append(f"    class {cls.name} ({class_lines} lines, {len(methods)} methods)")
        for m in methods:
            m_end = getattr(m, 'end_lineno', m.lineno)
            m_lines = m_end - m.lineno + 1
            if m_lines > 100:
                output.append(f"      [{m_lines:4d} lines] {m.name}()")
            else:
                output.append(f"      [ {m_lines:3d} lines] {m.name}()")

    # Top-level functions
    top_funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if top_funcs:
        output.append(f"  Top-level functions: {len(top_funcs)}")
        for f2 in top_funcs:
            f_end = getattr(f2, 'end_lineno', f2.lineno)
            f_lines = f_end - f2.lineno + 1
            output.append(f"    [{f_lines:4d} lines] {f2.name}()")

    return '\n'.join(output)

for fpath in TARGET_FILES:
    abs_path = os.path.abspath(fpath)
    if not os.path.exists(abs_path):
        print(f"\n=== {fpath} === NOT FOUND")
        continue
    with open(abs_path, 'r', encoding='utf-8', errors='ignore') as fh:
        total_lines = sum(1 for _ in fh)
    print(f"\n{'='*100}")
    print(f"  FILE: {fpath}  ({total_lines} lines)")
    print('='*100)
    print(analyze_file(abs_path))
