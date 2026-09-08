"""
사회복지 스마트 사례관리 SaaS 어시스턴트 - PyQt6 데스크톱 프로그램

업무 메뉴는 현장에서 실제로 나누어 쓰는 네 가지 일로만 구성한다.
- 👥 대상자 관리 (업무 현황 요약 + 대상자 등록·검색·위기도 + 확인할 일정·최근 기록)
- 🗂 사례관리 (AI 대상자 맥락, 단계별 서류, 사정·목표·모니터링·연계 등 전체 과정 검토)
- 📝 서류작성 및 보관함 (상담일지 작성 + 첨부·직접 작성 서류 검색·열람)
- ⚙️ 데이터 관리 (서류 양식 편집 + 전체 백업·복원, 저장 위치)
"""

import os
import sys
import time

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
from counseling_workspace import CounselingWorkspaceMixin
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QComboBox, QPushButton, QCheckBox, QLineEdit,
    QProgressBar, QSplitter, QGroupBox, QFileDialog, QMessageBox,
    QStatusBar, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QScrollArea, QInputDialog, QDateEdit, QDialog, QTabWidget
)
from PyQt6.QtCore import Qt, QEvent, QMimeData, QDate, QTimer
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

# 사이드바 "업무 메뉴"와 QStackedWidget 인덱스를 한 곳에서 관리한다.
PAGE_CLIENTS = 0
PAGE_CASE = 1
PAGE_DOCS = 2
PAGE_DATA = 3

NAV_MENUS = (
    ("대상자 관리", PAGE_CLIENTS),
    ("사례관리", PAGE_CASE),
    ("서류작성 및 보관함", PAGE_DOCS),
    ("데이터 관리", PAGE_DATA),
)

# 대상자 관리 화면 안의 보조 탭
CLIENT_TAB_LIST = 0
CLIENT_TAB_DUE = 1
CLIENT_TAB_RECENT = 2
CLIENT_TAB_DOCS = 3

# 서류작성 및 보관함 화면 안의 탭
DOCS_TAB_WRITE = 0
DOCS_TAB_VAULT = 1

# 데이터 관리 화면 안의 탭
DATA_TAB_FORMS = 0
DATA_TAB_BACKUP = 1

# 사례관리 작업판의 탭
CASE_TAB_CONTEXT = 0
CASE_TAB_MONITORING = 4

