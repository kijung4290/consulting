"""애플리케이션 전역 디자인 토큰과 재사용 가능한 UI 구성요소."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


COLORS = {
    "ink": "#172A2A",
    "muted": "#60706D",
    "canvas": "#F4F7F5",
    "surface": "#FFFFFF",
    "line": "#D9E2DE",
    "primary": "#176B5B",
    "primary_hover": "#115346",
    "primary_soft": "#E3F0EC",
    "accent": "#D99132",
    "danger": "#B83A4B",
    "danger_soft": "#FCEBED",
}


def set_button_role(button: QPushButton, role: str = "secondary") -> QPushButton:
    """버튼의 의미에 맞는 전역 스타일 역할을 지정합니다."""
    button.setProperty("role", role)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def make_page_header(title: str, description: str, eyebrow: str) -> QFrame:
    """모든 주요 화면에서 동일하게 쓰는 기록지형 페이지 머리말."""
    frame = QFrame()
    frame.setObjectName("pageHeader")

    root = QHBoxLayout(frame)
    root.setContentsMargins(14, 10, 14, 10)
    root.setSpacing(14)

    marker = QFrame()
    marker.setObjectName("caseMarker")
    marker.setFixedWidth(5)
    root.addWidget(marker)

    text_layout = QVBoxLayout()
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)

    eyebrow_label = QLabel(eyebrow)
    eyebrow_label.setObjectName("pageEyebrow")
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    description_label = QLabel(description)
    description_label.setObjectName("pageDescription")
    description_label.setWordWrap(True)

    # 실제 업무 제목과 안내를 우선 표시한다.
    eyebrow_label.hide()
    text_layout.addWidget(title_label)
    text_layout.addWidget(description_label)
    root.addLayout(text_layout, stretch=1)
    return frame


def make_action_card(
    title: str,
    description: str,
    button_text: str,
    handler,
    role: str = "secondary",
) -> QFrame:
    """한 가지 작업과 결과만 설명하는 데이터 관리용 액션 카드."""
    card = QFrame()
    card.setObjectName("actionCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(7)

    title_label = QLabel(title)
    title_label.setObjectName("actionCardTitle")
    description_label = QLabel(description)
    description_label.setObjectName("actionCardDescription")
    description_label.setWordWrap(True)

    button = QPushButton(button_text)
    set_button_role(button, role)
    if role == "primary":
        button.setObjectName("primaryActionButton")
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: #FFFFFF;
                border: 1px solid {COLORS['primary']};
                border-radius: 7px;
                font-weight: 800;
            }}
            QPushButton:hover {{ background-color: {COLORS['primary_hover']}; }}
            QPushButton:focus {{ border: 2px solid {COLORS['accent']}; }}
        """)
    button.setMinimumHeight(40)
    button.clicked.connect(handler)

    layout.addWidget(title_label)
    layout.addWidget(description_label)
    layout.addStretch()
    layout.addWidget(button)
    return card


