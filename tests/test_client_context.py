import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QPushButton
from database import Database
from client_context import ContextWorker, collect_sources, read_context, source_chunks
from template_manager import TemplateManagerPage
from prompts import TEMPLATES


class FakeEngine:
    n_ctx = 2048
    def __init__(self, callback=None):
        self.llm = self
        self.callback = callback
        self.prompts = []
    def is_loaded(self):
        return True
    def tokenize(self, data):
        return list(data)
    def detokenize(self, tokens):
        return bytes(tokens)
    def generate_stream(self, prompt, max_tokens):
        self.prompts.append(prompt)
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        yield {'token': '현재 상황: 기록 확인 [기본정보 #1]'}


class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name)
        self.a = self.db.add_client({'name': '가', 'memo': '주거 어려움'})
        self.b = self.db.add_client({'name': '나', 'memo': '다른 대상자'})

    def tearDown(self):
        self.temp.cleanup()

    def run_context(self, engine=None):
        revision = read_context(self.db, self.a)['revision']
        ContextWorker(self.db, engine or FakeEngine(), self.a, revision).run()

    def test_changes_and_deletion_invalidate_only_affected_client(self):
        self.run_context()
        previous = read_context(self.db, self.a)
        doc = self.db.add_text_document(self.a, '초기상담', '상담', '지원 필요')
        self.assertGreater(read_context(self.db, self.a)['revision'], previous['revision'])
        self.assertEqual(read_context(self.db, self.b)['revision'], 1)
        self.assertIn('지원 필요', str(collect_sources(self.db, self.a)))
        self.assertNotIn('다른 대상자', str(collect_sources(self.db, self.a)))
        self.run_context()
        self.db.delete_document(doc)
        context = read_context(self.db, self.a)
        self.assertNotEqual(context['revision'], context['processed_revision'])
        self.assertNotIn('지원 필요', str(collect_sources(self.db, self.a)))
        self.db.delete_client(self.a)
        self.assertEqual(read_context(self.db, self.a), {})

    def test_concurrent_change_does_not_publish_stale_summary(self):
        engine = FakeEngine(lambda: self.db.add_text_document(self.a, '추가', '상담', '새 내용'))
        self.run_context(engine)
        self.assertEqual(read_context(self.db, self.a)['processed_revision'], 0)
        self.run_context()
        context = read_context(self.db, self.a)
        self.assertEqual(context['revision'], context['processed_revision'])
        self.assertIn('첨부서류', context['sources'])

    def test_restart_preserves_summary_and_pending_work(self):
        self.run_context()
        old = read_context(self.db, self.a)
        restored = Database(self.temp.name)
        self.assertEqual(read_context(restored, self.a), old)

    def test_generated_draft_does_not_replace_original_evidence(self):
        self.db.add_counseling_record({'client_id': self.a, 'session_date': '2026-09-07',
            'template_name': '상담', 'raw_memo': '밑반찬 지원 시작',
            'ai_result': '근거 없는 시각 10:00'})
        sources = str(collect_sources(self.db, self.a))
        self.assertIn('밑반찬 지원 시작', sources)
        self.assertNotIn('10:00', sources)

    def test_registry_includes_forms_counseling_and_attachments_without_duplicates(self):
        owner = self.db.get_current_profile()['id']
        form_data = {'source_key': '초기상담지', 'stage': '접수', 'record_date': '2026-09-01',
                     'status': '작성중', 'template_snapshot': {}, 'fields': {'상담 내용': '식사 어려움'},
                     'result_html': '<p>식사 어려움</p>'}
        form_id = self.db.save_case_form(self.a, owner, form_data)
        doc_id = self.db.add_text_document(self.a, '첨부검증', '메모', '지원 필요')
        self.db.add_counseling_record({'client_id': self.a, 'session_date': '2026-09-01',
                                     'template_name': '상담일지', 'ai_result': '상담 내용'})
        self.assertEqual(len(self.db.list_document_registry(self.a)), 3)
        self.assertEqual(self.db.get_dashboard_stats()['total_docs'], 3)
        self.assertEqual(len(self.db.list_document_registry(self.a, '사례관리 서류')), 1)
        self.assertEqual(len(self.db.list_document_registry(self.a, keyword='초기상담지')), 1)
        self.assertEqual(self.db.list_document_registry(self.b), [])
        self.db.save_case_form(self.a, owner, {**form_data, 'status': '작성완료'}, form_id)
        self.assertEqual(len(self.db.list_document_registry(self.a)), 3)
        self.assertEqual(self.db.list_document_registry(self.a, '사례관리 서류')[0]['status'], '작성완료')
        self.db.delete_document(doc_id)
        self.assertEqual(len(self.db.list_case_forms(self.a)), 1)
        self.assertEqual(self.db.get_dashboard_stats()['total_docs'], 2)

    def test_chunks_preserve_long_sources_and_combine_short_records(self):
        chunks = list(source_chunks([('A #1', 'a' * 1600), ('B #2', 'bbb')], FakeEngine(), 500))
        self.assertEqual(''.join(chunks).count('a'), 1600)
        self.assertIn('[B #2]', chunks[-1])
        self.assertTrue(all(len(chunk.encode()) <= 500 for chunk in chunks))
        short = list(source_chunks([('A #1', 'one'), ('B #2', 'two')], FakeEngine(), 500))
        self.assertEqual(len(short), 1)

    def test_designer_focus_and_tools(self):
        owner = self.db.get_current_profile()['id']
        self.db.ensure_builtin_templates(owner, TEMPLATES)
        page = TemplateManagerPage(self.db, owner)
        page.resize(1000, 700)
        page.show()
        self.app.processEvents()
        buttons = {b.text(): b for b in page.findChildren(QPushButton)}
        editor = page.form_editor
        editor.insertPlainText('전체화면 전 편집')
        buttons['전체화면 편집'].click()
        self.app.processEvents()
        self.assertTrue(page.fullscreen_dialog.isFullScreen())
        self.assertEqual(page.editor_tabs.indexOf(page.design_tab), -1)
        self.assertGreater(page.form_editor.width(), page.fullscreen_dialog.width() * 0.8)
        buttons['도구 펼치기'].click()
        self.app.processEvents()
        self.assertTrue(page.element_palette.isVisible())
        editor.insertPlainText(' 전체화면에서 추가')
        page.fullscreen_dialog.reject()  # QDialog의 Esc 종료 경로
        self.app.processEvents()
        self.assertIsNone(page.fullscreen_dialog)
        self.assertIs(page.form_editor, editor)
        self.assertIs(page.editor_tabs.currentWidget(), page.design_tab)
        self.assertIn('전체화면에서 추가', editor.toPlainText())
        self.assertTrue(editor.document().isUndoAvailable())
        page.toggle_fullscreen_editor()
        self.app.processEvents()
        page.fullscreen_dialog.accept()
        self.app.processEvents()
        self.assertIsNone(page.fullscreen_dialog)
        page.close()
