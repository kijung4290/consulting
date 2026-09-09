import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from database import Database
from prompts import TEMPLATES
from case_forms import CaseFormDialog, STAGE_FORMS
from case_management import CaseManagementPage


class CaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name)
        self.owner = self.db.get_current_profile()['id']
        self.db.ensure_builtin_templates(self.owner, TEMPLATES)
        self.first = self.db.add_client({'name': '첫 대상자'})
        self.second = self.db.add_client({'name': '둘째 대상자'})
        self.template = next(t for t in self.db.list_form_templates(self.owner) if t['source_key'] == '초기상담지')

    def tearDown(self):
        self.temp.cleanup()

    def test_stages_cover_all_fourteen_forms(self):
        self.assertEqual(set().union(*map(set, STAGE_FORMS.values())), set(TEMPLATES))

    def test_save_resume_snapshot_and_client_owner_isolation(self):
        dialog = CaseFormDialog(self.db, self.first, self.owner, '접수', self.template)
        dialog.inputs['상담 내용'].setPlainText('첫 상담 내용 <확인> \\1')
        self.assertTrue(dialog.save('작성중'))
        row = self.db.list_case_forms(self.first)[0]
        self.assertEqual(self.db.list_case_forms(self.second), [])
        self.assertIn('&lt;확인&gt;', row['result_html'])
        self.template['form_html'] = '<p>바뀐 양식</p>'
        resumed = CaseFormDialog(self.db, self.first, self.owner, '계획', self.template, row)
        self.assertEqual(resumed.inputs['상담 내용'].toPlainText(), '첫 상담 내용 <확인> \\1')
        self.assertTrue(resumed.save('작성완료'))
        self.assertEqual(len(self.db.list_case_forms(self.first)), 1)
        other = self.db.create_profile('다른 작성자')
        data = {'source_key': row['source_key'], 'stage': row['stage'], 'record_date': row['record_date'],
                'status': '작성중', 'template_snapshot': json.loads(row['template_snapshot']), 'fields': {}, 'result_html': ''}
        with self.assertRaises(ValueError):
            self.db.save_case_form(self.second, self.owner, data, row['id'])
        with self.assertRaises(ValueError):
            self.db.save_case_form(self.first, other, data, row['id'])
        dialog.close()
        resumed.close()

    def test_switching_client_separates_unsaved_inputs(self):
        page = CaseManagementPage(self.db)
        page.select_client(self.first)
        page.assessment_inputs['경제'].setCurrentIndex(3)
        page.goal_title.setText('첫 대상자의 목표')
        page.select_client(self.second)
        self.assertEqual(page.assessment_inputs['경제'].currentIndex(), 0)
        self.assertEqual(page.goal_title.text(), '')
        page.select_client(self.first)
        self.assertEqual(page.goal_title.text(), '첫 대상자의 목표')
        self.assertEqual(page.assessment_inputs['경제'].currentIndex(), 3)
        page.stage_combo.setCurrentText('사후관리')
        page._save_stage()
        self.assertEqual(page.documents_panel.table.rowCount(), 0)
        self.assertIn('전체 0건', page.documents_panel.summary.text())
        page.close()

    def test_case_page_reads_each_clients_documents_without_writing_controls(self):
        dialog = CaseFormDialog(self.db, self.first, self.owner, '접수', self.template)
        dialog.inputs['상담 내용'].setPlainText('초기 상담에서 확인한 내용')
        self.assertTrue(dialog.save('작성완료'))
        self.db.add_text_document(self.first, '소득 확인 메모', '기타 증빙서류/메모', '확인 내용')
        self.db.add_text_document(self.second, '다른 대상자 서류', '기타 증빙서류/메모', '분리 내용')

        page = CaseManagementPage(self.db)
        page.select_client(self.first)
        self.assertEqual(page.tabs.tabText(0), '대상자 맥락')
        self.assertEqual(page.tabs.tabText(1), '작성 서류 현황')
        self.assertEqual(page.documents_panel.table.rowCount(), 2)
        titles = {page.documents_panel.table.item(row, 2).text()
                  for row in range(page.documents_panel.table.rowCount())}
        self.assertEqual(titles, {'초기상담지', '소득 확인 메모'})
        self.assertNotIn('다른 대상자 서류', titles)
        page.documents_panel.table.selectRow(next(
            row for row in range(page.documents_panel.table.rowCount())
            if page.documents_panel.table.item(row, 2).text() == '초기상담지'))
        self.assertIn('초기 상담에서 확인한 내용', page.documents_panel.detail.toPlainText())
        self.assertTrue(page.documents_panel.detail.isReadOnly())
        page.close()
        dialog.close()


if __name__ == '__main__':
    unittest.main()