class MainWindow(CounselingWorkspaceMixin, QMainWindow):
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
        self.ai_started_at = None

        self.init_ui()
        self.apply_styling()
        self.check_and_load_model()
        self.refresh_all_data()
        self.update_system_status()

        self.context_controller = ContextController(self)

    def closeEvent(self, event):
        if not self.template_manager_page.may_leave():
            event.ignore()
            return
        if not self.persist_counseling_draft():
            event.ignore()
            return
        # 창을 닫은 뒤에도 주기 갱신이 남아 있으면 사라진 저장 위치를 읽다가 프로그램이 죽는다.
        self.activity_timer.stop()
        self.case_management_page.stop_timers()
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
        sidebar.setMinimumWidth(186)
        sidebar.setMaximumWidth(204)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(8)

        # 앱 브랜드: 현장의 '상담 기록지'를 닮은 차분한 업무 도구
        app_title = QLabel("복지상담 기록실")
        app_title.setObjectName("brandTitle")
        app_subtitle = QLabel("상담 · 기록 · 사례관리")
        app_subtitle.setObjectName("brandSubtitle")

        sidebar_layout.addWidget(app_title)
        sidebar_layout.addWidget(app_subtitle)

        nav_section = QLabel("업무 메뉴")
        nav_section.setObjectName("navSection")
        sidebar_layout.addWidget(nav_section)

        # 메뉴 버튼들 (업무 메뉴는 네 가지 일로만 유지한다)
        self.nav_btns = []

        for text, page_idx in NAV_MENUS:
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
        self.profile_combo.setMinimumWidth(110)
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

        sidebar_layout.addWidget(self.build_activity_box())

        # 보안 배지
        security_box = QFrame()
        security_box.setObjectName('securityBox')
        security_box.setStyleSheet("QFrame#securityBox { background-color: #102F2B; border: 1px solid #2C5751; border-radius: 7px; }")
        sec_layout = QVBoxLayout(security_box)
        sec_label = QLabel("● 로컬 처리 중")
        sec_label.setStyleSheet("color: #7FD1BF; font-weight: bold; font-size: 11px;")
        sec_desc = QLabel("AI 입력은 외부로 전송하지 않음\n데이터는 지정 폴더에 보관")
        sec_desc.setWordWrap(True)
        sec_desc.setStyleSheet("color: #94A3B8; font-size: 10px;")
        sec_layout.addWidget(sec_label)
        sec_layout.addWidget(sec_desc)
        sidebar_layout.addWidget(security_box)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFixedWidth(204)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setWidget(sidebar)
        root_layout.addWidget(sidebar_scroll)

        # ================= [우측: 스택 위젯 (업무 메뉴 4화면)] =================
        self.template_manager_page = TemplateManagerPage(
            self.db,
            self.current_profile["id"],
            on_templates_changed=self.refresh_template_combo,
            parent=self,
        )
        self.case_management_page = CaseManagementPage(self.db, self)
        self.case_management_page.status_message.connect(lambda message: self.status_bar.showMessage(message, 4000))

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.create_clients_page())    # PAGE_CLIENTS
        self.stacked_widget.addWidget(self.case_management_page)     # PAGE_CASE
        self.stacked_widget.addWidget(self.create_docs_page())       # PAGE_DOCS
        self.stacked_widget.addWidget(self.create_data_page())       # PAGE_DATA

        # 화면 최소 크기가 전체 창을 밀어내지 않도록 각 작업면을 스크롤 가능하게 한다.
        pages = [self.stacked_widget.widget(i) for i in range(self.stacked_widget.count())]
        for content in pages:
            self.stacked_widget.removeWidget(content)
            self.stacked_widget.addWidget(self.wrap_in_scroll(content))
        root_layout.addWidget(self.stacked_widget, stretch=1)
        self.refresh_profile_combo()

        # 하단 상태바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_model_label = QLabel("모델: 확인 중...")
        self.status_sys_label = QLabel("시스템: 준비 중")
        self.status_speed_label = QLabel("속도: 대기 중")
        self.status_activity_label = QLabel()

        self.status_bar.addWidget(self.status_model_label, stretch=2)
        self.status_bar.addWidget(self.status_sys_label, stretch=2)
        self.status_bar.addPermanentWidget(self.status_activity_label)
        self.status_bar.addPermanentWidget(self.status_speed_label)

        # 백그라운드 AI 작업은 화면 어디에 있어도 보여야 한다.
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self.refresh_activity_indicator)
        self.activity_timer.start(1000)
        self.refresh_activity_indicator()

        # 단축키 설정
        shortcut_run = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_run.activated.connect(lambda: self.start_generation() if self.on_counseling_tab() else None)

        shortcut_esc = QShortcut(QKeySequence("Escape"), self)
        shortcut_esc.activated.connect(self.stop_generation)

        shortcut_save = QShortcut(QKeySequence('Ctrl+S'), self)
        shortcut_save.activated.connect(lambda: self.save_record_to_database() if self.on_counseling_tab() else None)
        shortcut_find = QShortcut(QKeySequence('Ctrl+F'), self)
        shortcut_find.activated.connect(self.focus_client_search)

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

    def build_activity_box(self) -> QFrame:
        """지금 AI가 무엇을 하고 있는지 사이드바에 항상 보여 준다."""
        box = QFrame()
        box.setObjectName("activityBox")
        box.setStyleSheet(
            "QFrame#activityBox { background-color: #14213A; border: 1px solid #2C3E63;"
            " border-radius: 7px; }"
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        caption = QLabel("AI 작업 상태")
        caption.setStyleSheet("color: #93A4C4; font-size: 10px; font-weight: 700;")
        layout.addWidget(caption)

        self.activity_title = QLabel()
        self.activity_title.setWordWrap(True)
        self.activity_title.setStyleSheet("color: #DCE6F7; font-size: 11px; font-weight: 700;")
        layout.addWidget(self.activity_title)

        self.activity_detail = QLabel()
        self.activity_detail.setWordWrap(True)
        self.activity_detail.setStyleSheet("color: #93A4C4; font-size: 10px;")
        layout.addWidget(self.activity_detail)

        # 무한 반복 막대(range 0,0)는 계속 다시 그려지며 화면 검증 스크립트를 멈추게 한다.
        # 실제 진행률을 알 수 있을 때만 막대를 보여 주고, 그 밖에는 경과 시간으로 알린다.
        self.activity_bar = QProgressBar()
        self.activity_bar.setRange(0, 1)
        self.activity_bar.setTextVisible(False)
        self.activity_bar.setFixedHeight(8)
        self.activity_bar.setStyleSheet(
            "QProgressBar { background-color: #0D1728; border: none; border-radius: 4px; }"
            "QProgressBar::chunk { background-color: #4C8BF5; border-radius: 4px; }"
        )
        self.activity_bar.hide()
        layout.addWidget(self.activity_bar)
        return box

    def ai_elapsed_text(self) -> str:
        """작업이 살아 있음을 보여 주는 경과 시간. 매 초 값이 바뀐다."""
        if self.ai_started_at is None:
            return ""
        return f" · {int(time.monotonic() - self.ai_started_at)}초 경과"

    def current_ai_activity(self):
        """지금 돌고 있는 AI 작업을 (제목, 설명, 진행률)로 돌려준다. 없으면 None.

        진행률은 (처리한 양, 전체 양)이며, 남은 양을 알 수 없으면 None이다.
        """
        if self.download_worker and self.download_worker.isRunning():
            return "AI 모델 내려받는 중", "처음 한 번만 필요합니다. 창을 닫지 마세요.", None
        if self.model_load_worker and self.model_load_worker.isRunning():
            return ("AI 모델 불러오는 중",
                    "최초 실행은 20초 이상 걸릴 수 있습니다" + self.ai_elapsed_text(), None)
        if self.worker and self.worker.isRunning():
            return "상담일지 초안 작성 중", self.status_speed_label.text() + self.ai_elapsed_text(), None
        controller = getattr(self, "context_controller", None)
        client_id = controller.current_client_id() if controller else None
        if client_id:
            name = self.client_name(client_id) or "대상자"
            return f"{name} 맥락 갱신 중", controller.progress_text(), controller.progress_values()
        return None

    def client_name(self, client_id: int):
        """표시용 대상자 성명. 저장 위치를 읽을 수 없으면 None."""
        try:
            client = self.db.get_client(client_id)
        except Exception:
            return None
        return client["name"] if client else None

    def refresh_activity_indicator(self):
        """사이드바 표시판과 상태바를 현재 AI 작업에 맞춘다."""
        activity = self.current_ai_activity()
        if activity:
            title, detail, progress = activity
            self.activity_title.setText("● " + title)
            self.activity_title.setStyleSheet("color: #9DC2FF; font-size: 11px; font-weight: 700;")
            self.activity_detail.setText(detail)
            self.activity_bar.setVisible(progress is not None)
            if progress is not None:
                value, maximum = progress
                self.activity_bar.setMaximum(max(1, maximum))
                self.activity_bar.setValue(value)
            self.status_activity_label.setText(f"AI 작업: {title}")
            self.status_activity_label.setToolTip(detail)
            return

        waiting = self.count_pending_context()
        deferred = self.count_deferred_context()
        # 프로그램을 켜기 전부터 밀려 있던 건은 자동으로 돌지 않으므로 따로 알린다.
        deferred_text = (f" 프로그램을 켜기 전에 밀린 대상자 {deferred}명은 사례관리 화면의 "
                         "[맥락 다시 갱신]에서 자료를 골라 반영하세요." if deferred else "")
        if not self.model_ready():
            self.activity_title.setText("○ AI 모델 없음")
            self.activity_title.setStyleSheet("color: #E8B87A; font-size: 11px; font-weight: 700;")
            self.activity_detail.setText(
                (f"대상자 {waiting}명의 맥락 갱신이 기다리고 있습니다. 모델을 준비하면 이어서 진행합니다."
                 if waiting else "직접 작성은 모델 없이도 사용할 수 있습니다.") + deferred_text)
            self.status_activity_label.setText("AI 작업: 모델 없음")
        elif waiting:
            self.activity_title.setText("○ 갱신 대기 중")
            self.activity_title.setStyleSheet("color: #DCE6F7; font-size: 11px; font-weight: 700;")
            self.activity_detail.setText(f"대상자 {waiting}명의 맥락을 곧 갱신합니다." + deferred_text)
            self.status_activity_label.setText(f"AI 작업: 대기 {waiting}명")
        else:
            self.activity_title.setText("○ 진행 중인 작업 없음")
            self.activity_title.setStyleSheet("color: #DCE6F7; font-size: 11px; font-weight: 700;")
            self.activity_detail.setText("기록을 저장하면 맥락을 자동으로 갱신합니다." + deferred_text)
            self.status_activity_label.setText("AI 작업: 없음")
        self.activity_bar.hide()
        self.status_activity_label.setToolTip(self.activity_detail.text())

    def count_pending_context(self) -> int:
        controller = getattr(self, "context_controller", None)
        if not controller:
            return 0
        try:
            return len(controller.pending_client_ids())
        except Exception:
            return 0

    def count_deferred_context(self) -> int:
        """프로그램을 켤 때부터 밀려 있어 직접 눌러야 갱신되는 대상자 수."""
        controller = getattr(self, "context_controller", None)
        if not controller or not hasattr(controller, "deferred_client_ids"):
            return 0
        try:
            return len(controller.deferred_client_ids())
        except Exception:
            return 0

    @staticmethod
    def wrap_in_scroll(content: QWidget) -> QScrollArea:
        """내용이 창보다 커도 화면이 잘리지 않도록 스크롤 영역으로 감싼다."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        scroll.setWidget(content)
        return scroll

    def switch_page(self, page_idx: int):
        self.stacked_widget.setCurrentIndex(page_idx)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == page_idx)

        # 페이지 전환 시 데이터 자동 갱신
        if page_idx == PAGE_CLIENTS:
            self.refresh_dashboard()
            self.refresh_clients_table()
        elif page_idx == PAGE_CASE:
            self.case_management_page.refresh_clients()
        elif page_idx == PAGE_DOCS:
            self.refresh_ai_client_combo()
            self.populate_doc_client_filter()
            self.refresh_documents_table()
        elif page_idx == PAGE_DATA:
            self.template_manager_page.refresh_templates()

    def on_counseling_tab(self) -> bool:
        """Ctrl+Enter·Ctrl+S 단축키는 상담일지 작성 탭이 열린 동안에만 동작한다."""
        return (self.stacked_widget.currentIndex() == PAGE_DOCS
                and self.docs_tabs.currentIndex() == DOCS_TAB_WRITE)

    def open_client_tab(self, tab_idx: int):
        self.switch_page(PAGE_CLIENTS)
        self.client_tabs.setCurrentIndex(tab_idx)

    def open_counseling_writer(self):
        self.switch_page(PAGE_DOCS)
        self.docs_tabs.setCurrentIndex(DOCS_TAB_WRITE)

    def open_document_vault(self):
        self.switch_page(PAGE_DOCS)
        self.docs_tabs.setCurrentIndex(DOCS_TAB_VAULT)

    def open_form_designer(self):
        self.switch_page(PAGE_DATA)
        self.data_tabs.setCurrentIndex(DATA_TAB_FORMS)

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
        if self._generation_busy or not self.persist_counseling_draft():
            self.refresh_profile_combo()
            return
        if not self.template_manager_page.may_leave():
            self.refresh_profile_combo()
            return
        self.db.set_current_profile(profile_id)
        self.current_profile = self.db.get_profile(profile_id)
        self.db.ensure_builtin_templates(profile_id, TEMPLATES)
        if hasattr(self, "template_manager_page"):
            self.template_manager_page.set_profile(profile_id)
        if hasattr(self, "tmpl_combo"):
            self.refresh_template_combo()
        self.restore_counseling_draft()
        self.status_bar.showMessage(
            f"현재 사용자를 '{self.current_profile['name']}'(으)로 전환했습니다.",
            4000,
        )

    # ================= [PAGE 0: 대시보드] =================
    def open_due_task(self):
        item = self.due_table.item(self.due_table.currentRow(), 0)
        if item:
            self.switch_page(PAGE_CASE)
            self.case_management_page.select_client(item.data(Qt.ItemDataRole.UserRole))
            self.case_management_page.tabs.setCurrentIndex(CASE_TAB_MONITORING)

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
        self.open_client_tab(CLIENT_TAB_LIST)
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
        container.setStyleSheet("background: #FFFFFF;")
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
        today = QDate.currentDate().toString('yyyy-MM-dd')
        cutoff = QDate.currentDate().addDays(7).toString('yyyy-MM-dd')
        tasks = [t for t in self.db.list_monitoring_tasks(include_completed=False) if t['due_date'] <= cutoff]
        tasks.sort(key=lambda t: (t['due_date'], t['id']))
        self.due_table.setRowCount(len(tasks))
        self.open_due_btn.setEnabled(False)
        for row, task in enumerate(tasks):
            status = '기한 지남' if task['due_date'] < today else ('오늘' if task['due_date'] == today else '예정')
            for col, value in enumerate((task['due_date'], task['client_name'],
                                        task['task_type'] + (' · ' + task['notes'] if task['notes'] else ''), status)):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, task['client_id'])
                item.setToolTip(value)
                self.due_table.setItem(row, col, item)
        self.due_hint.setText(f'기한이 지났거나 7일 이내 확인할 일정 {len(tasks)}건 · 더블 클릭으로 해당 대상자 열기'
                             if tasks else '7일 이내 확인할 일정이 없습니다. 사례관리 → 모니터링 일정에서 다음 약속을 등록하세요.')
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
            self.case_due_btn.setText(f"7일 이내 모니터링 {upcoming}건 · 확인할 일정 보기  →")
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

    # ================= [PAGE_CLIENTS: 대상자 관리 · 업무 현황] =================
    def create_clients_page(self) -> QWidget:
        """대상자 목록과 업무 현황 요약을 한 화면에 모은 시작 화면."""
        page = QWidget()
        page.setObjectName("pageRoot")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(make_page_header(
            "대상자 관리",
            "오늘 확인할 일과 대상자 현황을 한 화면에서 보고 바로 이어서 처리합니다.",
            "CLIENT REGISTRY",
        ))

        layout.addLayout(self.build_kpi_row())
        layout.addLayout(self.build_quick_action_bar())

        self.case_due_btn = QPushButton("모니터링 일정을 확인하세요")
        self.case_due_btn.setObjectName("caseDueButton")
        self.case_due_btn.clicked.connect(lambda: self.client_tabs.setCurrentIndex(CLIENT_TAB_DUE))
        layout.addWidget(self.case_due_btn)

        self.client_tabs = QTabWidget()
        self.client_tabs.setUsesScrollButtons(True)
        self.client_tabs.addTab(self.build_client_list_tab(), "대상자 목록")
        self.client_tabs.addTab(self.build_due_tab(), "확인할 일정")
        self.client_tabs.addTab(self.build_recent_records_tab(), "최근 상담")
        self.client_tabs.addTab(self.build_recent_documents_tab(), "최근 서류")
        self.client_tabs.setCurrentIndex(CLIENT_TAB_LIST)
        layout.addWidget(self.client_tabs, stretch=1)

        return page

    def build_kpi_row(self) -> QHBoxLayout:
        """업무 현황 KPI 카드 네 장. 누르면 해당 목록으로 바로 이동한다."""
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(14)

        self.kpi_clients = self.create_kpi_card(
            "총 관리 대상자", "0명", "#176B5B", "#E3F0EC", "등록된 전체 사례 대상자",
            lambda: self.open_client_tab(CLIENT_TAB_LIST))
        self.kpi_high_risk = self.create_kpi_card(
            "고위기 집중관리", "0명", "#B83A4B", "#FCEBED", "집중 모니터링 필요 대상",
            self.nav_to_high_risk_clients)
        self.kpi_monthly = self.create_kpi_card(
            "이달의 상담 실적", "0건", "#237A64", "#E7F3EF", "이번 달 누적 상담 기록",
            lambda: self.open_client_tab(CLIENT_TAB_RECENT))
        self.kpi_docs = self.create_kpi_card(
            "등록 서류", "0건", "#A76318", "#FFF1DC", "작성 서류·상담일지·첨부 파일",
            self.open_document_vault)

        for card in (self.kpi_clients, self.kpi_high_risk, self.kpi_monthly, self.kpi_docs):
            kpi_layout.addWidget(card)
        return kpi_layout

    def build_quick_action_bar(self) -> QHBoxLayout:
        """대상자 화면에서 가장 자주 누르는 다섯 가지 작업."""
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        act_label = QLabel("⚡ 빠른 실행:")
        act_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        act_label.setStyleSheet("color: #475569; padding-right: 4px;")
        action_layout.addWidget(act_label)

        btn_new_client = QPushButton("대상자 등록")
        set_button_role(btn_new_client, "primary")
        btn_new_client.clicked.connect(self.open_new_client_dialog)

        btn_new_counsel = QPushButton("상담 작성")
        set_button_role(btn_new_counsel, "soft")
        btn_new_counsel.clicked.connect(self.open_counseling_writer)

        btn_manual_counsel = QPushButton("직접 작성")
        set_button_role(btn_manual_counsel, "soft")
        btn_manual_counsel.clicked.connect(self.open_manual_counseling_dialog)

        btn_new_doc = QPushButton("서류 첨부")
        btn_new_doc.clicked.connect(self.open_new_document_dialog)

        btn_typed_memo = QPushButton("메모 보관")
        btn_typed_memo.clicked.connect(self.open_new_typed_memo_dialog)

        for button in (btn_new_client, btn_new_counsel, btn_manual_counsel, btn_new_doc, btn_typed_memo):
            action_layout.addWidget(button)
        action_layout.addStretch()
        return action_layout

    def build_client_list_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(10)

        # 검색 및 필터
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("대상자 찾기"))

        self.client_search_input = QLineEdit()
        self.client_search_input.setPlaceholderText("🔍 성명, 가명, 연락처, 주소 검색...")
        self.client_search_input.setFixedWidth(220)
        self.client_search_input.setClearButtonEnabled(True)
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
        top_layout.addStretch()

        self.client_count_label = QLabel()
        self.client_count_label.setObjectName('sectionHint')
        top_layout.addWidget(self.client_count_label)

        reset_clients = QPushButton('필터 초기화')
        reset_clients.clicked.connect(self.reset_client_filters)
        top_layout.addWidget(reset_clients)
        layout.addLayout(top_layout)

        # 선택한 대상자에게 적용하는 작업 행
        act_row = QHBoxLayout()
        act_caption = QLabel("선택한 대상자:")
        act_caption.setObjectName('sectionHint')
        act_row.addWidget(act_caption)

        btn_detail = QPushButton("상세·이력")
        set_button_role(btn_detail, "soft")
        btn_detail.clicked.connect(self.open_selected_client_detail)

        btn_case = QPushButton("사례관리")
        set_button_role(btn_case, "soft")
        btn_case.clicked.connect(self.open_case_for_selected_client)

        btn_counsel = QPushButton("상담 작성")
        set_button_role(btn_counsel, "primary")
        btn_counsel.clicked.connect(self.write_counsel_for_selected_client)

        btn_manual = QPushButton("직접 작성")
        set_button_role(btn_manual, "soft")
        btn_manual.clicked.connect(self.write_manual_for_selected_client)

        btn_edit = QPushButton("정보 수정")
        btn_edit.clicked.connect(self.open_edit_client_dialog)

        btn_del = QPushButton("삭제")
        set_button_role(btn_del, "danger")
        btn_del.clicked.connect(self.delete_selected_client)

        for button in (btn_detail, btn_case, btn_counsel, btn_manual, btn_edit, btn_del):
            act_row.addWidget(button)
        act_row.addStretch()
        layout.addLayout(act_row)

        # 대상자 테이블
        self.clients_table = QTableWidget()
        self.clients_table.setColumnCount(8)
        self.clients_table.setHorizontalHeaderLabels(["ID", "성명", "가명(비식별)", "성별/생년", "위기도", "수급자격", "연락처", "주소"])
        self.clients_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.clients_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.clients_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.clients_table.verticalHeader().hide()
        self.clients_table.setColumnHidden(0, True)
        self.clients_table.setAlternatingRowColors(True)
        self.client_selection_actions = [btn_detail, btn_case, btn_counsel, btn_manual, btn_edit, btn_del]
        self.clients_table.itemSelectionChanged.connect(self.update_client_actions)
        self.clients_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.clients_table.cellDoubleClicked.connect(lambda r, c: self.open_selected_client_detail())
        layout.addWidget(self.clients_table, stretch=1)

        return tab

    def build_due_tab(self) -> QWidget:
        tab = QWidget()
        due_layout = QVBoxLayout(tab)
        due_layout.setContentsMargins(4, 10, 4, 4)
        self.due_hint = QLabel('일정을 선택하고 대상자 작업판 열기를 누르세요.')
        self.due_hint.setObjectName('sectionHint')
        due_layout.addWidget(self.due_hint)
        self.due_table = QTableWidget(0, 4)
        self.due_table.setHorizontalHeaderLabels(['예정일', '대상자', '확인할 일', '상태'])
        self.due_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.due_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.due_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.due_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.due_table.verticalHeader().hide()
        self.due_table.cellDoubleClicked.connect(lambda *_: self.open_due_task())
        due_layout.addWidget(self.due_table, 1)
        self.open_due_btn = QPushButton('대상자 작업판 열기')
        self.open_due_btn.clicked.connect(self.open_due_task)
        self.open_due_btn.setEnabled(False)
        self.due_table.itemSelectionChanged.connect(lambda: self.open_due_btn.setEnabled(bool(self.due_table.selectedItems())))
        due_layout.addWidget(self.open_due_btn)
        return tab

    def build_recent_records_tab(self) -> QWidget:
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
        return recent_group

    def build_recent_documents_tab(self) -> QWidget:
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
        return documents_group

    def reset_client_filters(self):
        for widget in (self.client_search_input, self.filter_risk, self.filter_welfare):
            widget.blockSignals(True)
        self.client_search_input.clear()
        self.filter_risk.setCurrentIndex(0)
        self.filter_welfare.setCurrentIndex(0)
        for widget in (self.client_search_input, self.filter_risk, self.filter_welfare):
            widget.blockSignals(False)
        self.refresh_clients_table()

    def update_client_actions(self):
        selected = bool(self.clients_table.selectedItems())
        for button in self.client_selection_actions:
            button.setEnabled(selected)

    def refresh_clients_table(self):
        selected_id = self.get_selected_client_id()
        kw = self.client_search_input.text().strip()
        risk = self.filter_risk.currentText()
        welf = self.filter_welfare.currentText()
        clients = self.db.list_clients(keyword=kw, risk_filter=risk, welfare_filter=welf)

        self.clients_table.setSortingEnabled(False)
        self.clients_table.clearSelection()
        self.clients_table.setCurrentCell(-1, -1)
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
        for row in range(self.clients_table.rowCount()):
            if self.clients_table.item(row, 0).data(Qt.ItemDataRole.DisplayRole) == selected_id:
                self.clients_table.selectRow(row)
                break
        self.client_count_label.setText(f'{len(clients)}명' if clients else '검색 결과 없음')
        self.update_client_actions()

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
        self.switch_page(PAGE_CASE)
        self.case_management_page.select_client(cid)

    def delete_selected_client(self):
        cid = self.get_selected_client_id()
        if self._generation_busy and cid == self.ai_client_combo.currentData():
            self.status_bar.showMessage('이 대상자의 초안 작성을 마친 뒤 삭제하세요.', 4000)
            return
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
            if self._draft_client == cid:
                self._draft_ready = False
                self._draft_timer.stop()
                self.refresh_ai_client_combo()
                self.restore_counseling_draft()
            self.refresh_clients_table()
            self.refresh_dashboard()
    # ================= [PAGE_DOCS: 서류작성 및 보관함] =================
    def create_docs_page(self) -> QWidget:
        """상담일지를 쓰는 곳과 완성된 서류를 찾는 곳을 한 메뉴 안의 두 탭으로 둔다."""
        page = QWidget()
        page.setObjectName("pageRoot")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 0)
        layout.setSpacing(0)

        self.docs_tabs = QTabWidget()
        self.docs_tabs.setUsesScrollButtons(True)
        self.docs_tabs.addTab(self.wrap_in_scroll(self.build_counseling_workspace()), "상담일지 작성")
        self.docs_tabs.addTab(self.wrap_in_scroll(self.create_documents_page()), "서류 보관함")
        self.docs_tabs.setCurrentIndex(DOCS_TAB_WRITE)
        self.docs_tabs.currentChanged.connect(self.on_docs_tab_changed)
        layout.addWidget(self.docs_tabs)
        return page

    def on_docs_tab_changed(self, index: int):
        """탭을 옮길 때마다 대상자 목록과 서류 목록을 최신 상태로 맞춘다."""
        if index == DOCS_TAB_WRITE:
            self.refresh_ai_client_combo()
        else:
            self.populate_doc_client_filter()
            self.refresh_documents_table()

    # ================= [PAGE_DATA: 데이터 관리] =================
    def create_data_page(self) -> QWidget:
        """서류 양식 편집과 데이터 백업·복원을 한 메뉴 안의 두 탭으로 둔다."""
        page = QWidget()
        page.setObjectName("pageRoot")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 0)
        layout.setSpacing(0)

        self.data_tabs = QTabWidget()
        self.data_tabs.setUsesScrollButtons(True)
        self.data_tabs.addTab(self.wrap_in_scroll(self.template_manager_page), "서류 양식")
        self.data_tabs.addTab(self.create_settings_page(), "데이터 백업·복원")
        self.data_tabs.setCurrentIndex(DATA_TAB_FORMS)
        layout.addWidget(self.data_tabs)
        return page

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'writing_splitter'):
            orientation = Qt.Orientation.Vertical if self.width() < 1180 else Qt.Orientation.Horizontal
            if self.writing_splitter.orientation() != orientation:
                self.writing_splitter.setOrientation(orientation)

    def focus_client_search(self):
        self.open_client_tab(CLIENT_TAB_LIST)
        self.client_search_input.setFocus()
        self.client_search_input.selectAll()

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
        if self._draft_ready and not self.persist_counseling_draft():
            self.ai_client_combo.blockSignals(True)
            self.ai_client_combo.setCurrentIndex(self.ai_client_combo.findData(self._draft_client))
            self.ai_client_combo.blockSignals(False)
            return
        self.restore_counseling_draft()

    def switch_to_ai_counsel_with_client(self, client_id: int):
        if self._generation_busy:
            self.status_bar.showMessage('AI 초안 작성을 마친 뒤 대상자를 변경하세요.', 4000)
            return
        self.open_counseling_writer()
        for idx in range(self.ai_client_combo.count()):
            if self.ai_client_combo.itemData(idx) == client_id:
                self.ai_client_combo.setCurrentIndex(idx)
                break

    def save_record_to_database(self):
        if self._generation_busy or self.counseling_state() == self._saved_state:
            return
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

        data['session_method'] = self.session_method_input.currentText()
        if self._record_id and self._saved_state:
            data['_expected'] = {
                'ai_result': self._saved_state['text'].strip(),
                'session_date': self._saved_state['date'],
                'session_method': self._saved_state['method'],
                'raw_memo': self._saved_state['memo'].strip(),
            }
        try:
            if self._record_id:
                self.db.update_counseling_record(self._record_id, data)
            else:
                self._record_id = self.db.add_counseling_record(data)
        except Exception as exc:
            QMessageBox.warning(self, '상담 저장 실패', f'내용은 작성 화면에 남아 있습니다.\n{exc}')
            return
        self._saved_state = self.counseling_state()
        self.persist_counseling_draft()
        self.update_counseling_actions()
        self.status_bar.showMessage('상담 이력에 저장했습니다. 다음 상담은 새 상담 시작을 눌러 주세요.', 5000)

        self.refresh_dashboard()

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

        btn_add_doc = QPushButton("➕ 서류 첨부")
        set_button_role(btn_add_doc, "primary")
        btn_add_doc.setToolTip("HWP·PDF·이미지 등 원본 서류 파일을 대상자에게 첨부합니다.")
        btn_add_doc.clicked.connect(self.open_new_document_dialog)

        btn_type_doc = QPushButton("✍️ 직접 작성")
        set_button_role(btn_type_doc, "soft")
        btn_type_doc.setToolTip("메모나 서류를 이 프로그램에서 직접 타이핑해 보관합니다.")
        btn_type_doc.clicked.connect(self.open_new_typed_memo_dialog)

        btn_open_doc = QPushButton("열기")
        btn_open_doc.setToolTip("선택한 서류를 엽니다. (HWP/PDF/TXT)")
        btn_open_doc.clicked.connect(self.open_selected_document)

        btn_edit_doc = QPushButton("수정")
        btn_edit_doc.setToolTip("선택한 서류의 제목·구분·내용을 고칩니다.")
        btn_edit_doc.clicked.connect(self.edit_selected_document)

        btn_del_doc = QPushButton("삭제")
        set_button_role(btn_del_doc, "danger")
        btn_del_doc.clicked.connect(self.delete_selected_document)

        btn_backup_docs = QPushButton("📦 일괄 백업")
        set_button_role(btn_backup_docs, "soft")
        btn_backup_docs.setToolTip("현재 대상자 필터에 맞춰 첨부 서류를 ZIP으로 내보냅니다.")
        btn_backup_docs.clicked.connect(self.export_documents_only_backup)

        for button in (btn_add_doc, btn_type_doc, btn_open_doc, btn_edit_doc, btn_del_doc, btn_backup_docs):
            top_layout.addWidget(button)
        top_layout.addStretch()
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
        self.doc_search_input.setClearButtonEnabled(True)
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
        self.docs_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.docs_table.verticalHeader().hide()
        self.docs_table.setColumnHidden(0, True)
        self.docs_table.setAlternatingRowColors(True)
        self.docs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.docs_table.cellDoubleClicked.connect(lambda r, c: self.open_selected_document())
        layout.addWidget(self.docs_table, stretch=1)
        self.document_count_label = QLabel()
        self.document_count_label.setObjectName('sectionHint')
        layout.addWidget(self.document_count_label)

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
        sel_idx = 1 if current_data == -1 else 0
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
        selected = self.docs_table.item(self.docs_table.currentRow(), 0)
        previous = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.docs_table.setSortingEnabled(False)
        self.docs_table.clearSelection()
        self.docs_table.setCurrentCell(-1, -1)
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
        if previous:
            for row in range(self.docs_table.rowCount()):
                current = self.docs_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                if (current['source_type'], current['id']) == (previous['source_type'], previous['id']):
                    self.docs_table.selectRow(row)
                    break
        self.document_count_label.setText(f'서류 {len(docs)}건 · 더블 클릭으로 열기' if docs else
                                          '조건에 맞는 서류가 없습니다. 필터를 초기화하거나 새 서류를 등록하세요.')

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
            "데이터 백업·복원",
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
        if self._generation_busy or not self.persist_counseling_draft():
            self.status_bar.showMessage('진행 중인 작성을 마치고 저장 위치를 변경하세요.', 4000)
            return
        if not self.template_manager_page.may_leave():
            return
        dlg = StorageSetupDialog(self, is_change_mode=True)
        if dlg.exec():
            new_dir = config.get_data_dir()
            self.context_controller.stop()
            self.db = Database(data_dir=new_dir)
            self.context_controller.resume()
            self.db_dir_label.setText(self.db.data_dir)
            self.refresh_all_data()
            QMessageBox.information(self, "완료", f"데이터 저장 위치가 성공적으로 변경되었습니다:\n{new_dir}")

    def export_full_zip_backup(self):
        if not self.persist_counseling_draft():
            return
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
        if self._generation_busy or not self.persist_counseling_draft():
            self.status_bar.showMessage('진행 중인 작성을 마친 뒤 복원하세요.', 4000)
            return
        if not self.template_manager_page.may_leave():
            return
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
                if ok:
                    self.db = Database(data_dir=self.db.data_dir)
                    self.refresh_all_data()
                    # 복원한 저장 위치를 연 뒤에 감시를 다시 시작해야 밀린 건을 제대로 셈한다.
                    self.context_controller.resume()
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
                    self.context_controller.resume()
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
        if self._generation_busy or not self.persist_counseling_draft():
            self.status_bar.showMessage('진행 중인 작성을 마친 뒤 복원하세요.', 4000)
            return
        if not self.template_manager_page.may_leave():
            return
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
                    self.context_controller.resume()

    def refresh_all_data(self):
        # 저장 위치 변경·백업 복원 뒤에도 각 화면이 새 DB와 현재 사용자 정보를 바라보게 합니다.
        self.current_profile = self.db.get_current_profile()
        self.db.ensure_builtin_templates(self.current_profile["id"], TEMPLATES)
        if hasattr(self, "profile_combo"):
            self.refresh_profile_combo()
        if hasattr(self, "template_manager_page"):
            self.template_manager_page.db = self.db
            self.template_manager_page.set_storage_path(self.db.db_path)
            self.template_manager_page.set_profile(self.current_profile["id"])
        self.refresh_dashboard()
        self.refresh_clients_table()
        if hasattr(self, "case_management_page"):
            self.case_management_page.set_database(self.db)
        self.refresh_ai_client_combo()
        self.refresh_template_combo()
        self.populate_doc_client_filter()
        self.refresh_documents_table()
        self.restore_counseling_draft()

    # ================= [AI 상담일지 생성 로직] =================
    def apply_styling(self):
        self.setStyleSheet(APP_STYLESHEET)

    def update_system_status(self):
        info = InferenceEngine.get_system_memory_info()
        cores = self.engine.n_threads
        self.status_sys_label.setText(f"현재 사용자: {self.current_profile['name']}")
        self.status_sys_label.setToolTip(
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
        selected_index = next((i for i, t in enumerate(templates) if t.get('source_key') == '상담일지 (사례관리양식)'), 0)
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
                '확인한 사실과 담당자의 판단을 구분해서 적어 주세요.' if template.get('source_key')
                else template.get('description', '')
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
            if self.input_text.toPlainText().strip() and not self.confirm_replace('현재 메모를 예시 메모로 바꿀까요?'):
                return
            self.input_text.setPlainText(sample)
            if not self.name_input.text():
                self.name_input.setText("김OO")

    def model_ready(self) -> bool:
        """내려받은 모델이 실제로 쓸 수 있는 상태인지 판단하는 단일 기준."""
        return is_model_downloaded()

    def check_and_load_model(self):
        if self.model_ready():
            self.status_model_label.setText("모델: Gemma-2-2B (준비 완료)")
            self.generate_btn.setEnabled(True)
        else:
            self.status_model_label.setText("모델: 다운로드 필요 (최초 1회)")
            self.generate_btn.setEnabled(False)

    def start_generation(self):
        if self._generation_busy or any(w and w.isRunning() for w in (self.worker, self.model_load_worker)):
            return
        if not self.model_ready():
            self.set_generation_phase('AI 모델이 없어 초안을 만들 수 없습니다. 오른쪽 칸에 직접 작성해 저장할 수 있습니다.')
            self.status_bar.showMessage('AI 모델을 설치한 뒤 사용하세요. 직접 작성은 바로 가능합니다.', 5000)
            return
        if self.context_controller.busy():
            self.set_generation_phase('다른 대상자의 맥락을 갱신하는 중입니다. 왼쪽 아래 AI 작업 상태가 끝나면 다시 눌러 주세요.')
            self.status_bar.showMessage("대상자 맥락을 갱신 중입니다. 완료 후 상담일지를 생성해 주세요.", 5000)
            return
        raw_text = self.input_text.toPlainText().strip()
        if not raw_text:
            self.set_generation_phase()
            QMessageBox.warning(self, "입력 확인", "상담 메모를 먼저 입력해 주세요.")
            return

        if self.output_text.toPlainText().strip() and not self.confirm_replace('현재 결과를 새 AI 초안으로 바꿀까요? 직접 수정한 내용도 바뀝니다.'):
            return
        self._generation_cancelled = False

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
                self.mask_stat_label.setText("🛡️ 감지된 개인정보 패턴 없음 · 본문을 직접 확인하세요")
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
            self.set_counseling_busy(True)
            self.set_generation_phase('AI 모델을 메모리에 불러오는 중입니다. 최초 실행은 20초 이상 걸릴 수 있습니다.')
            self.pending_prompt = prompt
            self.generate_btn.setEnabled(False)
            self.status_model_label.setText("모델: 메모리에 불러오는 중…")
            self.status_speed_label.setText("첫 실행 준비 중")
            self.ai_started_at = time.monotonic()
            self.refresh_activity_indicator()
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
            self.set_counseling_busy(False)
            self.status_model_label.setText("모델: 로드 실패")
            self.status_speed_label.setText("준비 실패")
            self.set_generation_phase(f'AI 모델을 불러오지 못했습니다: {message}')
            self.refresh_activity_indicator()
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
        self.set_counseling_busy(True)
        self.output_text.clear()
        self.last_generated_raw_text = ""
        self.generate_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stop_output_btn.setEnabled(True)
        self.status_speed_label.setText("생성 시작 중...")
        self.ai_started_at = time.monotonic()
        self.set_generation_phase('AI가 초안을 작성하는 중입니다. 결과가 아래 칸에 실시간으로 나타납니다.')
        self.refresh_activity_indicator()

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
        self.set_generation_phase(
            f'AI가 초안을 작성하는 중입니다 · {total_tokens}토큰 · 초당 {tps:.1f}토큰')

    def on_generation_finished(self, success, msg):
        self.set_counseling_busy(False)
        self.generate_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_output_btn.setEnabled(False)
        self.update_system_status()
        if self._generation_cancelled or msg == '중단':
            self.status_speed_label.setText('작성 중단됨')
            self.set_generation_phase('작성을 중단했습니다. 작성된 부분은 그대로 남아 있습니다.')
            self.status_bar.showMessage('작성한 부분을 남겼습니다. 검토하거나 다시 정리하세요.', 5000)
        elif success:
            self.last_generated_raw_text = self.output_text.toPlainText().strip()
            self.apply_selected_form_to_output(show_message=False)
            self.set_generation_phase('초안 작성을 끝냈습니다. 내용을 검토한 뒤 상담 이력에 저장하세요.')
            self.status_bar.showMessage('초안 작성이 끝났습니다. 내용을 검토한 뒤 저장하세요.', 5000)
        else:
            self.status_speed_label.setText('작성 실패')
            self.set_generation_phase(f'AI 작성에 실패했습니다: {msg}')
            QMessageBox.warning(self, 'AI 작성 실패', msg)
        self.persist_counseling_draft()
        self.update_counseling_actions()
        self.ai_started_at = None
        self.refresh_activity_indicator()

    def stop_generation(self):
        if not self._generation_busy or not self.worker or not self.worker.isRunning():
            return
        self._generation_cancelled = True
        self.engine.abort()
        self.stop_btn.setEnabled(False)
        self.stop_output_btn.setEnabled(False)
        self.status_speed_label.setText('중단 처리 중…')
        self.set_generation_phase('중단을 요청했습니다. 지금 만들던 문장까지 마치고 멈춥니다.')

    def apply_selected_form_to_output(self, _checked=False, show_message=True):
        """AI 결과를 현재 사용자의 워드형 표 양식 셀에 배치합니다."""
        template = self.get_selected_form_template()
        if not template:
            if show_message:
                QMessageBox.warning(self, "표 양식 적용", "적용할 서류 양식을 선택해 주세요.")
            return
        if show_message and self.last_generated_raw_text and not self.confirm_replace('표 양식을 다시 적용하면 원래 AI 초안을 사용합니다. 직접 수정한 내용을 바꿀까요?'):
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
        if self._generation_busy:
            return
        if (self.input_text.toPlainText().strip() or self.output_text.toPlainText().strip()) and self.counseling_state() != self._saved_state:
            if not self.confirm_replace('상담 이력에 저장하지 않은 작성 내용을 비우고 새 상담을 시작할까요?'):
                return
        self.clear_output()
        self.input_text.clear()
        self.session_date_input.setDate(QDate.currentDate())
        self.session_method_input.setCurrentIndex(0)
        self._record_id = None
        self._saved_state = None
        self.set_generation_phase()
        self.persist_counseling_draft()
        self.update_counseling_actions()
        self.input_text.setFocus()

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
