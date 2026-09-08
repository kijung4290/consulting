import json
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QPushButton
from database import Database
from client_context import (ContextController, ContextWorker, collect_source_index,
                            collect_sources, read_context, source_chunks, source_key)
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


class FakeWindow(QObject):
    """맥락 관리자가 들여다보는 메인 창의 최소한만 흉내 낸다."""

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.engine = FakeEngine()
        self.worker = None
        self.model_load_worker = None

    def model_ready(self):
        return True


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

    def test_worker_reports_progress_so_the_screen_can_show_it(self):
        revision = read_context(self.db, self.a)['revision']
        worker = ContextWorker(self.db, FakeEngine(), self.a, revision)
        # 시작 전에도 화면에 보여줄 문구가 있어야 한다.
        self.assertIn('시작 준비 중', worker.progress_text())
        self.assertIn('초 경과', worker.progress_text())
        worker.run()
        self.assertGreaterEqual(worker.chunk_total, 1)
        self.assertEqual(worker.chunk_index, worker.chunk_total)
        self.assertGreater(worker.written_chars, 0)
        text = worker.progress_text()
        self.assertIn(f'자료 {worker.chunk_total}/{worker.chunk_total}', text)
        self.assertIn('자 작성', text)

    def test_chunks_preserve_long_sources_and_combine_short_records(self):
        chunks = list(source_chunks([('A #1', 'a' * 1600), ('B #2', 'bbb')], FakeEngine(), 500))
        self.assertEqual(''.join(chunks).count('a'), 1600)
        self.assertIn('[B #2]', chunks[-1])
        self.assertTrue(all(len(chunk.encode()) <= 500 for chunk in chunks))
        short = list(source_chunks([('A #1', 'one'), ('B #2', 'two')], FakeEngine(), 500))
        self.assertEqual(len(short), 1)

    def test_new_document_adds_to_the_summary_without_rereading_everything(self):
        self.db.add_text_document(self.a, '초기상담', '상담', '이미 반영한 자료')
        self.run_context()
        first = read_context(self.db, self.a)
        engine = FakeEngine()
        self.db.add_text_document(self.a, '추가서류', '상담', '새로 올린 자료')
        self.run_context(engine)
        fed = '\n'.join(engine.prompts)
        self.assertIn('새로 올린 자료', fed)
        # 이미 반영한 자료와 기본정보는 다시 읽지 않고 기존 요약을 이어서 쓴다.
        self.assertNotIn('이미 반영한 자료', fed)
        self.assertNotIn('주거 어려움', fed)
        self.assertIn(first['summary'], fed)
        sources = read_context(self.db, self.a)['sources']
        self.assertIn('첨부서류', sources)
        self.assertEqual(len(sources.splitlines()), len(collect_sources(self.db, self.a)))

    def test_manual_selection_reads_only_the_chosen_material(self):
        chosen = self.db.add_text_document(self.a, '고른 서류', '상담', '고른 자료 내용')
        self.db.add_text_document(self.a, '뺀 서류', '상담', '뺀 자료 내용')
        self.run_context()
        with self.db.get_connection() as conn:
            conn.execute("UPDATE client_context SET revision=revision+1, error='', "
                         "mode='selected', selection=? WHERE client_id=?",
                         (json.dumps([f'첨부서류 #{chosen}']), self.a))
        engine = FakeEngine()
        self.run_context(engine)
        fed = '\n'.join(engine.prompts)
        self.assertIn('고른 자료 내용', fed)
        self.assertNotIn('뺀 자료 내용', fed)
        self.assertNotIn('주거 어려움', fed)
        context = read_context(self.db, self.a)
        self.assertEqual(context['sources'].strip(), f'첨부서류 #{chosen}')
        # 한 번 고른 목록은 그 회차에만 쓰고, 다음부터는 다시 평소 방식으로 돌아간다.
        self.assertEqual(context['mode'], '')
        self.assertEqual(context['revision'], context['processed_revision'])

    def test_source_index_lists_exactly_what_the_ai_reads(self):
        self.db.add_text_document(self.a, '첨부검증', '메모', '지원 필요')
        index = collect_source_index(self.db, self.a)
        self.assertEqual([entry['key'] for entry in index],
                         [source_key(reference) for reference, _ in collect_sources(self.db, self.a)])
        self.assertIn('첨부검증', ' '.join(entry['detail'] for entry in index))

    def test_backlog_from_before_startup_waits_for_the_user(self):
        self.db.add_text_document(self.a, '켜기 전 서류', '상담', '밀린 자료')
        window = FakeWindow(self.db)
        controller = ContextController(window)
        controller.timer.stop()
        try:
            self.assertEqual(controller.pending_client_ids(), [])
            self.assertIn(self.a, controller.deferred_client_ids())
            controller.tick()
            self.assertFalse(controller.busy())
            # 프로그램을 켠 뒤에 저장한 기록은 예전처럼 자동으로 갱신된다.
            self.db.add_text_document(self.a, '켠 뒤 서류', '상담', '새 자료')
            self.assertIn(self.a, controller.pending_client_ids())
            self.assertEqual(controller.deferred_client_ids(), [self.b])
        finally:
            controller.stop()

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
