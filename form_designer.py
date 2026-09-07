"""드래그 앤 드롭 기반 서류 양식 요소 팔레트와 리치 문서 편집기."""

from PyQt6.QtCore import QByteArray, QMimeData, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QTextCharFormat,
    QTextDocumentFragment,
    QTextLength,
    QTextTableFormat,
)
from PyQt6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QTextEdit


FORM_ELEMENT_MIME = "application/x-welfare-form-element"


def make_table_format(column_widths=None) -> QTextTableFormat:
    table_format = QTextTableFormat()
    table_format.setBorder(1)
    table_format.setBorderBrush(QColor("#82938d"))
    table_format.setCellPadding(7)
    table_format.setCellSpacing(0)
    table_format.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
    if column_widths:
        table_format.setColumnWidthConstraints([
            QTextLength(QTextLength.Type.PercentageLength, width)
            for width in column_widths
        ])
    return table_format


class FormElementPalette(QListWidget):
    """문서로 끌어 놓을 수 있는 현장 서류 구성요소 모음입니다."""

    ELEMENTS = (
        ("▰  큰 제목", "title", "문서 제목"),
        ("▤  기본정보 표", "metadata", "대상자·일자·작성자"),
        ("▥  입력항목 행", "field_row", "항목명 + 입력칸"),
        ("▬  구분 제목행", "section", "표 안의 소제목"),
        ("¶  안내 문장", "paragraph", "설명 또는 유의사항"),
        ("☐  체크 항목", "checklist", "선택 항목 3개"),
        ("✎  서명란", "signature", "담당자 확인 서명"),
        ("―  구분선", "divider", "내용 영역 나누기"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSpacing(5)
        self.setMinimumWidth(164)
        self.setMaximumWidth(190)
        self.setStyleSheet("""
            QListWidget {
                background:#eef3f1;
                border:1px solid #c5d2ce;
                border-radius:8px;
                padding:6px;
            }
            QListWidget::item {
                background:#ffffff;
                color:#304641;
                border:1px solid #d5dfdc;
                border-radius:6px;
                padding:9px 8px;
            }
            QListWidget::item:hover { border-color:#4f8b7d; background:#f7fbfa; }
            QListWidget::item:selected { background:#dcece7; color:#145a4d; border-color:#6eaa9b; }
        """)
        for title, element_type, tooltip in self.ELEMENTS:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, element_type)
            item.setToolTip(f"문서로 끌어 놓기 · {tooltip}")
            self.addItem(item)

    def mimeData(self, items):
        mime_data = QMimeData()
        if items:
            element_type = items[0].data(Qt.ItemDataRole.UserRole)
            mime_data.setData(FORM_ELEMENT_MIME, QByteArray(str(element_type).encode("utf-8")))
            mime_data.setText(items[0].text())
        return mime_data

    def filter_elements(self, query: str) -> int:
        """요소 이름이나 설명으로 팔레트를 즉시 걸러냅니다."""
        keyword = (query or "").strip().lower()
        visible_count = 0
        for row in range(self.count()):
            item = self.item(row)
            searchable = f"{item.text()} {item.toolTip()}".lower()
            hidden = bool(keyword and keyword not in searchable)
            item.setHidden(hidden)
            if not hidden:
                visible_count += 1
        return visible_count


class FormDesignEditor(QTextEdit):
    """서류 구성요소를 원하는 위치에 놓고 직접 편집하는 문서 캔버스입니다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom_percent = 100
        self.setAcceptRichText(True)
        self.setAcceptDrops(True)
        self.setUndoRedoEnabled(True)
        self.setFont(QFont("Batang", 10))
        self.setStyleSheet("""
            QTextEdit {
                background:#fffefd;
                color:#202c29;
                border:1px solid #aebdb8;
                border-radius:2px;
                padding:20px 24px;
                selection-background-color:#b9ddd2;
                selection-color:#172a2a;
            }
            QTextEdit:focus { border:2px solid #4f8b7d; }
        """)

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    def set_zoom(self, percent: int) -> None:
        """저장되는 문서 내용은 건드리지 않고 편집 화면만 확대·축소합니다."""
        percent = max(50, min(200, int(percent)))
        current_steps = round((self._zoom_percent - 100) / 10)
        requested_steps = round((percent - 100) / 10)
        point_steps = requested_steps - current_steps
        if point_steps:
            self.zoomIn(point_steps)
        self._zoom_percent = percent

    def setHtml(self, text: str) -> None:
        """문서를 바꾸어도 사용자가 고른 보기 배율을 유지합니다."""
        requested_zoom = self._zoom_percent
        self._zoom_percent = 100
        super().setHtml(text)
        self.set_zoom(requested_zoom)

    def document_html(self) -> str:
        """보기 배율을 제외한 원래 서식 HTML을 반환합니다."""
        requested_zoom = self._zoom_percent
        self.set_zoom(100)
        html = super().toHtml()
        self.set_zoom(requested_zoom)
        return html

    def selected_context(self) -> str:
        cursor = self.textCursor()
        if cursor.currentTable() is not None:
            return "표 셀"
        if cursor.hasSelection():
            return "선택한 글자"
        return "문서 본문"

    def duplicate_selection(self) -> bool:
        """현재 선택한 서식 있는 내용을 바로 뒤에 복제합니다."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        fragment = QTextDocumentFragment(cursor)
        insert_at = cursor.selectionEnd()
        cursor.setPosition(insert_at)
        cursor.insertFragment(fragment)
        self.setTextCursor(cursor)
        return True

    def delete_selection(self) -> bool:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        return True

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(FORM_ELEMENT_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(FORM_ELEMENT_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(FORM_ELEMENT_MIME):
            element_type = bytes(event.mimeData().data(FORM_ELEMENT_MIME)).decode("utf-8")
            cursor = self.cursorForPosition(event.position().toPoint())
            self.setTextCursor(cursor)
            self.insert_design_element(element_type)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def insertFromMimeData(self, source) -> None:
        if source.hasFormat(FORM_ELEMENT_MIME):
            element_type = bytes(source.data(FORM_ELEMENT_MIME)).decode("utf-8")
            self.insert_design_element(element_type)
            return
        super().insertFromMimeData(source)

    def insert_design_element(self, element_type: str) -> None:
        cursor = self.textCursor()
        if element_type == "title":
            cursor.insertHtml(
                "<h2 style='text-align:center;font-family:Batang;margin:10px 0 16px 0;'>문서 제목</h2><p></p>"
            )
        elif element_type == "metadata":
            table = cursor.insertTable(2, 4, make_table_format([16, 34, 16, 34]))
            for row, values in enumerate((
                ("대상자", "{{대상자명}}", "작성일", "{{상담일자}}"),
                ("작성자", "{{작성자}}", "상담방법", "{{상담방법}}"),
            )):
                for column, value in enumerate(values):
                    self._set_cell(table.cellAt(row, column), value, label_cell=column % 2 == 0)
            cursor = self._cursor_after_table(table)
        elif element_type == "field_row":
            table = cursor.insertTable(1, 2, make_table_format([25, 75]))
            self._set_cell(table.cellAt(0, 0), "항목명", label_cell=True)
            self._set_cell(table.cellAt(0, 1), "{{입력칸}}")
            cursor = self._cursor_after_table(table)
        elif element_type == "section":
            table = cursor.insertTable(1, 1, make_table_format([100]))
            self._set_cell(table.cellAt(0, 0), "구분 제목", label_cell=True, centered=True)
            cursor = self._cursor_after_table(table)
        elif element_type == "paragraph":
            cursor.insertHtml("<p style='margin:6px 0;'>안내 또는 작성 지침을 입력하세요.</p>")
        elif element_type == "checklist":
            cursor.insertHtml("<p style='margin:6px 0;'>☐ 항목 1&nbsp;&nbsp;&nbsp; ☐ 항목 2&nbsp;&nbsp;&nbsp; ☐ 기타: __________</p>")
        elif element_type == "signature":
            cursor.insertHtml("<p style='text-align:right;margin-top:14px;'>담당자: ____________________ (서명)</p>")
        elif element_type == "divider":
            cursor.insertHtml("<hr style='border:0;border-top:1px solid #82938d;margin:10px 0;'>")
        self.setTextCursor(cursor)
        self.setFocus()

    @staticmethod
    def _cursor_after_table(table):
        cursor = table.lastCursorPosition()
        cursor.movePosition(cursor.MoveOperation.NextBlock)
        return cursor

    @staticmethod
    def _set_cell(cell, text: str, label_cell: bool = False, centered: bool = False) -> None:
        if label_cell:
            cell_format = cell.format()
            cell_format.setBackground(QColor("#e4efeb"))
            cell.setFormat(cell_format)
        cursor = cell.firstCursorPosition()
        if centered:
            block_format = cursor.blockFormat()
            block_format.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cursor.setBlockFormat(block_format)
        char_format = QTextCharFormat()
        if label_cell:
            char_format.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(text, char_format)
