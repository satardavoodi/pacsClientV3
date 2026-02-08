import subprocess
import sys
import time
import os

os.chdir('D:\\New folder\\PacsClientV2')

# Run the app and redirect to file
with open('app_output.log', 'w') as f:
    proc = subprocess.Popen([sys.executable, 'main.py'], 
                           stdout=f, 
                           stderr=subprocess.STDOUT,
                           text=True)
    # Wait for 20 seconds
    time.sleep(20)
    # Kill the process
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except:
        proc.kill()

# Now read and show relevant lines
with open('app_output.log', 'r') as f:
    lines = f.readlines()

print("===== FILTERED LOGS (last 150 lines) =====")
filtered = [l for l in lines if any(x in l for x in ['SYNC_LOAD', 'SYNC_LAYOUT', 'new_viewer', 'Dummy widget', '[LAYOUT]', 'START', 'END', 'IV2D'])]
for line in filtered[-50:]:
    print(line.rstrip())

print("\n\n===== LAST 100 RAW LINES =====")
for line in lines[-100:]:
    print(line.rstrip())
