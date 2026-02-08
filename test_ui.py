#!/usr/bin/env python3
import subprocess
import sys
import time
import threading

def run_app():
    subprocess.run([sys.executable, 'main.py'], 
                   stdout=subprocess.PIPE, 
                   stderr=subprocess.STDOUT)

# Run app in thread
thread = threading.Thread(target=run_app, daemon=True)
thread.start()

# Wait 25 seconds
time.sleep(25)

# Kill the thread by terminating Python
import os
os.system('taskkill /F /IM python.exe 2>nul')

print("Test completed")