APP_STYLESHEET = f"""
    QWidget {{ font-family: "Malgun Gothic", "Noto Sans KR", sans-serif; font-size: 12px; }}
    QMainWindow {{
        background-color: {COLORS['canvas']};
        font-family: "Pretendard", "Noto Sans KR", "Segoe UI", "Malgun Gothic", sans-serif;
        color: {COLORS['ink']};
    }}
    QWidget#pageRoot {{ background-color: {COLORS['canvas']}; }}
    #sidebar {{
        background-color: #163B37;
        border-right: 1px solid #214A45;
    }}
    #brandTitle {{ color: #FFFFFF; font-size: 17px; font-weight: 800; }}
    #brandSubtitle {{ color: #A9C4BE; font-size: 11px; }}
    #navSection {{ color: #789B94; font-size: 10px; font-weight: 800; padding: 14px 12px 2px 12px; }}
    #navBtn {{
        min-height: 20px;
        text-align: left;
        padding: 8px 14px;
        background-color: transparent;
        color: #BBD0CB;
        border: none;
        border-radius: 7px;
        font-weight: 650;
        font-size: 13px;
        margin: 1px 0;
    }}
    #navBtn:hover {{ background-color: #214A45; color: #FFFFFF; }}
    #navBtn:checked {{
        background-color: #F1F7F4;
        color: #174E45;
        font-weight: 800;
        border-left: 4px solid {COLORS['accent']};
        padding-left: 10px;
    }}
    #pageHeader {{
        background-color: {COLORS['surface']};
        border: 1px solid {COLORS['line']};
        border-radius: 10px;
    }}
    #caseMarker {{ background-color: {COLORS['accent']}; border-radius: 2px; }}
    #pageEyebrow {{ color: {COLORS['primary']}; font-size: 10px; font-weight: 800; letter-spacing: 1px; }}
    #pageTitle {{ color: {COLORS['ink']}; font-size: 19px; font-weight: 850; }}
    #pageDescription {{ color: {COLORS['muted']}; font-size: 11px; }}
    #actionCard {{ background-color: #F8FBF9; border: 1px solid {COLORS['line']}; border-radius: 9px; }}
    #actionCardTitle {{ color: {COLORS['ink']}; font-size: 15px; font-weight: 800; }}
    #actionCardDescription {{ color: {COLORS['muted']}; font-size: 11px; }}
    #storageBar {{ background-color: #EAF1EE; border: 1px solid #CFDCD7; border-radius: 8px; }}
    #storagePath {{ color: #36534E; font-family: Consolas, "Malgun Gothic"; font-size: 11px; }}
    #sectionHint {{ color: {COLORS['muted']}; font-size: 12px; padding: 2px 0; }}
    #draftStatus {{ color: {COLORS['primary']}; background: {COLORS['primary_soft']}; padding: 8px; border-radius: 6px; font-size: 12px; }}
    #warningHint {{ background-color: #FFF6E8; color: #805215; border: 1px solid #F0D6AA; border-radius: 7px; padding: 8px 10px; font-size: 11px; }}
    #caseSelector {{ background-color: #EAF1EE; border: 1px solid #CFDCD7; border-radius: 8px; }}
    #caseSummary {{ color: #4E6661; font-size: 11px; }}
    #caseDueButton {{ text-align: left; background-color: #EAF3F0; color: #176B5B; border: 1px solid #C6DBD5; padding: 8px 12px; font-weight: 750; }}
    #caseDueButton[attention="true"] {{ background-color: #FCEBED; color: #A62F40; border-color: #EDC2C8; }}
    #writingModeBar {{ background-color: #EAF1EE; border: 1px solid #CFDCD7; border-radius: 8px; }}
    #activeWritingMode {{ background-color: {COLORS['primary']}; color: #FFFFFF; border: none; font-weight: 800; }}
    #activeWritingMode:hover {{ background-color: {COLORS['primary_hover']}; }}
    #writingModeHint {{ color: #5E716D; font-size: 11px; padding-left: 6px; }}
    #reportTitle {{ color: {COLORS['ink']}; font-size: 20px; font-weight: 850; }}
    #reportCount {{ color: {COLORS['primary']}; font-size: 12px; font-weight: 800; padding: 3px 0; }}
    #reportPreview {{ background-color: #FFFFFF; border: 1px solid {COLORS['line']}; border-radius: 8px; padding: 8px; }}
    QGroupBox {{
        font-weight: 750;
        font-size: 13px;
        color: {COLORS['ink']};
        border: 1px solid {COLORS['line']};
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 18px;
        background-color: {COLORS['surface']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
        left: 12px;
        color: #344B48;
    }}
    QPushButton {{
        min-height: 26px;
        padding: 4px 10px;
        border-radius: 7px;
        border: 1px solid #BBCAC5;
        background-color: #FFFFFF;
        color: #314744;
        font-weight: 650;
    }}
    QPushButton:hover {{ background-color: #F0F5F3; border-color: #8BA59E; }}
    #compactButton {{ min-height: 18px; padding: 3px 8px; font-size: 11px; }}
    QPushButton:focus {{ border: 2px solid {COLORS['primary']}; padding: 4px 11px; }}
    QPushButton:disabled {{ background-color: #EDF1EF; color: #9AA8A4; border-color: #DCE4E1; }}
    QPushButton[role="primary"] {{ background-color: {COLORS['primary']}; color: #FFFFFF; border: none; font-weight: 800; }}
    QPushButton[role="primary"]:hover {{ background-color: {COLORS['primary_hover']}; }}
    #primaryActionButton {{ background-color: {COLORS['primary']}; color: #FFFFFF; border: none; font-weight: 800; }}
    #primaryActionButton:hover {{ background-color: {COLORS['primary_hover']}; }}
    QPushButton[role="soft"] {{ background-color: {COLORS['primary_soft']}; color: #145A4D; border-color: #B9D5CD; }}
    QPushButton[role="danger"] {{ background-color: {COLORS['danger_soft']}; color: {COLORS['danger']}; border-color: #F0C6CC; }}
    QPushButton[role]:disabled {{ background-color: #EDF1EF; color: #71847D; border: 1px solid #DCE4E1; }}
    QPushButton[role]:focus {{ border: 2px solid {COLORS['accent']}; }}
    QMenu {{ background: #FFFFFF; color: {COLORS['ink']}; padding: 6px; border: 1px solid {COLORS['line']}; }}
    QMenu::item {{ padding: 8px 20px; }}
    QMenu::item:selected {{ background: {COLORS['primary_soft']}; }}
    QMenu::item:disabled {{ color: #71847D; }}
    QTableWidget {{
        background-color: #FFFFFF;
        alternate-background-color: #F8FAF9;
        border: 1px solid {COLORS['line']};
        border-radius: 9px;
        gridline-color: #EBF0EE;
        selection-background-color: #DCEDE8;
        selection-color: #123F37;
        font-size: 12px;
        outline: none;
    }}
    QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #EDF1EF; }}
    QHeaderView::section {{
        background-color: #EAF1EE;
        padding: 9px 12px;
        border: none;
        border-bottom: 1px solid #C8D6D1;
        font-weight: 800;
        font-size: 11px;
        color: #405753;
    }}
    QTextEdit, QLineEdit, QComboBox, QDateEdit, QSpinBox {{
        border: 1px solid #C9D5D1;
        border-radius: 7px;
        padding: 7px 10px;
        background-color: #FFFFFF;
        color: {COLORS['ink']};
        font-size: 13px;
        selection-background-color: #BBDDD4;
    }}
    QTextEdit:hover, QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover {{ border-color: #94AAA4; }}
    QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{ border: 2px solid {COLORS['primary']}; }}
    QComboBox {{ min-height: 29px; }}
    QCheckBox {{ font-size: 12px; color: #344B48; font-weight: 650; spacing: 8px; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border: 1px solid #AFC1BC; border-radius: 4px; background: #FFFFFF; }}
    QCheckBox::indicator:checked {{ background-color: {COLORS['primary']}; border-color: {COLORS['primary']}; }}
    QTabWidget::pane {{ background: #FFFFFF; border: 1px solid {COLORS['line']}; border-radius: 8px; top: -1px; }}
    QTabBar::tab {{ background: #EAF1EE; color: #516762; padding: 9px 16px; border: 1px solid #D3DEDA; border-bottom: none; margin-right: 2px; font-weight: 700; }}
    QTabBar::tab:selected {{ background: #FFFFFF; color: {COLORS['primary']}; border-top: 3px solid {COLORS['accent']}; padding-top: 7px; }}
    QSplitter::handle {{ background-color: #D3DFDB; width: 4px; border-radius: 2px; }}
    QSplitter::handle:hover {{ background-color: {COLORS['accent']}; }}
    QStatusBar {{ background-color: #FFFFFF; border-top: 1px solid {COLORS['line']}; color: #5F716D; font-size: 11px; padding: 5px 10px; }}
    QProgressBar {{ border: 1px solid {COLORS['line']}; border-radius: 5px; background: #EDF2F0; text-align: center; }}
    QProgressBar::chunk {{ background-color: {COLORS['primary']}; border-radius: 4px; }}
    QScrollBar:vertical {{ border: none; background: #EDF2F0; width: 9px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #B5C6C1; border-radius: 4px; min-height: 30px; }}
"""
