@echo off
rem Start miaoyixia with no console window.
rem
rem pythonw.exe rather than python.exe: it is the windowed interpreter, so nothing opens a black
rem box behind the app. `start ""` hands the process to the shell and returns immediately, so this
rem script exits rather than lingering as the app's parent -- which matters, because a parent that
rem goes away can take the child with it.
rem
rem Launching this twice is safe: the second copy tells the first to show its window, then exits.
rem
rem NOTE: this file must stay ASCII with CRLF line endings. cmd.exe parses batch files by byte
rem offset and mis-seeks on bare LF, silently eating characters -- "start" once arrived as "art".

cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m app.main
