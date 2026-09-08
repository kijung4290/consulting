"""가상 데이터로 작성 복구, 저장 격리, 생성 상태를 검증한다."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from app import (MainWindow, PAGE_CLIENTS, PAGE_DATA, PAGE_DOCS, CLIENT_TAB_LIST,
                 DATA_TAB_FORMS, DOCS_TAB_VAULT)
from database import Database
from engine import InferenceEngine
from workers import GenerationWorker


class CounselingUXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = Database(self.temp.name)
        self.first = db.add_client({'name': '가상 대상자 하나'})
        self.second = db.add_client({'name': '가상 대상자 둘'})
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

    def test_client_and_profile_drafts_survive_restart(self):
        w = self.window
        w.switch_to_ai_counsel_with_client(self.first)
        w.input_text.setPlainText('첫 대상자 상담 메모')
        w.output_text.setHtml('<p><b>첫 초안</b></p>')
        w.session_method_input.setCurrentText('전화')
        w.session_date_input.setDate(QDate(2026, 9, 1))
        w.switch_to_ai_counsel_with_client(self.second)
        self.assertEqual(w.input_text.toPlainText(), '')
        self.assertEqual(w.name_input.text(), '가상 대상자 둘')
        w.input_text.setPlainText('둘째 메모')
        w.switch_to_ai_counsel_with_client(self.first)
        self.assertEqual(w.input_text.toPlainText(), '첫 대상자 상담 메모')
        self.assertEqual(w.session_method_input.currentText(), '전화')
        profile = w.db.create_profile('두 번째 담당자')
        w._activate_profile(profile)
        self.assertEqual(w.input_text.toPlainText(), '')
        w.close()
        self.window = MainWindow()
        self.window.context_controller.stop()
        self.window._activate_profile(1)
        self.window.switch_to_ai_counsel_with_client(self.first)
        self.assertEqual(self.window.input_text.toPlainText(), '첫 대상자 상담 메모')
        self.assertEqual(self.window.session_date_input.date(), QDate(2026, 9, 1))
        self.assertIn('font-weight:700', self.window.output_text.toHtml())

    def test_save_is_idempotent_and_edits_update_original(self):
        w = self.window
        w.switch_to_ai_counsel_with_client(self.first)
        w.input_text.setPlainText('방문 메모')
        w.output_text.setPlainText('밑반찬 지원 가능 여부 확인 예정')
        w.session_method_input.setCurrentText('방문')
        w.save_record_to_database()
        w.save_record_to_database()
        self.assertEqual(len(w.db.list_counseling_records(self.first)), 1)
        self.assertFalse(w.save_to_db_btn.isEnabled())
        w.output_text.setPlainText('9월 10일 전화로 지원 가능 여부 확인')
        w.save_record_to_database()
        records = w.db.list_counseling_records(self.first)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['session_method'], '방문')
        self.assertEqual(records[0]['raw_memo'], '방문 메모')
        self.assertIn('9월 10일', records[0]['ai_result'])
        w.clear_fields()
        w.output_text.setPlainText('다음 상담 기록')
        w.save_record_to_database()
        self.assertEqual(len(w.db.list_counseling_records(self.first)), 2)

    def test_clear_and_switch_preserve_draft_on_cancel_or_disk_error(self):
        w = self.window
        w.switch_to_ai_counsel_with_client(self.first)
        w.input_text.setPlainText('보관할 메모')
        with patch.object(w, 'confirm_replace', return_value=False):
            w.clear_fields()
        self.assertEqual(w.input_text.toPlainText(), '보관할 메모')
        with patch.object(w.db, 'save_counseling_draft', side_effect=OSError('쓰기 실패')):
            w.switch_to_ai_counsel_with_client(self.second)
        self.assertEqual(w.ai_client_combo.currentData(), self.first)
        self.assertEqual(w.input_text.toPlainText(), '보관할 메모')

    def test_busy_state_prevents_partial_save_and_cancel_preserves_partial_text(self):
        w = self.window
        w.output_text.setPlainText('생성 중인 내용')
        w.set_counseling_busy(True)
        self.assertFalse(w.ai_client_combo.isEnabled())
        self.assertTrue(w.output_text.isReadOnly())
        w.save_record_to_database()
        self.assertEqual(w.db.list_counseling_records(), [])
        w._generation_cancelled = True
        w.on_generation_finished(False, '중단')
        self.assertEqual(w.output_text.toPlainText(), '생성 중인 내용')
        self.assertTrue(w.ai_client_combo.isEnabled())

    def test_due_list_filters_and_opens_correct_client(self):
        w = self.window
        today = QDate.currentDate()
        overdue = w.db.add_monitoring_task(self.first, '전화 확인', today.addDays(-1).toString('yyyy-MM-dd'))
        w.db.add_monitoring_task(self.second, '방문', today.addDays(20).toString('yyyy-MM-dd'))
        w.refresh_dashboard()
        self.assertEqual(w.due_table.rowCount(), 1)
        w.due_table.selectRow(0)
        w.open_due_task()
        self.assertEqual(w.case_management_page.client_id, self.first)
        self.assertEqual(w.case_management_page.tabs.currentIndex(), 4)
        w.db.complete_monitoring_task(overdue)
        w.refresh_dashboard()
        self.assertEqual(w.due_table.rowCount(), 0)

    def test_small_window_and_filter_selection(self):
        w = self.window
        w.show()
        w.resize(880, 540)
        self.app.processEvents()
        self.assertEqual(w.width(), 880)
        self.assertEqual(w.writing_splitter.orientation(), Qt.Orientation.Vertical)
        w.clients_table.selectRow(0)
        w.client_search_input.setText('존재하지 않는 이름')
        self.assertEqual(w.clients_table.rowCount(), 0)
        self.assertTrue(all(not b.isEnabled() for b in w.client_selection_actions))
        w.reset_client_filters()
        self.assertEqual(w.clients_table.rowCount(), 2)

    def test_template_edit_survives_navigation_and_save(self):
        w = self.window
        page = w.template_manager_page
        template_id = page.current_template_id
        page.name_input.setText('수정 중인 양식')
        w.switch_page(PAGE_CLIENTS)
        w.switch_page(PAGE_DATA)
        w.data_tabs.setCurrentIndex(DATA_TAB_FORMS)
        self.assertEqual(page.name_input.text(), '수정 중인 양식')
        with patch.object(page, 'may_leave', return_value=False):
            page.template_list.setCurrentRow(1)
        self.assertEqual(page.current_template_id, template_id)
        self.assertTrue(page.save_template())
        self.assertFalse(page.has_unsaved_changes())
        self.assertEqual(w.db.get_form_template(template_id)['name'], '수정 중인 양식')

    def test_stale_editor_cannot_overwrite_external_edit(self):
        w = self.window
        w.output_text.setPlainText('최초 상담')
        w.save_record_to_database()
        w.db.update_counseling_content(w._record_id, w.current_profile['id'], '수정 기록',
                                      '2026-09-08', '담당자', '보관함에서 수정', '<p>보관함에서 수정</p>')
        w.output_text.setPlainText('오래된 창에서 수정')
        with patch.object(QMessageBox, 'warning') as warning:
            w.save_record_to_database()
        warning.assert_called_once()
        self.assertEqual(w.db.list_counseling_records()[0]['ai_result'], '보관함에서 수정')

    def test_deleting_active_client_clears_draft_without_recreating_it(self):
        w = self.window
        w.switch_to_ai_counsel_with_client(self.first)
        w.input_text.setPlainText('삭제할 대상자 메모')
        w.persist_counseling_draft()
        for row in range(w.clients_table.rowCount()):
            if w.clients_table.item(row, 0).data(Qt.ItemDataRole.DisplayRole) == self.first:
                w.clients_table.selectRow(row)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            w.delete_selected_client()
        self.assertIsNone(w.ai_client_combo.currentData())
        self.assertEqual(w.input_text.toPlainText(), '')
        self.assertTrue(w.persist_counseling_draft())
        self.assertEqual(w.db.get_counseling_draft(1, self.first), {})

    def test_general_document_filter_is_preserved(self):
        w = self.window
        w.doc_filter_client.setCurrentIndex(w.doc_filter_client.findData(-1))
        w.switch_page(PAGE_CLIENTS)
        w.client_tabs.setCurrentIndex(CLIENT_TAB_LIST)
        w.switch_page(PAGE_DOCS)
        w.docs_tabs.setCurrentIndex(DOCS_TAB_VAULT)
        self.assertEqual(w.doc_filter_client.currentData(), -1)

    def test_manual_blank_form_and_cancel_do_not_save(self):
        from dialogs import ManualCounselingDialog
        dialog = ManualCounselingDialog(self.window.db, self.first, parent=self.window)
        with patch.object(QMessageBox, 'warning') as warning:
            dialog.save_record()
        warning.assert_called_once()
        dialog.content_text.insertPlainText('실제 면담 내용')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            dialog.reject()
        self.assertIn('실제 면담 내용', dialog.content_text.toPlainText())
        self.assertEqual(self.window.db.list_counseling_records(), [])
        with patch.object(QMessageBox, 'information'):
            dialog.save_record()
        self.assertEqual(len(self.window.db.list_counseling_records()), 1)


class GenerationFailureTests(unittest.TestCase):
    def test_form_preserves_literal_backslashes(self):
        from form_document import fill_form_html
        rendered = fill_form_html('<p>{{상담내용}}</p>', generated_text='[상담내용]\n경로 C:\\new\\1 <확인>')
        self.assertIn('C:\\new\\1', rendered)
        self.assertIn('&lt;확인&gt;', rendered)

    def test_stream_exception_is_reported_as_failure(self):
        def broken(**kwargs):
            yield {'choices': [{'text': '일부 초안'}]}
            raise RuntimeError('추론 실패')
        engine = InferenceEngine('unused')
        engine.llm = lambda *a, **kw: broken(**kw)
        worker = GenerationWorker(engine, 'test')
        outcomes = []
        worker.finished_signal.connect(lambda ok, message: outcomes.append((ok, message)))
        worker.run()
        self.assertEqual(outcomes, [(False, '추론 실패')])


if __name__ == '__main__':
    unittest.main()
