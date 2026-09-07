"""사례 진행단계별 서류 목록과 대상자별 작성·출력 화면."""

import json
from html import escape

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QScrollArea, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from form_document import PLACEHOLDER_PATTERN, inject_approval_line
from ui_theme import set_button_role


STAGE_FORMS = {
    '접수': ['이용신청서', '개인정보 수집·이용, 제공 동의서', '초기상담지'],
    '사정': ['욕구조사(사정)표 [기본]', '욕구조사(사정)표 [노인]', '욕구조사(사정)표 [장애인]'],
    '계획': ['사례회의록', '서비스 제공계획 및 점검표'],
    '개입': ['사례관리 과정기록지', '상담일지 (사례관리양식)', '서비스의뢰서', '사례회의록'],
    '점검': ['서비스 제공계획 및 점검표', '평가보고서', '사례회의록'],
    '종결': ['종결평가서'],
    '사후관리': ['사후관리평가서 (사후관리상담지)'],
}


class CaseFormDialog(QDialog):
    def __init__(self, db, client_id, owner_id, stage, template, record=None, parent=None):
        super().__init__(parent)
        self.db, self.client_id, self.owner_id = db, client_id, owner_id
        self.record_id = record['id'] if record else None
        self.template = json.loads(record['template_snapshot']) if record else dict(template)
        self.stage = record['stage'] if record else stage
        self.read_only = bool(record and record['owner_id'] != owner_id)
        self.dirty = False
        self.setWindowTitle(self.template['name'] + (' · 열람' if self.read_only else ' · 작성'))
        self.resize(960, 720)
        root = QVBoxLayout(self)
        client = db.get_client(client_id)
        root.addWidget(QLabel(f"{client['name']} · {self.stage} · 작성중인 내용을 저장한 뒤 닫으세요."))
        bar = QHBoxLayout()
        self.date = QDateEdit(QDate.fromString(record['record_date'], 'yyyy-MM-dd') if record else QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        self.date.setEnabled(not self.read_only)
        bar.addWidget(QLabel('기록일'))
        bar.addWidget(self.date)
        self.state = QLabel(record['status'] if record else '새 서류')
        bar.addWidget(self.state)
        bar.addStretch()
        root.addLayout(bar)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        values = json.loads(record['fields_json']) if record else {
            '대상자명': client['name'], '생년월일': client.get('birth_date') or '',
            '주소': client.get('address') or '', '연락처': client.get('phone') or '',
            '성별': client.get('gender') or '', '가구유형': client.get('household_type') or '',
            '작성자': db.get_profile(owner_id)['name'],
        }
        self.inputs = {}
        for field in dict.fromkeys(PLACEHOLDER_PATTERN.findall(self.template['form_html'])):
            field = field.strip()
            edit = QTextEdit()
            edit.setAcceptRichText(False)
            edit.setFixedHeight(66)
            edit.setPlaceholderText('확인된 내용을 입력하세요. 여러 항목은 같은 순서로 줄바꿈하세요.')
            edit.setPlainText(values.get(field, ''))
            edit.setReadOnly(self.read_only)
            edit.textChanged.connect(self.mark_dirty)
            self.inputs[field] = edit
            form.addRow(field, edit)
        scroll.setWidget(body)
        tabs.addTab(scroll, '내용 입력')
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        tabs.addTab(self.preview, '인쇄 미리보기')
        tabs.currentChanged.connect(lambda _: self.render_preview())
        if '동의서' in self.template['name']:
            root.addWidget(QLabel('동의·서명란은 출력 후 직접 작성하세요. 작성완료는 서명 확인을 의미하지 않습니다.'))
        root.addWidget(QLabel('기록일과 서류 안의 상담일·작성일은 별도입니다. 실제 일자를 입력해 주세요.'))
        actions = QHBoxLayout()
        for title, handler in [('이전 내용 불러오기', self.load_previous), ('임시저장', lambda: self.save('작성중')), ('작성완료', lambda: self.save('작성완료'))]:
            button = QPushButton(title)
            button.setEnabled(not self.read_only)
            button.clicked.connect(handler)
            set_button_role(button, 'primary' if title == '작성완료' else 'soft')
            actions.addWidget(button)
        actions.addStretch()
        pdf = QPushButton('PDF 저장')
        pdf.clicked.connect(self.export_pdf)
        actions.addWidget(pdf)
        close = QPushButton('닫기')
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)
        self.date.dateChanged.connect(self.mark_dirty)
        self.render_preview()

    def mark_dirty(self, *_):
        self.dirty = True
        self.state.setText('저장하지 않은 변경사항')

    def fields(self):
        return {name: edit.toPlainText() for name, edit in self.inputs.items()}

    def render_preview(self):
        values = self.fields()
        html = PLACEHOLDER_PATTERN.sub(lambda m: escape(values.get(m.group(1).strip(), '')).replace('\n', '<br>'), self.template['form_html'])
        # 과거 문서는 작성 당시 결재라인을 유지합니다.
        approval = self.template.get('approval_steps', self.db.get_approval_line(self.owner_id))
        self.preview.setHtml(inject_approval_line(html, approval))
        return self.preview.toHtml()

    def load_previous(self):
        records = [r for r in self.db.list_case_forms(self.client_id) if r['id'] != self.record_id]
        if not records:
            QMessageBox.information(self, '이전 내용', '이 대상자에게 저장된 이전 서류가 없습니다.')
            return
        from PyQt6.QtWidgets import QInputDialog
        labels = [f"#{r['id']} · {r['record_date']} · {json.loads(r['template_snapshot'])['name']} · {r['status']}" for r in records]
        choice, ok = QInputDialog.getItem(self, '이전 내용 불러오기', '같은 항목명의 빈칸에만 반영합니다. 날짜와 작성자는 제외합니다.', labels, 0, False)
        if not ok:
            return
        values = json.loads(records[labels.index(choice)]['fields_json'])
        for name, edit in self.inputs.items():
            if not edit.toPlainText().strip() and name != '작성자' and not any(word in name for word in ('일자', '일시', '날짜', '서명', '동의')):
                edit.setPlainText(values.get(name, ''))

    def save(self, status):
        if self.read_only:
            return False
        try:
            self.template.setdefault('approval_steps', self.db.get_approval_line(self.owner_id))
            self.record_id = self.db.save_case_form(self.client_id, self.owner_id, {
                'source_key': self.template.get('source_key') or self.template['name'],
                'stage': self.stage, 'record_date': self.date.date().toString('yyyy-MM-dd'),
                'status': status, 'template_snapshot': self.template, 'fields': self.fields(),
                'result_html': self.render_preview(),
            }, self.record_id)
        except Exception as exc:
            QMessageBox.warning(self, '서류 저장 실패', str(exc))
            return False
        self.dirty = False
        self.state.setText(f'{status} · 저장됨')
        return True

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, 'PDF 저장', '사례관리서류.pdf', 'PDF (*.pdf)')
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        self.render_preview()
        from PyQt6.QtGui import QPageSize
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        self.preview.document().print(printer)

    def may_close(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, '작성 내용 저장', '변경 내용을 임시저장할까요?', QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        return self.save('작성중') if answer == QMessageBox.StandardButton.Save else answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        event.accept() if self.may_close() else event.ignore()

    def reject(self):
        if self.may_close():
            super().reject()


class CaseFormsPanel(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db, self.client_id = db, None
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.stage = QComboBox()
        self.stage.addItems(['전체 서류', *STAGE_FORMS])
        self.stage.currentTextChanged.connect(self.refresh)
        bar.addWidget(QLabel('단계별 서류'))
        bar.addWidget(self.stage)
        self.summary = QLabel('대상자를 선택해 주세요.')
        bar.addWidget(self.summary, 1)
        root.addLayout(bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['서류', '최근 상태', '기록일', '누적 건수'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self.refresh_history)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_record())
        root.addWidget(self.table, 2)
        actions = QHBoxLayout()
        for title, callback in [('새로 작성', lambda: self.open_record(new=True)), ('선택 이력 열기·이어쓰기', self.open_record)]:
            button = QPushButton(title)
            set_button_role(button, 'primary' if title == '새로 작성' else 'soft')
            button.clicked.connect(callback)
            actions.addWidget(button)
        root.addLayout(actions)
        root.addWidget(QLabel('작성 이력 · 반복 상담은 새로 작성하세요. 다른 작성자의 서류는 열람할 수 있습니다.'))
        self.history = QComboBox()
        root.addWidget(self.history)

    def set_client(self, client_id, stage):
        self.client_id = client_id
        self.stage.blockSignals(True)
        self.stage.setCurrentText(stage if stage in STAGE_FORMS else '전체 서류')
        self.stage.blockSignals(False)
        self.refresh()

    def refresh(self, *_):
        if not self.client_id:
            self.table.setRowCount(0)
            self.history.clear()
            return
        owner = self.db.get_current_profile()['id']
        templates = self.db.list_form_templates(owner)
        stage = self.stage.currentText()
        self.templates = [t for t in templates if stage == '전체 서류' or t.get('source_key') in STAGE_FORMS[stage]]
        self.records = self.db.list_case_forms(self.client_id)
        self.table.setRowCount(len(self.templates))
        for row, template in enumerate(self.templates):
            records = [r for r in self.records if r['source_key'] == (template.get('source_key') or template['name'])]
            latest = records[0] if records else None
            for col, value in enumerate([template['name'], latest['status'] if latest else '미작성', latest['record_date'] if latest else '—', str(len(records))]):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.summary.setText(f'{len(self.templates)}종 · 대상자 작성 이력 {len(self.records)}건')
        if self.templates:
            self.table.selectRow(0)
        self.refresh_history()

    def refresh_history(self):
        if not hasattr(self, 'history'):
            return
        self.history.clear()
        row = self.table.currentRow()
        if row < 0 or row >= len(getattr(self, 'templates', [])):
            return
        template = self.templates[row]
        for record in self.records:
            if record['source_key'] == (template.get('source_key') or template['name']):
                self.history.addItem(f"#{record['id']} · {record['record_date']} · {record['status']}", record)

    def open_record(self, _checked=False, new=False):
        row = self.table.currentRow()
        if row < 0 or not self.client_id:
            return
        record = None if new else self.history.currentData()
        stage = self.stage.currentText()
        if stage == '전체 서류':
            stage = self.db.get_case_profile(self.client_id)['stage']
        dialog = CaseFormDialog(self.db, self.client_id, self.db.get_current_profile()['id'], stage, self.templates[row], record, self)
        dialog.exec()
        self.refresh()
