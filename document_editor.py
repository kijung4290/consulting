"""서류보관함의 첨부·상담 기록 수정창. 사례 서류는 기존 서식 편집기를 사용한다."""
from pathlib import Path
import sqlite3
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QHBoxLayout, QLabel, QFileDialog, QMessageBox)


class DocumentEditDialog(QDialog):
    def __init__(self, db, document, owner_id, parent=None):
        super().__init__(parent)
        self.db, self.document, self.owner_id = db, document, owner_id
        self.replacement = None
        self.setWindowTitle('서류 수정')
        self.resize(900, 700)
        table = 'documents' if document['source_type'] == 'attachment' else 'counseling_records'
        with db.get_connection() as conn:
            row = conn.execute(f'SELECT * FROM {table} WHERE id=?', (document['id'],)).fetchone()
        if not row:
            raise ValueError('서류가 존재하지 않습니다.')
        self.record = dict(row)
        if table == 'counseling_records' and row['owner_id'] not in (None, owner_id):
            raise ValueError('본인이 작성한 상담일지만 수정할 수 있습니다.')
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit(document['title'])
        form.addRow('서류 제목', self.title)
        self.extra = QLineEdit(row['doc_type'] if table == 'documents' else row['session_date'])
        form.addRow('서류 구분' if table == 'documents' else '상담일 (YYYY-MM-DD)', self.extra)
        self.notes = QLineEdit((row['notes'] or '') if table == 'documents' else (row['worker_name'] or ''))
        form.addRow('비고' if table == 'documents' else '작성자', self.notes)
        layout.addLayout(form)
        self.content = QTextEdit()
        layout.addWidget(self.content, 1)
        self.text_editable = False
        if table == 'documents':
            path = Path(db.get_document_full_path(row['file_name']))
            self.content.setAcceptRichText(False)
            if path.suffix.lower() == '.txt' and path.is_file():
                try:
                    self.content.setPlainText(path.read_text(encoding='utf-8-sig'))
                    self.text_editable = True
                except (OSError, UnicodeError):
                    pass
            self.content.setReadOnly(not self.text_editable)
            self.file_status = QLabel('TXT 본문을 수정하거나 파일을 교체할 수 있습니다.' if self.text_editable else 'PDF·HWP 등은 수정한 파일로 교체하세요. 제목·구분·비고는 여기서 수정할 수 있습니다.')
            self.file_status.setWordWrap(True)
            layout.addWidget(self.file_status)
            replace = QPushButton('첨부 파일 교체…')
            replace.clicked.connect(self.choose_replacement)
            layout.addWidget(replace)
        elif row['result_html']:
            self.content.setHtml(row['result_html'])
        else:
            self.content.setPlainText(row['ai_result'])
        actions = QHBoxLayout()
        actions.addStretch()
        save = QPushButton('수정 저장')
        save.clicked.connect(self.save)
        cancel = QPushButton('취소')
        cancel.clicked.connect(self.reject)
        actions.addWidget(save)
        actions.addWidget(cancel)
        layout.addLayout(actions)

    def choose_replacement(self):
        path, _ = QFileDialog.getOpenFileName(self, '교체할 파일 선택', '', '모든 파일 (*.*)')
        if path:
            self.replacement = path
            self.content.setReadOnly(True)
            self.file_status.setText(f'교체 예정: {path}\n저장하면 이 파일로 교체합니다. 위 본문 편집은 적용하지 않습니다.')

    def save(self):
        try:
            if self.document['source_type'] == 'attachment':
                text = self.content.toPlainText() if self.text_editable and not self.replacement else None
                self.db.update_attachment(self.document['id'], self.title.text(), self.extra.text(), self.notes.text(), text, self.replacement)
            else:
                self.db.update_counseling_content(self.document['id'], self.owner_id, self.title.text(), self.extra.text(),
                    self.notes.text(), self.content.toPlainText(), self.content.toHtml())
            self.accept()
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, '수정 실패', str(exc))
