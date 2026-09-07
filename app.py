"""
사회복지 스마트 사례관리 SaaS 어시스턴트 - PyQt6 데스크톱 프로그램
- 📊 업무 대시보드 (KPI 통계, 최근 상담 요약)
- 👥 대상자 통합 관리 (신규 등록, 검색/필터, 위기도 관리, 상세 이력)
- 📝 AI 상담일지 작성실 (Gemma-2 로컬 보안 AI + 13대 서식 + 대상자 자동 연동 및 영구 저장)
- 📂 서류/문서 보관함 (초기면접지, 동의서, HWP/PDF 원클릭 열람)
- ⚙️ 데이터 관리 및 백업 (SQLite DB 원클릭 USB 백업/복원)
"""

import os
import sys

# pythonw.exe 실행 시 stdout/stderr가 None이어 crash되는 현상 방지
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QComboBox, QPushButton, QCheckBox, QLineEdit,
    QProgressBar, QSplitter, QGroupBox, QFileDialog, QMessageBox,
    QStatusBar, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QScrollArea, QInputDialog, QDateEdit, QDialog
)
from PyQt6.QtCore import Qt, QEvent, QMimeData, QDate
from PyQt6.QtGui import QFont, QKeySequence, QShortcut

# 내부 모듈 로드
import config
from database import Database
from dialogs import (
    ClientDialog, ClientDetailDialog, DocumentAddDialog,
    ManualCounselingDialog, TextViewerDialog, open_system_file
)
from setup_dialog import StorageSetupDialog
from anonymizer import Anonymizer
from prompts import TEMPLATES, build_prompt
from engine import InferenceEngine
from client_context import ContextController
from download_model import get_model_path, is_model_downloaded
from ui_theme import APP_STYLESHEET, make_action_card, make_page_header, set_button_role
from workers import DownloadWorker, GenerationWorker, ModelLoadWorker
from case_management import CaseManagementPage
from counseling_report import CounselingReportDialog
from template_manager import TemplateManagerPage
from form_document import build_form_html, fill_form_html, inject_approval_line

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("복지상담 기록실 · 로컬 AI 사례관리")
        
        # 윈도우/리눅스 창 제어 플래그 명시 (리눅스 민트에서 최대화 및 전체화면 지원 보장)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        # 저해상도 노트북(1280x720, 1366x768)에서도 창이 잘리지 않도록 최소 크기 최적화
        self.setMinimumSize(880, 540)
        self.resize(1200, 780)

        # 최초 실행 시 데이터 저장 폴더 설정 다이얼로그 표시
        if config.is_first_run():
            setup_dlg = StorageSetupDialog(self)
            setup_dlg.exec()

        self.db = Database(data_dir=config.get_data_dir())
        self.current_profile = self.db.get_current_profile()
        self.db.ensure_builtin_templates(self.current_profile["id"], TEMPLATES)
        self.anonymizer = Anonymizer()
        self.model_path = get_model_path()
        self.engine = InferenceEngine(self.model_path)
        self.worker = None
        self.download_worker = None
        self.model_load_worker = None
        self.pending_prompt = None
        self.last_generated_raw_text = ""

        self.init_ui()
        self.apply_styling()
        self.check_and_load_model()
        self.refresh_all_data()

        self.context_controller = ContextController(self)

    def closeEvent(self, event):
        self.context_controller.stop()
        for worker in (self.worker, self.model_load_worker):
            if worker and worker.isRunning():
                self.engine.abort()
                worker.wait()
        super().closeEvent(event)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ================= [좌측: SaaS 네비게이션 사이드바] =================
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(8)

        # 앱 브랜드: 현장의 '상담 기록지'를 닮은 차분한 업무 도구
        app_title = QLabel("복지상담 기록실")
        app_title.setObjectName("brandTitle")
        app_subtitle = QLabel("LOCAL CASEWORK DESK")
        app_subtitle.setObjectName("brandSubtitle")

        sidebar_layout.addWidget(app_title)
        sidebar_layout.addWidget(app_subtitle)

        nav_section = QLabel("업무 메뉴")
        nav_section.setObjectName("navSection")
        sidebar_layout.addWidget(nav_section)

        # 메뉴 버튼들
        self.nav_btns = []
        menus = [
            ("업무 현황", 0),
            ("대상자 관리", 1),
            ("사례관리", 2),
            ("상담일지 작성", 3),
            ("서류 보관함", 4),
            ("서류 양식 관리", 5),
            ("데이터 관리", 6)
        ]

        for text, page_idx in menus:
            btn = QPushButton(text)
            btn.setObjectName("navBtn")
            btn.setFont(QFont("Malgun Gothic", 10))
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.clicked.connect(lambda checked, idx=page_idx: self.switch_page(idx))
            sidebar_layout.addWidget(btn)
            self.nav_btns.append(btn)

        self.nav_btns[0].setChecked(True)

        sidebar_layout.addStretch()

        profile_label = QLabel("현재 사용자")
        profile_label.setObjectName("navSection")
        sidebar_layout.addWidget(profile_label)
        profile_row = QHBoxLayout()
        profile_row.setSpacing(5)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        add_profile_btn = QPushButton("＋")
        add_profile_btn.setToolTip("새 사용자 프로필 만들기")
        add_profile_btn.setFixedWidth(34)
        add_profile_btn.clicked.connect(self.add_profile)
        profile_row.addWidget(self.profile_combo, stretch=1)
        profile_row.addWidget(add_profile_btn)
        sidebar_layout.addLayout(profile_row)

        # 전체화면 / 창모드 전환 버튼 (리눅스 및 윈도우 공통 지원)
        self.fullscreen_btn = QPushButton("⛶ 전체화면 (F11)")
        self.fullscreen_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: #CBD5E1;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 600;
                font-size: 11px;
                text-align: center;
                margin-bottom: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.16);
                color: #FFFFFF;
                border-color: #64748B;
            }
        """)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        sidebar_layout.addWidget(self.fullscreen_btn)

        # 보안 배지
        security_box = QGroupBox()
        security_box.setStyleSheet("background-color: #102F2B; border: 1px solid #2C5751; border-radius: 7px; padding: 6px;")
        sec_layout = QVBoxLayout(security_box)
        sec_label = QLabel("● 로컬 처리 중")
        sec_label.setStyleSheet("color: #7FD1BF; font-weight: bold; font-size: 11px;")
        sec_desc = QLabel("AI 입력은 외부로 전송하지 않음\n데이터는 지정 폴더에 보관")
        sec_desc.setStyleSheet("color: #94A3B8; font-size: 10px;")
        sec_layout.addWidget(sec_label)
        sec_layout.addWidget(sec_desc)
        sidebar_layout.addWidget(security_box)

        root_layout.addWidget(sidebar)

        # ================= [우측: 스택 위젯 (메인 화면들)] =================
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.create_dashboard_page())  # Page 0
        self.stacked_widget.addWidget(self.create_clients_page())    # Page 1
        self.case_management_page = CaseManagementPage(self.db, self)
        self.case_management_page.status_message.connect(lambda message: self.status_bar.showMessage(message, 4000))
        self.stacked_widget.addWidget(self.case_management_page)     # Page 2
        self.stacked_widget.addWidget(self.create_ai_counsel_page()) # Page 3
        self.stacked_widget.addWidget(self.create_documents_page())  # Page 4
        self.template_manager_page = TemplateManagerPage(
            self.db,
            self.current_profile["id"],
            on_templates_changed=self.refresh_template_combo,
            parent=self,
        )
        self.stacked_widget.addWidget(self.template_manager_page)     # Page 5
        self.stacked_widget.addWidget(self.create_settings_page())    # Page 6

        root_layout.addWidget(self.stacked_widget, stretch=1)
        self.refresh_profile_combo()

        # 하단 상태바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_model_label = QLabel("모델: 확인 중...")
        self.status_sys_label = QLabel("시스템: 준비 중")
        self.status_speed_label = QLabel("속도: 대기 중")

        self.status_bar.addWidget(self.status_model_label, stretch=2)
        self.status_bar.addWidget(self.status_sys_label, stretch=2)
        self.status_bar.addPermanentWidget(self.status_speed_label)

        # 단축키 설정
        shortcut_run = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_run.activated.connect(self.start_generation)

        shortcut_esc = QShortcut(QKeySequence("Escape"), self)
        shortcut_esc.activated.connect(self.stop_generation)

        # F11 전체화면 단축키
        shortcut_f11 = QShortcut(QKeySequence("F11"), self)
        shortcut_f11.activated.connect(self.toggle_fullscreen)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if hasattr(self, 'fullscreen_btn'):
                self.fullscreen_btn.setText("⛶ 전체화면 (F11)")
        else:
            self.showFullScreen()
            if hasattr(self, 'fullscreen_btn'):
                self.fullscreen_btn.setText("🗗 창모드 복귀 (F11)")

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, 'fullscreen_btn'):
                if self.isFullScreen():
                    self.fullscreen_btn.setText("🗗 창모드 복귀 (F11)")
                else:
                    self.fullscreen_btn.setText("⛶ 전체화면 (F11)")
        super().changeEvent(event)

    def switch_page(self, page_idx: int):
        self.stacked_widget.setCurrentIndex(page_idx)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == page_idx)
        
        # 페이지 전환 시 데이터 자동 갱신
        if page_idx == 0:
            self.refresh_dashboard()
        elif page_idx == 1:
            self.refresh_clients_table()
        elif page_idx == 2:
            self.case_management_page.refresh_clients()
        elif page_idx == 3:
            self.refresh_ai_client_combo()
        elif page_idx == 4:
            self.populate_doc_client_filter()
            self.refresh_documents_table()
        elif page_idx == 5:
            self.template_manager_page.refresh_templates()

    def refresh_profile_combo(self, select_id: int = None):
        """로컬 작업자 목록을 갱신하고 현재 작업자를 유지합니다."""
        target_id = select_id or self.current_profile["id"]
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        select_index = 0
        for index, profile in enumerate(self.db.list_profiles()):
            self.profile_combo.addItem(profile["name"], profile["id"])
            if profile["id"] == target_id:
                select_index = index
        self.profile_combo.setCurrentIndex(select_index)
        self.profile_combo.blockSignals(False)

    def add_profile(self):
        name, accepted = QInputDialog.getText(
            self,
            "새 사용자 추가",
            "사회복지사 또는 작업자 이름을 입력해 주세요:",
        )
        if not accepted:
            return
        try:
            profile_id = self.db.create_profile(name)
        except ValueError as exc:
            QMessageBox.warning(self, "사용자 추가", str(exc))
            return
        self.db.ensure_builtin_templates(profile_id, TEMPLATES)
        self._activate_profile(profile_id)
        self.refresh_profile_combo(select_id=profile_id)
        QMessageBox.information(
            self,
            "사용자 추가 완료",
            f"{len(TEMPLATES)}개 기본 서류 양식의 개인 사본을 구성했습니다.\n이제 이 사용자만의 양식으로 수정할 수 있습니다.",
        )

    def on_profile_changed(self):
        profile_id = self.profile_combo.currentData()
        if profile_id and profile_id != self.current_profile["id"]:
            self._activate_profile(profile_id)

    def _activate_profile(self, profile_id: int):
        self.db.set_current_profile(profile_id)
        self.current_profile = self.db.get_profile(profile_id)
        self.db.ensure_builtin_templates(profile_id, TEMPLATES)
        if hasattr(self, "template_manager_page"):
            self.template_manager_page.set_profile(profile_id)
        if hasattr(self, "tmpl_combo"):
            self.refresh_template_combo()
        self.status_bar.showMessage(
            f"현재 사용자를 '{self.current_profile['name']}'(으)로 전환했습니다.",
            4000,
        )

    # ================= [PAGE 0: 대시보드] =================
    def create_dashboard_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageRoot")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(make_page_header(
            "오늘의 사례관리 현황",
            "대상자, 상담 기록, 서류 현황을 한눈에 확인하고 이어서 처리합니다.",
            "CASEWORK OVERVIEW",
        ))

        # 1. KPI 카드 영역 (토스 스타일 위젯)
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(14)

        self.kpi_clients = self.create_kpi_card("총 관리 대상자", "0명", "#176B5B", "#E3F0EC", "등록된 전체 사례 대상자", lambda: self.switch_page(1))
        self.kpi_high_risk = self.create_kpi_card("고위기 집중관리", "0명", "#B83A4B", "#FCEBED", "집중 모니터링 필요 대상", self.nav_to_high_risk_clients)
        self.kpi_monthly = self.create_kpi_card("이달의 상담 실적", "0건", "#237A64", "#E7F3EF", "이번 달 누적 상담 기록", lambda: self.switch_page(3))
        self.kpi_docs = self.create_kpi_card("등록 서류", "0건", "#A76318", "#FFF1DC", "작성 서류·상담일지·첨부 파일", lambda: self.switch_page(4))

        kpi_layout.addWidget(self.kpi_clients)
        kpi_layout.addWidget(self.kpi_high_risk)
        kpi_layout.addWidget(self.kpi_monthly)
        kpi_layout.addWidget(self.kpi_docs)
        layout.addLayout(kpi_layout)

        # 2. 퀵 액션 바
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        act_label = QLabel("⚡ 빠른 실행:")
        act_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        act_label.setStyleSheet("color: #475569; padding-right: 4px;")
        action_layout.addWidget(act_label)

        btn_new_client = QPushButton("➕ 신규 대상자 등록")
        set_button_role(btn_new_client, "primary")
        btn_new_client.clicked.connect(self.open_new_client_dialog)

        btn_new_counsel = QPushButton("🚀 AI 상담일지 작성")
        set_button_role(btn_new_counsel, "soft")
        btn_new_counsel.clicked.connect(lambda: self.switch_page(3))

        btn_manual_counsel = QPushButton("✍️ 수기 상담일지 직접 작성")
        set_button_role(btn_manual_counsel, "soft")
        btn_manual_counsel.clicked.connect(self.open_manual_counseling_dialog)

        btn_new_doc = QPushButton("📂 서류 첨부")
        btn_new_doc.clicked.connect(self.open_new_document_dialog)

        btn_typed_memo = QPushButton("✍️ 직접 메모/서류 작성")
        btn_typed_memo.clicked.connect(self.open_new_typed_memo_dialog)

        action_layout.addWidget(btn_new_client)
        action_layout.addWidget(btn_new_counsel)
        action_layout.addWidget(btn_manual_counsel)
        action_layout.addWidget(btn_new_doc)
        action_layout.addWidget(btn_typed_memo)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.case_due_btn = QPushButton("모니터링 일정을 확인하세요")
        self.case_due_btn.setObjectName("caseDueButton")
        self.case_due_btn.clicked.connect(lambda: self.switch_page(2))
        layout.addWidget(self.case_due_btn)

        # 3. 최근 상담 및 개입 기록 테이블
        recent_group = QGroupBox("최근 상담 및 개입 기록 (최근 5건 - 더블 클릭 시 상세 카드 열림)")
        rg_layout = QVBoxLayout(recent_group)
        rg_layout.setContentsMargins(12, 16, 12, 12)

        self.dash_table = QTableWidget()
        self.dash_table.setColumnCount(5)
        self.dash_table.setHorizontalHeaderLabels(["대상자 성명", "가명(비식별)", "상담 일자", "서식/종류", "핵심 요약"])
        self.dash_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.dash_table.verticalHeader().setDefaultSectionSize(40)
        self.dash_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.dash_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dash_table.cellDoubleClicked.connect(self.on_dash_record_double_clicked)
        rg_layout.addWidget(self.dash_table)

        layout.addWidget(recent_group, stretch=1)
        documents_group = QGroupBox('최근 등록·수정 서류 (더블 클릭으로 열기)')
        documents_layout = QVBoxLayout(documents_group)
        self.dash_documents_table = QTableWidget(0, 4)
        self.dash_documents_table.setHorizontalHeaderLabels(['대상자', '서류명', '구분', '등록·수정일'])
        self.dash_documents_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.dash_documents_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dash_documents_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.dash_documents_table.cellDoubleClicked.connect(
            lambda row, _col: self.open_registry_document(self.dash_documents_table.item(row, 0).data(Qt.ItemDataRole.UserRole)))
        documents_layout.addWidget(self.dash_documents_table)
        layout.addWidget(documents_group, stretch=1)
        return page

    def create_kpi_card(self, title: str, value: str, color_hex: str, bg_tint: str, subtext: str, click_handler=None) -> QWidget:
        class ClickableCard(QFrame):
            def __init__(self, handler, parent=None):
                super().__init__(parent)
                self.handler = handler
                if handler:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)

            def mousePressEvent(self, event):
                if self.handler and event.button() == Qt.MouseButton.LeftButton:
                    self.handler()
                super().mousePressEvent(event)

        card = ClickableCard(click_handler)
        card.setObjectName("kpiCard")
        card.setStyleSheet(f"""
            #kpiCard {{
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 14px;
                padding: 14px 16px;
            }}
            #kpiCard:hover {{
                border: 1.5px solid {color_hex};
                background-color: #FBFCFE;
            }}
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(4, 4, 4, 4)
        c_layout.setSpacing(6)

        # Header: Title + Pill Badge
        top_row = QHBoxLayout()
        t_label = QLabel(title)
        t_label.setStyleSheet("color: #475569; font-size: 13px; font-weight: 700;")
        
        pill = QLabel("보기 →")
        pill.setStyleSheet(f"background-color: {bg_tint}; color: {color_hex}; font-size: 11px; font-weight: 700; border-radius: 10px; padding: 2px 8px;")
        
        top_row.addWidget(t_label)
        top_row.addStretch()
        top_row.addWidget(pill)
        c_layout.addLayout(top_row)

        # Large Metric Value
        v_label = QLabel(value)
        v_label.setObjectName("kpiValue")
        v_label.setStyleSheet("color: #0F172A; font-size: 28px; font-weight: 800; padding: 2px 0;")
        c_layout.addWidget(v_label)

        # Subtitle caption
        sub_label = QLabel(subtext)
        sub_label.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 500;")
        c_layout.addWidget(sub_label)

        return card

    def nav_to_high_risk_clients(self):
        self.switch_page(1)
        self.filter_risk.setCurrentText("고위기")
        self.refresh_clients_table()

    def on_dash_record_double_clicked(self, row, col):
        item = self.dash_table.item(row, 0)
        if item:
            cid = item.data(Qt.ItemDataRole.UserRole)
            if cid:
                dlg = ClientDetailDialog(self.db, client_id=cid, parent=self)
                dlg.write_counseling_signal.connect(self.switch_to_ai_counsel_with_client)
                dlg.exec()
                self.refresh_dashboard()
                self.refresh_clients_table()

    @staticmethod
    def create_pill_badge(text: str, bg_hex: str, text_hex: str) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            background-color: {bg_hex};
            color: {text_hex};
            font-size: 11px;
            font-weight: 700;
            border-radius: 9px;
            padding: 2px 10px;
        """)
        layout.addWidget(lbl)
        return container

    def get_risk_badge(self, risk_text: str) -> QWidget:
        if "고위기" in risk_text or "긴급" in risk_text:
            return self.create_pill_badge("🚨 고위기", "#FFE4E6", "#BE123C")
        elif "중위기" in risk_text:
            return self.create_pill_badge("⚠️ 중위기", "#FEF3C7", "#B45309")
        else:
            return self.create_pill_badge("🌱 일반", "#F1F5F9", "#475569")

    def get_welfare_badge(self, welf_text: str) -> QWidget:
        if "기초" in welf_text:
            return self.create_pill_badge("기초수급", "#DBEAFE", "#1D4ED8")
        elif "차상위" in welf_text:
            return self.create_pill_badge("차상위", "#E0E7FF", "#4338CA")
        elif "한부모" in welf_text or "조손" in welf_text:
            return self.create_pill_badge("한부모/조손", "#FCE7F3", "#BE185D")
        elif "장애" in welf_text or "독거" in welf_text:
            return self.create_pill_badge("독거/장애", "#EDE9FE", "#6D28D9")
        else:
            return self.create_pill_badge(welf_text if welf_text else "일반", "#F1F5F9", "#64748B")

    def get_doc_type_badge(self, doc_type: str) -> QWidget:
        if "상담" in doc_type or "일지" in doc_type:
            return self.create_pill_badge(doc_type, "#EEF2FF", "#4338CA")
        elif "계획" in doc_type:
            return self.create_pill_badge(doc_type, "#F5F3FF", "#6D28D9")
        elif "회의" in doc_type or "행정" in doc_type:
            return self.create_pill_badge(doc_type, "#ECFDF5", "#059669")
        else:
            return self.create_pill_badge(doc_type, "#F1F5F9", "#475569")

    def refresh_dashboard(self):
        stats = self.db.get_dashboard_stats()
        recent_documents = self.db.list_document_registry()[:5]
        self.dash_documents_table.setRowCount(len(recent_documents))
        for row, document in enumerate(recent_documents):
            for column, value in enumerate((document['client_name'] or '미지정', document['title'], document['doc_type'], document['created_at'])):
                item = QTableWidgetItem(str(value or ''))
                item.setData(Qt.ItemDataRole.UserRole, document)
                self.dash_documents_table.setItem(row, column, item)
        self.kpi_clients.findChild(QLabel, "kpiValue").setText(f"{stats['total_clients']}명")
        self.kpi_high_risk.findChild(QLabel, "kpiValue").setText(f"{stats['high_risk_clients']}명")
        self.kpi_monthly.findChild(QLabel, "kpiValue").setText(f"{stats['monthly_counselings']}건")
        self.kpi_docs.findChild(QLabel, "kpiValue").setText(f"{stats['total_docs']}건")
        overdue = stats.get("overdue_monitoring", 0)
        upcoming = stats.get("upcoming_monitoring", 0)
        if overdue:
            self.case_due_btn.setText(f"확인이 늦어진 모니터링 {overdue}건 · 7일 이내 예정 {upcoming}건  →")
            self.case_due_btn.setProperty("attention", True)
        else:
            self.case_due_btn.setText(f"7일 이내 모니터링 {upcoming}건 · 사례관리 작업판 열기  →")
            self.case_due_btn.setProperty("attention", False)
        self.case_due_btn.style().unpolish(self.case_due_btn)
        self.case_due_btn.style().polish(self.case_due_btn)

        recs = stats.get("recent_records", [])
        self.dash_table.setRowCount(len(recs))
        self.dash_table.verticalHeader().setDefaultSectionSize(40)
        for idx, r in enumerate(recs):
            cname_raw = r.get('client_name', '미지정')
            name_item = QTableWidgetItem(cname_raw)
            name_item.setData(Qt.ItemDataRole.UserRole, r.get("client_id"))
            name_item.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
            self.dash_table.setItem(idx, 0, name_item)

            self.dash_table.setItem(idx, 1, QTableWidgetItem(r.get('masked_name', '')))
            
            date_item = QTableWidgetItem(r.get("session_date", ""))
            self.dash_table.setItem(idx, 2, date_item)

            tmpl_name = r.get("template_name", "일반상담")
            self.dash_table.setItem(idx, 3, QTableWidgetItem(tmpl_name))
            self.dash_table.setCellWidget(idx, 3, self.get_doc_type_badge(tmpl_name))

            result_text = r.get("ai_result", "") or ""
            summary = result_text[:60].replace("\n", " ") + ("..." if len(result_text) > 60 else "")
            self.dash_table.setItem(idx, 4, QTableWidgetItem(summary))

    # ================= [PAGE 1: 대상자 관리] =================
    def create_clients_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageRoot")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(make_page_header(
            "대상자 관리",
            "사례 대상자를 찾고 위기도를 살핀 뒤 상담 이력으로 바로 이동합니다.",
            "CLIENT REGISTRY",
        ))

        # 검색 및 필터
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("대상자 찾기"))

        self.client_search_input = QLineEdit()
        self.client_search_input.setPlaceholderText("🔍 성명, 가명, 연락처, 주소 검색...")
        self.client_search_input.setFixedWidth(220)
        self.client_search_input.textChanged.connect(self.refresh_clients_table)
        top_layout.addWidget(self.client_search_input)

        top_layout.addWidget(QLabel("위기도:"))
        self.filter_risk = QComboBox()
        self.filter_risk.addItems(["전체", "고위기", "중위기", "저위기", "일반"])
        self.filter_risk.currentTextChanged.connect(self.refresh_clients_table)
        top_layout.addWidget(self.filter_risk)

        top_layout.addWidget(QLabel("수급:"))
        self.filter_welfare = QComboBox()
        self.filter_welfare.addItems(["전체", "기초수급", "차상위", "일반"])
        self.filter_welfare.currentTextChanged.connect(self.refresh_clients_table)
        top_layout.addWidget(self.filter_welfare)

        layout.addLayout(top_layout)

        # 액션 버튼 행
        act_row = QHBoxLayout()
        btn_add = QPushButton("➕ 신규 대상자 등록")
        set_button_role(btn_add, "primary")
        btn_add.clicked.connect(self.open_new_client_dialog)

        btn_detail = QPushButton("📋 상세 및 상담이력 보기")
        set_button_role(btn_detail, "soft")
        btn_detail.clicked.connect(self.open_selected_client_detail)

        btn_case = QPushButton("사례관리 열기")
        set_button_role(btn_case, "primary")
        btn_case.clicked.connect(self.open_case_for_selected_client)

        btn_counsel = QPushButton("🚀 AI 상담 작성")
        set_button_role(btn_counsel, "primary")
        btn_counsel.clicked.connect(self.write_counsel_for_selected_client)

        btn_manual = QPushButton("✍️ 수기 상담 작성")
        set_button_role(btn_manual, "soft")
        btn_manual.clicked.connect(self.write_manual_for_selected_client)

        btn_edit = QPushButton("✏️ 정보 수정")
        btn_edit.clicked.connect(self.open_edit_client_dialog)

        btn_del = QPushButton("🗑️ 삭제")
        set_button_role(btn_del, "danger")
        btn_del.clicked.connect(self.delete_selected_client)

        act_row.addWidget(btn_add)
        act_row.addWidget(btn_detail)
        act_row.addWidget(btn_case)
        act_row.addWidget(btn_counsel)
        act_row.addWidget(btn_manual)
        act_row.addWidget(btn_edit)
        act_row.addWidget(btn_del)
        act_row.addStretch()
        layout.addLayout(act_row)

        # 대상자 테이블
        self.clients_table = QTableWidget()
        self.clients_table.setColumnCount(8)
        self.clients_table.setHorizontalHeaderLabels(["ID", "성명", "가명(비식별)", "성별/생년", "위기도", "수급자격", "연락처", "주소"])
        self.clients_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.clients_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.clients_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.clients_table.cellDoubleClicked.connect(lambda r, c: self.open_selected_client_detail())
        layout.addWidget(self.clients_table, stretch=1)

        return page

    def refresh_clients_table(self):
        kw = self.client_search_input.text().strip()
        risk = self.filter_risk.currentText()
        welf = self.filter_welfare.currentText()
        clients = self.db.list_clients(keyword=kw, risk_filter=risk, welfare_filter=welf)

        self.clients_table.setSortingEnabled(False)
        self.clients_table.setRowCount(len(clients))
        self.clients_table.verticalHeader().setDefaultSectionSize(42)
        for idx, c in enumerate(clients):
            id_item = QTableWidgetItem()
            id_item.setData(Qt.ItemDataRole.DisplayRole, c['id'])
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.clients_table.setItem(idx, 0, id_item)
            
            name_item = QTableWidgetItem(c.get('name', ''))
            name_item.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
            self.clients_table.setItem(idx, 1, name_item)
            
            self.clients_table.setItem(idx, 2, QTableWidgetItem(c.get('masked_name', '')))
            birth_gender = f"{c.get('gender', '')} / {c.get('birth_date', '')}"
            self.clients_table.setItem(idx, 3, QTableWidgetItem(birth_gender))
            
            # 위기도 컬러 뱃지
            risk_val = c.get('risk_level', '일반')
            r_item = QTableWidgetItem(risk_val)
            self.clients_table.setItem(idx, 4, r_item)
            self.clients_table.setCellWidget(idx, 4, self.get_risk_badge(risk_val))

            # 수급자격 컬러 뱃지
            welf_val = c.get('welfare_type', '일반')
            w_item = QTableWidgetItem(welf_val)
            self.clients_table.setItem(idx, 5, w_item)
            self.clients_table.setCellWidget(idx, 5, self.get_welfare_badge(welf_val))

            self.clients_table.setItem(idx, 6, QTableWidgetItem(c.get('phone', '')))
            self.clients_table.setItem(idx, 7, QTableWidgetItem(c.get('address', '')))
        self.clients_table.setSortingEnabled(True)

    def open_new_client_dialog(self):
        dlg = ClientDialog(self.db, parent=self)
        if dlg.exec():
            self.refresh_clients_table()
            self.refresh_dashboard()

    def get_selected_client_id(self) -> int:
        sel = self.clients_table.currentRow()
        if sel >= 0:
            id_item = self.clients_table.item(sel, 0)
            if id_item:
                return int(id_item.text())
        return None

    def open_edit_client_dialog(self):
        cid = self.get_selected_client_id()
        if not cid:
            QMessageBox.information(self, "알림", "수정할 대상자를 먼저 선택해 주세요.")
            return
        dlg = ClientDialog(self.db, client_id=cid, parent=self)
        if dlg.exec():
            self.refresh_clients_table()

    def open_selected_client_detail(self):
        cid = self.get_selected_client_id()
        if not cid:
            QMessageBox.information(self, "알림", "조회할 대상자를 먼저 선택해 주세요.")
            return
        dlg = ClientDetailDialog(self.db, client_id=cid, parent=self)
        dlg.write_counseling_signal.connect(self.switch_to_ai_counsel_with_client)
        dlg.exec()

    def write_counsel_for_selected_client(self):
        cid = self.get_selected_client_id()
        if not cid:
            QMessageBox.information(self, "알림", "상담을 작성할 대상자를 먼저 선택해 주세요.")
            return
        self.switch_to_ai_counsel_with_client(cid)

    def open_case_for_selected_client(self):
        cid = self.get_selected_client_id()
        if not cid:
            QMessageBox.information(self, "대상자 선택", "사례관리를 열 대상자를 먼저 선택해 주세요.")
            return
        self.switch_page(2)
        self.case_management_page.select_client(cid)

    def delete_selected_client(self):
        cid = self.get_selected_client_id()
        if not cid:
            QMessageBox.information(self, "알림", "삭제할 대상자를 먼저 선택해 주세요.")
            return
        reply = QMessageBox.question(
            self,
            "대상자 삭제 확인",
            "정말 이 대상자를 삭제하시겠습니까?\n대상자에 등록된 상담 일지와 서류 기록도 함께 정리됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_client(cid)
            self.refresh_clients_table()
            self.refresh_dashboard()
    # ================= [PAGE 2: AI 상담일지 작성실] =================
    def create_ai_counsel_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageRoot")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        layout.addWidget(make_page_header(
            "상담일지 작성",
            "AI로 메모를 정리하거나 사회복지사가 상담 내용을 직접 작성해 이력에 저장합니다.",
            "COUNSELING RECORD",
        ))

        writing_mode_bar = QFrame()
        writing_mode_bar.setObjectName("writingModeBar")
        mode_layout = QHBoxLayout(writing_mode_bar)
        mode_layout.setContentsMargins(12, 8, 12, 8)
        mode_layout.setSpacing(8)
        mode_layout.addWidget(QLabel("작성 방식"))

        ai_mode_btn = QPushButton("AI로 메모 정리")
        ai_mode_btn.setObjectName("activeWritingMode")
        ai_mode_btn.clicked.connect(lambda: self.input_text.setFocus())
        direct_mode_btn = QPushButton("직접 작성·저장")
        set_button_role(direct_mode_btn, "soft")
        direct_mode_btn.clicked.connect(self.open_manual_from_counsel_page)
        report_btn = QPushButton("상담일지 조회·출력")
        report_btn.clicked.connect(self.open_counseling_report)
        mode_layout.addWidget(ai_mode_btn)
        mode_layout.addWidget(direct_mode_btn)
        mode_layout.addWidget(report_btn)
        mode_hint = QLabel("직접 작성은 AI 모델 없이 바로 사용할 수 있습니다.")
        mode_hint.setObjectName("writingModeHint")
        mode_layout.addWidget(mode_hint, stretch=1)
        layout.addWidget(writing_mode_bar)

        # 대상자 연동 상단 카드
        client_link_box = QFrame()
        client_link_box.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 6px 12px;
            }
        """)
        cl_layout = QHBoxLayout(client_link_box)
        cl_layout.setContentsMargins(8, 6, 8, 6)
        cl_layout.setSpacing(10)

        cl_title = QLabel("👤 상담 대상자 연동:")
        cl_title.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        cl_title.setStyleSheet("color: #334155;")
        cl_layout.addWidget(cl_title)

        self.ai_client_combo = QComboBox()
        self.ai_client_combo.setMinimumWidth(320)
        self.ai_client_combo.currentIndexChanged.connect(self.on_ai_client_selected)
        cl_layout.addWidget(self.ai_client_combo)

        self.client_info_badge = QLabel("대상자를 선택하면 가명이 자동 적용되며 상담 이력에 즉시 누적 저장됩니다.")
        self.client_info_badge.setStyleSheet("color: #145A4D; background-color: #E3F0EC; font-size: 11px; font-weight: 700; padding: 4px 12px; border-radius: 8px;")
        cl_layout.addWidget(self.client_info_badge)
        cl_layout.addStretch()
        layout.addWidget(client_link_box)

        session_row = QHBoxLayout()
        self.session_date_input = QDateEdit(QDate.currentDate())
        self.session_date_input.setCalendarPopup(True)
        self.session_date_input.setDisplayFormat('yyyy-MM-dd')
        self.session_method_input = QComboBox()
        self.session_method_input.addItems(['', '방문', '복지관 내방', '전화', '온라인', '기타'])
        session_row.addWidget(QLabel('실제 상담일'))
        session_row.addWidget(self.session_date_input)
        session_row.addWidget(QLabel('상담방법'))
        session_row.addWidget(self.session_method_input)
        session_row.addStretch()
        layout.addLayout(session_row)

        # 좌우 분할 스플리터
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # 좌측 입력 패널
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        # 서식 선택
        opt_group = QGroupBox("1. 상담 서식 및 옵션")
        opt_layout = QVBoxLayout(opt_group)

        tmpl_h_layout = QHBoxLayout()
        tmpl_label = QLabel("상담 서식:")
        tmpl_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        self.tmpl_combo = QComboBox()
        self.tmpl_combo.currentIndexChanged.connect(self.on_template_changed)
        tmpl_h_layout.addWidget(tmpl_label)
        tmpl_h_layout.addWidget(self.tmpl_combo, stretch=1)
        manage_template_btn = QPushButton("내 양식 편집")
        manage_template_btn.clicked.connect(lambda: self.switch_page(5))
        tmpl_h_layout.addWidget(manage_template_btn)
        opt_layout.addLayout(tmpl_h_layout)

        self.tmpl_desc_label = QLabel("")
        self.tmpl_desc_label.setStyleSheet("color: #64748B; font-size: 11px; padding: 2px 0;")
        self.tmpl_desc_label.setWordWrap(True)
        opt_layout.addWidget(self.tmpl_desc_label)

        detail_h_layout = QHBoxLayout()
        detail_label = QLabel("상세도:")
        self.detail_combo = QComboBox()
        self.detail_combo.addItems(["표준", "간결하게", "상세하게"])
        self.detail_combo.setCurrentText("표준")
        detail_h_layout.addWidget(detail_label)
        detail_h_layout.addWidget(self.detail_combo)

        detail_h_layout.addSpacing(15)
        name_label = QLabel("대상자 성명:")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: 홍길동 (가명 변환용)")
        self.name_input.setMaximumWidth(150)
        detail_h_layout.addWidget(name_label)
        detail_h_layout.addWidget(self.name_input)
        detail_h_layout.addStretch()
        opt_layout.addLayout(detail_h_layout)

        self.mask_checkbox = QCheckBox("개인정보 자동 마스킹 적용 (주민번호, 전화번호, 상세주소 비식별화)")
        self.mask_checkbox.setChecked(True)
        self.mask_checkbox.setStyleSheet("color: #176B5B; font-weight: 700; margin-top: 4px;")
        opt_layout.addWidget(self.mask_checkbox)
        left_layout.addWidget(opt_group)

        # 거친 상담 메모 입력 영역
        memo_group = QGroupBox("2. 거친 상담 메모 / 핵심 키워드 입력")
        memo_layout = QVBoxLayout(memo_group)

        sample_btn_layout = QHBoxLayout()
        memo_hint = QLabel("면담 중 기록한 단어, 문장, 녹취 요약을 자유롭게 적어주세요:")
        memo_hint.setStyleSheet("color: #64748B; font-size: 11px;")
        self.sample_btn = QPushButton("💡 예시 메모 불러오기")
        self.sample_btn.clicked.connect(self.load_sample_memo)
        sample_btn_layout.addWidget(memo_hint)
        sample_btn_layout.addStretch()
        sample_btn_layout.addWidget(self.sample_btn)
        memo_layout.addLayout(sample_btn_layout)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("여기에 상담 메모를 입력하세요...\n(예: 김OO 어르신 허리 통증으로 식사 해결 곤란, 밑반찬 지원 요청, 다음 주 방문 예정)")
        self.input_text.setFont(QFont("Malgun Gothic", 10))
        memo_layout.addWidget(self.input_text)

        # 실행 및 중단 버튼
        btn_layout = QHBoxLayout()
        self.generate_btn = QPushButton("✨ AI 상담일지 작성 (Ctrl+Enter)")
        self.generate_btn.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        set_button_role(self.generate_btn, "primary")
        self.generate_btn.setMinimumHeight(44)
        self.generate_btn.clicked.connect(self.start_generation)

        self.stop_btn = QPushButton("🛑 중단 (Esc)")
        self.stop_btn.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        set_button_role(self.stop_btn, "danger")
        self.stop_btn.setMinimumHeight(44)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_generation)

        btn_layout.addWidget(self.generate_btn, stretch=3)
        btn_layout.addWidget(self.stop_btn, stretch=1)
        memo_layout.addLayout(btn_layout)

        left_layout.addWidget(memo_group, stretch=1)
        splitter.addWidget(left_widget)

        # 우측 결과 패널
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        result_group = QGroupBox("3. 정형화된 상담일지 결과")
        res_layout = QVBoxLayout(result_group)

        tool_layout = QHBoxLayout()
        self.mask_stat_label = QLabel("")
        self.mask_stat_label.setStyleSheet("color: #176B5B; font-size: 11px; font-weight: bold;")
        tool_layout.addWidget(self.mask_stat_label)
        tool_layout.addStretch()

        self.stop_output_btn = QPushButton("🛑 중단")
        self.stop_output_btn.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        set_button_role(self.stop_output_btn, "danger")
        self.stop_output_btn.setEnabled(False)
        self.stop_output_btn.clicked.connect(self.stop_generation)

        # SaaS 전용: 대상자 히스토리 저장 버튼
        self.save_to_db_btn = QPushButton("💾 DB 이력에 저장")
        self.save_to_db_btn.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        set_button_role(self.save_to_db_btn, "primary")
        self.save_to_db_btn.clicked.connect(self.save_record_to_database)

        self.apply_form_btn = QPushButton("▦ 표 양식 적용")
        self.apply_form_btn.clicked.connect(self.apply_selected_form_to_output)

        self.copy_btn = QPushButton("📋 원클릭 복사")
        self.copy_btn.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        set_button_role(self.copy_btn, "soft")
        self.copy_btn.clicked.connect(self.copy_to_clipboard)

        self.save_file_btn = QPushButton("📄 파일 저장")
        self.save_file_btn.clicked.connect(self.save_to_file)

        self.clear_btn = QPushButton("🧹 지우기")
        self.clear_btn.clicked.connect(self.clear_fields)

        tool_layout.addWidget(self.stop_output_btn)
        tool_layout.addWidget(self.save_to_db_btn)
        tool_layout.addWidget(self.apply_form_btn)
        tool_layout.addWidget(self.copy_btn)
        tool_layout.addWidget(self.save_file_btn)
        tool_layout.addWidget(self.clear_btn)
        res_layout.addLayout(tool_layout)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(False)
        self.output_text.setFont(QFont("Malgun Gothic", 10))
        self.output_text.setPlaceholderText("AI가 작성한 표준 양식 상담일지가 실시간으로 여기에 출력됩니다.\n출력 후 자유롭게 추가 편집 및 보완이 가능합니다.")
        res_layout.addWidget(self.output_text)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        res_layout.addWidget(self.progress_bar)

        right_layout.addWidget(result_group)
        splitter.addWidget(right_widget)

        splitter.setSizes([540, 560])
        layout.addWidget(splitter, stretch=1)
        self.refresh_template_combo()
        return page

    def refresh_ai_client_combo(self):
        current_data = self.ai_client_combo.currentData()
        self.ai_client_combo.blockSignals(True)
        self.ai_client_combo.clear()
        self.ai_client_combo.addItem("[ 👤 미지정 (일반 상담 기록) ]", None)

        clients = self.db.list_clients()
        select_idx = 0
        for idx, c in enumerate(clients, start=1):
            text = f"{c['name']} ({c['masked_name']} / {c['gender']} / {c['risk_level']})"
            self.ai_client_combo.addItem(text, c['id'])
            if current_data and c['id'] == current_data:
                select_idx = idx

        self.ai_client_combo.setCurrentIndex(select_idx)
        self.ai_client_combo.blockSignals(False)

    def on_ai_client_selected(self):
        cid = self.ai_client_combo.currentData()
        if cid:
            c = self.db.get_client(cid)
            if c:
                self.name_input.setText(c.get("name", ""))
                self.client_info_badge.setText(f"선택됨: {c.get('name')} | {c.get('risk_level')} | {c.get('welfare_type')} (상담 완료 후 DB 자동 저장 가능)")
        else:
            self.client_info_badge.setText("대상자를 선택하면 본문에 가명이 자동 적용되며, 상담 이력에 영구 누적 저장됩니다.")

    def switch_to_ai_counsel_with_client(self, client_id: int):
        self.switch_page(3) # AI 페이지로 전환
        for idx in range(self.ai_client_combo.count()):
            if self.ai_client_combo.itemData(idx) == client_id:
                self.ai_client_combo.setCurrentIndex(idx)
                break

    def save_record_to_database(self):
        result_text = self.output_text.toPlainText().strip()
        if not result_text:
            QMessageBox.warning(self, "확인", "저장할 상담일지 결과가 없습니다.")
            return

        cid = self.ai_client_combo.currentData()
        tmpl = self.tmpl_combo.currentText()
        template = self.get_selected_form_template()
        raw_memo = self.input_text.toPlainText().strip()
        detail = self.detail_combo.currentText()

        data = {
            "client_id": cid,
            "session_date": self.session_date_input.date().toString('yyyy-MM-dd'),
            "template_name": tmpl,
            "template_id": template.get("id") if template else None,
            "template_snapshot": self.db.make_template_snapshot(template),
            "owner_id": self.current_profile["id"],
            "detail_level": detail,
            "raw_memo": raw_memo,
            "ai_result": result_text,
            "result_html": self.output_text.toHtml(),
            "worker_name": self.current_profile["name"]
        }

        rec_id = self.db.add_counseling_record(data)
        if cid:
            c = self.db.get_client(cid)
            cname = c.get('name', '') if c else '대상자'
            self.status_bar.showMessage(f"✅ '{cname}' 대상자의 누적 상담 이력에 성공적으로 저장되었습니다 (ID: {rec_id})", 5000)
            QMessageBox.information(self, "저장 완료", f"'{cname}' 대상자의 상담 이력에 성공적으로 저장되었습니다!\n대상자 관리 화면에서 언제든 과거 상담을 열람할 수 있습니다.")
        else:
            self.status_bar.showMessage(f"✅ 일반 상담 기록으로 데이터베이스에 저장되었습니다 (ID: {rec_id})", 4000)
            QMessageBox.information(self, "저장 완료", "일반 상담 기록으로 데이터베이스에 안전하게 저장되었습니다.")

        self.refresh_dashboard()

    # ================= [PAGE 3: 서류/문서 보관함] =================
    def create_documents_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageRoot")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(make_page_header(
            "서류 보관함",
            "대상자별 증빙자료와 직접 작성한 기록을 검색하고 안전하게 백업합니다.",
            "DOCUMENT VAULT",
        ))

        top_layout = QHBoxLayout()

        btn_add_doc = QPushButton("➕ 새 서류 첨부 등록")
        set_button_role(btn_add_doc, "primary")
        btn_add_doc.clicked.connect(self.open_new_document_dialog)

        btn_type_doc = QPushButton("✍️ 직접 타이핑 메모/서류 작성")
        set_button_role(btn_type_doc, "soft")
        btn_type_doc.clicked.connect(self.open_new_typed_memo_dialog)

        btn_open_doc = QPushButton("🔍 선택 서류 열기 (HWP/PDF/TXT)")
        btn_open_doc.clicked.connect(self.open_selected_document)
        btn_edit_doc = QPushButton('선택 서류 수정')
        btn_edit_doc.clicked.connect(self.edit_selected_document)

        btn_del_doc = QPushButton("🗑️ 서류 삭제")
        set_button_role(btn_del_doc, "danger")
        btn_del_doc.clicked.connect(self.delete_selected_document)

        btn_backup_docs = QPushButton("📦 서류 일괄 백업 (.zip)")
        set_button_role(btn_backup_docs, "soft")
        btn_backup_docs.clicked.connect(self.export_documents_only_backup)

        top_layout.addWidget(btn_add_doc)
        top_layout.addWidget(btn_type_doc)
        top_layout.addWidget(btn_open_doc)
        top_layout.addWidget(btn_edit_doc)
        top_layout.addWidget(btn_del_doc)
        top_layout.addWidget(btn_backup_docs)
        layout.addLayout(top_layout)

        # 🔍 서류 검색 및 다중 필터 영역 (대상자별, 서류구분별, 제목/내용 검색)
        filter_box = QFrame()
        filter_box.setStyleSheet("background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 6px 10px;")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.setContentsMargins(6, 4, 6, 4)
        filter_layout.setSpacing(10)

        # 1. 대상자별 필터
        f_client_label = QLabel("👤 대상자별:")
        f_client_label.setStyleSheet("font-weight: bold; color: #334155; font-size: 11px;")
        self.doc_filter_client = QComboBox()
        self.doc_filter_client.setMinimumWidth(180)
        self.doc_filter_client.currentIndexChanged.connect(self.on_doc_filter_changed)

        # 2. 서류 구분별 필터
        f_type_label = QLabel("📑 구분별:")
        f_type_label.setStyleSheet("font-weight: bold; color: #334155; font-size: 11px;")
        self.doc_filter_type = QComboBox()
        self.doc_filter_type.setMinimumWidth(160)
        self.doc_filter_type.addItems([
            "전체 구분",
            "사례관리 서류",
            "상담일지",
            "초기면접지/인테이크",
            "전화상담/민원메모",
            "가정방문 현장기록",
            "병원 진단서/소견서",
            "복지급여 신청서",
            "개인정보 동의서",
            "사례관리 계획서",
            "회의록/행정기록",
            "기타 증빙서류/메모"
        ])
        self.doc_filter_type.currentIndexChanged.connect(self.on_doc_filter_changed)

        # 3. 키워드 검색
        f_search_label = QLabel("🔍 검색:")
        f_search_label.setStyleSheet("font-weight: bold; color: #334155; font-size: 11px;")
        self.doc_search_input = QLineEdit()
        self.doc_search_input.setPlaceholderText("서류 제목 또는 비고 메모 검색...")
        self.doc_search_input.textChanged.connect(self.on_doc_filter_changed)

        # 4. 필터 초기화 버튼
        btn_reset_doc_filter = QPushButton("🔄 초기화")
        btn_reset_doc_filter.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #E2E8F0; }
        """)
        btn_reset_doc_filter.clicked.connect(self.reset_doc_filters)

        filter_layout.addWidget(f_client_label)
        filter_layout.addWidget(self.doc_filter_client)
        filter_layout.addSpacing(6)
        filter_layout.addWidget(f_type_label)
        filter_layout.addWidget(self.doc_filter_type)
        filter_layout.addSpacing(6)
        filter_layout.addWidget(f_search_label)
        filter_layout.addWidget(self.doc_search_input, stretch=1)
        filter_layout.addWidget(btn_reset_doc_filter)
        layout.addWidget(filter_box)

        # 서류 목록 테이블
        self.docs_table = QTableWidget()
        self.docs_table.setColumnCount(6)
        self.docs_table.setHorizontalHeaderLabels(["ID", "서류 제목", "구분", "대상자(가명)", "등록·수정일시", "크기/상태"])
        self.docs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.docs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.docs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.docs_table.cellDoubleClicked.connect(lambda r, c: self.open_selected_document())
        layout.addWidget(self.docs_table, stretch=1)

        self.populate_doc_client_filter()
        return page

    def populate_doc_client_filter(self):
        if not hasattr(self, 'doc_filter_client'):
            return
        current_data = self.doc_filter_client.currentData()
        self.doc_filter_client.blockSignals(True)
        self.doc_filter_client.clear()
        self.doc_filter_client.addItem("[ 👥 전체 대상자 ]", None)
        self.doc_filter_client.addItem("[ 👤 미지정 (기관 일반 서류) ]", -1)

        clients = self.db.list_clients()
        sel_idx = 0
        for idx, c in enumerate(clients, start=2):
            self.doc_filter_client.addItem(f"{c['name']} ({c['masked_name']})", c['id'])
            if current_data and c['id'] == current_data:
                sel_idx = idx

        self.doc_filter_client.setCurrentIndex(sel_idx)
        self.doc_filter_client.blockSignals(False)

    def on_doc_filter_changed(self):
        self.refresh_documents_table()

    def reset_doc_filters(self):
        self.doc_filter_client.setCurrentIndex(0)
        self.doc_filter_type.setCurrentIndex(0)
        self.doc_search_input.clear()
        self.refresh_documents_table()

    def refresh_documents_table(self):
        if not hasattr(self, 'doc_filter_client'):
            return

        client_id = self.doc_filter_client.currentData()
        doc_type = self.doc_filter_type.currentText()
        if "전체" in doc_type or doc_type.startswith("["):
            doc_type = "전체"
        keyword = self.doc_search_input.text().strip()

        docs = self.db.list_document_registry(client_id=client_id, doc_type=doc_type, keyword=keyword)
        self.docs_table.setSortingEnabled(False)
        self.docs_table.setRowCount(len(docs))
        self.docs_table.verticalHeader().setDefaultSectionSize(40)
        for idx, d in enumerate(docs):
            id_item = QTableWidgetItem()
            id_item.setData(Qt.ItemDataRole.DisplayRole, d['id'])
            id_item.setData(Qt.ItemDataRole.UserRole, d)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.docs_table.setItem(idx, 0, id_item)

            title_item = QTableWidgetItem(d.get('title', ''))
            title_item.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
            self.docs_table.setItem(idx, 1, title_item)

            # 서류 구분 뱃지
            doc_type = d.get('doc_type', '')
            self.docs_table.setItem(idx, 2, QTableWidgetItem(doc_type))
            self.docs_table.setCellWidget(idx, 2, self.get_doc_type_badge(doc_type))

            cname = f"{d.get('client_name', '미지정')} ({d.get('masked_name', '')})" if d.get('client_name') else "미지정 (기관 일반)"
            self.docs_table.setItem(idx, 3, QTableWidgetItem(cname))
            self.docs_table.setItem(idx, 4, QTableWidgetItem(d.get('created_at', '')[:16]))
            kb = round(d.get('file_size', 0) / 1024, 1)
            self.docs_table.setItem(idx, 5, QTableWidgetItem(f"{kb} KB" if d['source_type'] == 'attachment' else d['status']))
        self.docs_table.setSortingEnabled(True)

    def open_new_document_dialog(self):
        dlg = DocumentAddDialog(self.db, parent=self)
        if dlg.exec():
            self.refresh_documents_table()
            self.refresh_dashboard()

    def open_new_typed_memo_dialog(self):
        dlg = DocumentAddDialog(self.db, default_typing_mode=True, parent=self)
        if dlg.exec():
            self.refresh_documents_table()
            self.refresh_dashboard()

    def open_manual_counseling_dialog(self):
        dlg = ManualCounselingDialog(self.db, parent=self)
        if dlg.exec():
            self.refresh_dashboard()
            self.refresh_clients_table()

    def open_manual_from_counsel_page(self):
        """상담일지 화면에서 선택한 대상자를 이어받아 직접 작성창을 엽니다."""
        client_id = self.ai_client_combo.currentData()
        dlg = ManualCounselingDialog(self.db, client_id=client_id, parent=self)
        if dlg.exec():
            self.refresh_dashboard()
            self.refresh_clients_table()
            if hasattr(self, "case_management_page"):
                self.case_management_page.refresh_clients(select_client_id=client_id)
            self.status_bar.showMessage("직접 작성한 상담일지를 상담 이력에 저장했습니다.", 5000)

    def open_counseling_report(self):
        """현재 대상자를 기본 조건으로 상담일지 조회·출력창을 엽니다."""
        dialog = CounselingReportDialog(
            self.db,
            selected_client_id=self.ai_client_combo.currentData(),
            parent=self,
        )
        dialog.exec()

    def write_manual_for_selected_client(self):
        cid = self.get_selected_client_id()
        dlg = ManualCounselingDialog(self.db, client_id=cid, parent=self)
        if dlg.exec():
            self.refresh_dashboard()
            self.refresh_clients_table()

    def get_selected_doc_id(self) -> int:
        sel = self.docs_table.currentRow()
        if sel >= 0:
            id_item = self.docs_table.item(sel, 0)
            if id_item:
                return int(id_item.text())
        return None

    def open_selected_document(self):
        row = self.docs_table.currentRow()
        if row >= 0:
            document = self.docs_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if document and document['source_type'] != 'attachment':
                self.open_registry_document(document)
                return
        did = self.get_selected_doc_id()
        if not did:
            QMessageBox.information(self, "알림", "열람할 서류를 먼저 선택해 주세요.")
            return
        
        # 파일 경로 조회 (상대 파일명을 절대 경로로 변환)
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, file_name FROM documents WHERE id = ?", (did,))
            row = cursor.fetchone()
            if row:
                full_p = self.db.get_document_full_path(row['file_name'])
                if os.path.exists(full_p):
                    if full_p.lower().endswith(".txt"):
                        dlg = TextViewerDialog(row['title'], full_p, parent=self, db=self.db, doc_id=did)
                        dlg.exec()
                        self.refresh_documents_table()
                        self.refresh_dashboard()
                    else:
                        open_system_file(full_p)
                    return
        QMessageBox.warning(self, "오류", "서류 원본 파일을 찾을 수 없습니다.")

    def open_registry_document(self, document):
        if document['source_type'] == 'case_form':
            from case_forms import CaseFormDialog
            record = next((r for r in self.db.list_case_forms(document['client_id']) if r['id'] == document['id']), None)
            if record:
                dialog = CaseFormDialog(self.db, document['client_id'], self.current_profile['id'], record['stage'], {}, record, self)
                dialog.exec()
                self.refresh_documents_table()
                self.refresh_dashboard()
        elif document['source_type'] == 'counseling':
            with self.db.get_connection() as conn:
                record = conn.execute('SELECT * FROM counseling_records WHERE id=?', (document['id'],)).fetchone()
            if record:
                dialog = QDialog(self)
                dialog.setWindowTitle(document['title'])
                dialog.resize(900, 700)
                layout = QVBoxLayout(dialog)
                text = QTextEdit()
                text.setReadOnly(True)
                if record['result_html']:
                    text.setHtml(record['result_html'])
                else:
                    text.setPlainText(record['ai_result'])
                layout.addWidget(text)
                dialog.exec()
        else:
            with self.db.get_connection() as conn:
                record = conn.execute('SELECT title, file_name FROM documents WHERE id=?', (document['id'],)).fetchone()
            if record:
                path = self.db.get_document_full_path(record['file_name'])
                if os.path.isfile(path):
                    if path.lower().endswith('.txt'):
                        TextViewerDialog(record['title'], path, parent=self, db=self.db, doc_id=document['id']).exec()
                        self.refresh_documents_table()
                        self.refresh_dashboard()
                    else:
                        open_system_file(path)
                else:
                    QMessageBox.warning(self, '파일 확인', '서류 원본 파일을 찾을 수 없습니다.')

    def edit_selected_document(self):
        row = self.docs_table.currentRow()
        if row < 0:
            QMessageBox.information(self, '서류 선택', '수정할 서류를 선택해 주세요.')
            return
        document = self.docs_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        try:
            if document['source_type'] == 'case_form':
                self.open_registry_document(document)
            else:
                from document_editor import DocumentEditDialog
                DocumentEditDialog(self.db, document, self.current_profile['id'], self).exec()
            self.refresh_documents_table()
            self.refresh_dashboard()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '수정 실패', str(exc))

    def delete_selected_document(self):
        row = self.docs_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "알림", "삭제할 서류를 먼저 선택해 주세요.")
            return
        document = self.docs_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "서류 삭제", f"'{document['title']}' ({document['doc_type']})을 삭제할까요?\n원본 기록이 삭제되며 업무현황과 AI 맥락에도 반영됩니다. 복구하려면 기존 백업이 필요합니다.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.db.delete_registered_document(document['source_type'], document['id'], self.current_profile['id'])
                self.refresh_documents_table()
                self.refresh_dashboard()
                self.status_bar.showMessage('서류를 삭제했습니다. AI 맥락은 자동으로 다시 갱신됩니다.', 5000)
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, '삭제 실패', str(exc))

    # ================= [PAGE 4: 설정 및 백업] =================
    def create_settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(make_page_header(
            "데이터 관리",
            "저장 위치를 확인하고 전체 기록을 정기적으로 백업하거나 복원합니다.",
            "STORAGE & RECOVERY",
        ))

        # 저장 위치는 상태 정보로 간결하게 표시합니다.
        storage_bar = QFrame()
        storage_bar.setObjectName("storageBar")
        storage_layout = QHBoxLayout(storage_bar)
        storage_layout.setContentsMargins(14, 10, 14, 10)
        storage_layout.addWidget(QLabel("현재 저장 위치"))
        self.db_dir_label = QLabel(self.db.data_dir)
        self.db_dir_label.setObjectName("storagePath")
        self.db_dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        storage_layout.addWidget(self.db_dir_label, stretch=1)
        change_dir_btn = QPushButton("위치 변경")
        change_dir_btn.clicked.connect(self.change_data_directory)
        storage_layout.addWidget(change_dir_btn)
        layout.addWidget(storage_bar)

        # 평소 사용하는 작업은 두 가지 선택지만 전면에 둡니다.
        backup_group = QGroupBox("백업 및 복원")
        bg_layout = QVBoxLayout(backup_group)
        bg_layout.setSpacing(12)

        backup_intro = QLabel("평소에는 전체 백업만 사용하면 됩니다. 대상자 기록과 첨부 서류가 한 파일에 함께 보관됩니다.")
        backup_intro.setObjectName("sectionHint")
        backup_intro.setWordWrap(True)
        bg_layout.addWidget(backup_intro)

        main_actions = QHBoxLayout()
        main_actions.setSpacing(12)
        main_actions.addWidget(make_action_card(
            "전체 백업 만들기",
            "현재 대상자, 상담일지, 첨부 서류를 하나의 ZIP 파일로 저장합니다.",
            "백업 파일 저장",
            self.export_full_zip_backup,
            "primary",
        ))
        main_actions.addWidget(make_action_card(
            "백업에서 복원하기",
            "이전에 만든 ZIP 파일을 불러옵니다. 현재 데이터는 선택한 백업으로 교체됩니다.",
            "백업 파일 선택",
            self.import_full_zip_restore,
            "soft",
        ))
        bg_layout.addLayout(main_actions)

        restore_notice = QLabel("복원하기 전에는 현재 데이터를 먼저 백업해 두는 것이 안전합니다. Windows와 Linux 백업을 모두 사용할 수 있습니다.")
        restore_notice.setObjectName("warningHint")
        restore_notice.setWordWrap(True)
        bg_layout.addWidget(restore_notice)

        advanced_group = QGroupBox("추가 내보내기 · 필요한 경우에만 사용")
        advanced_layout = QHBoxLayout(advanced_group)
        advanced_layout.setContentsMargins(12, 16, 12, 12)
        export_docs_btn = QPushButton("첨부 서류만 내보내기")
        export_docs_btn.clicked.connect(self.export_documents_only_backup)
        export_db_btn = QPushButton("상담 DB만 내보내기")
        export_db_btn.clicked.connect(self.export_single_db_backup)
        import_db_btn = QPushButton("DB 파일 직접 복원")
        set_button_role(import_db_btn, "danger")
        import_db_btn.clicked.connect(self.import_single_db_restore)
        advanced_layout.addWidget(export_docs_btn)
        advanced_layout.addWidget(export_db_btn)
        advanced_layout.addWidget(import_db_btn)
        advanced_layout.addStretch()
        bg_layout.addWidget(advanced_group)

        layout.addWidget(backup_group)

        # 프로그램 설치 파일은 백업 작업과 시각적으로 분리합니다.
        pkg_group = QGroupBox("프로그램 설치 파일")
        pkg_layout = QVBoxLayout(pkg_group)
        pkg_layout.setSpacing(10)

        pkg_cards_layout = QHBoxLayout()
        pkg_cards_layout.setSpacing(12)

        # 윈도우 패키지 카드
        win_card = QFrame()
        win_card.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px;")
        wc_layout = QVBoxLayout(win_card)
        wc_title = QLabel("🪟 Windows 버전 패키지")
        wc_title.setStyleSheet("font-weight: bold; color: #1E293B; font-size: 12px;")
        wc_desc = QLabel("• 설치형: 사회복지_상담기록_AI_설치프로그램_v1.0.exe\n• 무설치: 사회복지_상담기록_AI_무설치포터블.zip\n• 대상: Windows 10, 11 (일반 행정 PC)")
        wc_desc.setStyleSheet("color: #475569; font-size: 11px; line-height: 140%;")
        win_open_btn = QPushButton("📂 윈도우 패키지 폴더 열기")
        win_open_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #1E293B;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 7px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #F1F5F9; }
        """)
        win_open_btn.clicked.connect(lambda: self.open_package_folder("01_Windows_버전"))
        wc_layout.addWidget(wc_title)
        wc_layout.addWidget(wc_desc)
        wc_layout.addWidget(win_open_btn)
        pkg_cards_layout.addWidget(win_card)

        # 리눅스 민트 패키지 카드
        linux_card = QFrame()
        linux_card.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px;")
        lc_layout = QVBoxLayout(linux_card)
        lc_title = QLabel("🐧 Linux Mint 버전 패키지")
        lc_title.setStyleSheet("font-weight: bold; color: #1E293B; font-size: 12px;")
        lc_desc = QLabel("• 전용 압축본: 사회복지_상담기록_AI_리눅스민트_전용.zip\n• 특징: 1.7GB 모델 포함 + run_linux.sh 원클릭 실행\n• 대상: Linux Mint 21, 22 (우분투 계열)")
        lc_desc.setStyleSheet("color: #475569; font-size: 11px; line-height: 140%;")
        linux_open_btn = QPushButton("📂 리눅스 패키지 폴더 열기")
        linux_open_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #1E293B;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 7px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #F1F5F9; }
        """)
        linux_open_btn.clicked.connect(lambda: self.open_package_folder("02_Linux_Mint_버전"))
        lc_layout.addWidget(lc_title)
        lc_layout.addWidget(lc_desc)
        lc_layout.addWidget(linux_open_btn)
        pkg_cards_layout.addWidget(linux_card)

        pkg_layout.addLayout(pkg_cards_layout)
        layout.addWidget(pkg_group)

        ai_group = QGroupBox("로컬 AI 정보")
        aig_layout = QVBoxLayout(ai_group)
        aig_layout.setSpacing(8)

        ai_desc = QLabel(
            "• 적용 모델: Google Gemma-2-2B-it (Q4_K_M 양자화 GGUF)\n"
            "• 구동 엔진: llama.cpp 고속 C++ 네이티브 추론 엔진\n"
            f"• CPU 최적화: 물리 코어 {self.engine.n_threads}스레드 완전 매핑\n"
            "• 개인정보 보안: 네트워크 통신 완전 차단 (외부 API/클라우드 전송 0%)"
        )
        ai_desc.setStyleSheet("color: #334155; line-height: 160%; font-size: 12px;")
        aig_layout.addWidget(ai_desc)
        layout.addWidget(ai_group)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def open_package_folder(self, sub_dir: str = ""):
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "installer_output", sub_dir)
        if not os.path.exists(base_path):
            base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "installer_output")
        open_system_file(base_path)

    def change_data_directory(self):
        dlg = StorageSetupDialog(self, is_change_mode=True)
        if dlg.exec():
            new_dir = config.get_data_dir()
            self.context_controller.stop()
            self.db = Database(data_dir=new_dir)
            self.context_controller.timer.start()
            self.db_dir_label.setText(self.db.data_dir)
            self.refresh_all_data()
            QMessageBox.information(self, "완료", f"데이터 저장 위치가 성공적으로 변경되었습니다:\n{new_dir}")

    def export_full_zip_backup(self):
        default_name = f"복지상담_전체백업_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        save_path, _ = QFileDialog.getSaveFileName(self, "백업 파일 저장", default_name, "백업 파일 (*.zip)")
        if save_path:
            ok, msg = self.db.create_full_backup_zip(save_path)
            if ok:
                QMessageBox.information(
                    self, "백업 완료",
                    "대상자 기록과 첨부 서류를 백업했습니다.\n\n"
                    f"저장 위치: {save_path}\n"
                    f"백업 내용: {msg}"
                )
            else:
                QMessageBox.critical(self, "백업 실패", msg)

    def export_documents_only_backup(self):
        current_os = "Windows" if sys.platform.startswith("win") else ("macOS" if sys.platform == "darwin" else "Linux")
        
        # 필터링 상태 확인 (특정 대상자 필터 중인지 확인)
        selected_cid = None
        filter_label = "전체"
        if hasattr(self, 'doc_filter_client'):
            cid = self.doc_filter_client.currentData()
            if cid and cid > 0:
                selected_cid = cid
                filter_label = self.doc_filter_client.currentText().split(" (")[0]
        
        target_client_id = None
        if selected_cid:
            reply = QMessageBox.question(
                self, "서류 백업 범위 선택",
                f"현재 '{filter_label}' 대상자가 선택되어 있습니다.\n\n"
                f"• [예(Yes)]: '{filter_label}' 대상자의 서류만 백업\n"
                f"• [아니오(No)]: 복지관 '전체 서류' 일괄 백업",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            elif reply == QMessageBox.StandardButton.Yes:
                target_client_id = selected_cid

        target_name_prefix = f"[{filter_label}]_" if target_client_id else "복지관_증빙서류_전체_"
        default_name = f"{target_name_prefix}백업_{current_os}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        save_path, _ = QFileDialog.getSaveFileName(self, "서류 압축 백업 저장", default_name, "서류 압축 파일 (*.zip)")
        if save_path:
            ok, msg, cnt = self.db.export_documents_only_zip(save_path, client_id=target_client_id)
            if ok:
                QMessageBox.information(
                    self, "서류 백업 완료",
                    f"🎉 서류 파일이 성공적으로 압축 백업되었습니다!\n\n"
                    f"• 저장 파일: {save_path}\n"
                    f"• 백업된 서류: 총 {cnt}건\n"
                    f"• 내부 구조: [대상자명]/[구분_서류명.확장자]\n\n"
                    "압축 파일 안에서 HWP, PDF, 이미지 등 원본 서류를 바로 확인하실 수 있습니다."
                )
            else:
                QMessageBox.critical(self, "백업 실패", f"서류 백업 중 오류 발생:\n{msg}")

    def import_full_zip_restore(self):
        import_path, _ = QFileDialog.getOpenFileName(self, "복원할 백업 파일 선택", "", "백업 파일 (*.zip)")
        if import_path:
            reply = QMessageBox.warning(
                self,
                "백업에서 복원할까요?",
                "현재 대상자 기록과 첨부 서류가 선택한 백업 내용으로 교체됩니다.\n"
                "필요하면 취소한 뒤 현재 데이터를 먼저 백업하세요.\n\n"
                f"선택한 파일: {os.path.basename(import_path)}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.context_controller.stop()
                ok, msg, meta = Database.restore_from_backup_zip(import_path, self.db.data_dir)
                self.context_controller.timer.start()
                if ok:
                    self.db = Database(data_dir=self.db.data_dir)
                    self.refresh_all_data()
                    if meta.get("is_documents_only"):
                        docs_cnt = meta.get("total_docs", 0)
                        QMessageBox.information(
                            self, "서류 복원 완료",
                            f"첨부 서류 {docs_cnt}건을 복원했습니다.\n"
                            "서류 보관함에서 확인할 수 있습니다."
                        )
                    else:
                        clients_cnt = meta.get("total_clients", "여러")
                        docs_cnt = meta.get("total_docs", "여러")
                        QMessageBox.information(
                            self, "복원 완료",
                            "백업 내용을 복원했습니다.\n\n"
                            f"대상자 {clients_cnt}명 · 첨부 서류 {docs_cnt}건\n"
                            f"백업 일시: {meta.get('backup_date', '기록 없음')}"
                        )
                else:
                    QMessageBox.critical(self, "복원 실패", msg)

    def export_single_db_backup(self):
        default_name = f"welfare_db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        save_path, _ = QFileDialog.getSaveFileName(self, "단일 DB 백업 저장", default_name, "SQLite DB (*.db)")
        if save_path:
            with self.db.get_connection() as conn:
                conn.commit()
            import shutil
            try:
                shutil.copy2(self.db.db_path, save_path)
                QMessageBox.information(self, "백업 완료", f"welfare_saas.db 파일이 성공적으로 복사 백업되었습니다:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "백업 실패", f"DB 파일 백업 중 오류 발생:\n{str(e)}")

    def import_single_db_restore(self):
        import_path, _ = QFileDialog.getOpenFileName(self, "복원할 DB 파일 선택", "", "SQLite DB (*.db)")
        if import_path:
            reply = QMessageBox.warning(
                self,
                "데이터베이스 복원 경고",
                "현재 데이터베이스 파일이 선택한 DB 파일로 완전히 덮어씌워집니다.\n계속 진행하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                import shutil
                self.context_controller.stop()
                try:
                    shutil.copy2(import_path, self.db.db_path)
                    self.db = Database(data_dir=self.db.data_dir)
                    self.refresh_all_data()
                    QMessageBox.information(self, "복원 완료", "데이터베이스 파일이 성공적으로 복원되었습니다!")
                except Exception as e:
                    QMessageBox.critical(self, "복원 실패", f"DB 복원 중 오류 발생:\n{str(e)}")
                finally:
                    self.context_controller.timer.start()

    def refresh_all_data(self):
        # 저장 위치 변경·백업 복원 뒤에도 각 화면이 새 DB와 현재 사용자 정보를 바라보게 합니다.
        self.current_profile = self.db.get_current_profile()
        self.db.ensure_builtin_templates(self.current_profile["id"], TEMPLATES)
        if hasattr(self, "profile_combo"):
            self.refresh_profile_combo()
        if hasattr(self, "template_manager_page"):
            self.template_manager_page.db = self.db
            self.template_manager_page.storage_label.setText(f"로컬 저장: {self.db.db_path}")
            self.template_manager_page.set_profile(self.current_profile["id"])
        self.refresh_dashboard()
        self.refresh_clients_table()
        if hasattr(self, "case_management_page"):
            self.case_management_page.set_database(self.db)
        self.refresh_ai_client_combo()
        self.refresh_template_combo()
        self.populate_doc_client_filter()
        self.refresh_documents_table()

    # ================= [AI 상담일지 생성 로직] =================
    def apply_styling(self):
        self.setStyleSheet(APP_STYLESHEET)

    def update_system_status(self):
        info = InferenceEngine.get_system_memory_info()
        cores = self.engine.n_threads
        self.status_sys_label.setText(
            f"RAM: {info['used_gb']}GB / {info['total_gb']}GB ({info['percent']}%) | CPU 물리코어: {cores}개"
        )

    def refresh_template_combo(self):
        """현재 사용자의 개인 양식 목록을 상담 작성 화면에 반영합니다."""
        if not hasattr(self, "tmpl_combo"):
            return
        previous_id = self.tmpl_combo.currentData()
        templates = self.db.list_form_templates(self.current_profile["id"])
        self.tmpl_combo.blockSignals(True)
        self.tmpl_combo.clear()
        selected_index = 0
        for index, template in enumerate(templates):
            self.tmpl_combo.addItem(template["name"], template["id"])
            if previous_id and template["id"] == previous_id:
                selected_index = index
        if templates:
            self.tmpl_combo.setCurrentIndex(selected_index)
        self.tmpl_combo.blockSignals(False)
        self.on_template_changed()

    def get_selected_form_template(self):
        template_id = self.tmpl_combo.currentData() if hasattr(self, "tmpl_combo") else None
        if not template_id:
            return None
        return self.db.get_form_template(template_id, self.current_profile["id"])

    def on_template_changed(self):
        template = self.get_selected_form_template()
        if template:
            self.tmpl_desc_label.setText(
                f"[{template.get('category', '상담기록')}] {template.get('description', '')}"
            )
        else:
            self.tmpl_desc_label.setText("사용할 서류 양식을 먼저 만들어 주세요.")

    def load_sample_memo(self):
        template = self.get_selected_form_template()
        if template:
            sample = template.get("example_input", "")
            if not sample:
                QMessageBox.information(self, "예시 메모", "이 양식에는 저장된 예시 메모가 없습니다.")
                return
            self.input_text.setText(sample)
            if not self.name_input.text():
                self.name_input.setText("김OO")

    def check_and_load_model(self):
        if is_model_downloaded():
            self.status_model_label.setText("모델: Gemma-2-2B (준비 완료)")
            self.generate_btn.setEnabled(True)
        else:
            self.status_model_label.setText("모델: 다운로드 필요 (최초 1회)")
            self.generate_btn.setEnabled(False)

    def start_generation(self):
        if self.context_controller.busy():
            self.status_bar.showMessage("대상자 맥락을 갱신 중입니다. 완료 후 상담일지를 생성해 주세요.", 5000)
            return
        raw_text = self.input_text.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "입력 확인", "상담 메모를 먼저 입력해 주세요.")
            return

        # 1. 개인정보 마스킹
        client_name = self.name_input.text().strip()
        final_input = raw_text
        if self.mask_checkbox.isChecked():
            final_input, stats = self.anonymizer.anonymize(raw_text, client_name=client_name)
            masked_count = sum(stats.values())
            if masked_count > 0:
                summary = ", ".join([f"{k} {v}건" for k, v in stats.items() if v > 0])
                self.mask_stat_label.setText(f"🛡️ 개인정보 비식별화 완료 ({summary})")
            else:
                self.mask_stat_label.setText("🛡️ 감지된 민감정보 없음 (안전)")
        else:
            self.mask_stat_label.setText("⚠️ 마스킹 해제됨 (원본 유지)")

        # 2. 프롬프트 구성
        selected_tmpl = self.tmpl_combo.currentText()
        selected_detail = self.detail_combo.currentText()
        template = self.get_selected_form_template()
        if not template:
            QMessageBox.warning(self, "양식 확인", "사용할 서류 양식을 선택해 주세요.")
            return
        prompt = build_prompt(
            selected_tmpl,
            final_input,
            detail_level=selected_detail,
            guide_override=template.get("guide", ""),
        )

        # 첫 모델 로드는 수 초가 걸릴 수 있으므로 UI 스레드 밖에서 처리합니다.
        if not self.engine.is_loaded():
            if self.model_load_worker and self.model_load_worker.isRunning():
                self.status_bar.showMessage("로컬 AI 모델을 불러오는 중입니다.", 3000)
                return
            self.pending_prompt = prompt
            self.generate_btn.setEnabled(False)
            self.status_model_label.setText("모델: 메모리에 불러오는 중…")
            self.status_speed_label.setText("첫 실행 준비 중")
            self.model_load_worker = ModelLoadWorker(self.engine)
            self.model_load_worker.finished_signal.connect(self.on_model_loaded)
            self.model_load_worker.start()
            return

        self.begin_generation(prompt)

    def on_model_loaded(self, success: bool, message: str):
        """백그라운드 모델 로드가 끝난 뒤 대기 중인 작성을 이어갑니다."""
        if not success:
            self.pending_prompt = None
            self.generate_btn.setEnabled(True)
            self.status_model_label.setText("모델: 로드 실패")
            self.status_speed_label.setText("준비 실패")
            QMessageBox.critical(self, "모델 로드 실패", message)
            return

        self.status_model_label.setText("모델: Gemma-2-2B (로드 완료)")
        self.update_system_status()
        prompt = self.pending_prompt
        self.pending_prompt = None
        if prompt:
            self.begin_generation(prompt)
        else:
            self.generate_btn.setEnabled(True)

    def begin_generation(self, prompt: str):
        """준비된 프롬프트의 스트리밍 생성을 시작합니다."""

        # UI 상태
        self.output_text.clear()
        self.last_generated_raw_text = ""
        self.generate_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stop_output_btn.setEnabled(True)
        self.status_speed_label.setText("생성 시작 중...")

        # 스트리밍 스레드 실행
        self.worker = GenerationWorker(self.engine, prompt)
        self.worker.token_signal.connect(self.on_token_received)
        self.worker.metrics_signal.connect(self.on_metrics_updated)
        self.worker.finished_signal.connect(self.on_generation_finished)
        self.worker.start()

    def on_token_received(self, token: str):
        cursor = self.output_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(token)
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

    def on_metrics_updated(self, tps: float, total_tokens: int):
        self.status_speed_label.setText(f"속도: {tps:.1f} 토큰/초 | 총 {total_tokens} 토큰")

    def on_generation_finished(self, success, msg):
        self.generate_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_output_btn.setEnabled(False)
        self.update_system_status()
        if success:
            self.last_generated_raw_text = self.output_text.toPlainText().strip()
            self.apply_selected_form_to_output(show_message=False)
            self.status_bar.showMessage("상담일지 초안 작성이 끝났습니다. 내용을 검토한 뒤 저장하세요.", 5000)
        else:
            self.status_speed_label.setText("작성 실패")
            QMessageBox.critical(self, "AI 작성 실패", msg)

    def stop_generation(self):
        if not self.stop_btn.isEnabled() and not self.stop_output_btn.isEnabled():
            return
        if self.engine:
            self.engine.abort()
        if self.worker and self.worker.isRunning():
            self.worker.wait(500)

        self.status_speed_label.setText("🛑 작성 중단됨")
        self.status_bar.showMessage("🛑 사용자에 의해 상담일지 작성이 즉시 중단되었습니다.", 4000)

        cursor = self.output_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("\n\n[🛑 사용자에 의해 작성이 중단되었습니다.]")
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

        self.generate_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_output_btn.setEnabled(False)

    def apply_selected_form_to_output(self, _checked=False, show_message=True):
        """AI 결과를 현재 사용자의 워드형 표 양식 셀에 배치합니다."""
        template = self.get_selected_form_template()
        if not template:
            if show_message:
                QMessageBox.warning(self, "표 양식 적용", "적용할 서류 양식을 선택해 주세요.")
            return
        generated_text = self.last_generated_raw_text or self.output_text.toPlainText().strip()
        if not generated_text:
            if show_message:
                QMessageBox.information(self, "표 양식 적용", "먼저 상담일지 내용을 작성해 주세요.")
            return
        client_id = self.ai_client_combo.currentData()
        client = self.db.get_client(client_id) if client_id else None
        metadata = {
            "대상자명": client.get("masked_name", "") if client else self.name_input.text().strip(),
            "상담일자": self.session_date_input.date().toString('yyyy-MM-dd'),
            "작성자": self.current_profile["name"],
            "상담방법": self.session_method_input.currentText() or None,
        }
        form_html = template.get("form_html", "") or build_form_html(
            template.get("name", "상담 기록지"),
            template.get("guide", ""),
        )
        form_html = inject_approval_line(
            form_html,
            self.db.get_approval_line(self.current_profile["id"]),
        )
        self.output_text.setHtml(fill_form_html(form_html, metadata, generated_text))
        if show_message:
            self.status_bar.showMessage("선택한 표 양식을 적용했습니다. 셀 내용을 직접 수정한 뒤 저장하세요.", 5000)

    def copy_to_clipboard(self):
        text = self.output_text.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "알림", "복사할 내용이 없습니다.")
            return
        mime_data = QMimeData()
        mime_data.setText(text)
        mime_data.setHtml(self.output_text.toHtml())
        QApplication.clipboard().setMimeData(mime_data)
        self.status_bar.showMessage("✅ 표 모양을 포함해 복사했습니다. 한글이나 워드에 바로 붙여넣을 수 있습니다.", 4000)

    def save_to_file(self):
        text = self.output_text.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "알림", "저장할 내용이 없습니다.")
            return

        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            "상담일지 저장",
            "상담일지.html",
            "표 서식 문서 (*.html);;텍스트 파일 (*.txt)"
        )
        if filename:
            try:
                save_as_html = selected_filter.startswith("표 서식") or filename.lower().endswith((".html", ".htm"))
                if save_as_html and not filename.lower().endswith((".html", ".htm")):
                    filename += ".html"
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(self.output_text.toHtml() if save_as_html else text)
                self.status_bar.showMessage(f"✅ 파일이 저장되었습니다: {filename}", 4000)
            except Exception as e:
                QMessageBox.critical(self, "저장 오류", f"파일 저장 중 오류 발생:\n{str(e)}")

    def clear_output(self):
        self.output_text.clear()
        self.last_generated_raw_text = ""
        self.mask_stat_label.setText("")

    def clear_fields(self):
        self.clear_output()
        self.input_text.clear()

def main():
    # Windows 및 Linux 고해상도(HiDPI) 화면 최적화 (QApplication 생성 전 호출 필수)
    try:
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv)
    window = MainWindow()
    
    # 모니터 화면 크기에 맞추어 작업표시줄과 어우러지게 시원한 최대화 화면으로 시작
    window.showMaximized()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
