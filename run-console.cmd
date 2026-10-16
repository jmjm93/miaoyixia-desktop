@echo off
rem The same app, attached to this console so you can watch it work.
rem
rem Use this when something misbehaves: python.exe keeps stdout, so warm-up timings, recognition
rem errors and any traceback appear here as they happen. Closing the console closes the app.
rem
rem miaoyixia.log records the same information either way, so this is convenience rather than the
rem only route to a diagnosis.
rem
rem ASCII + CRLF, for the reason given in run.cmd.

cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.main
pause
