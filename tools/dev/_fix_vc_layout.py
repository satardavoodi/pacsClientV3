"""Fix formatting corruption in _vc_layout.py — two merged lines missing CRLF."""
import sys

path = r'PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py'
with open(path, 'rb') as f:
    content = f.read()

old1 = b'Slider connected")            # Slider thumb-drag'
new1 = b'Slider connected")\r\n            # Slider thumb-drag'

old2 = b'pass  # Kill-switch block failure never breaks the standard valueChanged path        except Exception as e:'
new2 = b'pass  # Kill-switch block failure never breaks the standard valueChanged path\r\n        except Exception as e:'

count1 = content.count(old1)
count2 = content.count(old2)
print(f'Fix1 occurrences: {count1}')
print(f'Fix2 occurrences: {count2}')

if count1 == 0 and count2 == 0:
    print('Nothing to fix — file may already be correct or pattern not found.')
    sys.exit(1)

content = content.replace(old1, new1, 1)
content = content.replace(old2, new2, 1)

with open(path, 'wb') as f:
    f.write(content)

print('Fixed and written.')

# Verify: try compiling
import py_compile, tempfile, os, shutil
tmp = path + '.tmp_check.py'
shutil.copy(path, tmp)
try:
    py_compile.compile(tmp, doraise=True)
    print('Syntax OK.')
except py_compile.PyCompileError as e:
    print(f'SYNTAX ERROR after fix: {e}')
    sys.exit(2)
finally:
    if os.path.exists(tmp):
        os.remove(tmp)
    if os.path.exists(tmp + 'c'):
        os.remove(tmp + 'c')
