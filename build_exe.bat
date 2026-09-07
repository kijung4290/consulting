@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" build_package.py --platform windows --exe-only
if errorlevel 1 exit /b 1
pause
