"""상담일지 조건 조회와 인쇄·PDF 출력을 제공하는 대화상자."""

import html
from datetime import datetime

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from database import Database
from form_document import extract_body_html
from ui_theme import set_button_role


class CounselingReportDialog(QDialog):
    """DB에 저장된 상담일지를 대상자·양식·기간으로 조회해 출력합니다."""

    def __init__(self, db: Database, selected_client_id=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.selected_client_id = selected_client_id
        self.records = []
        self.document = QTextDocument(self)
        self.setWindowTitle("상담일지 조회·출력")
        self.setMinimumSize(980, 640)
        self.resize(1180, 760)
        self._build_ui()
        self._load_filters()
        self.search_records()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)

        title = QLabel("상담일지 조회·출력")
        title.setObjectName("reportTitle")
        description = QLabel("대상자와 상담 양식, 기간을 선택하면 저장된 상담일지를 모아서 출력할 수 있습니다.")
        description.setObjectName("sectionHint")
        root.addWidget(title)
        root.addWidget(description)

        filter_group = QGroupBox("조회 조건")
        filters = QHBoxLayout(filter_group)
        filters.setContentsMargins(12, 18, 12, 10)
        self.client_combo = QComboBox()
        self.client_combo.setMinimumWidth(210)
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(220)
        self.date_from = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_to = QDateEdit(QDate.currentDate())
        for date_edit in (self.date_from, self.date_to):
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("yyyy-MM-dd")
        search_btn = QPushButton("조건에 맞게 조회")
        set_button_role(search_btn, "primary")
        search_btn.clicked.connect(self.search_records)
        filters.addWidget(QLabel("대상자"))
        filters.addWidget(self.client_combo)
        filters.addWidget(QLabel("상담 양식"))
        filters.addWidget(self.template_combo)
        filters.addWidget(QLabel("기간"))
        filters.addWidget(self.date_from)
        filters.addWidget(QLabel("~"))
        filters.addWidget(self.date_to)
        filters.addWidget(search_btn)
        root.addWidget(filter_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 5, 0)
        self.result_count = QLabel("조회 결과 0건")
        self.result_count.setObjectName("reportCount")
        left_layout.addWidget(self.result_count)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["상담일", "대상자", "상담 양식", "작성자"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        left_layout.addWidget(self.table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(5, 0, 0, 0)
        preview_label = QLabel("출력 미리보기 · 조회된 전체 기록")
        preview_label.setObjectName("reportCount")
        right_layout.addWidget(preview_label)
        self.preview = QTextBrowser()
        self.preview.setObjectName("reportPreview")
        right_layout.addWidget(self.preview)
        splitter.addWidget(right)
        splitter.setSizes([430, 650])
        root.addWidget(splitter, stretch=1)

        actions = QHBoxLayout()
        self.pdf_btn = QPushButton("PDF로 저장")
        set_button_role(self.pdf_btn, "soft")
        self.pdf_btn.clicked.connect(self.export_pdf)
        self.print_btn = QPushButton("프린터로 인쇄")
        set_button_role(self.print_btn, "primary")
        self.print_btn.clicked.connect(self.print_records)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(QLabel("조회된 기록 전체가 출력됩니다."))
        actions.addStretch()
        actions.addWidget(self.pdf_btn)
        actions.addWidget(self.print_btn)
        actions.addWidget(close_btn)
        root.addLayout(actions)

    def _load_filters(self):
        self.client_combo.addItem("전체 대상자", None)
        selected_index = 0
        for index, client in enumerate(self.db.list_clients(), start=1):
            self.client_combo.addItem(f"{client['name']} ({client.get('masked_name', '')})", client["id"])
            if client["id"] == self.selected_client_id:
                selected_index = index
        self.client_combo.setCurrentIndex(selected_index)

        self.template_combo.addItem("전체 상담 양식", "")
        for template_name in self.db.list_counseling_templates():
            self.template_combo.addItem(template_name, template_name)

    def search_records(self):
        start = self.date_from.date().toString(Qt.DateFormat.ISODate)
        end = self.date_to.date().toString(Qt.DateFormat.ISODate)
        if start > end:
            QMessageBox.warning(self, "기간 확인", "시작일은 종료일보다 늦을 수 없습니다.")
            return
        self.records = self.db.search_counseling_records(
            client_id=self.client_combo.currentData(),
            template_name=self.template_combo.currentData() or "",
            date_from=start,
            date_to=end,
        )
        self._fill_table()
        self._build_document()
        enabled = bool(self.records)
        self.pdf_btn.setEnabled(enabled)
        self.print_btn.setEnabled(enabled)

    def _fill_table(self):
        self.table.setRowCount(len(self.records))
        for row_index, record in enumerate(self.records):
            values = [
                record.get("session_date", ""),
                record.get("client_name") or "미지정",
                record.get("template_name", ""),
                record.get("worker_name", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, record.get("id"))
                self.table.setItem(row_index, column, item)
        self.result_count.setText(f"조회 결과 {len(self.records)}건")

    def _document_header(self) -> str:
        client = self.client_combo.currentText()
        template = self.template_combo.currentText()
        period = f"{self.date_from.date().toString('yyyy-MM-dd')} ~ {self.date_to.date().toString('yyyy-MM-dd')}"
        return f"""
            <div class="report-header">
              <h1>상담일지 조회 보고서</h1>
              <table class="conditions">
                <tr><th>대상자</th><td>{html.escape(client)}</td><th>상담 양식</th><td>{html.escape(template)}</td></tr>
                <tr><th>조회 기간</th><td colspan="3">{period}</td></tr>
              </table>
            </div>
        """

    def _record_html(self, record, page_break: bool = True) -> str:
        content = (
            extract_body_html(record.get("result_html", ""))
            if record.get("result_html")
            else html.escape(record.get("ai_result", "") or "").replace("\n", "<br>")
        )
        client_name = record.get("client_name") or "미지정"
        css_class = "record page-break" if page_break else "record"
        return f"""
          <section class="{css_class}">
            <div class="record-title">{html.escape(record.get('template_name', '상담일지'))}</div>
            <table class="meta">
              <tr><th>대상자</th><td>{html.escape(client_name)}</td><th>상담일</th><td>{html.escape(record.get('session_date', ''))}</td></tr>
              <tr><th>작성자</th><td>{html.escape(record.get('worker_name', ''))}</td><th>작성 방식</th><td>{'직접 작성' if record.get('detail_level') == '직접수기작성' else 'AI 보조 작성'}</td></tr>
            </table>
            <div class="content">{content}</div>
          </section>
        """

    def _build_document(self):
        if not self.records:
            self.preview.setHtml("<div style='padding:32px;color:#60706d'>조건에 맞는 상담일지가 없습니다.</div>")
            self.document.setHtml("")
            return
        records_html = "".join(
            self._record_html(record, page_break=index < len(self.records) - 1)
            for index, record in enumerate(self.records)
        )
        stylesheet = """
          <style>
            body { font-family: 'Malgun Gothic', sans-serif; color:#172a2a; font-size:10pt; }
            h1 { font-size:20pt; color:#176b5b; margin:0 0 14px 0; }
            table { border-collapse:collapse; width:100%; }
            th { background:#eaf1ee; color:#36534e; text-align:left; width:15%; }
            th, td { border:1px solid #bfcfc9; padding:7px; }
            .report-header { margin-bottom:22px; }
            .record { margin-top:14px; }
            .record-title { font-size:15pt; font-weight:bold; border-left:5px solid #d99132; padding:5px 10px; margin-bottom:10px; }
            .meta { margin-bottom:14px; }
            .content { border:1px solid #cedbd6; padding:16px; line-height:1.65; min-height:280px; }
            .page-break { page-break-after:always; }
            .footer { color:#71817e; font-size:8pt; margin-top:18px; }
          </style>
        """
        footer = f"<div class='footer'>출력일시 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 총 {len(self.records)}건</div>"
        final_html = f"<html><head>{stylesheet}</head><body>{self._document_header()}{records_html}{footer}</body></html>"
        self.preview.setHtml(final_html)
        self.document.setHtml(final_html)

    def _restore_full_preview(self):
        self._build_document()

    def export_pdf(self):
        default_name = f"상담일지_{self.date_from.date().toString('yyyyMMdd')}_{self.date_to.date().toString('yyyyMMdd')}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "상담일지 PDF 저장", default_name, "PDF 파일 (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._restore_full_preview()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        self.document.print(printer)
        QMessageBox.information(self, "PDF 저장 완료", f"상담일지 {len(self.records)}건을 저장했습니다.\n{path}")

    def print_records(self):
        self._restore_full_preview()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("상담일지 인쇄")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.document.print(printer)
