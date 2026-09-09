"""업무 메뉴 4화면과 화면 안 탭의 이동 경로를 검증한다."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication
from app import (MainWindow, NAV_MENUS, PAGE_CLIENTS, PAGE_CASE, PAGE_DOCS, PAGE_DATA,
                 CLIENT_TAB_LIST, CLIENT_TAB_DUE, CLIENT_TAB_RECENT,
                 DOCS_TAB_WRITE, DOCS_TAB_CASE_FORMS, DOCS_TAB_VAULT,
                 DATA_TAB_FORMS, DATA_TAB_BACKUP,
                 CASE_TAB_MONITORING)
from database import Database


class FakeContextController:
    """맥락 갱신이 돌고 있는 상황을 모델 없이 재현한다."""

    def __init__(self, client_id):
        self.client_id = client_id

    def busy(self):
        return True

    def current_client_id(self):
        return self.client_id

    def progress_text(self):
        return 'AI가 기록 읽는 중 · 자료 2/5 · 3초 경과'

    def progress_values(self):
        return 2, 5

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


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = Database(self.temp.name)
        self.client = db.add_client({'name': '가상 대상자', 'masked_name': '가OO', 'risk_level': '고위기'})
        db.add_monitoring_task(self.client, '전화 확인',
                               QDate.currentDate().toString('yyyy-MM-dd'), '지원 희망 확인')
        self.patches = [patch('config.is_first_run', return_value=False),
                        patch('config.get_data_dir', return_value=self.temp.name),
                        patch('app.is_model_downloaded', return_value=False)]
        for item in self.patches:
            item.start()
        self.window = MainWindow()
        self.window.context_controller.stop()

    def tearDown(self):
        self.window.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_work_menu_has_four_screens(self):
        w = self.window
        self.assertEqual([text for text, _ in NAV_MENUS],
                         ['대상자 관리', '사례관리', '서류작성 및 보관함', '데이터 관리'])
        self.assertEqual([button.text() for button in w.nav_btns], [text for text, _ in NAV_MENUS])
        self.assertEqual(w.stacked_widget.count(), len(NAV_MENUS))
        self.assertEqual([w.client_tabs.tabText(i) for i in range(w.client_tabs.count())],
                         ['대상자 목록', '확인할 일정', '최근 상담', '최근 서류'])
        self.assertEqual([w.docs_tabs.tabText(i) for i in range(w.docs_tabs.count())],
                         ['상담일지 작성', '사례관리 서류 작성', '서류 보관함'])
        self.assertEqual([w.data_tabs.tabText(i) for i in range(w.data_tabs.count())],
                         ['서류 양식', '데이터 백업·복원'])

    def test_kpi_cards_and_quick_actions_reach_their_screen(self):
        w = self.window
        w.open_client_tab(CLIENT_TAB_RECENT)
        self.assertEqual(w.stacked_widget.currentIndex(), PAGE_CLIENTS)
        self.assertEqual(w.client_tabs.currentIndex(), CLIENT_TAB_RECENT)

        w.nav_to_high_risk_clients()
        self.assertEqual(w.client_tabs.currentIndex(), CLIENT_TAB_LIST)
        self.assertEqual(w.filter_risk.currentText(), '고위기')
        w.reset_client_filters()

        w.case_due_btn.click()
        self.assertEqual(w.client_tabs.currentIndex(), CLIENT_TAB_DUE)

        w.open_document_vault()
        self.assertEqual((w.stacked_widget.currentIndex(), w.docs_tabs.currentIndex()),
                         (PAGE_DOCS, DOCS_TAB_VAULT))

        w.open_form_designer()
        self.assertEqual((w.stacked_widget.currentIndex(), w.data_tabs.currentIndex()),
                         (PAGE_DATA, DATA_TAB_FORMS))

    def test_counseling_shortcuts_only_apply_on_the_writing_tab(self):
        w = self.window
        w.open_counseling_writer()
        self.assertEqual(w.docs_tabs.currentIndex(), DOCS_TAB_WRITE)
        self.assertTrue(w.on_counseling_tab())
        w.open_document_vault()
        self.assertFalse(w.on_counseling_tab())
        w.switch_page(PAGE_CLIENTS)
        self.assertFalse(w.on_counseling_tab())
        w.switch_to_ai_counsel_with_client(self.client)
        self.assertTrue(w.on_counseling_tab())
        self.assertEqual(w.ai_client_combo.currentData(), self.client)

    def test_case_document_status_leads_to_the_same_client_writing_workspace(self):
        w = self.window
        w.switch_page(PAGE_CASE)
        w.case_management_page.select_client(self.client)
        w.case_management_page.documents_panel._open_workspace()
        self.assertEqual((w.stacked_widget.currentIndex(), w.docs_tabs.currentIndex()),
                         (PAGE_DOCS, DOCS_TAB_CASE_FORMS))
        self.assertEqual(w.case_forms_panel.client_id, self.client)
        self.assertEqual(w.case_forms_panel.client_combo.currentData(), self.client)

    def test_due_task_opens_the_case_monitoring_tab(self):
        w = self.window
        w.open_client_tab(CLIENT_TAB_DUE)
        w.refresh_dashboard()
        self.assertEqual(w.due_table.rowCount(), 1)
        w.due_table.selectRow(0)
        w.open_due_task()
        self.assertEqual(w.stacked_widget.currentIndex(), PAGE_CASE)
        self.assertEqual(w.case_management_page.client_id, self.client)
        self.assertEqual(w.case_management_page.tabs.currentIndex(), CASE_TAB_MONITORING)

    def test_form_screen_shows_a_short_storage_label(self):
        w = self.window
        w.open_form_designer()
        label = w.template_manager_page.storage_label
        # 긴 절대 경로가 화면 최소 너비를 늘리지 않도록 파일명만 표시하고 경로는 도구 설명에 둔다.
        self.assertNotIn(w.db.db_path, label.text())
        self.assertIn(os.path.basename(w.db.db_path), label.text())
        self.assertEqual(label.toolTip(), w.db.db_path)
        w.data_tabs.setCurrentIndex(DATA_TAB_BACKUP)
        self.assertEqual(w.db_dir_label.text(), w.db.data_dir)

    def test_activity_panel_reports_nothing_running_when_idle(self):
        w = self.window
        self.assertIsNone(w.current_ai_activity())
        w.refresh_activity_indicator()
        # 모델이 없는 검증 환경에서는 그 사실을 먼저 알려 준다.
        self.assertIn('AI 모델 없음', w.activity_title.text())
        self.assertIn('모델 없음', w.status_activity_label.text())
        self.assertTrue(w.activity_bar.isHidden())

    def test_activity_panel_names_the_client_being_summarised(self):
        w = self.window
        w.context_controller = FakeContextController(self.client)
        activity = w.current_ai_activity()
        self.assertIsNotNone(activity)
        title, detail, progress = activity
        self.assertIn('가상 대상자', title)
        self.assertIn('맥락 갱신 중', title)
        self.assertIn('AI가 기록 읽는 중', detail)
        self.assertEqual(progress, (2, 5))
        w.refresh_activity_indicator()
        self.assertTrue(w.activity_title.text().startswith('●'))
        self.assertFalse(w.activity_bar.isHidden())
        self.assertEqual((w.activity_bar.value(), w.activity_bar.maximum()), (2, 5))

    def test_context_tab_shows_progress_and_blocks_repeated_requests(self):
        w = self.window
        page = w.case_management_page
        page.select_client(self.client)
        w.context_controller = FakeContextController(self.client)
        page.refresh_context()
        self.assertIn('이 대상자 갱신 중', page.context_status.text())
        self.assertIn('자료 2/5', page.context_status.text())
        self.assertFalse(page.context_progress.isHidden())
        self.assertEqual((page.context_progress.value(), page.context_progress.maximum()), (2, 5))
        self.assertFalse(page.context_retry_btn.isEnabled())
        self.assertEqual(page.context_retry_btn.text(), '갱신 중…')

    def test_context_tab_explains_why_nothing_is_running(self):
        w = self.window
        page = w.case_management_page
        page.select_client(self.client)
        # 모델이 없으면 자동 갱신이 시작되지 않는다는 사실을 밝힌다.
        page.refresh_context()
        self.assertIn('로컬 AI 모델이 없어', page.context_status.text())
        self.assertTrue(page.context_progress.isHidden())
        self.assertTrue(page.context_retry_btn.isEnabled())

    def test_context_tab_survives_unreadable_storage(self):
        w = self.window
        page = w.case_management_page
        page.select_client(self.client)
        with patch('case_management.read_context', side_effect=OSError('저장 위치 없음')):
            page.refresh_context()
        self.assertIn('기록을 읽지 못했습니다', page.context_status.text())
        self.assertTrue(page.context_retry_btn.isEnabled())

    def test_generation_phase_line_appears_only_while_it_matters(self):
        w = self.window
        w.open_counseling_writer()
        self.assertTrue(w.generation_status.isHidden())
        w.set_generation_phase('AI 모델을 메모리에 불러오는 중입니다.')
        self.assertFalse(w.generation_status.isHidden())
        w.set_generation_phase()
        self.assertTrue(w.generation_status.isHidden())

    def test_writing_screen_reports_each_generation_step(self):
        w = self.window
        w.open_counseling_writer()
        w.set_counseling_busy(True)
        # 생성 중에는 버튼 문구부터 진행 중임을 알린다.
        self.assertEqual(w.generate_btn.text(), 'AI가 작성 중…')
        self.assertFalse(w.progress_bar.isHidden())
        w.set_generation_phase('AI가 초안을 작성하는 중입니다.')
        w.on_metrics_updated(12.5, 40)
        self.assertIn('40토큰', w.generation_status.text())
        self.assertIn('초당 12.5토큰', w.generation_status.text())
        w._generation_cancelled = True
        w.on_generation_finished(False, '중단')
        self.assertEqual(w.generate_btn.text(), 'AI로 초안 정리')
        self.assertIn('중단', w.generation_status.text())
        self.assertIsNone(w.ai_started_at)
        # 새 상담을 시작하면 지난 안내를 남기지 않는다.
        w.clear_fields()
        self.assertTrue(w.generation_status.isHidden())

    def test_closing_the_window_stops_periodic_refresh(self):
        w = self.window
        self.assertTrue(w.activity_timer.isActive())
        self.assertTrue(w.case_management_page.context_timer.isActive())
        w.close()
        # 창을 닫은 뒤 남은 타이머가 사라진 저장 위치를 읽으면 프로그램이 죽는다.
        self.assertFalse(w.activity_timer.isActive())
        self.assertFalse(w.case_management_page.context_timer.isActive())

    def test_switching_every_menu_refreshes_without_error(self):
        w = self.window
        w.refresh_all_data()
        for _, index in NAV_MENUS:
            w.switch_page(index)
            self.app.processEvents()
            self.assertEqual(w.stacked_widget.currentIndex(), index)
            self.assertTrue(w.nav_btns[index].isChecked())


if __name__ == '__main__':
    unittest.main()
