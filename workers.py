"""시간이 오래 걸리는 모델 다운로드·로드·생성을 담당하는 백그라운드 작업."""

from PyQt6.QtCore import QThread, pyqtSignal

from download_model import download_gemma_model
from engine import InferenceEngine


class DownloadWorker(QThread):
    progress_signal = pyqtSignal(str, int, int)
    finished_signal = pyqtSignal(bool, str)

    def run(self):
        try:
            def callback(message, current, total):
                self.progress_signal.emit(message, current, total)

            path = download_gemma_model(progress_callback=callback)
            self.finished_signal.emit(True, path)
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class GenerationWorker(QThread):
    token_signal = pyqtSignal(str)
    metrics_signal = pyqtSignal(float, int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, engine: InferenceEngine, prompt: str, max_tokens: int = 1024):
        super().__init__()
        self.engine = engine
        self.prompt = prompt
        self.max_tokens = max_tokens

    def run(self):
        try:
            for item in self.engine.generate_stream(self.prompt, max_tokens=self.max_tokens):
                token = item.get("token", "")
                if token:
                    self.token_signal.emit(token)
                self.metrics_signal.emit(
                    item.get("tokens_sec", 0.0),
                    item.get("total_tokens", 0),
                )
                if item.get("done", False):
                    break
            self.finished_signal.emit(True, "완료")
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class ModelLoadWorker(QThread):
    """용량이 큰 로컬 모델을 UI 스레드 밖에서 읽습니다."""

    finished_signal = pyqtSignal(bool, str)

    def __init__(self, engine: InferenceEngine):
        super().__init__()
        self.engine = engine

    def run(self):
        ok, message = self.engine.load_model()
        self.finished_signal.emit(ok, message)

