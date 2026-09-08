"""실제 데이터에 접근하지 않고 가상 상담 화면을 캡처한다."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import sys
from unittest.mock import patch
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication, QScrollArea
from database import Database
from app import (MainWindow, PAGE_CLIENTS, PAGE_CASE, PAGE_DOCS, PAGE_DATA,
                 CLIENT_TAB_LIST, CLIENT_TAB_DUE, CLIENT_TAB_RECENT, CLIENT_TAB_DOCS,
                 DOCS_TAB_WRITE, DOCS_TAB_VAULT, DATA_TAB_FORMS, DATA_TAB_BACKUP,
                 CASE_TAB_CONTEXT)


class _RunningContext:
    """맥락 갱신이 진행 중인 상태를 모델 없이 재현한다."""

    def __init__(self, client_id):
        self.client_id = client_id

    def busy(self):
        return True

    def current_client_id(self):
        return self.client_id

    def progress_text(self):
        return 'AI가 기록 읽는 중 · 자료 2/4 · 7초 경과'

    def progress_values(self):
        return 2, 4

    def model_ready(self):
        return True

    def pending_client_ids(self):
        return [self.client_id]

    def deferred_client_ids(self):
        return []

    def is_deferred(self, client_id, revision):
        return False

    def stop(self):
        pass


def main():
    app = QApplication.instance() or QApplication([])
    for path in ('C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/malgunbd.ttf'):
        if Path(path).exists():
            QFontDatabase.addApplicationFont(path)
    output = Path(__file__).parent / 'docs' / 'ux_preview'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder, patch('config.is_first_run', return_value=False), \
            patch('config.get_data_dir', return_value=folder), patch('app.is_model_downloaded', return_value=False):
        db = Database(folder)
        first = db.add_client({'name': '김가상', 'masked_name': '김OO', 'risk_level': '중위기',
                               'welfare_type': '기초수급', 'gender': '여'})
        db.add_client({'name': '이가상', 'masked_name': '이OO', 'risk_level': '일반', 'gender': '남'})
        db.add_monitoring_task(first, '전화 확인', QDate.currentDate().toString('yyyy-MM-dd'), '식사 준비 상황과 지원 희망 여부 확인')
        window = MainWindow()
        window.context_controller.stop()
        real_context = window.context_controller
        window.show()
        window.resize(1366, 768)
        window.switch_to_ai_counsel_with_client(first)
        window.input_text.setPlainText('가상 자료: 전화 상담. 식사 준비가 어렵다고 함.\n밑반찬 지원 절차를 안내함.\n다음 주 지원 신청 의사를 다시 확인하기로 함.')
        window.output_text.setPlainText('[상담 내용]\n식사 준비에 어려움이 있다고 이야기함.\n\n[개입 내용]\n밑반찬 지원 절차를 안내함.\n\n[다음 계획]\n다음 주 전화로 지원 신청 의사를 확인하기로 함.\n\n※ 화면 검증을 위한 가상 기록입니다.')
        window.persist_counseling_draft()
        # 업무 메뉴 4화면과 그 안의 보조 탭을 모두 지나며 화면 잘림을 확인한다.
        screens = ((PAGE_DOCS, DOCS_TAB_WRITE, 'counseling'),
                   (PAGE_CLIENTS, CLIENT_TAB_LIST, 'clients'),
                   (PAGE_CLIENTS, CLIENT_TAB_DUE, 'clients_due'),
                   (PAGE_CLIENTS, CLIENT_TAB_RECENT, 'clients_recent'),
                   (PAGE_CLIENTS, CLIENT_TAB_DOCS, 'clients_documents'),
                   (PAGE_CASE, None, 'casework'),
                   (PAGE_DOCS, DOCS_TAB_VAULT, 'documents'),
                   (PAGE_DATA, DATA_TAB_FORMS, 'templates'),
                   (PAGE_DATA, DATA_TAB_BACKUP, 'settings'))
        for index, tab, name in screens:
            window.switch_page(index)
            if tab is not None:
                {PAGE_CLIENTS: window.client_tabs,
                 PAGE_DOCS: window.docs_tabs,
                 PAGE_DATA: window.data_tabs}[index].setCurrentIndex(tab)
            for _ in range(5):
                app.processEvents()
            window.grab().save(str(output / f'{name}.png'))
            # 탭 안쪽 스크롤이 가로 넘침을 흡수하므로 지금 보이는 스크롤 영역을 모두 확인한다.
            # 숨어 있는 탭의 스크롤은 아직 배치되지 않아 지난 값이 남으므로 제외한다.
            page = window.stacked_widget.widget(index)
            overflow = max(scroll.horizontalScrollBar().maximum()
                           for scroll in [page] + page.findChildren(QScrollArea)
                           if scroll is page or scroll.isVisible())
            print(name, window.width(), window.height(), 'horizontal overflow', overflow)
        # AI 작업이 돌고 있을 때의 표시를 실제 모델 없이 확인한다.
        window.switch_page(PAGE_CASE)
        window.case_management_page.select_client(first)
        window.case_management_page.tabs.setCurrentIndex(CASE_TAB_CONTEXT)
        window.context_controller = _RunningContext(first)
        window.refresh_activity_indicator()
        window.case_management_page.refresh_context()
        for _ in range(5):
            app.processEvents()
        window.grab().save(str(output / 'ai_activity.png'))
        print('ai_activity', window.activity_title.text(), '|', window.activity_detail.text())
        print('context', window.case_management_page.context_status.text().splitlines()[0])
        window.context_controller = real_context

        window.resize(880, 540)
        window.open_counseling_writer()
        app.processEvents()
        window.grab().save(str(output / 'counseling_small.png'))
        print('small', window.width(), window.height())
        window.close()
    if '--ai-smoke' in sys.argv:
        from engine import InferenceEngine
        from download_model import get_model_path
        engine = InferenceEngine(get_model_path())
        ok, message = engine.load_model()
        if not ok:
            raise RuntimeError(message)
        print('AI model loaded', flush=True)
        result = ''
        last = None
        for last in engine.generate_stream('<start_of_turn>user\n가상 메모: 전화로 안부를 확인함. 다음 주 다시 전화하기로 함. 이 사실만 한국어 한 문장으로 정리하세요.\n<end_of_turn>\n<start_of_turn>model\n', max_tokens=96):
            result += last.get('token', '')
        assert result.strip() and last and last.get('done') and not last.get('aborted')
        print('AI_SMOKE_OK', len(result), 'characters', flush=True)


if __name__ == '__main__':
    main()
