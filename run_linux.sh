#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv_linux/bin/python || ! -f .venv_linux/.installed ]]; then
    echo '먼저 bash install_linux.sh 를 실행해 설치를 완료해 주세요.'
    exit 1
fi
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough
exec .venv_linux/bin/python app.py
