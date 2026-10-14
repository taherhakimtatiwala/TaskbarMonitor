@echo off
REM Builds a single-file, windowless TaskbarMonitor.exe into .\dist
python -m pip install -r requirements-dev.txt
python -m PyInstaller --onefile --noconsole --name TaskbarMonitor taskbar_monitor.py
echo.
echo Done. Your executable is in .\dist\TaskbarMonitor.exe
pause
