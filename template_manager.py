"""사용자별 로컬 서류 양식 생성·편집 화면."""

import json
import os
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QTextCharFormat
from PyQt6.QtWidgets import (
    QFileDialog,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QFontComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database import Database
from form_designer import FormDesignEditor, FormElementPalette, make_table_format
from form_document import (
    build_blank_form_html,
    build_form_html,
    inject_approval_line,
    render_approval_line_html,
)
from prompts import TEMPLATES
from ui_theme import make_page_header, set_button_role


NEW_TEMPLATE_GUIDE = """다음 상담 메모를 아래 서류 양식에 맞춰 작성해 주십시오.

[출력 양식]
### [새 서류 양식]
1. **기본 정보**:
2. **주요 내용**:
3. **담당자 소견**:
4. **처리 결과 및 향후 계획**:
"""


class ApprovalLineDialog(QDialog):
    """결재 직위, 결재자명, 순서를 사용자별로 편집합니다."""

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("사용자 맞춤 결재라인 설정")
        self.resize(540, 430)
        layout = QVBoxLayout(self)
        description = QLabel(
            "결재 직위와 결재자명을 입력하고 순서를 조정하세요. 최대 8칸이며 모든 개인 양식의 우측 상단에 적용됩니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["결재 직위", "결재자명 (선택)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)
        for step in steps:
            self.add_row(step.get("title", ""), step.get("name", ""))

        row_actions = QHBoxLayout()
        for label, handler in (
            ("＋ 결재칸 추가", self.add_row),
            ("선택 삭제", self.remove_row),
            ("위로", lambda: self.move_row(-1)),
            ("아래로", lambda: self.move_row(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            row_actions.addWidget(button)
        row_actions.addStretch()
        layout.addLayout(row_actions)

        actions = QHBoxLayout()
        save_btn = QPushButton("저장")
        set_button_role(save_btn, "primary")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        actions.addStretch()
        actions.addWidget(save_btn)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    def add_row(self, title: str = "", name: str = "") -> None:
        if self.table.rowCount() >= 8:
            QMessageBox.information(self, "결재라인", "결재라인은 최대 8칸까지 만들 수 있습니다.")
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(title if isinstance(title, str) else ""))
        self.table.setItem(row, 1, QTableWidgetItem(name if isinstance(name, str) else ""))
        self.table.setCurrentCell(row, 0)

    def remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def move_row(self, direction: int) -> None:
        row = self.table.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        current_values = [self.table.item(row, column).text() if self.table.item(row, column) else "" for column in range(2)]
        target_values = [self.table.item(target, column).text() if self.table.item(target, column) else "" for column in range(2)]
        for column in range(2):
            self.table.setItem(row, column, QTableWidgetItem(target_values[column]))
            self.table.setItem(target, column, QTableWidgetItem(current_values[column]))
        self.table.setCurrentCell(target, 0)

    def approval_steps(self):
        return [
            {
                "title": self.table.item(row, 0).text().strip() if self.table.item(row, 0) else "",
                "name": self.table.item(row, 1).text().strip() if self.table.item(row, 1) else "",
            }
            for row in range(self.table.rowCount())
            if self.table.item(row, 0) and self.table.item(row, 0).text().strip()
        ]

    def accept(self) -> None:
        if not self.approval_steps():
            QMessageBox.warning(self, "결재라인 확인", "결재 직위를 한 개 이상 입력해 주세요.")
            return
        super().accept()


class TemplateManagerPage(QWidget):
    """현재 작업자에게만 적용되는 서류 양식 관리 페이지입니다."""

    def __init__(
        self,
        db: Database,
        profile_id: int,
        on_templates_changed: Optional[Callable[[], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.db = db
        self.profile_id = profile_id
        self.on_templates_changed = on_templates_changed
        self.current_template_id = None
        self.current_source_key = None
        self._build_ui()
        self.refresh_templates()

    def _build_ui(self) -> None:
        self.setObjectName("pageRoot")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        layout.addWidget(make_page_header(
            "서류 양식 관리",
            "기본 양식을 내 업무 방식에 맞게 수정하거나 새 양식을 직접 만들어 상담 작성에 사용합니다.",
            "PERSONAL FORM BUILDER",
        ))

        info_bar = QFrame()
        info_bar.setStyleSheet(
            "QFrame { background: #EAF5F1; border: 1px solid #B9DDD2; border-radius: 9px; }"
        )
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(12, 8, 12, 8)
        self.owner_label = QLabel()
        self.owner_label.setStyleSheet("color: #145A4D; font-weight: 700;")
        approval_settings_btn = QPushButton("결재라인 설정")
        approval_settings_btn.clicked.connect(self.open_approval_line_editor)
        self.storage_label = QLabel()
        self.storage_label.setStyleSheet("color: #52656A; font-size: 10px;")
        self.storage_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.set_storage_path(self.db.db_path)
        info_layout.addWidget(self.owner_label)
        info_layout.addWidget(approval_settings_btn)
        info_layout.addStretch()
        info_layout.addWidget(self.storage_label)
        layout.addWidget(info_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        left = QWidget()
        left.setMinimumWidth(190)
        left.setMaximumWidth(310)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        title = QLabel("내 서류 양식")
        title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        left_layout.addWidget(title)
        self.template_list = QListWidget()
        self.template_list.currentItemChanged.connect(self._load_selected)
        left_layout.addWidget(self.template_list, stretch=1)

        left_buttons = QHBoxLayout()
        new_btn = QPushButton("＋ 새 양식")
        set_button_role(new_btn, "primary")
        new_btn.clicked.connect(self.new_template)
        self.duplicate_btn = QPushButton("복사")
        self.duplicate_btn.clicked.connect(self.duplicate_template)
        self.delete_btn = QPushButton("삭제")
        set_button_role(self.delete_btn, "danger")
        self.delete_btn.clicked.connect(self.delete_template)
        left_buttons.addWidget(new_btn)
        left_buttons.addWidget(self.duplicate_btn)
        left_buttons.addWidget(self.delete_btn)
        left_layout.addLayout(left_buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: 독거어르신 정기 안부확인 기록지")
        self.category_input = QLineEdit()
        self.category_input.setPlaceholderText("예: 상담기록, 초기면접, 사례관리, 회의록")
        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(68)
        self.description_input.setPlaceholderText("이 양식을 언제 사용하는지 간단히 설명해 주세요.")
        form.addRow("양식 이름(*):", self.name_input)
        form.addRow("서류 종류:", self.category_input)
        form.addRow("설명:", self.description_input)
        right_layout.addLayout(form)

        editor_tabs = QTabWidget()
        self.editor_tabs = editor_tabs
        self.fullscreen_dialog = None

        design_tab = QWidget()
        self.design_tab = design_tab
        design_layout = QVBoxLayout(design_tab)
        design_layout.setContentsMargins(0, 0, 0, 0)
        design_layout.setSpacing(0)

        self.form_editor = FormDesignEditor()

        command_bar = QFrame()
        command_bar.setObjectName("designerCommandBar")
        command_bar.setStyleSheet(
            "QFrame#designerCommandBar { background:#FFFFFF;border-bottom:1px solid #D7E1DE; }"
        )
        command_layout = QHBoxLayout(command_bar)
        command_layout.setContentsMargins(10, 7, 10, 7)
        command_layout.setSpacing(5)
        command_title = QLabel("서식 편집")
        command_title.setStyleSheet("font-weight:850;color:#243532;margin-right:5px;")
        command_layout.addWidget(command_title)
        undo_btn = QPushButton("↶")
        undo_btn.setToolTip("실행 취소 (Ctrl+Z)")
        undo_btn.setMaximumWidth(34)
        undo_btn.clicked.connect(self.form_editor.undo)
        redo_btn = QPushButton("↷")
        redo_btn.setToolTip("다시 실행 (Ctrl+Y)")
        redo_btn.setMaximumWidth(34)
        redo_btn.clicked.connect(self.form_editor.redo)
        command_layout.addWidget(undo_btn)
        command_layout.addWidget(redo_btn)
        command_layout.addSpacing(6)
        for label, tooltip, handler in (
            ("▦ 표", "원하는 행·열의 표 삽입", self.insert_table),
            ("{{ }} 입력칸", "AI 결과가 들어갈 자동 입력칸", self.insert_placeholder),
            ("☐ 체크칸", "현재 위치에 체크칸 삽입", self.insert_checkbox),
        ):
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            command_layout.addWidget(button)
        command_layout.addStretch()
        preview_btn = QPushButton("미리보기")
        set_button_role(preview_btn, "soft")
        preview_btn.clicked.connect(self.show_form_preview)
        command_layout.addWidget(preview_btn)
        design_layout.addWidget(command_bar)

        designer_splitter = QSplitter(Qt.Orientation.Horizontal)
        designer_splitter.setHandleWidth(5)

        palette_box = QFrame()
        palette_box.setMinimumWidth(172)
        palette_box.setMaximumWidth(215)
        palette_box.setStyleSheet("QFrame { background:#F7FAF9;border:0; }")
        palette_layout = QVBoxLayout(palette_box)
        palette_layout.setContentsMargins(10, 12, 8, 10)
        palette_layout.setSpacing(7)
        palette_title = QLabel("복지서식 블록")
        palette_title.setStyleSheet("font-weight:850;color:#243532;font-size:12px;")
        palette_help = QLabel("찾아서 캔버스로 끌어 놓으세요")
        palette_help.setWordWrap(True)
        palette_help.setStyleSheet("color:#6A7D78;font-size:9px;")
        self.element_search = QLineEdit()
        self.element_search.setPlaceholderText("요소 검색")
        self.element_search.setClearButtonEnabled(True)
        self.element_search.textChanged.connect(self.filter_element_palette)
        self.element_palette = FormElementPalette()
        self.element_palette.itemDoubleClicked.connect(
            lambda item: self.form_editor.insert_design_element(item.data(Qt.ItemDataRole.UserRole))
        )
        palette_layout.addWidget(palette_title)
        palette_layout.addWidget(palette_help)
        palette_layout.addWidget(self.element_search)
        palette_layout.addWidget(self.element_palette, stretch=1)
        palette_tip = QLabel("TIP  두 번 클릭하면 현재 커서 위치에 바로 들어갑니다.")
        palette_tip.setWordWrap(True)
        palette_tip.setStyleSheet(
            "background:#E6F1ED;color:#31655A;border-radius:6px;padding:7px;font-size:9px;"
        )
        palette_layout.addWidget(palette_tip)
        designer_splitter.addWidget(palette_box)

        canvas_box = QFrame()
        canvas_box.setMinimumWidth(330)
        canvas_box.setStyleSheet("QFrame { background:#E9EEEC;border:0; }")
        canvas_layout = QVBoxLayout(canvas_box)
        canvas_layout.setContentsMargins(14, 10, 14, 8)
        canvas_layout.setSpacing(6)
        canvas_header = QHBoxLayout()
        paper_label = QLabel("A4 세로")
        paper_label.setStyleSheet("color:#465D58;font-weight:800;font-size:10px;")
        approval_note = QLabel("결재라인은 우측 상단에 자동 배치")
        approval_note.setStyleSheet("color:#7A8C87;font-size:9px;")
        canvas_header.addWidget(paper_label)
        canvas_header.addStretch()
        canvas_header.addWidget(approval_note)
        canvas_layout.addLayout(canvas_header)

        paper = QFrame()
        paper.setObjectName("designerPaper")
        paper.setStyleSheet(
            "QFrame#designerPaper { background:#FFFDFC;border:1px solid #C9D4D0;border-radius:2px; }"
        )
        paper_layout = QVBoxLayout(paper)
        paper_layout.setContentsMargins(10, 10, 10, 10)
        paper_layout.setSpacing(2)
        self.approval_preview = QTextEdit()
        self.approval_preview.setReadOnly(True)
        self.approval_preview.setMaximumHeight(82)
        self.approval_preview.setStyleSheet(
            "QTextEdit { background:#FFFDFC;border:0;padding:0;color:#243532; }"
        )
        paper_layout.addWidget(self.approval_preview)
        paper_layout.addWidget(self.form_editor, stretch=1)
        canvas_layout.addWidget(paper, stretch=1)

        zoom_bar = QHBoxLayout()
        zoom_bar.setContentsMargins(0, 0, 0, 0)
        zoom_hint = QLabel("화면 확대")
        zoom_hint.setStyleSheet("color:#647873;font-size:9px;")
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(["75%", "90%", "100%", "110%", "125%", "150%"])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.setMaximumWidth(76)
        self.zoom_combo.currentTextChanged.connect(self.apply_canvas_zoom)
        zoom_bar.addStretch()
        zoom_bar.addWidget(zoom_hint)
        zoom_bar.addWidget(self.zoom_combo)
        canvas_layout.addLayout(zoom_bar)
        designer_splitter.addWidget(canvas_box)

        inspector = QFrame()
        inspector.setMinimumWidth(215)
        inspector.setMaximumWidth(270)
        inspector.setStyleSheet("QFrame { background:#FFFFFF;border:0; }")
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(11, 12, 11, 10)
        inspector_layout.setSpacing(7)
        inspector_title = QLabel("선택 항목 설정")
        inspector_title.setStyleSheet("font-weight:850;color:#243532;font-size:12px;")
        self.context_label = QLabel("문서 본문")
        self.context_label.setStyleSheet(
            "background:#D9ECE6;color:#176B5B;border-radius:8px;padding:5px 8px;font-weight:800;font-size:10px;"
        )
        self.selection_hint = QLabel("글자를 선택하거나 표 셀을 클릭하면 여기에서 모양을 바꿀 수 있습니다.")
        self.selection_hint.setWordWrap(True)
        self.selection_hint.setStyleSheet("color:#70827D;font-size:9px;")
        inspector_layout.addWidget(inspector_title)
        inspector_layout.addWidget(self.context_label)
        inspector_layout.addWidget(self.selection_hint)

        text_title = QLabel("글자")
        text_title.setStyleSheet("font-weight:800;color:#455B56;margin-top:5px;")
        inspector_layout.addWidget(text_title)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("Batang"))
        self.font_combo.currentFontChanged.connect(self.apply_font_family)
        self.font_size_combo = QComboBox()
        self.font_size_combo.setEditable(True)
        self.font_size_combo.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32"])
        self.font_size_combo.setCurrentText("10")
        self.font_size_combo.currentTextChanged.connect(self.apply_font_size)
        font_row = QHBoxLayout()
        font_row.setSpacing(5)
        font_row.addWidget(self.font_combo, stretch=1)
        font_row.addWidget(self.font_size_combo)
        inspector_layout.addLayout(font_row)

        type_row = QHBoxLayout()
        type_row.setSpacing(4)
        for label, tooltip, handler in (
            ("B", "굵게", self.toggle_bold),
            ("I", "기울임", self.toggle_italic),
            ("U", "밑줄", self.toggle_underline),
        ):
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.setMaximumWidth(36)
            button.clicked.connect(handler)
            type_row.addWidget(button)
        type_row.addStretch()
        inspector_layout.addLayout(type_row)

        color_label = QLabel("글자색")
        color_label.setStyleSheet("color:#667A75;font-size:9px;")
        inspector_layout.addWidget(color_label)
        font_colors = QHBoxLayout()
        font_colors.setSpacing(4)
        for color in ("#243532", "#176B5B", "#315E9B", "#B83A4B", "#D99132"):
            font_colors.addWidget(self._make_color_button(
                color,
                lambda checked=False, selected=color: self.apply_font_color(selected),
                "글자색 적용",
            ))
        custom_font_color = QPushButton("+")
        custom_font_color.setToolTip("다른 글자색 선택")
        custom_font_color.setMaximumWidth(30)
        custom_font_color.clicked.connect(self.choose_font_color)
        font_colors.addWidget(custom_font_color)
        font_colors.addStretch()
        inspector_layout.addLayout(font_colors)

        highlight_btn = QPushButton("글자 강조색")
        highlight_btn.setToolTip("선택한 글자의 배경색을 지정합니다")
        highlight_btn.clicked.connect(self.choose_text_background)
        inspector_layout.addWidget(highlight_btn)

        align_row = QHBoxLayout()
        align_row.setSpacing(4)
        for label, tooltip, alignment in (
            ("왼쪽", "왼쪽 정렬", Qt.AlignmentFlag.AlignLeft),
            ("가운데", "가운데 정렬", Qt.AlignmentFlag.AlignCenter),
            ("오른쪽", "오른쪽 정렬", Qt.AlignmentFlag.AlignRight),
        ):
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda checked=False, value=alignment: self.set_alignment(value))
            align_row.addWidget(button)
        inspector_layout.addLayout(align_row)

        table_title = QLabel("표 셀")
        table_title.setStyleSheet("font-weight:800;color:#455B56;margin-top:7px;")
        inspector_layout.addWidget(table_title)
        cell_label = QLabel("배경색")
        cell_label.setStyleSheet("color:#667A75;font-size:9px;")
        inspector_layout.addWidget(cell_label)
        cell_colors = QHBoxLayout()
        cell_colors.setSpacing(4)
        for color in ("#FFFFFF", "#E4EFEB", "#D9ECE6", "#FFF2DA", "#EAF0F8"):
            cell_colors.addWidget(self._make_color_button(
                color,
                lambda checked=False, selected=color: self.apply_cell_background(selected),
                "셀 배경색 적용",
            ))
        custom_cell_color = QPushButton("+")
        custom_cell_color.setToolTip("다른 셀 배경색 선택")
        custom_cell_color.setMaximumWidth(30)
        custom_cell_color.clicked.connect(self.choose_cell_background)
        cell_colors.addWidget(custom_cell_color)
        cell_colors.addStretch()
        inspector_layout.addLayout(cell_colors)

        table_grid = QGridLayout()
        table_grid.setSpacing(4)
        for index, (label, handler) in enumerate((
            ("＋ 행", self.add_table_row),
            ("－ 행", self.remove_table_row),
            ("＋ 열", self.add_table_column),
            ("－ 열", self.remove_table_column),
            ("셀 합치기", self.merge_table_cells),
            ("셀 나누기", self.split_table_cell),
        )):
            button = QPushButton(label)
            button.clicked.connect(handler)
            table_grid.addWidget(button, index // 2, index % 2)
        inspector_layout.addLayout(table_grid)

        selection_title = QLabel("선택 내용")
        selection_title.setStyleSheet("font-weight:800;color:#455B56;margin-top:7px;")
        inspector_layout.addWidget(selection_title)
        selection_actions = QHBoxLayout()
        self.duplicate_selection_btn = QPushButton("복제")
        self.duplicate_selection_btn.clicked.connect(self.duplicate_selected_content)
        self.delete_selection_btn = QPushButton("삭제")
        set_button_role(self.delete_selection_btn, "danger")
        self.delete_selection_btn.clicked.connect(self.delete_selected_content)
        selection_actions.addWidget(self.duplicate_selection_btn)
        selection_actions.addWidget(self.delete_selection_btn)
        inspector_layout.addLayout(selection_actions)
        inspector_layout.addStretch()
        inspector_footer = QLabel("변경 내용은 아래 ‘내 양식 저장’을 눌러야 로컬에 저장됩니다.")
        inspector_footer.setWordWrap(True)
        inspector_footer.setStyleSheet(
            "background:#FFF4E2;color:#7A541E;border-radius:6px;padding:7px;font-size:9px;"
        )
        inspector_layout.addWidget(inspector_footer)
        inspector_scroll = QScrollArea()
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setMinimumWidth(230)
        inspector_scroll.setWidget(inspector)
        designer_splitter.addWidget(inspector_scroll)

        tools_btn = QPushButton("도구 펼치기")
        tools_btn.setCheckable(True)
        tools_btn.toggled.connect(palette_box.setVisible)
        tools_btn.toggled.connect(inspector_scroll.setVisible)
        command_layout.insertWidget(0, tools_btn)
        palette_box.hide()
        inspector_scroll.hide()

        focus_btn = QPushButton("전체화면 편집")
        self.fullscreen_button = focus_btn
        set_button_role(focus_btn, "primary")
        command_layout.insertWidget(1, focus_btn)
        focus_btn.clicked.connect(self.toggle_fullscreen_editor)

        designer_splitter.setStretchFactor(0, 0)
        designer_splitter.setStretchFactor(1, 1)
        designer_splitter.setStretchFactor(2, 0)
        designer_splitter.setSizes([185, 520, 235])
        design_layout.addWidget(designer_splitter, stretch=1)

        self.form_editor.cursorPositionChanged.connect(self.update_selection_context)
        self.form_editor.selectionChanged.connect(self.update_selection_context)
        self.form_editor.currentCharFormatChanged.connect(lambda _format: self.update_selection_context())
        self.update_selection_context()
        editor_tabs.addTab(design_tab, "표 양식 디자인")

        instruction_tab = QWidget()
        instruction_layout = QVBoxLayout(instruction_tab)
        instruction_layout.setContentsMargins(8, 8, 8, 8)
        guide_title = QLabel("AI 작성 지침 (*)")
        guide_title.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        instruction_layout.addWidget(guide_title)
        guide_hint = QLabel(
            "AI가 어떤 내용을 작성해야 하는지 지정합니다. 표 안의 {{입력칸 이름}}과 지침의 항목명을 같게 하면 결과가 해당 셀에 자동 배치됩니다."
        )
        guide_hint.setWordWrap(True)
        guide_hint.setStyleSheet("color: #64748B; font-size: 10px;")
        instruction_layout.addWidget(guide_hint)
        self.guide_input = QTextEdit()
        self.guide_input.setPlaceholderText(NEW_TEMPLATE_GUIDE)
        self.guide_input.setFont(QFont("Malgun Gothic", 10))
        instruction_layout.addWidget(self.guide_input, stretch=3)

        sample_title = QLabel("예시 상담 메모 (선택)")
        sample_title.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        instruction_layout.addWidget(sample_title)
        self.sample_input = QTextEdit()
        self.sample_input.setMaximumHeight(82)
        self.sample_input.setPlaceholderText("상담일지 작성 화면의 ‘예시 메모 불러오기’에서 사용할 내용")
        instruction_layout.addWidget(self.sample_input)
        editor_tabs.addTab(instruction_tab, "AI 작성 지침")
        right_layout.addWidget(editor_tabs, stretch=1)

        actions = QHBoxLayout()
        import_btn = QPushButton("양식 가져오기")
        import_btn.clicked.connect(self.import_template)
        self.export_btn = QPushButton("선택 양식 내보내기")
        self.export_btn.clicked.connect(self.export_template)
        self.reset_btn = QPushButton("기본값으로 되돌리기")
        self.reset_btn.clicked.connect(self.reset_template)
        save_btn = QPushButton("💾 내 양식 저장")
        set_button_role(save_btn, "primary")
        save_btn.clicked.connect(self.save_template)
        actions.addWidget(import_btn)
        actions.addWidget(self.export_btn)
        actions.addWidget(self.reset_btn)
        actions.addStretch()
        actions.addWidget(save_btn)
        right_layout.addLayout(actions)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 1000])
        layout.addWidget(splitter, stretch=1)

    def toggle_fullscreen_editor(self):
        """동일한 편집기를 옮겨 서식, 선택 위치와 실행 취소 이력을 유지한다."""
        if self.fullscreen_dialog is not None:
            self.fullscreen_dialog.reject()
            return
        dialog = QDialog(self)
        self.fullscreen_dialog = dialog
        dialog.setWindowTitle("표 양식 전체화면 편집")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)
        self._design_tab_index = self.editor_tabs.indexOf(self.design_tab)
        self.editor_tabs.removeTab(self._design_tab_index)
        layout.addWidget(self.design_tab, stretch=1)
        self.design_tab.show()
        footer = QHBoxLayout()
        footer.addWidget(QLabel("Esc로 돌아가기 · 편집 내용은 유지됩니다. 저장하려면 ‘내 양식 저장’을 누르세요."))
        footer.addStretch()
        save = QPushButton("내 양식 저장")
        set_button_role(save, "primary")
        save.clicked.connect(self.save_template)
        footer.addWidget(save)
        done = QPushButton("편집 마치기")
        done.clicked.connect(dialog.accept)
        footer.addWidget(done)
        layout.addLayout(footer)
        self.fullscreen_button.setText("전체화면 나가기")
        dialog.finished.connect(self.restore_design_editor)
        dialog.showFullScreen()
        self.form_editor.setFocus()

    def restore_design_editor(self, _result=0):
        dialog = self.fullscreen_dialog
        if dialog is None:
            return
        dialog.layout().removeWidget(self.design_tab)
        self.editor_tabs.insertTab(self._design_tab_index, self.design_tab, "표 양식 디자인")
        self.editor_tabs.setCurrentWidget(self.design_tab)
        self.design_tab.show()
        self.fullscreen_button.setText("전체화면 편집")
        self.fullscreen_dialog = None
        dialog.deleteLater()
        self.form_editor.setFocus()

    def set_storage_path(self, db_path: str) -> None:
        """전체 경로는 데이터 관리 · 데이터 백업·복원 탭에서 보여주므로 여기서는 파일명만 남긴다.

        긴 절대 경로를 그대로 붙이면 이 화면의 최소 너비가 경로 길이만큼 늘어나
        1366×768 노트북에서 가로 스크롤이 생기기 때문이다.
        """
        self.storage_label.setText(f"로컬 저장: {os.path.basename(db_path)}")
        self.storage_label.setToolTip(db_path)

    def set_profile(self, profile_id: int) -> None:
        self.profile_id = profile_id
        self.current_template_id = None
        self.current_source_key = None
        self.refresh_templates()

    def refresh_templates(self, select_id: int = None) -> None:
        if select_id is None and self.has_unsaved_changes():
            return
        select_id = select_id or self.current_template_id
        profile = self.db.get_profile(self.profile_id) or {"name": "알 수 없음"}
        self.owner_label.setText(f"현재 사용자: {profile['name']} · 이 사용자에게만 적용")
        self.refresh_approval_preview()
        templates = self.db.list_form_templates(self.profile_id)
        self.template_list.blockSignals(True)
        self.template_list.clear()
        target_row = 0
        for row, template in enumerate(templates):
            badge = "기본" if template.get("source_key") else "사용자 제작"
            item = QListWidgetItem(f"{template['name']}\n{template['category']} · {badge}")
            item.setData(Qt.ItemDataRole.UserRole, template["id"])
            self.template_list.addItem(item)
            if select_id and template["id"] == select_id:
                target_row = row
        self.template_list.blockSignals(False)
        if templates:
            self.template_list.setCurrentRow(target_row)
            self._load_template(templates[target_row])
        else:
            self.new_template()

    def _load_selected(self, current, _previous) -> None:
        if current:
            target_id = current.data(Qt.ItemDataRole.UserRole)
            if not self.may_leave():
                self.template_list.blockSignals(True)
                self.template_list.setCurrentItem(_previous)
                self.template_list.blockSignals(False)
                return
            template = self.db.get_form_template(target_id, self.profile_id)
            if template:
                self._load_template(template)

    def _load_template(self, template: dict) -> None:
        self.current_template_id = template["id"]
        self.current_source_key = template.get("source_key")
        self.name_input.setText(template.get("name", ""))
        self.category_input.setText(template.get("category", ""))
        self.description_input.setPlainText(template.get("description", ""))
        self.guide_input.setPlainText(template.get("guide", ""))
        self.form_editor.setHtml(
            template.get("form_html", "") or build_form_html(template.get("name", "서류 양식"), template.get("guide", ""))
        )
        self.sample_input.setPlainText(template.get("example_input", ""))
        self.reset_btn.setEnabled(bool(self.current_source_key))
        # 기본 양식은 개인 사본이라 수정·초기화할 수 있지만 실수로 목록에서 제거되지는 않습니다.
        self.delete_btn.setEnabled(not bool(self.current_source_key))
        self.duplicate_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self._baseline = self._editor_data()
        self.form_editor.document().setModified(False)

    def new_template(self) -> None:
        if not self.may_leave():
            return
        self.template_list.clearSelection()
        self.current_template_id = None
        self.current_source_key = None
        self.name_input.clear()
        self.category_input.setText("상담기록")
        self.description_input.clear()
        self.guide_input.setPlainText(NEW_TEMPLATE_GUIDE)
        self.form_editor.setHtml(build_blank_form_html())
        self.sample_input.clear()
        self.reset_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.duplicate_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.name_input.setFocus()
        self._baseline = self._editor_data()
        self.form_editor.document().setModified(False)

    def has_unsaved_changes(self):
        if not hasattr(self, '_baseline'):
            return False
        # 화면 스타일이 바꾼 문서 기본 글꼴을 사용자 편집으로 오인하지 않는다.
        data = self._editor_data()
        return self.form_editor.document().isModified() or any(
            data[key] != self._baseline[key] for key in data if key != 'form_html')

    def may_leave(self):
        if not self.has_unsaved_changes():
            return True
        box = QMessageBox(self)
        box.setWindowTitle('양식 변경 내용')
        box.setText('수정한 양식을 저장할까요?')
        save = box.addButton('저장하고 계속', QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton('변경 버리기', QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton('계속 편집', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() == save:
            return bool(self.save_template())
        if box.clickedButton() == discard:
            self._baseline = self._editor_data()
            self.form_editor.document().setModified(False)
            return True
        return False

    def _editor_data(self) -> dict:
        return {
            "name": self.name_input.text(),
            "category": self.category_input.text(),
            "description": self.description_input.toPlainText(),
            "guide": self.guide_input.toPlainText(),
            "form_html": self.form_editor.document_html(),
            "example_input": self.sample_input.toPlainText(),
        }

    def save_template(self) -> None:
        try:
            template_id = self.db.save_form_template(
                self.profile_id,
                self._editor_data(),
                template_id=self.current_template_id,
            )
        except Exception as exc:
            QMessageBox.warning(self, "양식 저장 확인", str(exc))
            return False
        self.current_template_id = template_id
        self._baseline = self._editor_data()
        self.form_editor.document().setModified(False)
        self.refresh_templates(select_id=template_id)
        self._notify_changed()
        return True

    def duplicate_template(self) -> None:
        if not self.may_leave():
            return
        if not self.current_template_id:
            return
        try:
            template_id = self.db.duplicate_form_template(self.current_template_id, self.profile_id)
        except ValueError as exc:
            QMessageBox.warning(self, "양식 복사", str(exc))
            return
        self.refresh_templates(select_id=template_id)
        self._notify_changed()

    def delete_template(self) -> None:
        if not self.current_template_id or self.current_source_key:
            return
        reply = QMessageBox.question(
            self,
            "사용자 제작 양식 삭제",
            f"'{self.name_input.text()}' 양식을 삭제하시겠습니까?\n이미 작성한 과거 상담기록은 그대로 보존됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_form_template(self.current_template_id, self.profile_id)
            self.current_template_id = None
            self.refresh_templates()
            self._notify_changed()

    def reset_template(self) -> None:
        if not self.current_template_id or not self.current_source_key:
            return
        reply = QMessageBox.question(
            self,
            "기본 양식 복원",
            "이 양식의 개인 수정 내용을 지우고 최초 기본값으로 되돌리시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = self.db.reset_form_template(self.current_template_id, self.profile_id, TEMPLATES)
        except Exception as exc:
            QMessageBox.warning(self, "복원 실패", str(exc))
            return
        if restored:
            self.refresh_templates(select_id=self.current_template_id)
            self._notify_changed()

    def export_template(self) -> None:
        template = self.db.get_form_template(self.current_template_id, self.profile_id)
        if not template:
            return
        safe_name = "".join(
            "_" if char in '\\/:*?\"<>|' else char
            for char in template["name"]
        ).strip() or "서류_양식"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "서류 양식 내보내기",
            f"{safe_name}.json",
            "서류 양식 JSON (*.json)",
        )
        if not filename:
            return
        payload = {
            "schema_version": 2,
            "template": {
                key: template.get(key, "")
                for key in ("name", "category", "description", "guide", "form_html", "example_input")
            },
        }
        try:
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "내보내기 완료", f"양식 파일을 저장했습니다.\n{filename}")
        except OSError as exc:
            QMessageBox.critical(self, "내보내기 실패", str(exc))

    def import_template(self) -> None:
        if not self.may_leave():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "서류 양식 가져오기",
            "",
            "서류 양식 JSON (*.json)",
        )
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as file:
                payload = json.load(file)
            data = payload.get("template", payload)
            if not isinstance(data, dict):
                raise ValueError("올바른 서류 양식 파일이 아닙니다.")
            template_id = self.db.save_form_template(self.profile_id, data)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(self, "가져오기 실패", str(exc))
            return
        self.refresh_templates(select_id=template_id)
        self._notify_changed()
        QMessageBox.information(self, "가져오기 완료", "가져온 양식을 현재 사용자에게 저장했습니다.")

    def _notify_changed(self) -> None:
        if self.on_templates_changed:
            self.on_templates_changed()

    @staticmethod
    def _make_color_button(color: str, handler, tooltip: str) -> QPushButton:
        button = QPushButton("")
        button.setFixedSize(25, 25)
        button.setToolTip(f"{tooltip} · {color}")
        border = "#AEBDB8" if color.upper() == "#FFFFFF" else color
        button.setStyleSheet(
            f"QPushButton {{ background:{color};border:1px solid {border};border-radius:5px;padding:0; }}"
            "QPushButton:hover { border:2px solid #176B5B; }"
            "QPushButton:focus { border:2px solid #D99132; }"
        )
        button.clicked.connect(handler)
        return button

    def filter_element_palette(self, query: str) -> None:
        self.element_palette.filter_elements(query)

    def apply_canvas_zoom(self, value: str) -> None:
        try:
            percent = int(value.replace("%", "").strip())
        except (TypeError, ValueError):
            return
        self.form_editor.set_zoom(percent)

    def update_selection_context(self) -> None:
        cursor = self.form_editor.textCursor()
        context = self.form_editor.selected_context()
        self.context_label.setText(context)
        if context == "표 셀":
            self.selection_hint.setText("현재 셀의 글자·정렬·배경색과 표 구조를 바꿀 수 있습니다.")
        elif context == "선택한 글자":
            self.selection_hint.setText("선택한 글자에만 글꼴·크기·색상·강조가 적용됩니다.")
        else:
            self.selection_hint.setText("글자를 선택하거나 표 셀을 클릭하면 해당 설정이 나타납니다.")

        char_format = cursor.charFormat()
        current_font = char_format.font()
        family = current_font.family() or "Batang"
        point_size = char_format.fontPointSize()
        if point_size <= 0:
            point_size = current_font.pointSizeF()
        if point_size <= 0:
            point_size = 10.0

        self.font_combo.blockSignals(True)
        self.font_size_combo.blockSignals(True)
        self.font_combo.setCurrentFont(QFont(family))
        self.font_size_combo.setCurrentText(str(int(point_size)) if point_size.is_integer() else f"{point_size:g}")
        self.font_combo.blockSignals(False)
        self.font_size_combo.blockSignals(False)

        has_selection = cursor.hasSelection()
        self.duplicate_selection_btn.setEnabled(has_selection)
        self.delete_selection_btn.setEnabled(has_selection)

    def duplicate_selected_content(self) -> None:
        if self.form_editor.duplicate_selection():
            self.update_selection_context()

    def delete_selected_content(self) -> None:
        if self.form_editor.delete_selection():
            self.update_selection_context()

    def show_form_preview(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("인쇄 형태 미리보기")
        dialog.resize(760, 860)
        layout = QVBoxLayout(dialog)
        header = QLabel("A4 출력 시 보이는 형태 · 결재라인 포함")
        header.setStyleSheet("font-weight:800;color:#405753;padding:4px;")
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setHtml(inject_approval_line(
            self.form_editor.document_html(),
            self.db.get_approval_line(self.profile_id),
        ))
        preview.setStyleSheet(
            "QTextEdit { background:#FFFDFC;color:#243532;border:1px solid #B9C8C3;padding:28px 34px; }"
        )
        close_btn = QPushButton("미리보기 닫기")
        set_button_role(close_btn, "primary")
        close_btn.clicked.connect(dialog.accept)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(close_btn)
        layout.addWidget(header)
        layout.addWidget(preview, stretch=1)
        layout.addLayout(actions)
        dialog.exec()

    def refresh_approval_preview(self) -> None:
        steps = self.db.get_approval_line(self.profile_id)
        self.approval_preview.setHtml(render_approval_line_html(steps))

    def open_approval_line_editor(self) -> None:
        dialog = ApprovalLineDialog(self.db.get_approval_line(self.profile_id), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.db.save_approval_line(self.profile_id, dialog.approval_steps())
        except ValueError as exc:
            QMessageBox.warning(self, "결재라인 저장", str(exc))
            return
        self.refresh_approval_preview()
        QMessageBox.information(
            self,
            "결재라인 저장 완료",
            "현재 사용자의 결재라인을 저장했습니다. 새로 작성하는 모든 양식 우측 상단에 적용됩니다.",
        )

    def _table_context(self, show_message: bool = True):
        cursor = self.form_editor.textCursor()
        table = cursor.currentTable()
        if table is None and show_message:
            QMessageBox.information(self, "표 편집", "먼저 표 안의 셀을 클릭해 주세요.")
        return cursor, table

    def insert_table(self) -> None:
        rows, accepted = QInputDialog.getInt(self, "표 삽입", "행 개수:", 3, 1, 30)
        if not accepted:
            return
        columns, accepted = QInputDialog.getInt(self, "표 삽입", "열 개수:", 2, 1, 10)
        if not accepted:
            return
        self.form_editor.textCursor().insertTable(rows, columns, make_table_format())

    def add_table_row(self) -> None:
        cursor, table = self._table_context()
        if table:
            cell = table.cellAt(cursor)
            table.insertRows(cell.row() + cell.rowSpan(), 1)

    def remove_table_row(self) -> None:
        cursor, table = self._table_context()
        if table:
            if table.rows() <= 1:
                QMessageBox.information(self, "표 편집", "마지막 행은 삭제할 수 없습니다.")
                return
            table.removeRows(table.cellAt(cursor).row(), 1)

    def add_table_column(self) -> None:
        cursor, table = self._table_context()
        if table:
            cell = table.cellAt(cursor)
            table.insertColumns(cell.column() + cell.columnSpan(), 1)

    def remove_table_column(self) -> None:
        cursor, table = self._table_context()
        if table:
            if table.columns() <= 1:
                QMessageBox.information(self, "표 편집", "마지막 열은 삭제할 수 없습니다.")
                return
            table.removeColumns(table.cellAt(cursor).column(), 1)

    def merge_table_cells(self) -> None:
        cursor, table = self._table_context()
        if not table:
            return
        first_row, row_count, first_column, column_count = cursor.selectedTableCells()
        if row_count <= 0 or column_count <= 0 or row_count * column_count < 2:
            QMessageBox.information(self, "셀 합치기", "합칠 셀을 마우스로 드래그해 두 칸 이상 선택해 주세요.")
            return
        table.mergeCells(first_row, first_column, row_count, column_count)

    def split_table_cell(self) -> None:
        cursor, table = self._table_context()
        if not table:
            return
        cell = table.cellAt(cursor)
        if cell.rowSpan() == 1 and cell.columnSpan() == 1:
            QMessageBox.information(self, "셀 나누기", "현재 셀은 합쳐진 셀이 아닙니다.")
            return
        table.splitCell(cell.row(), cell.column(), cell.rowSpan(), cell.columnSpan())

    def toggle_bold(self) -> None:
        cursor = self.form_editor.textCursor()
        char_format = QTextCharFormat()
        weight = (
            QFont.Weight.Normal
            if cursor.charFormat().fontWeight() >= QFont.Weight.Bold.value
            else QFont.Weight.Bold
        )
        char_format.setFontWeight(weight)
        self._apply_char_format(char_format)

    def toggle_italic(self) -> None:
        char_format = QTextCharFormat()
        char_format.setFontItalic(not self.form_editor.textCursor().charFormat().fontItalic())
        self._apply_char_format(char_format)

    def toggle_underline(self) -> None:
        char_format = QTextCharFormat()
        char_format.setFontUnderline(not self.form_editor.textCursor().charFormat().fontUnderline())
        self._apply_char_format(char_format)

    def apply_font_family(self, font: QFont) -> None:
        char_format = QTextCharFormat()
        char_format.setFontFamilies([font.family()])
        self._apply_char_format(char_format)

    def apply_font_size(self, value: str) -> None:
        try:
            size = float(value)
        except (TypeError, ValueError):
            return
        if not 6 <= size <= 72:
            return
        char_format = QTextCharFormat()
        char_format.setFontPointSize(size)
        self._apply_char_format(char_format)

    def choose_font_color(self) -> None:
        color = QColorDialog.getColor(QColor("#202C29"), self, "글자 색상 선택")
        if color.isValid():
            self.apply_font_color(color)

    def apply_font_color(self, color) -> None:
        color = QColor(color)
        if not color.isValid():
            return
        char_format = QTextCharFormat()
        char_format.setForeground(color)
        self._apply_char_format(char_format)

    def choose_text_background(self) -> None:
        color = QColorDialog.getColor(QColor("#FFF1A8"), self, "글자 강조 색상 선택")
        if color.isValid():
            char_format = QTextCharFormat()
            char_format.setBackground(color)
            self._apply_char_format(char_format)

    def choose_cell_background(self) -> None:
        color = QColorDialog.getColor(QColor("#E4EFEB"), self, "표 셀 배경 색상 선택")
        if color.isValid():
            self.apply_cell_background(color)

    def apply_cell_background(self, color) -> None:
        cursor, table = self._table_context()
        color = QColor(color)
        if not table or not color.isValid():
            return
        cell = table.cellAt(cursor)
        cell_format = cell.format()
        cell_format.setBackground(color)
        cell.setFormat(cell_format)

    def _apply_char_format(self, char_format: QTextCharFormat) -> None:
        cursor = self.form_editor.textCursor()
        cursor.mergeCharFormat(char_format)
        self.form_editor.mergeCurrentCharFormat(char_format)

    def set_alignment(self, alignment) -> None:
        self.form_editor.setAlignment(alignment)

    def insert_checkbox(self) -> None:
        self.form_editor.textCursor().insertText("☐ ")

    def insert_placeholder(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "입력칸 추가",
            "입력칸 이름을 적어 주세요 (예: 상담 내용):",
        )
        if accepted and name.strip():
            self.form_editor.textCursor().insertText("{{" + name.strip() + "}}")
