import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from case_form_templates import CASE_FORM_TEMPLATES
from database import Database
from form_document import PLACEHOLDER_PATTERN, extract_guide_fields, fill_form_html
from prompts import TEMPLATES, RETIRED_TEMPLATE_KEYS, build_prompt


class CaseFormTemplateTests(unittest.TestCase):
    def test_every_cell_has_an_ai_field_and_can_be_filled(self):
        self.assertEqual(len(CASE_FORM_TEMPLATES), 14)
        for name, template in CASE_FORM_TEMPLATES.items():
            with self.subTest(name=name):
                fields = PLACEHOLDER_PATTERN.findall(template['form_html'])
                _, guide_fields = extract_guide_fields(template['guide'])
                self.assertEqual(fields, guide_fields)
                self.assertEqual(len(fields), len(set(fields)))
                generated = '\n'.join(f'{i}. **{field}**: 검증내용{i}' for i, field in enumerate(fields, 1))
                result = fill_form_html(template['form_html'], generated_text=generated)
                self.assertNotIn('{{', result)
                for i in range(1, len(fields) + 1):
                    self.assertIn(f'>검증내용{i}</td>', result)

    def test_upgrade_preserves_personal_edits_and_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(directory)
            owner = db.get_current_profile()['id']
            previous = {name: {'guide': '이전 양식 지침'} for name in RETIRED_TEMPLATE_KEYS}
            db.ensure_builtin_templates(owner, previous)
            retired_id = db.list_form_templates(owner)[0]['id']
            personal_id = db.save_form_template(owner, {'name': '직접 만든 양식', 'guide': '지침'})
            personal = db.get_form_template(personal_id, owner)
            personal['guide'] = '사용자가 수정한 지침'
            db.save_form_template(owner, personal, personal['id'])
            self.assertEqual(db.ensure_builtin_templates(owner, TEMPLATES), 14)
            self.assertEqual(db.ensure_builtin_templates(owner, TEMPLATES), 0)
            self.assertEqual(db.get_form_template(personal['id'], owner)['guide'], personal['guide'])
            self.assertIsNone(db.get_form_template(retired_id, owner))
            with db.get_connection() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM retired_form_templates').fetchone()[0], 13)
            for saved in db.list_form_templates(owner):
                if saved['source_key'] in CASE_FORM_TEMPLATES:
                    self.assertEqual(saved['form_html'], CASE_FORM_TEMPLATES[saved['source_key']]['form_html'])
                    self.assertTrue(db.reset_form_template(saved['id'], owner, TEMPLATES))

    def test_only_case_forms_are_available_and_unknown_names_have_a_default(self):
        self.assertEqual(set(TEMPLATES), set(CASE_FORM_TEMPLATES))
        self.assertIn('상담일지 (사례관리양식)', build_prompt('삭제된 양식', '상담 메모'))

    def test_consent_signatures_are_manual_and_example_facts_are_absent(self):
        consent = CASE_FORM_TEMPLATES['개인정보 수집·이용, 제공 동의서']['form_html']
        self.assertEqual(PLACEHOLDER_PATTERN.findall(consent), ['대상자명'])
        self.assertIn('법정대리인', consent)
        self.assertIn('□ 동의함  □ 동의하지 않음', consent)
        for template in CASE_FORM_TEMPLATES.values():
            for example in ('2024년 11월 14일', '박기정', '평균 5점', '푸른자연유치원'):
                self.assertNotIn(example, template['form_html'])

    def test_missing_guardian_field_does_not_reuse_client_information(self):
        template = CASE_FORM_TEMPLATES['이용신청서']
        result = fill_form_html(template['form_html'], generated_text='1. **성별**: 여')
        self.assertEqual(result.count('>여</td>'), 1)
        self.assertIn('>보호자 성별</th><td></td>', result)


if __name__ == '__main__':
    unittest.main()
