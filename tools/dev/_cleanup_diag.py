"""Remove diagnostic file writes from _legacy_widget.py."""
import re

f = 'PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_legacy_widget.py'
with open(f, 'r', encoding='utf-8') as fh:
    content = fh.read()

original_len = len(content)

# 1. Remove INIT_DIAG block
p1 = (
    r'            # TEMP DIAG: log backend choice to file\n'
    r'            try:\n'
    r'                import tempfile as _tf, os as _os\n'
    r'                with open\(_os\.path\.join\(_tf\.gettempdir\(\), .aipacs_wheel_diag\.log.\), .a.\) as _df:\n'
    r'                    _df\.write\(f.\[INIT_DIAG\][^\n]*\n'
    r'            except Exception:\n'
    r'                pass\n'
)
c1 = len(re.findall(p1, content))
content = re.sub(p1, '', content)
print(f"[1] INIT_DIAG: {c1} removed")

# 2. Remove FLUSH_ERR diag block (replace with simple logger)
p2 = (
    r'            except Exception as _diag_exc:\n'
    r'                try:\n'
    r'                    import tempfile as _tf, os as _os\n'
    r'                    with open\(_os\.path\.join\(_tf\.gettempdir\(\), .aipacs_wheel_diag\.log.\), .a.\) as _df:\n'
    r'                        _df\.write\(f.\[FLUSH_ERR\][^\n]*\n'
    r'                except Exception:\n'
    r'                    pass'
)
c2 = len(re.findall(p2, content))
content = re.sub(p2, '            except Exception as _diag_exc:\n                logger.debug("flush set_slice failed: %s", _diag_exc)', content)
print(f"[2] FLUSH_ERR: {c2} replaced")

# 3. Remove FLUSH_DIAG block in finally
p3 = (
    r'                try:\n'
    r'                    _diag_after = int\(self\.image_viewer\.GetSlice\(\)\) if self\.image_viewer else None\n'
    r'                    _diag_range_max2 = -1\n'
    r'                    try:\n'
    r'                        _diag_range_max2 = int\(self\.image_viewer\.GetSliceMax\(\)\)\n'
    r'                    except Exception:\n'
    r'                        pass\n'
    r'                    import tempfile as _tf2, os as _os2\n'
    r'                    with open\(_os2\.path\.join\(_tf2\.gettempdir\(\), .aipacs_wheel_diag\.log.\), .a.\) as _df2:\n'
    r'                        _df2\.write\(f.\[FLUSH_DIAG\][^\n]*\n'
    r'                except Exception:\n'
    r'                    pass'
)
c3 = len(re.findall(p3, content))
content = re.sub(p3, '', content)
print(f"[3] FLUSH_DIAG: {c3} removed")

# 4. Remove WHEEL_DIAG block
p4 = (
    r'        # TEMP DIAG: Write to file so we can see if wheelEvent is called\n'
    r'        try:\n'
    r'            import tempfile as _tf, os as _os\n'
    r'            _pending = getattr\(self, ._pending_wheel_slice., None\)\n'
    r'            _vtk_slice = .\?.\n'
    r'            try:\n'
    r'                if self\.image_viewer:\n'
    r'                    _vtk_slice = int\(self\.image_viewer\.GetSlice\(\)\)\n'
    r'            except Exception:\n'
    r'                pass\n'
    r'            with open\(_os\.path\.join\(_tf\.gettempdir\(\), .aipacs_wheel_diag\.log.\), .a.\) as _df:\n'
    r'                _df\.write\(f.\[WHEEL_DIAG\][^\n]*\n'
    r'        except Exception:\n'
    r'            pass\n'
)
c4 = len(re.findall(p4, content))
content = re.sub(p4, '', content)
print(f"[4] WHEEL_DIAG: {c4} removed")

# Verify
remaining = content.count('aipacs_wheel_diag')
print(f"Remaining 'aipacs_wheel_diag': {remaining}")
print(f"Size: {original_len} -> {len(content)} ({original_len - len(content)} chars removed)")

with open(f, 'w', encoding='utf-8') as fh:
    fh.write(content)
print("Done!")
