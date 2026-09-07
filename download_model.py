"""
Gemma-2-2B-it Q4_K_M GGUF 모델 다운로더 모듈
- 4~8GB 저사양 PC에 최적화된 초경량(약 1.7GB) 모델 다운로드
- 이어받기 지원 및 다운로드 진행률(콜백) 지원
"""

import os
import sys
from typing import Callable, Optional
from huggingface_hub import hf_hub_download

REPO_ID = "bartowski/gemma-2-2b-it-GGUF"
FILENAME = "gemma-2-2b-it-Q4_K_M.gguf"

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_MODELS_DIR = os.path.join(_BASE_DIR, "models")

def get_model_path(models_dir: str = DEFAULT_MODELS_DIR) -> str:
    return os.path.join(models_dir, FILENAME)

def is_model_downloaded(models_dir: str = DEFAULT_MODELS_DIR) -> bool:
    target = get_model_path(models_dir)
    return os.path.exists(target) and os.path.getsize(target) > 1000_000_000 # 최소 1GB 이상

def download_gemma_model(
    models_dir: str = DEFAULT_MODELS_DIR,
    progress_callback: Optional[Callable[[str, int, int], None]] = None
) -> str:
    """
    Gemma-2-2B-it Q4_K_M GGUF 모델을 다운로드합니다.
    progress_callback: (status_text, current_bytes, total_bytes)
    """
    os.makedirs(models_dir, exist_ok=True)
    target_path = get_model_path(models_dir)

    if is_model_downloaded(models_dir):
        if progress_callback:
            progress_callback("이미 모델이 존재합니다.", 100, 100)
        return target_path

    if progress_callback:
        progress_callback("Hugging Face 서버 연결 중...", 0, 100)

    # hf_hub_download를 통해 안정적으로 다운로드 (이어받기 및 검증 지원)
    downloaded_path = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=models_dir,
        local_dir_use_symlinks=False
    )

    if progress_callback:
        progress_callback("다운로드 및 무결성 검증 완료!", 100, 100)

    return downloaded_path

if __name__ == "__main__":
    print(f"[*] Gemma-2-2B-it 모델 다운로드를 시작합니다 (저장위치: {DEFAULT_MODELS_DIR})...")
    path = download_gemma_model()
    print(f"[+] 다운로드 완료: {path} (크기: {os.path.getsize(path) / (1024*1024):.1f} MB)")
