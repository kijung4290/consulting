@echo off
cd /d "%~dp0"
chcp 65001 > nul
title 사회복지 상담기록 AI - 원클릭 Setup 설치 파일 생성 도구

echo ================================================================
echo   사회복지 상담기록 AI 어시스턴트 - 원클릭 Setup 설치파일 빌더
echo ================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [오류] 가상환경(.venv)이 존재하지 않습니다.
    pause
    exit /b
)

".venv\Scripts\python.exe" build_package.py
if errorlevel 1 exit /b 1
pause
exit /b
