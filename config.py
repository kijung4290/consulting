"""
설정 관리 모듈 (config.py)
- 로컬 데이터 저장 폴더 경로 및 프로그램 환경설정 관리
"""

import os
import sys
import json
from typing import Dict, Any

if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(APP_DIR, "config.json")
DEFAULT_DATA_DIR = os.path.join(APP_DIR, "data")

def load_config() -> Dict[str, Any]:
    """설정 파일을 로드합니다."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg: Dict[str, Any]):
    """설정을 저장합니다."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"설정 저장 실패: {e}")

def get_data_dir() -> str:
    """현재 지정된 데이터 저장소 경로를 반환합니다."""
    cfg = load_config()
    data_dir = cfg.get("data_dir")
    if not data_dir:
        data_dir = DEFAULT_DATA_DIR
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def set_data_dir(new_path: str):
    """새로운 데이터 저장소 경로를 설정합니다."""
    cfg = load_config()
    cfg["data_dir"] = os.path.abspath(new_path)
    os.makedirs(cfg["data_dir"], exist_ok=True)
    save_config(cfg)

def is_first_run() -> bool:
    """최초 실행 여부 확인 (설정 파일이나 지정 폴더가 아직 없는 경우)"""
    cfg = load_config()
    return "data_dir" not in cfg
