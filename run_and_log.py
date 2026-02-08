import subprocess
import sys
import time

# Run the app and capture output
proc = subprocess.Popen([sys.executable, 'main.py'], 
                       stdout=subprocess.PIPE, 
                       stderr=subprocess.STDOUT,
                       text=True,
                       bufsize=1)

# Capture for 25 seconds
start = time.time()
lines = []
try:
    while time.time() - start < 25:
        try:
            line = proc.stdout.readline()
            if line:
                lines.append(line.rstrip())
                # Print lines with key keywords
                if any(x in line for x in ['new_viewer', 'Dummy widget', 'Scheduling', 'Background', 'IV2D', 'VTK-', 'START', 'END', 'created successfully']):
                    print(line.rstrip())
        except:
            break
except KeyboardInterrupt:
    pass
finally:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except:
        proc.kill()

print("\n\n=== LAST 80 LINES ===")
for line in lines[-80:]:
    print(line)
