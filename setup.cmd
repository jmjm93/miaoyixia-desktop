@echo off
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe tools/setup_japanese.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe tools/setup_spanish.py
if errorlevel 1 goto failed
echo Setup complete. Double-click run.cmd to start.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11 x64 and check the error above.
pause
exit /b 1
