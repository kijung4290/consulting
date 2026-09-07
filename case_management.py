"""대상자별 사례관리 5대 업무를 한 화면에서 처리하는 작업판."""

from typing import Optional

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget, QScrollArea,
)

from database import Database
from case_forms import CaseFormsPanel
from ui_theme import make_page_header, set_button_role
from client_context import read_context


STAGES = ["접수", "사정", "계획", "개입", "점검", "종결", "사후관리"]
ASSESSMENT_DOMAINS = ["경제", "건강", "주거", "돌봄", "가족관계", "사회관계", "고용·교육", "안전"]
RISK_LEVELS = ["0 · 안정", "1 · 관찰", "2 · 주의", "3 · 긴급"]


class CaseManagementPage(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id: Optional[int] = None
        self.assessment_inputs = {}
        self._client_drafts = {}
        self._build_ui()
        self.refresh_clients()
        self.context_timer = QTimer(self)
        self.context_timer.timeout.connect(self.refresh_context)
        self.context_timer.start(1500)

    def _build_ui(self):
        self.setObjectName("pageRoot")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)
        root.addWidget(make_page_header(
            "사례관리 작업판",
            "단계별 서류를 작성하고 이력을 확인하세요. 보조 업무 탭의 입력은 대상자별로 구분됩니다.",
            "CASE MANAGEMENT",
        ))

        selector = QFrame()
        selector.setObjectName("caseSelector")
        selector_layout = QHBoxLayout(selector)
        selector_layout.setContentsMargins(14, 10, 14, 10)
        selector_layout.addWidget(QLabel("대상자"))
        self.client_combo = QComboBox()
        self.client_combo.setMinimumWidth(300)
        self.client_combo.currentIndexChanged.connect(self._on_client_changed)
        selector_layout.addWidget(self.client_combo)
        self.case_summary = QLabel("대상자를 선택해 주세요.")
        self.case_summary.setObjectName("caseSummary")
        selector_layout.addWidget(self.case_summary, stretch=1)
        root.addWidget(selector)

        stage_group = QGroupBox("사례 진행단계")
        stage_layout = QHBoxLayout(stage_group)
        stage_layout.setContentsMargins(12, 18, 12, 10)
        self.stage_combo = QComboBox()
        self.stage_combo.addItems(STAGES)
        self.stage_combo.setMinimumWidth(130)
        self.stage_note = QLineEdit()
        self.stage_note.setPlaceholderText("현재 단계에 대한 간단한 메모")
        stage_save = QPushButton("단계 저장")
        set_button_role(stage_save, "primary")
        stage_save.clicked.connect(self._save_stage)
        stage_layout.addWidget(QLabel("현재 단계"))
        stage_layout.addWidget(self.stage_combo)
        stage_layout.addWidget(self.stage_note, stretch=1)
        stage_layout.addWidget(stage_save)
        root.addWidget(stage_group)

        self.tabs = QTabWidget()
        context_page = QWidget()
        context_layout = QVBoxLayout(context_page)
        self.context_status = QLabel("등록·상담·서류 저장 후 로컬 AI가 자동으로 갱신합니다.")
        self.context_status.setWordWrap(True)
        context_layout.addWidget(self.context_status)
        retry = QPushButton("맥락 다시 갱신")
        retry.clicked.connect(self.retry_context)
        context_layout.addWidget(retry)
        self.context_text = QTextEdit()
        self.context_text.setReadOnly(True)
        context_layout.addWidget(self.context_text)
        self.tabs.addTab(context_page, "AI 대상자 맥락")
        self.forms_panel = CaseFormsPanel(self.db)
        self.tabs.addTab(self.forms_panel, "단계별 서류·작성 이력")
        for page, title in ((self._build_assessment_tab(), "욕구·위기도 사정"),
                            (self._build_goals_tab(), "목표·개입계획"),
                            (self._build_monitoring_tab(), "모니터링 일정"),
                            (self._build_services_tab(), "서비스 연계·지역자원")):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
        root.addWidget(self.tabs, stretch=1)

    def refresh_context(self):
        context = read_context(self.db, self.client_id) if self.client_id else {}
        status = "대상자를 선택해 주세요."
        if context:
            status = ("갱신 대기·처리 중 (로컬 AI 모델 설치 필요)" if context['revision'] != context['processed_revision']
                      else "최신 기록 반영 완료 · " + context['updated_at'] + " UTC")
            if context['error']:
                status = "갱신 실패 · " + context['error'] + " · 다시 갱신을 눌러 주세요."
        self.context_status.setText(status + "\nAI 요약은 담당자 확인이 필요합니다. 근거 번호는 각 기록의 ID입니다.")
        text = context.get('summary', '') + "\n\n[근거 자료]\n" + context.get('sources', '')
        if self.context_text.toPlainText() != text:
            self.context_text.setPlainText(text)

    def retry_context(self):
        if self.client_id:
            with self.db.get_connection() as conn:
                conn.execute("UPDATE client_context SET revision=revision+1, error='' WHERE client_id=?", (self.client_id,))
            self.refresh_context()

    @staticmethod
    def _date_edit(days_from_today: int = 0) -> QDateEdit:
        widget = QDateEdit(QDate.currentDate().addDays(days_from_today))
        widget.setCalendarPopup(True)
        widget.setDisplayFormat("yyyy-MM-dd")
        return widget

    @staticmethod
    def _configure_table(table: QTableWidget, headers):
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

    def _build_assessment_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        guide = QLabel("각 영역의 현재 위험 수준을 선택하고 판단 근거를 요약해 저장하세요. 이전 사정은 이력으로 남습니다.")
        guide.setObjectName("sectionHint")
        layout.addWidget(guide)

        domains = QFrame()
        form = QFormLayout(domains)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        for domain in ASSESSMENT_DOMAINS:
            combo = QComboBox()
            combo.addItems(RISK_LEVELS)
            self.assessment_inputs[domain] = combo
            form.addRow(domain, combo)
        layout.addWidget(domains)

        assessment_row = QHBoxLayout()
        self.assessment_summary = QLineEdit()
        self.assessment_summary.setPlaceholderText("주요 욕구, 강점, 위험 근거를 요약해 주세요")
        save_btn = QPushButton("사정 결과 저장")
        set_button_role(save_btn, "primary")
        save_btn.clicked.connect(self._save_assessment)
        assessment_row.addWidget(self.assessment_summary, stretch=1)
        assessment_row.addWidget(save_btn)
        layout.addLayout(assessment_row)

        self.assessment_table = QTableWidget()
        self._configure_table(self.assessment_table, ["사정일", "총 위험점수", "최고 위험영역", "요약"])
        layout.addWidget(self.assessment_table, stretch=1)
        return page

    def _build_goals_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        form_row = QHBoxLayout()
        self.goal_title = QLineEdit()
        self.goal_title.setPlaceholderText("달성할 목표")
        self.goal_action = QLineEdit()
        self.goal_action.setPlaceholderText("구체적인 개입 내용")
        self.goal_due = self._date_edit(30)
        add_btn = QPushButton("계획 추가")
        set_button_role(add_btn, "primary")
        add_btn.clicked.connect(self._add_goal)
        form_row.addWidget(self.goal_title, 2)
        form_row.addWidget(self.goal_action, 3)
        form_row.addWidget(self.goal_due)
        form_row.addWidget(add_btn)
        layout.addLayout(form_row)

        update_row = QHBoxLayout()
        update_row.addWidget(QLabel("선택한 계획 진행률"))
        self.goal_progress = QSpinBox()
        self.goal_progress.setRange(0, 100)
        self.goal_progress.setSuffix("%")
        self.goal_status = QComboBox()
        self.goal_status.addItems(["진행", "보류", "완료"])
        update_btn = QPushButton("진행상황 반영")
        update_btn.clicked.connect(self._update_goal)
        delete_btn = QPushButton("계획 삭제")
        set_button_role(delete_btn, "danger")
        delete_btn.clicked.connect(self._delete_goal)
        update_row.addWidget(self.goal_progress)
        update_row.addWidget(self.goal_status)
        update_row.addWidget(update_btn)
        update_row.addWidget(delete_btn)
        update_row.addStretch()
        layout.addLayout(update_row)

        self.goals_table = QTableWidget()
        self._configure_table(self.goals_table, ["ID", "목표", "개입 내용", "목표일", "진행률", "상태"])
        self.goals_table.setColumnHidden(0, True)
        self.goals_table.cellClicked.connect(self._goal_selected)
        layout.addWidget(self.goals_table, stretch=1)
        return page

    def _build_monitoring_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        form_row = QHBoxLayout()
        self.monitor_type = QComboBox()
        self.monitor_type.addItems(["전화 확인", "가정방문", "재사정", "서비스 제공 확인", "사후관리"])
        self.monitor_due = self._date_edit(7)
        self.monitor_note = QLineEdit()
        self.monitor_note.setPlaceholderText("확인할 내용")
        add_btn = QPushButton("일정 추가")
        set_button_role(add_btn, "primary")
        add_btn.clicked.connect(self._add_monitoring)
        form_row.addWidget(self.monitor_type)
        form_row.addWidget(self.monitor_due)
        form_row.addWidget(self.monitor_note, stretch=1)
        form_row.addWidget(add_btn)
        layout.addLayout(form_row)

        action_row = QHBoxLayout()
        complete_btn = QPushButton("선택 일정 완료")
        set_button_role(complete_btn, "soft")
        complete_btn.clicked.connect(self._complete_monitoring)
        delete_btn = QPushButton("일정 삭제")
        set_button_role(delete_btn, "danger")
        delete_btn.clicked.connect(self._delete_monitoring)
        action_row.addWidget(complete_btn)
        action_row.addWidget(delete_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.monitor_table = QTableWidget()
        self._configure_table(self.monitor_table, ["ID", "예정일", "방법", "확인 내용", "상태"])
        self.monitor_table.setColumnHidden(0, True)
        layout.addWidget(self.monitor_table, stretch=1)
        return page

    def _build_services_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)

        resource_group = QGroupBox("지역자원 등록")
        resource_row = QHBoxLayout(resource_group)
        self.resource_name = QLineEdit()
        self.resource_name.setPlaceholderText("기관·자원명")
        self.resource_category = QComboBox()
        self.resource_category.addItems(["생계", "의료", "주거", "돌봄", "고용", "교육", "정신건강", "법률", "기타"])
        self.resource_contact = QLineEdit()
        self.resource_contact.setPlaceholderText("연락처")
        self.resource_description = QLineEdit()
        self.resource_description.setPlaceholderText("지원 내용")
        resource_btn = QPushButton("자원 등록")
        resource_btn.clicked.connect(self._add_resource)
        resource_row.addWidget(self.resource_name, 2)
        resource_row.addWidget(self.resource_category)
        resource_row.addWidget(self.resource_contact)
        resource_row.addWidget(self.resource_description, 2)
        resource_row.addWidget(resource_btn)
        layout.addWidget(resource_group)

        link_group = QGroupBox("서비스 연계 기록")
        link_form = QHBoxLayout(link_group)
        self.resource_combo = QComboBox()
        self.resource_combo.setMinimumWidth(190)
        self.service_name = QLineEdit()
        self.service_name.setPlaceholderText("의뢰한 서비스")
        self.service_date = self._date_edit()
        self.service_check_date = self._date_edit(14)
        add_link_btn = QPushButton("연계 기록 추가")
        set_button_role(add_link_btn, "primary")
        add_link_btn.clicked.connect(self._add_service_link)
        link_form.addWidget(self.resource_combo)
        link_form.addWidget(self.service_name, stretch=1)
        link_form.addWidget(QLabel("의뢰일"))
        link_form.addWidget(self.service_date)
        link_form.addWidget(QLabel("확인일"))
        link_form.addWidget(self.service_check_date)
        link_form.addWidget(add_link_btn)
        layout.addWidget(link_group)

        status_row = QHBoxLayout()
        self.service_status = QComboBox()
        self.service_status.addItems(["의뢰", "대기", "제공 중", "완료", "미연계"])
        self.service_result = QLineEdit()
        self.service_result.setPlaceholderText("연계 결과 또는 미연계 사유")
        update_btn = QPushButton("선택 기록 상태 변경")
        update_btn.clicked.connect(self._update_service_link)
        delete_btn = QPushButton("연계 기록 삭제")
        set_button_role(delete_btn, "danger")
        delete_btn.clicked.connect(self._delete_service_link)
        status_row.addWidget(self.service_status)
        status_row.addWidget(self.service_result, stretch=1)
        status_row.addWidget(update_btn)
        status_row.addWidget(delete_btn)
        layout.addLayout(status_row)

        self.service_table = QTableWidget()
        self._configure_table(self.service_table, ["ID", "의뢰일", "기관·자원", "서비스", "상태", "다음 확인일", "결과"])
        self.service_table.setColumnHidden(0, True)
        self.service_table.cellClicked.connect(self._service_selected)
        layout.addWidget(self.service_table, stretch=1)
        return page

    def set_database(self, db: Database):
        self.db = db
        self.forms_panel.db = db
        self.client_id = None
        self._client_drafts.clear()
        self.refresh_clients()

    def refresh_clients(self, select_client_id: Optional[int] = None):
        wanted = select_client_id if select_client_id is not None else self.client_combo.currentData()
        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        self.client_combo.addItem("대상자를 선택하세요", None)
        selected_index = 0
        for index, client in enumerate(self.db.list_clients(), start=1):
            self.client_combo.addItem(
                f"{client['name']} · {client.get('risk_level', '일반')} · {client.get('welfare_type', '일반')}",
                client["id"],
            )
            if client["id"] == wanted:
                selected_index = index
        self.client_combo.setCurrentIndex(selected_index)
        self.client_combo.blockSignals(False)
        self._on_client_changed()

    def select_client(self, client_id: int):
        self.refresh_clients(select_client_id=client_id)

    def _on_client_changed(self):
        # 화면 갱신이나 대상자 전환 전의 미저장 보조 입력을 세션 안에서 분리 보관합니다.
        names = ('assessment_summary', 'goal_title', 'goal_action', 'monitor_note',
                 'service_name', 'service_result', 'stage_note')
        combo_names = ('goal_status', 'monitor_type', 'service_status', 'stage_combo')
        date_names = ('goal_due', 'monitor_due', 'service_date', 'service_check_date')
        if self.client_id is not None:
            self._client_drafts[self.client_id] = {
                'text': {name: getattr(self, name).text() for name in names},
                'scores': {name: combo.currentIndex() for name, combo in self.assessment_inputs.items()},
                'combos': {name: getattr(self, name).currentIndex() for name in combo_names},
                'dates': {name: getattr(self, name).date() for name in date_names},
                'progress': self.goal_progress.value(),
                'resource': self.resource_combo.currentData(),
            }
        self.client_id = self.client_combo.currentData()
        self.refresh_context()
        for name in names:
            getattr(self, name).clear()
        for combo in self.assessment_inputs.values():
            combo.setCurrentIndex(0)
        self.goal_progress.setValue(0)
        self.goal_status.setCurrentIndex(0)
        self.monitor_type.setCurrentIndex(0)
        self.service_status.setCurrentIndex(0)
        self.resource_combo.setCurrentIndex(0)
        for name, offset in [('goal_due', 30), ('monitor_due', 7), ('service_date', 0), ('service_check_date', 14)]:
            getattr(self, name).setDate(QDate.currentDate().addDays(offset))
        enabled = self.client_id is not None
        self.tabs.setEnabled(enabled)
        self.stage_combo.setEnabled(enabled)
        self.stage_note.setEnabled(enabled)
        if not enabled:
            self.case_summary.setText("대상자를 선택해 주세요.")
            self._clear_tables()
            self.forms_panel.set_client(None, '접수')
            return
        client = self.db.get_client(self.client_id)
        self.case_summary.setText(
            f"{client.get('masked_name', '')} · 위기도 {client.get('risk_level', '일반')} · 접수일 {client.get('intake_date', '-') or '-'}"
        )
        self.refresh_all()
        draft = self._client_drafts.get(self.client_id)
        if draft:
            for name, text in draft['text'].items():
                getattr(self, name).setText(text)
            for name, index in draft['scores'].items():
                self.assessment_inputs[name].setCurrentIndex(index)
            for name, index in draft['combos'].items():
                getattr(self, name).setCurrentIndex(index)
            for name, date in draft['dates'].items():
                getattr(self, name).setDate(date)
            self.goal_progress.setValue(draft['progress'])
            self.resource_combo.setCurrentIndex(max(0, self.resource_combo.findData(draft['resource'])))

    def _clear_tables(self):
        for table in (self.assessment_table, self.goals_table, self.monitor_table, self.service_table):
            table.setRowCount(0)

    def _require_client(self) -> bool:
        if self.client_id is None:
            QMessageBox.information(self, "대상자 선택", "먼저 사례관리 대상자를 선택해 주세요.")
            return False
        return True

    def refresh_all(self):
        if not self.client_id:
            return
        profile = self.db.get_case_profile(self.client_id)
        self.stage_combo.setCurrentText(profile.get("stage", "접수"))
        self.stage_note.setText(profile.get("stage_note", ""))
        self.forms_panel.set_client(self.client_id, profile.get('stage', '접수'))
        self._refresh_assessments()
        self._refresh_goals()
        self._refresh_monitoring()
        self._refresh_resources()
        self._refresh_services()

    def _save_stage(self):
        if not self._require_client():
            return
        self.db.save_case_profile(self.client_id, self.stage_combo.currentText(), self.stage_note.text().strip())
        self.forms_panel.set_client(self.client_id, self.stage_combo.currentText())
        self.status_message.emit(f"사례 진행단계를 '{self.stage_combo.currentText()}'로 저장했습니다.")

    def _save_assessment(self):
        if not self._require_client():
            return
        scores = {domain: combo.currentIndex() for domain, combo in self.assessment_inputs.items()}
        self.db.add_assessment(self.client_id, scores, self.assessment_summary.text().strip())
        self.assessment_summary.clear()
        self._refresh_assessments()
        self.status_message.emit("욕구·위기도 사정 결과를 저장했습니다.")

    def _refresh_assessments(self):
        rows = self.db.list_assessments(self.client_id)
        self.assessment_table.setRowCount(len(rows))
        for row_index, assessment in enumerate(rows):
            scores = assessment.get("scores", {})
            total = sum(int(value) for value in scores.values())
            highest = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else "안정"
            values = [assessment["assessed_at"], str(total), highest, assessment.get("summary", "")]
            for col, value in enumerate(values):
                self.assessment_table.setItem(row_index, col, QTableWidgetItem(value))
        if rows:
            latest = rows[0].get("scores", {})
            for domain, combo in self.assessment_inputs.items():
                combo.setCurrentIndex(int(latest.get(domain, 0)))

    def _add_goal(self):
        if not self._require_client():
            return
        title = self.goal_title.text().strip()
        if not title:
            QMessageBox.warning(self, "목표 확인", "달성할 목표를 입력해 주세요.")
            return
        self.db.add_goal(self.client_id, title, self.goal_action.text().strip(), self.goal_due.date().toString(Qt.DateFormat.ISODate))
        self.goal_title.clear()
        self.goal_action.clear()
        self._refresh_goals()
        self.status_message.emit("목표와 개입계획을 추가했습니다.")

    def _refresh_goals(self):
        rows = self.db.list_goals(self.client_id)
        self.goals_table.setRowCount(len(rows))
        for r, goal in enumerate(rows):
            values = [goal["id"], goal["title"], goal.get("action_plan", ""), goal.get("due_date", ""), f"{goal.get('progress', 0)}%", goal.get("status", "")]
            for c, value in enumerate(values):
                self.goals_table.setItem(r, c, QTableWidgetItem(str(value)))

    def _selected_id(self, table: QTableWidget) -> Optional[int]:
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        return int(item.text()) if item else None

    def _confirm_delete(self, item_name: str) -> bool:
        reply = QMessageBox.question(
            self,
            "삭제 확인",
            f"선택한 {item_name}을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _goal_selected(self, row, _column):
        self.goal_progress.setValue(int(self.goals_table.item(row, 4).text().rstrip("%")))
        self.goal_status.setCurrentText(self.goals_table.item(row, 5).text())

    def _update_goal(self):
        goal_id = self._selected_id(self.goals_table)
        if not goal_id:
            QMessageBox.information(self, "계획 선택", "진행상황을 변경할 계획을 선택해 주세요.")
            return
        progress = 100 if self.goal_status.currentText() == "완료" else self.goal_progress.value()
        self.db.update_goal_progress(goal_id, progress, self.goal_status.currentText())
        self._refresh_goals()

    def _delete_goal(self):
        goal_id = self._selected_id(self.goals_table)
        if goal_id and self._confirm_delete("개입계획"):
            self.db.delete_goal(goal_id)
            self._refresh_goals()

    def _add_monitoring(self):
        if not self._require_client():
            return
        self.db.add_monitoring_task(
            self.client_id, self.monitor_type.currentText(),
            self.monitor_due.date().toString(Qt.DateFormat.ISODate), self.monitor_note.text().strip(),
        )
        self.monitor_note.clear()
        self._refresh_monitoring()
        self.status_message.emit("모니터링 일정을 추가했습니다.")

    def _refresh_monitoring(self):
        rows = self.db.list_monitoring_tasks(self.client_id)
        today = QDate.currentDate().toString(Qt.DateFormat.ISODate)
        self.monitor_table.setRowCount(len(rows))
        for r, task in enumerate(rows):
            display_status = task["status"]
            overdue = display_status != "완료" and task["due_date"] < today
            if overdue:
                display_status = "기한 지남"
            values = [task["id"], task["due_date"], task["task_type"], task.get("notes", ""), display_status]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if overdue:
                    item.setForeground(QColor("#B83A4B"))
                self.monitor_table.setItem(r, c, item)

    def _complete_monitoring(self):
        task_id = self._selected_id(self.monitor_table)
        if not task_id:
            QMessageBox.information(self, "일정 선택", "완료할 일정을 선택해 주세요.")
            return
        self.db.complete_monitoring_task(task_id)
        self._refresh_monitoring()

    def _delete_monitoring(self):
        task_id = self._selected_id(self.monitor_table)
        if task_id and self._confirm_delete("모니터링 일정"):
            self.db.delete_monitoring_task(task_id)
            self._refresh_monitoring()

    def _add_resource(self):
        name = self.resource_name.text().strip()
        if not name:
            QMessageBox.warning(self, "지역자원 확인", "기관 또는 자원명을 입력해 주세요.")
            return
        self.db.add_resource(name, self.resource_category.currentText(), self.resource_contact.text().strip(), self.resource_description.text().strip())
        self.resource_name.clear()
        self.resource_contact.clear()
        self.resource_description.clear()
        self._refresh_resources()

    def _refresh_resources(self):
        current = self.resource_combo.currentData()
        self.resource_combo.clear()
        self.resource_combo.addItem("기관 미지정", None)
        selected = 0
        for index, resource in enumerate(self.db.list_resources(), start=1):
            self.resource_combo.addItem(f"{resource['category']} · {resource['name']}", resource["id"])
            if resource["id"] == current:
                selected = index
        self.resource_combo.setCurrentIndex(selected)

    def _add_service_link(self):
        if not self._require_client():
            return
        service = self.service_name.text().strip()
        if not service:
            QMessageBox.warning(self, "서비스 확인", "연계할 서비스명을 입력해 주세요.")
            return
        self.db.add_service_link(
            self.client_id, self.resource_combo.currentData(), service,
            self.service_date.date().toString(Qt.DateFormat.ISODate),
            next_check_date=self.service_check_date.date().toString(Qt.DateFormat.ISODate),
        )
        self.service_name.clear()
        self._refresh_services()
        self.status_message.emit("서비스 연계 기록을 추가했습니다.")

    def _refresh_services(self):
        rows = self.db.list_service_links(self.client_id)
        self.service_table.setRowCount(len(rows))
        for r, link in enumerate(rows):
            values = [link["id"], link["requested_date"], link.get("resource_name") or "미지정", link["service_name"], link["status"], link.get("next_check_date", ""), link.get("result", "")]
            for c, value in enumerate(values):
                self.service_table.setItem(r, c, QTableWidgetItem(str(value or "")))

    def _service_selected(self, row, _column):
        self.service_status.setCurrentText(self.service_table.item(row, 4).text())
        self.service_result.setText(self.service_table.item(row, 6).text())

    def _update_service_link(self):
        link_id = self._selected_id(self.service_table)
        if not link_id:
            QMessageBox.information(self, "연계 기록 선택", "상태를 변경할 연계 기록을 선택해 주세요.")
            return
        self.db.update_service_link_status(link_id, self.service_status.currentText(), self.service_result.text().strip())
        self._refresh_services()

    def _delete_service_link(self):
        link_id = self._selected_id(self.service_table)
        if link_id and self._confirm_delete("서비스 연계 기록"):
            self.db.delete_service_link(link_id)
            self._refresh_services()
