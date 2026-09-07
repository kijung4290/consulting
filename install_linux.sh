#!/usr/bin/env bash
# Linux Mint / Ubuntu 사용자별 설치·업데이트
set -euo pipefail
cd -- "$(dirname -- "$0")"
if ! command -v python3 >/dev/null; then
    echo 'python3가 필요합니다. docs/설치_배포.md의 준비 명령을 실행하세요.'
    exit 1
fi
python3 -m venv .venv_linux
.venv_linux/bin/python -m pip install --upgrade pip
.venv_linux/bin/python -m pip install -r requirements.txt
.venv_linux/bin/python -c 'import PyQt6.QtWidgets, PyQt6.QtPrintSupport, llama_cpp, psutil, huggingface_hub'
touch .venv_linux/.installed
echo '설치 완료. bash run_linux.sh 로 실행하세요.'
