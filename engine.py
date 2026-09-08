"""
llama.cpp 기반 고속 경량 LLM 추론 엔진
- 4~8GB RAM 환경 맞춤 최적화:
  1. CPU 물리 코어 자동 감지 및 100% 최적 스레드 할당
  2. 문맥 창(Context Window) 2048 크기로 제한하여 메모리 및 Time-to-First-Token 단축
  3. 실시간 토큰 스트리밍(Streaming)으로 체감 대기시간 최소화
  4. 중지(Abort) 제어 및 초당 토큰 수(Tokens/sec) 실시간 계측
"""

import os
import time
import psutil
from typing import Generator, Optional, Tuple, Dict, Any

class InferenceEngine:
    def __init__(self, model_path: str, n_ctx: int = 2048):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.llm = None
        self.stop_flag = False
        
        # CPU 물리 코어 감지 (하이퍼스레딩 배제하여 캐시 병목 해소)
        physical_cores = psutil.cpu_count(logical=False)
        self.n_threads = physical_cores if physical_cores and physical_cores > 0 else 4

    def load_model(self) -> Tuple[bool, str]:
        """모델을 메모리에 로드합니다."""
        if not os.path.exists(self.model_path):
            return False, f"모델 파일을 찾을 수 없습니다: {self.model_path}"

        try:
            from llama_cpp import Llama
            
            # 저사양 4~8GB PC 최적화 파라미터
            self.llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_batch=512,           # 프롬프트 처리 배치 크기
                n_ubatch=256,          # 마이크로 배치
                verbose=False,         # 불필요한 콘솔 로그 제거하여 오버헤드 감소
                use_mmap=True,         # OS 메모리 매핑 활용으로 로딩 속도 향상 및 RAM 절약
                use_mlock=False        # 저사양 환경에서 스왑 허용하여 OOM 방지
            )
            return True, f"성공적으로 로드됨 (CPU 물리 코어: {self.n_threads}개 할당)"
        except Exception as e:
            return False, f"모델 로드 중 오류 발생: {str(e)}"

    def is_loaded(self) -> bool:
        return self.llm is not None

    def abort(self):
        """진행 중인 토큰 생성을 즉시 중단합니다."""
        self.stop_flag = True

    def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        top_p: float = 0.9,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        토큰을 실시간으로 스트리밍 생성하며, 속도(t/s)와 통계를 딕셔너리로 반환합니다.
        반환 예: {"token": "...", "tokens_sec": 18.5, "total_tokens": 45, "done": False}
        """
        if not self.llm:
            raise RuntimeError("모델이 아직 로드되지 않았습니다.")

        self.stop_flag = False
        start_time = time.time()
        token_count = 0

        # Gemma-2 특화 종료 토큰
        stop_tokens = ["<end_of_turn>", "<eos>", "<start_of_turn>"]

        stream = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repeat_penalty=1.1,
                stream=True,
                stop=stop_tokens
            )
        try:
            for output in stream:
                if self.stop_flag:
                    break

                choices = output.get("choices", [])
                if not choices:
                    continue

                token_text = choices[0].get("text", "")
                if not token_text:
                    continue

                token_count += 1
                elapsed = time.time() - start_time
                t_per_sec = (token_count / elapsed) if elapsed > 0 else 0.0

                yield {
                    "token": token_text,
                    "tokens_sec": t_per_sec,
                    "total_tokens": token_count,
                    "done": False
                }

        finally:
            if hasattr(stream, 'close'):
                stream.close()
        # 예외가 발생하면 완료 신호를 내보내지 않고 호출자에게 전달한다.
        elapsed = time.time() - start_time
        yield {
            "token": "",
            "tokens_sec": token_count / elapsed if elapsed > 0 else 0.0,
            "total_tokens": token_count,
            "done": True,
            "aborted": self.stop_flag,
        }

    @staticmethod
    def get_system_memory_info() -> Dict[str, Any]:
        """시스템 현재 RAM 상태를 반환합니다."""
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "available_gb": round(mem.available / (1024 ** 3), 1),
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "percent": mem.percent
        }
