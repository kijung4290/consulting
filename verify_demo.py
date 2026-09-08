"""명시적으로 실행하는 가상 대상자 1명 기능 검증. 기존 대상자는 수정하지 않는다."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.stdout.reconfigure(encoding='utf-8')
from PyQt6.QtWidgets import QApplication, QMessageBox, QLabel, QDialog
from PyQt6.QtCore import Qt, QObject, QEventLoop
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtPrintSupport import QPrinter
from config import get_data_dir
from database import Database
from client_context import collect_sources
from prompts import TEMPLATES, build_prompt
from case_forms import CaseFormDialog, STAGE_FORMS
from client_context import ContextController, read_context
from engine import InferenceEngine
from download_model import get_model_path

NAME = '가상대상자_김테스트'
MARKER = 'DEMO-CONTEXT-20260907: 기능 검증용 가상 자료. 실제 인물 아님.'


def initial(db, owner, cid):
    if db.list_case_forms(cid):
        return
    template = next(t for t in db.list_form_templates(owner) if t['source_key'] == '초기상담지')
    dialog = CaseFormDialog(db, cid, owner, '접수', template)
    dialog.inputs['상담 내용'].setPlainText('2026-09-01 초기상담. 혼자 살며 식사 준비가 어려워 하루 한 끼만 먹는다고 함. 주 2회 밑반찬 지원 희망. 아직 지원 시작 전. 가상 사례.')
    assert dialog.save('작성중')
    assert dialog.save('작성완료')
    dialog.close()
    db.add_counseling_record({'client_id': cid, 'session_date': '2026-09-01',
        'template_name': template['name'], 'detail_level': '직접수기작성',
        'raw_memo': '혼자 생활. 하루 한 끼 식사. 밑반찬 지원 희망.',
        'ai_result': '가상 초기상담: 식사 준비 어려움 확인. 밑반찬 지원 가능 여부를 확인하기로 함.',
        'worker_name': '테스트담당자'})
    print('INITIAL_SAVED', cid, flush=True)


def followup(db, cid):
    if db.list_goals(cid):
        return
    db.save_case_profile(cid, '개입', '가상 사례: 9월 7일부터 밑반찬 지원 시작')
    db.add_assessment(cid, {'경제': 2, '건강': 1, '돌봄': 2}, '식생활 지원 필요. 가상 사정.', '2026-09-02')
    goal = db.add_goal(cid, '규칙적인 식사 유지', '밑반찬 주 2회 제공 및 식사 횟수 확인', '2026-10-01')
    db.update_goal_progress(goal, 40, '진행')
    task = db.add_monitoring_task(cid, '전화 확인', '2026-09-07', '가상: 첫 밑반찬 수령 확인')
    db.complete_monitoring_task(task)
    db.add_monitoring_task(cid, '전화 확인', '2026-09-14', '식사 횟수가 하루 두 끼로 유지되는지 확인')
    link = db.add_service_link(cid, None, '[가상] 밑반찬 지원', '2026-09-03')
    db.update_service_link_status(link, '제공 중', '2026-09-07 첫 수령. 주 2회 제공.')
    db.add_text_document(cid, '[가상] 후속상담_지원시작', '상담기록',
        '2026-09-07 후속상담: 밑반찬을 처음 수령했고 식사가 하루 한 끼에서 두 끼로 늘었다고 함. '
        '주 2회 지원 중. 9월 14일 식사 유지 여부 전화 확인 예정. 가상 기록.', MARKER)
    print('FOLLOWUP_SAVED', flush=True)


class ReportingEngine(InferenceEngine):
    def generate_stream(self, prompt, **kwargs):
        print('AI_GENERATING', len(self.llm.tokenize(prompt.encode('utf-8'))), 'prompt tokens', flush=True)
        for index, item in enumerate(super().generate_stream(prompt, **kwargs)):
            if index and index % 100 == 0:
                print('AI_PROGRESS', index, round(item.get('tokens_sec', 0), 1), 'tokens/sec', flush=True)
            yield item
        print('AI_STEP_DONE', flush=True)


def context(db, cid):
    engine = ReportingEngine(get_model_path())
    with db.get_connection() as conn:
        conn.execute("UPDATE client_context SET revision=revision+1, error='' WHERE client_id=?", (cid,))
    host = QObject()
    host.db, host.engine = db, engine
    host.worker = host.model_load_worker = None
    controller = ContextController(host)
    controller.tick()
    assert controller.worker and controller.worker.client_id == cid
    loop = QEventLoop()
    controller.worker.finished.connect(loop.quit)
    loop.exec()
    controller.stop()
    result = read_context(db, cid)
    assert not result['error'], result['error']
    assert result['revision'] == result['processed_revision'], result
    assert result['summary'].strip()
    assert '식사' in result['summary'] or '밑반찬' in result['summary'], '핵심 상담 내용이 요약에서 누락됨'
    print('CONTEXT_OK', result['revision'], result['summary'], result['sources'], sep='\n', flush=True)


def ui_checks(db, owner, cid, app):
    from app import MainWindow, NAV_MENUS
    from counseling_report import CounselingReportDialog
    from pypdf import PdfReader
    window = MainWindow()
    window.context_controller.stop()
    window.show()
    for _, index in NAV_MENUS:
        window.switch_page(index)
        app.processEvents()
    for tabs in (window.client_tabs, window.docs_tabs, window.data_tabs):
        for tab_index in range(tabs.count()):
            tabs.setCurrentIndex(tab_index)
            app.processEvents()
    window.doc_filter_client.setCurrentIndex(window.doc_filter_client.findData(cid))
    window.doc_filter_type.setCurrentIndex(0)
    window.doc_search_input.clear()
    window.refresh_documents_table()
    registry = db.list_document_registry(cid)
    assert window.docs_table.rowCount() == len(registry)
    displayed = {tuple(window.docs_table.item(row, 0).data(Qt.ItemDataRole.UserRole)[k] for k in ('source_type', 'id'))
                 for row in range(window.docs_table.rowCount())}
    assert displayed == {(r['source_type'], r['id']) for r in registry}
    assert {'attachment', 'case_form', 'counseling'} <= {r['source_type'] for r in registry}
    for kind in ('사례관리 서류', '상담일지'):
        window.doc_filter_type.setCurrentText(kind)
        window.refresh_documents_table()
        assert window.docs_table.rowCount() == len(db.list_document_registry(cid, kind))
    window.reset_doc_filters()
    window.refresh_dashboard()
    assert window.kpi_docs.findChild(QLabel, 'kpiValue').text() == f"{len(db.list_document_registry())}건"
    expected = db.list_document_registry()[:5]
    assert [window.dash_documents_table.item(i, 1).text() for i in range(len(expected))] == [r['title'] for r in expected]
    window.case_management_page.select_client(cid)
    window.case_management_page.refresh_context()
    assert window.case_management_page.client_id == cid
    assert read_context(db, cid)['summary'] in window.case_management_page.context_text.toPlainText()
    for index in range(window.case_management_page.tabs.count()):
        window.case_management_page.tabs.setCurrentIndex(index)
        app.processEvents()
    with patch('app.QDialog.exec', return_value=QDialog.DialogCode.Accepted):
        for document in registry:
            window.open_registry_document(document)
    designer = window.template_manager_page
    designer.toggle_fullscreen_editor()
    app.processEvents()
    assert designer.fullscreen_dialog.isFullScreen()
    designer.fullscreen_dialog.reject()
    app.processEvents()
    assert designer.editor_tabs.currentWidget() is designer.design_tab
    # 14개 양식 모두 입력·미리보기·PDF 출력을 확인한다. 더미 DB에는 초기상담만 유지한다.
    with tempfile.TemporaryDirectory() as temp:
        report = CounselingReportDialog(db, cid)
        assert report.records
        with patch('counseling_report.QFileDialog.getSaveFileName', return_value=(str(Path(temp) / 'report.pdf'), 'PDF')):
            with patch.object(QMessageBox, 'information'):
                report.export_pdf()
        assert len(PdfReader(str(Path(temp) / 'report.pdf')).pages) > 0
        report.close()
        for template in db.list_form_templates(owner):
            key = template['source_key']
            if key not in TEMPLATES:
                continue
            stage = next(s for s, keys in STAGE_FORMS.items() if key in keys)
            dialog = CaseFormDialog(db, cid, owner, stage, template)
            assert dialog.inputs and '<table' in dialog.render_preview()
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            path = str(Path(temp) / f"form-{template['id']}.pdf")
            printer.setOutputFileName(path)
            dialog.preview.document().print(printer)
            pdf = PdfReader(path)
            assert len(pdf.pages) > 0
            assert ''.join(p.extract_text() or '' for p in pdf.pages).strip(), 'PDF 본문이 비어 있음'
            dialog.close()
        backup = str(Path(temp) / 'demo-check.zip')
        assert db.create_full_backup_zip(backup)[0]
        restored_path = str(Path(temp) / 'restored')
        assert Database.restore_from_backup_zip(backup, restored_path)[0]
        restored = Database(restored_path)
        assert restored.get_client(cid)['memo'] == MARKER
        assert read_context(restored, cid)['summary'] == read_context(db, cid)['summary']
        assert len(restored.list_documents(cid)) == len(db.list_documents(cid))
        restored.add_document(cid, '[가상] PDF 읽기 검증', 'PDF', path)
        pdf_source = [
            content for reference, content in collect_sources(restored, cid)
            if '[가상] PDF 읽기 검증' in content
        ][0]
        assert '본문' in pdf_source and '읽지 못함' not in pdf_source
    window.close()
    print('UI_7_PAGES_14_FORMS_PDF_FULLSCREEN_BACKUP_RESTORE_OK', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['initial', 'followup', 'context', 'counsel', 'register', 'ui'], required=True)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    # offscreen 플랫폼은 Windows 시스템 글꼴을 자동 탐색하지 않는다.
    for font_file in ('malgun.ttf', 'batang.ttc'):
        font_path = Path('C:/Windows/Fonts') / font_file
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont('Malgun Gothic', 10))
    db = Database(get_data_dir())
    matches = [c for c in db.list_clients(NAME) if c['name'] == NAME and c['memo'] == MARKER]
    if not matches:
        assert args.phase == 'initial', 'Run initial first'
        backup = Path(db.data_dir) / ('before-demo-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip')
        assert db.create_full_backup_zip(str(backup))[0]
        cid = db.add_client({'name': NAME, 'memo': MARKER, 'household_type': '1인가구',
                             'risk_level': '중위기', 'intake_date': '2026-09-01'})
    else:
        assert len(matches) == 1
        cid = matches[0]['id']
    owner = db.get_current_profile()['id']
    db.ensure_builtin_templates(owner, TEMPLATES)
    if args.phase == 'initial':
        initial(db, owner, cid)
    elif args.phase == 'followup':
        followup(db, cid)
    elif args.phase == 'context':
        context(db, cid)
    elif args.phase == 'register':
        from dialogs import DocumentAddDialog
        title = '[가상] 등록조회검증_지원경과'
        if not db.list_documents(cid, keyword=title):
            dialog = DocumentAddDialog(db, client_id=cid)
            dialog.title_input.setText(title)
            dialog.file_path_input.setText(str(Path(__file__).parent / 'tests/fixtures/demo_attachment.txt'))
            dialog.notes_input.setText(MARKER)
            dialog.save_doc()
            assert dialog.result() == dialog.DialogCode.Accepted
        assert db.list_document_registry(cid, keyword=title)
        print('DOCUMENT_DIALOG_REGISTERED', title, flush=True)
    elif args.phase == 'counsel':
        from form_document import fill_form_html
        template = next(t for t in db.list_form_templates(owner) if t['source_key'] == '상담일지 (사례관리양식)')
        memo = '가상 대상자. 2026-09-07 밑반찬 첫 수령. 식사 하루 한 끼에서 두 끼로 증가. 9월 14일 유지 여부 전화 확인 예정.'
        engine = ReportingEngine(get_model_path())
        ok, message = engine.load_model()
        assert ok, message
        result = ''.join(item.get('token', '') for item in engine.generate_stream(
            build_prompt(template['source_key'], memo, '간결하게'), max_tokens=1024))
        assert result.strip()
        html = fill_form_html(template['form_html'], metadata={'대상자명': NAME, '상담일자': '2026-09-07', '작성자': '테스트담당자'}, generated_text=result)
        db.add_counseling_record({'client_id': cid, 'session_date': '2026-09-07',
            'template_name': template['name'], 'raw_memo': memo, 'ai_result': result,
            'result_html': html, 'worker_name': '테스트담당자', 'template_snapshot': db.make_template_snapshot(template)})
        print('AI_COUNSEL_SAVED', result, sep='\n', flush=True)
    else:
        ui_checks(db, owner, cid, app)
    print('PASS', args.phase, 'client_id=', cid, flush=True)


if __name__ == '__main__':
    main()
