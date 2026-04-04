"""One-shot script: convert remaining emoji print() calls to logger in controller."""

path = r"PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget_viewer_controller.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Replace by line number (1-based)
changes = {
    3462: '                self.logger.warning("change-series: invalid target viewport for series %s", series_number)\n',
    3479: '                    self.logger.debug("change-series: suppressed duplicate switch series=%s viewer=%s", series_number, viewer_id)\n',
}

for lineno, new_line in changes.items():
    old = lines[lineno - 1]
    lines[lineno - 1] = new_line
    print(f"Line {lineno}: {old[:80].rstrip()!r} -> replaced")

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Done")
