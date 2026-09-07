import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QLabel
from database import Database
from client_context import read_context, collect_sources
from document_editor import DocumentEditDialog


class DocumentEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name)
        self.owner = self.db.get_current_profile()['id']
        self.cid = self.db.add_client({'name': '수정삭제테스트'})
        self.doc = self.db.add_text_document(self.cid, '첨부', '메모', '이전 본문')
        self.counsel = self.db.add_counseling_record({'client_id': self.cid, 'owner_id': self.owner,
            'session_date': '2026-09-01', 'template_name': '상담', 'ai_result': '이전 상담'})
        self.form = self.db.save_case_form(self.cid, self.owner, {'source_key': '초기상담지',
            'stage': '접수', 'record_date': '2026-09-01', 'status': '작성완료',
            'fields': {'상담 내용': '기존'}, 'template_snapshot': {}, 'result_html': '<p>기존</p>'})

    def tearDown(self):
        self.temp.cleanup()

    def entry(self, kind):
        return next(r for r in self.db.list_document_registry(self.cid) if r['source_type'] == kind)

    def test_text_dialog_updates_existing_record_and_context(self):
        before = read_context(self.db, self.cid)['revision']
        dialog = DocumentEditDialog(self.db, self.entry('attachment'), self.owner)
        dialog.title.setText('수정된 제목')
        dialog.content.setPlainText('새 본문: 식사 지원 완료')
        dialog.save()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        docs = self.db.list_documents(self.cid)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['id'], self.doc)
        self.assertEqual(docs[0]['title'], '수정된 제목')
        self.assertIn('식사 지원 완료', Path(docs[0]['full_path']).read_text(encoding='utf-8'))
        self.assertGreater(read_context(self.db, self.cid)['revision'], before)
        self.assertIn('식사 지원 완료', str(collect_sources(self.db, self.cid)))

    def test_counsel_dialog_preserves_html_and_updates_same_record(self):
        dialog = DocumentEditDialog(self.db, self.entry('counseling'), self.owner)
        dialog.content.setHtml('<table><tr><td>수정된 상담</td></tr></table>')
        dialog.save()
        rows = self.db.list_counseling_records(self.cid)
        self.assertEqual(len(rows), 1)
        self.assertIn('<table', rows[0]['result_html'])
        self.assertIn('수정된 상담', rows[0]['raw_memo'])
        self.assertEqual(rows[0]['detail_level'], '직접수기작성')

    def test_failed_replacement_and_cancel_preserve_original(self):
        before = self.db.list_documents(self.cid)[0]
        with self.assertRaises(OSError):
            self.db.update_attachment(self.doc, '실패', '메모', replacement=str(Path(self.temp.name) / 'missing.pdf'))
        self.assertEqual(self.db.list_documents(self.cid)[0], before)
        dialog = DocumentEditDialog(self.db, self.entry('attachment'), self.owner)
        dialog.content.setPlainText('저장하지 않음')
        dialog.reject()
        self.assertIn('이전 본문', Path(before['full_path']).read_text(encoding='utf-8'))

    def test_file_replacement_uses_new_file_without_duplicate_record(self):
        fixture = Path(__file__).parent / 'fixtures/demo_attachment.txt'
        self.db.update_attachment(self.doc, '교체', '첨부', replacement=str(fixture))
        docs = self.db.list_documents(self.cid)
        self.assertEqual(len(docs), 1)
        self.assertEqual(Path(docs[0]['full_path']).read_bytes(), fixture.read_bytes())

    def test_owner_and_source_isolation_for_delete(self):
        other = self.db.create_profile('다른 작성자')
        for kind, record_id in [('case_form', self.form), ('counseling', self.counsel)]:
            with self.assertRaises(ValueError):
                self.db.delete_registered_document(kind, record_id, other)
        with self.assertRaises(ValueError):
            self.db.update_counseling_content(self.counsel, other, '상담', '2026-09-01', '작성자', '내용', '<p>내용</p>')
        before = read_context(self.db, self.cid)['revision']
        self.db.delete_registered_document('case_form', self.form, self.owner)
        self.assertEqual(len(self.db.list_documents(self.cid)), 1)
        self.assertEqual(len(self.db.list_counseling_records(self.cid)), 1)
        self.db.delete_registered_document('counseling', self.counsel, self.owner)
        self.assertEqual(len(self.db.list_documents(self.cid)), 1)
        self.db.delete_registered_document('attachment', self.doc, self.owner)
        self.assertEqual(self.db.list_document_registry(self.cid), [])
        self.assertGreater(read_context(self.db, self.cid)['revision'], before)
        self.assertEqual(self.db.get_dashboard_stats()['total_docs'], 0)

    def test_archive_delete_routes_by_source_and_refreshes_dashboard(self):
        from app import MainWindow
        with patch('app.config.get_data_dir', return_value=self.temp.name), patch('app.config.is_first_run', return_value=False), patch('app.is_model_downloaded', return_value=False):
            window = MainWindow()
        window.context_controller.stop()
        try:
            for row in range(window.docs_table.rowCount()):
                if window.docs_table.item(row, 0).data(Qt.ItemDataRole.UserRole)['source_type'] == 'case_form':
                    window.docs_table.selectRow(row)
                    break
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
                window.delete_selected_document()
            self.assertEqual(len(self.db.list_case_forms(self.cid)), 1)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                window.delete_selected_document()
            self.assertEqual(self.db.list_case_forms(self.cid), [])
            self.assertEqual(window.docs_table.rowCount(), 2)
            self.assertEqual(window.kpi_docs.findChild(QLabel, 'kpiValue').text(), '2건')
            self.assertEqual(len(self.db.list_documents(self.cid)), 1)
        finally:
            window.close()
