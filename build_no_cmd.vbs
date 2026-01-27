Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python build.py", 0, False
Set WshShell = Nothing

