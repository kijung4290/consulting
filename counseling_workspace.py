"""상담 작성 화면과 사용자·대상자별 작업 초안 복구."""
from PyQt6.QtCore import QDate, QTimer, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QLineEdit, QDateEdit, QTextEdit, QCheckBox, QPushButton, QGroupBox,
    QSplitter, QProgressBar, QMenu, QMessageBox,
)
from ui_theme import make_page_header, set_button_role


class CounselingWorkspaceMixin:
    def build_counseling_workspace(self):
        self._draft_ready = False
        self._restoring_draft = False
        self._generation_busy = False
        self._generation_cancelled = False
        self._record_id = None
        self._saved_state = None
        page = QWidget()
        page.setObjectName('pageRoot')
        page.setStyleSheet('QGroupBox { margin-top: 10px; padding-top: 8px; }')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(make_page_header('상담일지 작성',
            '메모를 정리하고 사실관계와 지원 계획을 확인한 뒤 상담 이력에 저장하세요.', '상담 기록'))

        top = QHBoxLayout()
        self.client_info_badge = QLabel('대상자를 먼저 선택하세요. 미지정 기록도 작성할 수 있습니다.')
        self.client_info_badge.setObjectName('sectionHint')
        self.client_info_badge.setWordWrap(True)
        top.addWidget(self.client_info_badge, 1)
        direct = QPushButton('직접 작성')
        direct.clicked.connect(self.open_manual_from_counsel_page)
        report = QPushButton('이력 조회·출력')
        report.clicked.connect(self.open_counseling_report)
        top.addWidget(direct)
        top.addWidget(report)
        layout.addLayout(top)

        identity = QGroupBox('1  대상자와 상담 정보')
        grid = QGridLayout(identity)
        self.ai_client_combo = QComboBox()
        self.ai_client_combo.setMinimumContentsLength(14)
        self.ai_client_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.ai_client_combo.currentIndexChanged.connect(self.on_ai_client_selected)
        self.session_date_input = QDateEdit(QDate.currentDate())
        self.session_date_input.setCalendarPopup(True)
        self.session_date_input.setDisplayFormat('yyyy-MM-dd')
        self.session_method_input = QComboBox()
        self.session_method_input.addItems(['', '방문', '복지관 내방', '전화', '온라인', '기타'])
        for col, (label, widget) in enumerate((('대상자', self.ai_client_combo),
                ('실제 상담일', self.session_date_input), ('상담방법', self.session_method_input))):
            caption = QLabel(label)
            caption.setBuddy(widget)
            grid.addWidget(caption, 0, col * 2)
            grid.addWidget(widget, 0, col * 2 + 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(identity)

        self.writing_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.writing_splitter.setChildrenCollapsible(False)
        self.writing_splitter.setHandleWidth(8)
        memo_group = QGroupBox('2  상담 메모')
        left = QVBoxLayout(memo_group)
        self.tmpl_combo = QComboBox()
        self.tmpl_combo.setMinimumContentsLength(12)
        self.tmpl_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.tmpl_combo.currentIndexChanged.connect(self.on_template_changed)
        left.addWidget(self.tmpl_combo)
        self.tmpl_desc_label = QLabel()
        self.tmpl_desc_label.setWordWrap(True)
        self.tmpl_desc_label.setObjectName('sectionHint')
        left.addWidget(self.tmpl_desc_label)

        options_toggle = QPushButton('작성 옵션 펼치기')
        options_toggle.setObjectName('compactButton')
        options_toggle.setCheckable(True)
        left.addWidget(options_toggle)
        options = QWidget()
        options_layout = QGridLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_combo = QComboBox()
        self.detail_combo.addItems(['표준', '간결하게', '상세하게'])
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText('가명으로 바꿀 성명')
        options_layout.addWidget(QLabel('상세도'), 0, 0)
        options_layout.addWidget(self.detail_combo, 0, 1)
        options_layout.addWidget(QLabel('성명'), 1, 0)
        options_layout.addWidget(self.name_input, 1, 1)
        self.mask_checkbox = QCheckBox('개인정보 마스킹 적용')
        self.mask_checkbox.setChecked(True)
        self.mask_checkbox.setToolTip('성명·주민번호·전화번호·주소 패턴을 가립니다. 결과를 직접 확인하세요.')
        options_layout.addWidget(self.mask_checkbox, 2, 0, 1, 2)
        left.addWidget(options)
        options.hide()
        options_toggle.toggled.connect(options.setVisible)
        options_toggle.toggled.connect(lambda checked: options_toggle.setText('작성 옵션 접기' if checked else '작성 옵션 펼치기'))

        self.input_text = QTextEdit()
        self.input_text.setAcceptRichText(False)
        self.input_text.setMinimumHeight(130)
        self.input_text.setPlaceholderText('대상자가 말한 어려움\n직접 관찰한 상황\n오늘 지원·안내한 내용\n다음에 확인할 일과 약속 날짜\n\n짧은 문장이나 핵심 단어로 적어도 됩니다.')
        left.addWidget(self.input_text, 1)
        memo_tools = QHBoxLayout()
        self.memo_count = QLabel('0자')
        memo_tools.addWidget(self.memo_count)
        memo_tools.addStretch()
        self.sample_btn = QPushButton('예시 메모')
        self.sample_btn.setObjectName('compactButton')
        self.sample_btn.clicked.connect(self.load_sample_memo)
        memo_tools.addWidget(self.sample_btn)
        left.addLayout(memo_tools)
        run_row = QHBoxLayout()
        self.generate_btn = set_button_role(QPushButton('AI로 초안 정리'), 'primary')
        self.generate_btn.setToolTip('Ctrl+Enter · 작성 화면에서 실행')
        self.generate_btn.clicked.connect(self.start_generation)
        self.stop_btn = set_button_role(QPushButton('중단'), 'danger')
        self.stop_btn.clicked.connect(self.stop_generation)
        self.stop_btn.setEnabled(False)
        run_row.addWidget(self.generate_btn, 1)
        run_row.addWidget(self.stop_btn)
        left.addLayout(run_row)
        self.writing_splitter.addWidget(memo_group)

        result_group = QGroupBox('3  검토하고 저장')
        right = QVBoxLayout(result_group)
        hint = QLabel('이름·상담일·사실관계·다음 계획을 확인하세요. 본문을 직접 수정할 수 있습니다.')
        hint.setObjectName('sectionHint')
        hint.setWordWrap(True)
        right.addWidget(hint)
        self.mask_stat_label = QLabel('')
        self.mask_stat_label.setWordWrap(True)
        right.addWidget(self.mask_stat_label)
        self.output_text = QTextEdit()
        self.output_text.setMinimumHeight(190)
        self.output_text.setPlaceholderText('정리한 초안이 여기에 표시됩니다.\nAI 없이 이 칸에 직접 작성하고 저장할 수도 있습니다.')
        right.addWidget(self.output_text, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        right.addWidget(self.progress_bar)
        # 모델을 불러오는 동안에는 화면에 아무 변화가 없어 멈춘 것처럼 보이므로 단계를 적어 준다.
        self.generation_status = QLabel()
        self.generation_status.setObjectName('sectionHint')
        self.generation_status.setWordWrap(True)
        self.generation_status.hide()
        right.addWidget(self.generation_status)
        self.draft_status = QLabel('메모는 이 PC에 임시 저장됩니다. 상담 이력 저장은 별도입니다.')
        self.draft_status.setObjectName('draftStatus')
        self.draft_status.setWordWrap(True)
        right.addWidget(self.draft_status)
        actions = QHBoxLayout()
        self.save_to_db_btn = set_button_role(QPushButton('상담 이력에 저장'), 'primary')
        self.save_to_db_btn.clicked.connect(self.save_record_to_database)
        self.copy_btn = QPushButton('본문 복사')
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        more = QPushButton('더 보기')
        menu = QMenu(more)
        self.apply_form_btn = menu.addAction('표 양식 적용', self.apply_selected_form_to_output)
        self.save_file_btn = menu.addAction('파일로 내보내기', self.save_to_file)
        menu.addSeparator()
        menu.addAction('내 양식 편집', lambda: self.open_form_designer())
        more.setMenu(menu)
        actions.addWidget(self.save_to_db_btn, 1)
        actions.addWidget(self.copy_btn)
        actions.addWidget(more)
        right.addLayout(actions)
        self.clear_btn = QPushButton('새 상담 시작')
        self.clear_btn.setObjectName('compactButton')
        self.clear_btn.clicked.connect(self.clear_fields)
        right.addWidget(self.clear_btn)
        self.stop_output_btn = QPushButton()  # 기존 생성 상태 API와 호환
        self.stop_output_btn.setEnabled(False)
        self.writing_splitter.addWidget(result_group)
        self.writing_splitter.setSizes([420, 520])
        layout.addWidget(self.writing_splitter, 1)
        self.refresh_template_combo()
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(700)
        self._draft_timer.timeout.connect(self.persist_counseling_draft)
        for signal in (self.input_text.textChanged, self.output_text.textChanged,
                       self.session_date_input.dateChanged, self.session_method_input.currentIndexChanged,
                       self.tmpl_combo.currentIndexChanged, self.detail_combo.currentIndexChanged,
                       self.name_input.textChanged, self.mask_checkbox.toggled):
            signal.connect(self.counseling_changed)
        return page

    def counseling_state(self):
        return dict(memo=self.input_text.toPlainText(), html=self.output_text.toHtml(),
                    text=self.output_text.toPlainText(), date=self.session_date_input.date().toString('yyyy-MM-dd'),
                    method=self.session_method_input.currentText(), template=self.tmpl_combo.currentData(),
                    detail=self.detail_combo.currentText(), name=self.name_input.text(), mask=self.mask_checkbox.isChecked())

    def counseling_changed(self, *_):
        if not self._draft_ready or self._restoring_draft:
            return
        self.memo_count.setText(f'{len(self.input_text.toPlainText()):,}자')
        self._draft_timer.start()
        self.draft_status.setText('임시 저장 대기 중 · 상담 이력에는 아직 반영되지 않았습니다.')
        self.update_counseling_actions()

    def update_counseling_actions(self):
        has_text = bool(self.output_text.toPlainText().strip())
        changed = self.counseling_state() != self._saved_state
        self.save_to_db_btn.setEnabled(has_text and changed and not self._generation_busy)
        self.save_to_db_btn.setText('수정 내용 저장' if self._record_id else '상담 이력에 저장')
        self.copy_btn.setEnabled(has_text and not self._generation_busy)
        self.apply_form_btn.setEnabled(has_text and not self._generation_busy)
        self.save_file_btn.setEnabled(has_text and not self._generation_busy)

    def persist_counseling_draft(self):
        if not self._draft_ready or self._restoring_draft:
            return True
        self._draft_timer.stop()
        state = self.counseling_state()
        state.update(record_id=self._record_id, saved_state=self._saved_state,
                     generated_raw=self.last_generated_raw_text)
        try:
            self._draft_db.save_counseling_draft(self._draft_owner, self._draft_client, state)
        except Exception as exc:
            self.draft_status.setText(f'임시 저장 실패 · 작성 화면을 유지하고 저장 위치를 확인하세요: {exc}')
            return False
        if self._saved_state == self.counseling_state():
            self.draft_status.setText('상담 이력 저장 완료 · 수정하면 같은 기록에 반영됩니다.')
        else:
            self.draft_status.setText('이 PC에 임시 저장됨 · 검토 후 상담 이력에 저장하세요.')
        return True

    def restore_counseling_draft(self):
        self._restoring_draft = True
        self._draft_timer.stop()
        self._draft_db = self.db
        self._draft_owner = self.current_profile['id']
        self._draft_client = self.ai_client_combo.currentData()
        state = self.db.get_counseling_draft(self._draft_owner, self._draft_client)
        try:
            self.input_text.setPlainText(state.get('memo', ''))
            self.output_text.setHtml(state.get('html', ''))
            date = QDate.fromString(state.get('date', ''), 'yyyy-MM-dd')
            self.session_date_input.setDate(date if date.isValid() else QDate.currentDate())
            self.session_method_input.setCurrentText(state.get('method', ''))
            index = self.tmpl_combo.findData(state.get('template'))
            if index >= 0:
                self.tmpl_combo.setCurrentIndex(index)
            self.detail_combo.setCurrentText(state.get('detail', '표준'))
            client = self.db.get_client(self._draft_client) if self._draft_client else None
            self.name_input.setText(state.get('name', client['name'] if client else ''))
            self.mask_checkbox.setChecked(state.get('mask', True))
            self.last_generated_raw_text = state.get('generated_raw', '')
            self._record_id = state.get('record_id')
            self._saved_state = state.get('saved_state')
            self.client_info_badge.setText(
                f"{client['name']} · {client.get('risk_level') or '일반'} · 이 대상자의 상담을 작성 중입니다."
                if client else '대상자 미지정 · 저장하면 일반 상담 기록으로 보관됩니다.')
            self.mask_stat_label.clear()
        finally:
            self._restoring_draft = False
            self._draft_ready = True
        self.memo_count.setText(f'{len(self.input_text.toPlainText()):,}자')
        self.set_generation_phase()
        self.draft_status.setText('이전에 작성한 내용을 불러왔습니다. 검토 후 저장하세요.' if state else
                                  '메모는 이 PC에 임시 저장됩니다. 상담 이력 저장은 별도입니다.')
        self.update_counseling_actions()

    def set_generation_phase(self, message: str = ''):
        """AI 작성이 지금 어느 단계인지 작성 화면에 보여 준다."""
        self.generation_status.setText(message)
        self.generation_status.setVisible(bool(message))

    def set_counseling_busy(self, busy):
        self._generation_busy = busy
        for widget in (self.ai_client_combo, self.tmpl_combo, self.session_date_input,
                       self.session_method_input, self.name_input, self.detail_combo,
                       self.mask_checkbox, self.sample_btn, self.clear_btn, self.profile_combo):
            widget.setEnabled(not busy)
        self.input_text.setReadOnly(busy)
        self.output_text.setReadOnly(busy)
        self.progress_bar.setVisible(busy)
        self.generate_btn.setText('AI가 작성 중…' if busy else 'AI로 초안 정리')
        self.update_counseling_actions()

    def confirm_replace(self, message):
        return QMessageBox.question(self, '작성 내용 확인', message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
