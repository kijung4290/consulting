@echo off
cd /d "%~dp0"
title 사회복지 상담기록 AI 어시스턴트
echo ========================================================
echo   사회복지 상담기록 AI 어시스턴트를 실행합니다...
echo ========================================================
echo.
if not exist "%~dp0.venv\Scripts\python.exe" goto NO_VENV
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
if errorlevel 1 goto ERROR_EXIT
exit /b 0
:NO_VENV
echo [오류] 가상환경(.venv)이 존재하지 않습니다.
echo 폴더 내에 .venv 폴더가 있는지 확인해 주세요.
pause
exit /b 1
:ERROR_EXIT
echo.
echo ========================================================
echo [오류] 프로그램 실행 중 오류가 발생하여 종료되었습니다.
echo ========================================================
pause
exit /b 1
