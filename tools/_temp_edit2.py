"""Insert progressive exit in load_series_on_demand."""
filepath = r'c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget_viewer_controller.py'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "_mark_download_active()" inside load_series_on_demand
target_line = None
for i, line in enumerate(lines):
    if '_mark_download_active()' in line and i > 5000:
        target_line = i
        break

if target_line is None:
    print("ERROR: could not find _mark_download_active()")
    exit(1)

print(f"Found _mark_download_active() at line {target_line + 1}")

# Insert after line target_line
insert_lines = [
    '\n',
    '            # Exit progressive mode for this series (fully downloaded now)\n',
    '            self.on_series_download_fully_complete(series_number_str)\n',
]

lines = lines[:target_line + 1] + insert_lines + lines[target_line + 1:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done - inserted progressive exit call")
