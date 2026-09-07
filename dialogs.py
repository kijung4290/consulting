"""
사회복지 스마트 사례관리 SaaS - 다이얼로그 모듈
1. ClientDialog: 대상자 신규 등록 및 수정
2. ClientDetailDialog: 대상자 통합 상세카드 (인적사항, 누적 상담기록 이력, 첨부 서류)
3. DocumentAddDialog: 신규 서류 및 증빙자료 등록
"""

import os
import subprocess
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QTextEdit, QPushButton, QFormLayout, QMessageBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QGroupBox,
    QSplitter, QWidget, QRadioButton, QButtonGroup, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QFont, QColor

from database import Database
from form_document import build_form_html, fill_form_html, inject_approval_line

def open_system_file(fpath: str):
    """OS에 맞게 기본 프로그램으로 파일 열기 (Windows / Linux / macOS 완벽 호환)"""
    if not os.path.exists(fpath):
        return
    import sys
    if sys.platform == "win32":
        os.startfile(fpath)
    elif sys.platform == "darwin":
        subprocess.run(["open", fpath])
    else:
        subprocess.run(["xdg-open", fpath])

class ClientDialog(QDialog):
    """대상자 등록 및 정보 수정 다이얼로그"""
    def __init__(self, db: Database, client_id: int = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id = client_id
        self.setWindowTitle("대상자 정보 등록" if client_id is None else "대상자 정보 수정")
        self.resize(520, 600)
        self.init_ui()
        if self.client_id:
            self.load_client_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(10)

        # 1. 성명 및 가명
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: 홍길동")
        self.name_input.textChanged.connect(self.auto_generate_masked)

        self.masked_input = QLineEdit()
        self.masked_input.setPlaceholderText("예: 홍OO님 (비식별 가명)")

        name_layout = QHBoxLayout()
        name_layout.addWidget(self.name_input)
        name_layout.addWidget(QLabel("가명:"))
        name_layout.addWidget(self.masked_input)
        form_layout.addRow("성명(*):", name_layout)

        # 2. 생년월일 & 성별
        self.birth_input = QLineEdit()
        self.birth_input.setPlaceholderText("YYYY-MM-DD (예: 1952-04-15)")
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["남", "여", "미상"])

        birth_layout = QHBoxLayout()
        birth_layout.addWidget(self.birth_input, stretch=2)
        birth_layout.addWidget(QLabel("성별:"))
        birth_layout.addWidget(self.gender_combo, stretch=1)
        form_layout.addRow("생년월일/성별:", birth_layout)

        # 3. 연락처
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("010-0000-0000")
        form_layout.addRow("연락처:", self.phone_input)

        # 4. 주소
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("예: 강원도 원주시 봉산동 OO빌라 201호")
        form_layout.addRow("주소:", self.address_input)

        # 5. 수급 자격 & 위기도
        self.welfare_combo = QComboBox()
        self.welfare_combo.addItems(["기초수급(생계/의료)", "기초수급(주거/교육)", "차상위계층", "일반저소득", "일반", "기타"])

        self.risk_combo = QComboBox()
        self.risk_combo.addItems(["일반", "저위기", "중위기", "고위기(집중관리)"])
        self.risk_combo.setCurrentText("일반")

        type_layout = QHBoxLayout()
        type_layout.addWidget(self.welfare_combo, stretch=2)
        type_layout.addWidget(QLabel("위기도:"))
        type_layout.addWidget(self.risk_combo, stretch=2)
        form_layout.addRow("수급/위기도:", type_layout)

        # 6. 가구 유형 & 최초 접수일
        self.household_combo = QComboBox()
        self.household_combo.addItems(["독거노인", "노인부부", "한부모가족", "장애인가구", "조손가구", "1인가구(청장년)", "다문화가구", "일반가구"])

        self.intake_date_input = QLineEdit()
        self.intake_date_input.setText(datetime.now().strftime("%Y-%m-%d"))

        house_layout = QHBoxLayout()
        house_layout.addWidget(self.household_combo, stretch=2)
        house_layout.addWidget(QLabel("접수일:"))
        house_layout.addWidget(self.intake_date_input, stretch=2)
        form_layout.addRow("가구/접수일:", house_layout)

        # 7. 특이사항 및 요약 메모
        self.memo_input = QTextEdit()
        self.memo_input.setPlaceholderText("주요 질환, 긴급 요구사항, 가족관계 특이사항 등을 적어주세요.")
        self.memo_input.setMaximumHeight(120)
        form_layout.addRow("특이사항/메모:", self.memo_input)

        layout.addLayout(form_layout)

        # 버튼 영역
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("💾 저장하기")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                padding: 8px 18px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #4338CA; }
        """)
        self.save_btn.clicked.connect(self.save_client)

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #E2E8F0; }
        """)
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def auto_generate_masked(self, text: str):
        if not self.client_id and text:
            name = text.strip()
            if len(name) >= 2:
                masked = name[0] + "OO님" if len(name) <= 3 else name[0] + "OO" + name[-1] + "님"
                self.masked_input.setText(masked)

    def load_client_data(self):
        c = self.db.get_client(self.client_id)
        if not c:
            return
        self.name_input.setText(c.get("name", ""))
        self.masked_input.setText(c.get("masked_name", ""))
        self.birth_input.setText(c.get("birth_date", ""))
        self.gender_combo.setCurrentText(c.get("gender", "미상"))
        self.phone_input.setText(c.get("phone", ""))
        self.address_input.setText(c.get("address", ""))
        self.welfare_combo.setCurrentText(c.get("welfare_type", "일반"))
        self.risk_combo.setCurrentText(c.get("risk_level", "일반"))
        self.household_combo.setCurrentText(c.get("household_type", "독거노인"))
        self.intake_date_input.setText(c.get("intake_date", ""))
        self.memo_input.setText(c.get("memo", ""))

    def save_client(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "확인", "대상자 성명을 입력해 주세요.")
            return

        data = {
            "name": name,
            "masked_name": self.masked_input.text().strip(),
            "birth_date": self.birth_input.text().strip(),
            "gender": self.gender_combo.currentText(),
            "phone": self.phone_input.text().strip(),
            "address": self.address_input.text().strip(),
            "welfare_type": self.welfare_combo.currentText(),
            "risk_level": self.risk_combo.currentText(),
            "household_type": self.household_combo.currentText(),
            "intake_date": self.intake_date_input.text().strip(),
            "memo": self.memo_input.toPlainText().strip()
        }

        if self.client_id:
            self.db.update_client(self.client_id, data)
        else:
            self.client_id = self.db.add_client(data)

        self.accept()


class ClientDetailDialog(QDialog):
    """대상자 종합 상세카드 (누적 상담 이력, 관련 서류)"""
    write_counseling_signal = pyqtSignal(int) # client_id 전달하여 AI 작성으로 이동

    def __init__(self, db: Database, client_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id = client_id
        self.client_data = self.db.get_client(self.client_id)
        self.setWindowTitle(f"대상자 상세 기록 - {self.client_data.get('name', '')} ({self.client_data.get('masked_name', '')})")
        self.resize(880, 680)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 상단 헤더 요약 바
        header_group = QGroupBox()
        h_layout = QHBoxLayout(header_group)
        
        c = self.client_data
        risk = c.get('risk_level', '일반')
        risk_color = "#D32F2F" if "고위기" in risk else ("#F57C00" if "중위기" in risk else "#2E7D32")
        
        summary_html = f"""
        <div style='font-size: 13px;'>
            <b style='font-size: 16px; color: #212121;'>{c.get('name')}</b> 
            <span style='color: #757575;'>({c.get('masked_name')})</span> | 
            <span>{c.get('gender')} / {c.get('birth_date', '생년월일 미입력')}</span> | 
            <span style='color: {risk_color}; font-weight: bold;'>[{risk}]</span> | 
            <span>{c.get('welfare_type')}</span> | 
            <span>{c.get('household_type')}</span>
            <div style='color: #424242; font-size: 11px; margin-top: 4px;'>
                📞 {c.get('phone', '연락처 없음')} &nbsp;|&nbsp; 🏠 {c.get('address', '주소 미등록')}
            </div>
        </div>
        """
        summary_label = QLabel(summary_html)
        h_layout.addWidget(summary_label)
        h_layout.addStretch()

        write_btn = QPushButton("📝 이 대상자 AI 상담일지 작성")
        write_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                padding: 8px 16px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #4338CA; }
        """)
        write_btn.clicked.connect(self.on_click_write)
        h_layout.addWidget(write_btn)

        layout.addWidget(header_group)

        # 탭 위젯 (상담 이력, 서류 보관함, 상세 메모)
        tabs = QTabWidget()

        # 탭 1: 누적 상담 기록
        history_widget = QWidget()
        hist_layout = QVBoxLayout(history_widget)
        
        hist_top_bar = QHBoxLayout()
        hist_hint = QLabel("💡 과거 상담 이력을 선택하여 우측에서 확인하거나 직접 새 기록을 추가하세요.")
        hist_hint.setStyleSheet("color: #64748B; font-size: 11px;")
        manual_record_btn = QPushButton("✍️ 수기 상담일지 직접 작성")
        manual_record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                padding: 6px 14px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #4338CA; }
        """)
        manual_record_btn.clicked.connect(self.on_manual_record)
        hist_top_bar.addWidget(hist_hint)
        hist_top_bar.addStretch()
        hist_top_bar.addWidget(manual_record_btn)
        hist_layout.addLayout(hist_top_bar)

        hist_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 좌측: 상담 목록 테이블
        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(3)
        self.hist_table.setHorizontalHeaderLabels(["일자", "상담 서식", "작성자"])
        self.hist_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.hist_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.hist_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.hist_table.itemSelectionChanged.connect(self.on_select_record)
        hist_splitter.addWidget(self.hist_table)

        # 우측: 상담일지 전문 뷰어
        right_view_widget = QWidget()
        right_view_layout = QVBoxLayout(right_view_widget)
        
        view_tool_layout = QHBoxLayout()
        self.record_title_label = QLabel("상담일지를 선택해 주세요.")
        self.record_title_label.setStyleSheet("font-weight: bold; color: #4F46E5;")
        self.copy_record_btn = QPushButton("📋 본문 복사")
        self.copy_record_btn.setStyleSheet("""
            QPushButton {
                background-color: #EEF2FF;
                color: #4338CA;
                border: 1px solid #C7D2FE;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E0E7FF; }
        """)
        self.copy_record_btn.clicked.connect(self.copy_record_text)

        self.del_record_btn = QPushButton("🗑️ 기록 삭제")
        self.del_record_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF1F2;
                color: #E11D48;
                border: 1px solid #FECDD3;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #FFE4E6; }
            QPushButton:disabled { background-color: #F8FAFC; color: #CBD5E1; border: 1px solid #E2E8F0; }
        """)
        self.del_record_btn.setEnabled(False)
        self.del_record_btn.clicked.connect(self.delete_selected_record)

        view_tool_layout.addWidget(self.record_title_label)
        view_tool_layout.addStretch()
        view_tool_layout.addWidget(self.copy_record_btn)
        view_tool_layout.addWidget(self.del_record_btn)
        right_view_layout.addLayout(view_tool_layout)

        self.record_text_view = QTextEdit()
        self.record_text_view.setReadOnly(True)
        right_view_layout.addWidget(self.record_text_view)
        hist_splitter.addWidget(right_view_widget)
        hist_splitter.setSizes([340, 500])

        hist_layout.addWidget(hist_splitter)
        tabs.addTab(history_widget, "📝 누적 상담 이력")

        # 탭 2: 관련 서류 보관함
        docs_widget = QWidget()
        docs_layout = QVBoxLayout(docs_widget)

        doc_btn_layout = QHBoxLayout()
        add_doc_btn = QPushButton("➕ 새 서류 첨부")
        add_doc_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                padding: 6px 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4338CA; }
        """)
        add_doc_btn.clicked.connect(self.on_add_document)

        add_typed_doc_btn = QPushButton("✍️ 직접 메모 작성")
        add_typed_doc_btn.setStyleSheet("""
            QPushButton {
                background-color: #EEF2FF;
                color: #4338CA;
                border: 1px solid #C7D2FE;
                padding: 6px 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E0E7FF; }
        """)
        add_typed_doc_btn.clicked.connect(self.on_add_typed_document)

        open_doc_btn = QPushButton("🔍 선택 서류 열기 (HWP/PDF/TXT)")
        open_doc_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #CBD5E1;
                padding: 6px 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E2E8F0; }
        """)
        open_doc_btn.clicked.connect(self.on_open_document)

        del_doc_btn = QPushButton("🗑️ 서류 삭제")
        del_doc_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF1F2;
                color: #E11D48;
                border: 1px solid #FECDD3;
                padding: 6px 12px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #FFE4E6; }
        """)
        del_doc_btn.clicked.connect(self.on_delete_document)

        doc_btn_layout.addWidget(add_doc_btn)
        doc_btn_layout.addWidget(add_typed_doc_btn)
        doc_btn_layout.addWidget(open_doc_btn)
        doc_btn_layout.addWidget(del_doc_btn)
        doc_btn_layout.addStretch()
        docs_layout.addLayout(doc_btn_layout)

        self.docs_table = QTableWidget()
        self.docs_table.setColumnCount(4)
        self.docs_table.setHorizontalHeaderLabels(["서류명", "구분", "등록일", "파일크기"])
        self.docs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.docs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.docs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.docs_table.cellDoubleClicked.connect(self.on_open_document)
        docs_layout.addWidget(self.docs_table)

        tabs.addTab(docs_widget, "📂 관련 서류 보관함")

        # 탭 3: 대상자 특이사항 메모
        memo_widget = QWidget()
        memo_layout = QVBoxLayout(memo_widget)
        memo_view = QTextEdit()
        memo_view.setReadOnly(True)
        memo_view.setText(c.get("memo", "등록된 특이사항이 없습니다."))
        memo_layout.addWidget(memo_view)
        tabs.addTab(memo_widget, "📌 특이사항 및 메모")

        layout.addWidget(tabs)

        self.load_records()
        self.load_documents()

    def load_records(self):
        self.records = self.db.list_counseling_records(client_id=self.client_id)
        self.hist_table.setRowCount(len(self.records))
        for r_idx, rec in enumerate(self.records):
            self.hist_table.setItem(r_idx, 0, QTableWidgetItem(rec.get("session_date", "")))
            self.hist_table.setItem(r_idx, 1, QTableWidgetItem(rec.get("template_name", "")))
            self.hist_table.setItem(r_idx, 2, QTableWidgetItem(rec.get("worker_name", "")))

    def on_select_record(self):
        sel = self.hist_table.currentRow()
        if sel >= 0 and sel < len(self.records):
            rec = self.records[sel]
            self.record_title_label.setText(f"{rec.get('session_date')} - {rec.get('template_name')}")
            if rec.get("result_html"):
                self.record_text_view.setHtml(rec["result_html"])
            else:
                self.record_text_view.setPlainText(rec.get("ai_result", ""))
            self.del_record_btn.setEnabled(True)
        else:
            self.del_record_btn.setEnabled(False)

    def delete_selected_record(self):
        sel = self.hist_table.currentRow()
        if sel >= 0 and sel < len(self.records):
            rec = self.records[sel]
            reply = QMessageBox.question(
                self,
                "상담 기록 삭제",
                f"[{rec.get('session_date', '')}] '{rec.get('template_name', '')}' 기록을 정말 삭제하시겠습니까?\n삭제된 기록은 복구할 수 없습니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.db.delete_counseling_record(rec['id'])
                self.load_records()
                self.record_text_view.clear()
                self.record_title_label.setText("상담일지를 선택해 주세요.")
                self.del_record_btn.setEnabled(False)
                QMessageBox.information(self, "삭제 완료", "상담 기록이 삭제되었습니다.")

    def copy_record_text(self):
        text = self.record_text_view.toPlainText()
        if text:
            from PyQt6.QtWidgets import QApplication
            mime_data = QMimeData()
            mime_data.setText(text)
            mime_data.setHtml(self.record_text_view.toHtml())
            QApplication.clipboard().setMimeData(mime_data)
            QMessageBox.information(self, "복사 완료", "표 모양을 포함해 상담일지가 복사되었습니다.")

    def load_documents(self):
        self.docs = self.db.list_documents(client_id=self.client_id)
        self.docs_table.setRowCount(len(self.docs))
        for r_idx, doc in enumerate(self.docs):
            self.docs_table.setItem(r_idx, 0, QTableWidgetItem(doc.get("title", "")))
            self.docs_table.setItem(r_idx, 1, QTableWidgetItem(doc.get("doc_type", "")))
            self.docs_table.setItem(r_idx, 2, QTableWidgetItem(doc.get("created_at", "")[:10]))
            kb = round(doc.get("file_size", 0) / 1024, 1)
            self.docs_table.setItem(r_idx, 3, QTableWidgetItem(f"{kb} KB"))

    def on_add_document(self):
        dlg = DocumentAddDialog(self.db, client_id=self.client_id, parent=self)
        if dlg.exec():
            self.load_documents()

    def on_add_typed_document(self):
        dlg = DocumentAddDialog(self.db, client_id=self.client_id, default_typing_mode=True, parent=self)
        if dlg.exec():
            self.load_documents()

    def on_delete_document(self):
        sel = self.docs_table.currentRow()
        if sel >= 0 and sel < len(self.docs):
            doc = self.docs[sel]
            reply = QMessageBox.question(
                self,
                "서류 삭제",
                f"'{doc.get('title', '')}' 서류를 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.db.delete_document(doc['id'])
                self.load_documents()
                QMessageBox.information(self, "삭제 완료", "서류가 삭제되었습니다.")
        else:
            QMessageBox.information(self, "알림", "삭제할 서류를 먼저 선택해 주세요.")

    def on_open_document(self):
        sel = self.docs_table.currentRow()
        if sel >= 0 and sel < len(self.docs):
            doc = self.docs[sel]
            fpath = doc.get("full_path", "")
            if os.path.exists(fpath):
                if fpath.lower().endswith(".txt"):
                    dlg = TextViewerDialog(doc.get("title", ""), fpath, parent=self, db=self.db, doc_id=doc['id'])
                    dlg.exec()
                    self.load_documents()
                else:
                    open_system_file(fpath)
            else:
                QMessageBox.warning(self, "파일 오류", f"파일을 찾을 수 없습니다:\n{fpath}")

    def on_manual_record(self):
        dlg = ManualCounselingDialog(self.db, client_id=self.client_id, parent=self)
        if dlg.exec():
            self.load_records()

    def on_click_write(self):
        self.write_counseling_signal.emit(self.client_id)
        self.accept()


class DocumentAddDialog(QDialog):
    """서류 및 증빙자료 등록 다이얼로그 (기존 파일 첨부 OR 직접 타이핑 기록 모두 지원)"""
    def __init__(self, db: Database, client_id: int = None, default_typing_mode: bool = False, parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id = client_id
        self.default_typing_mode = default_typing_mode
        self.setWindowTitle("서류 및 기록 등록")
        self.resize(600, 520)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. 등록 모드 선택 (라디오 버튼)
        mode_box = QFrame()
        mode_box.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 6px;")
        mode_layout = QHBoxLayout(mode_box)
        mode_label = QLabel("등록 방식 선택:")
        mode_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        mode_label.setStyleSheet("color: #1E293B;")

        self.btn_group = QButtonGroup(self)
        self.radio_file = QRadioButton("📁 기존 파일 첨부 (HWP, PDF, 사진 등)")
        self.radio_text = QRadioButton("✍️ 직접 본문 타이핑하여 기록 보관")
        self.btn_group.addButton(self.radio_file)
        self.btn_group.addButton(self.radio_text)

        if self.default_typing_mode:
            self.radio_text.setChecked(True)
        else:
            self.radio_file.setChecked(True)

        self.radio_file.toggled.connect(self.on_mode_toggled)
        self.radio_text.toggled.connect(self.on_mode_toggled)

        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.radio_file)
        mode_layout.addWidget(self.radio_text)
        mode_layout.addStretch()
        layout.addWidget(mode_box)

        # 2. 기본 정보 폼
        form_layout = QFormLayout()

        # 대상자 표시/선택
        self.client_combo = QComboBox()
        self.client_combo.addItem("[ 👤 미지정 (기관 일반 서류/기록) ]", None)
        clients = self.db.list_clients()
        for c in clients:
            self.client_combo.addItem(f"{c['name']} ({c['masked_name']})", c['id'])
        
        if self.client_id:
            for idx in range(self.client_combo.count()):
                if self.client_combo.itemData(idx) == self.client_id:
                    self.client_combo.setCurrentIndex(idx)
                    break
            self.client_combo.setEnabled(False)

        form_layout.addRow("대상자:", self.client_combo)

        # 서류 구분
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "초기면접지/인테이크", "전화상담/민원메모", "가정방문 현장기록",
            "병원 진단서/소견서", "복지급여 신청서", "개인정보 동의서",
            "사례관리 계획서", "회의록/행정기록", "기타 증빙서류/메모"
        ])
        form_layout.addRow("서류 구분:", self.type_combo)

        # 서류명
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("예: 2026년도 초기면접기록지 또는 전화 통화 상세 메모")
        form_layout.addRow("서류/기록 제목(*):", self.title_input)

        # 파일 선택 위젯 (파일 모드용)
        self.file_widget = QWidget()
        file_layout = QHBoxLayout(self.file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_path_input = QLineEdit()
        self.file_path_input.setReadOnly(True)
        self.file_browse_btn = QPushButton("파일 찾기...")
        self.file_browse_btn.setStyleSheet("background-color: #F1F5F9; border: 1px solid #CBD5E1; border-radius: 4px; padding: 6px 12px;")
        self.file_browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(self.file_path_input)
        file_layout.addWidget(self.file_browse_btn)
        form_layout.addRow("첨부 파일(*):", self.file_widget)

        layout.addLayout(form_layout)

        # 직접 타이핑 입력창 (텍스트 모드용)
        self.text_widget = QWidget()
        text_layout = QVBoxLayout(self.text_widget)
        text_layout.setContentsMargins(0, 4, 0, 0)
        t_label = QLabel("✍️ 본문 직접 타이핑 작성:")
        t_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        t_label.setStyleSheet("color: #4F46E5;")
        self.text_content_input = QTextEdit()
        self.text_content_input.setPlaceholderText("여기에 상담 메모, 전화 면담 내용, 동향 보고, 회의록 등을 자유롭게 직접 타이핑하여 기록하세요...\n저장 시 로컬 서류 보관함에 텍스트 문서로 안전하게 자동 보관됩니다.")
        self.text_content_input.setFont(QFont("Malgun Gothic", 10))
        text_layout.addWidget(t_label)
        text_layout.addWidget(self.text_content_input)
        layout.addWidget(self.text_widget, stretch=1)

        # 비고 입력
        bottom_form = QFormLayout()
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("참고사항 또는 비고 메모")
        bottom_form.addRow("비고:", self.notes_input)
        layout.addLayout(bottom_form)

        # 하단 저장 버튼
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 저장하기")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                padding: 8px 20px;
                font-weight: bold;
                border-radius: 6px;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #4338CA; }
        """)
        save_btn.clicked.connect(self.save_doc)

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                padding: 8px 16px;
                border-radius: 6px;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #E2E8F0; }
        """)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.on_mode_toggled()

    def on_mode_toggled(self):
        is_text = self.radio_text.isChecked()
        self.file_widget.setVisible(not is_text)
        self.text_widget.setVisible(is_text)

    def browse_file(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "첨부 서류 선택",
            "",
            "문서 및 이미지 (*.hwp *.hwpx *.pdf *.docx *.xlsx *.jpg *.png *.txt);;모든 파일 (*.*)"
        )
        if fpath:
            self.file_path_input.setText(fpath)
            if not self.title_input.text():
                self.title_input.setText(os.path.splitext(os.path.basename(fpath))[0])

    def save_doc(self):
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "확인", "서류/기록 제목을 입력해 주세요.")
            return

        cid = self.client_combo.currentData()
        doctype = self.type_combo.currentText()
        notes = self.notes_input.text().strip()

        if self.radio_text.isChecked():
            # 직접 타이핑 기록 모드
            content = self.text_content_input.toPlainText().strip()
            if not content:
                QMessageBox.warning(self, "확인", "직접 기록할 본문 내용을 입력해 주세요.")
                return
            self.db.add_text_document(cid, title, doctype, content, notes)
            self.accept()
        else:
            # 기존 파일 첨부 모드
            fpath = self.file_path_input.text().strip()
            if not fpath or not os.path.exists(fpath):
                QMessageBox.warning(self, "확인", "유효한 첨부 파일을 선택해 주세요.")
                return
            self.db.add_document(cid, title, doctype, fpath, notes)
            self.accept()


class ManualCounselingDialog(QDialog):
    """사회복지사 수기 상담일지 직접 작성 다이얼로그 (AI 없이 직접 타이핑하여 누적 상담 이력에 저장)"""
    def __init__(self, db: Database, client_id: int = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.client_id = client_id
        self.current_profile = self.db.get_current_profile()
        self.setWindowTitle("✍️ 수기 상담기록 직접 작성")
        self.resize(680, 600)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 안내 배너
        banner = QFrame()
        banner.setStyleSheet("background-color: #EEF2FF; border: 1px solid #C7D2FE; border-radius: 8px; padding: 10px;")
        b_layout = QVBoxLayout(banner)
        b_title = QLabel("✍️ 사회복지사 직접 작성 상담 기록")
        b_title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        b_title.setStyleSheet("color: #3730A3;")
        b_desc = QLabel("AI 변환 없이 면담 내용, 전화 상담, 가정방문 결과를 직접 타이핑하여 대상자의 상담 이력에 영구 누적 저장합니다.")
        b_desc.setStyleSheet("color: #4338CA; font-size: 11px;")
        b_layout.addWidget(b_title)
        b_layout.addWidget(b_desc)
        layout.addWidget(banner)

        # 입력 폼
        form_layout = QFormLayout()

        # 대상자
        self.client_combo = QComboBox()
        self.client_combo.addItem("[ 👤 미지정 (일반 상담 기록) ]", None)
        clients = self.db.list_clients()
        for c in clients:
            self.client_combo.addItem(f"{c['name']} ({c['masked_name']} / {c['risk_level']})", c['id'])
        
        if self.client_id:
            for idx in range(self.client_combo.count()):
                if self.client_combo.itemData(idx) == self.client_id:
                    self.client_combo.setCurrentIndex(idx)
                    break
            self.client_combo.setEnabled(False)
        form_layout.addRow("대상자:", self.client_combo)

        # 일자 및 작성자
        row_date_worker = QHBoxLayout()
        self.date_input = QLineEdit(datetime.now().strftime("%Y-%m-%d"))
        self.date_input.setMaximumWidth(140)
        self.worker_input = QLineEdit(self.current_profile["name"])
        self.worker_input.setMaximumWidth(140)

        row_date_worker.addWidget(QLabel("상담 일자:"))
        row_date_worker.addWidget(self.date_input)
        row_date_worker.addSpacing(20)
        row_date_worker.addWidget(QLabel("작성자:"))
        row_date_worker.addWidget(self.worker_input)
        row_date_worker.addStretch()
        form_layout.addRow("일자/작성자:", row_date_worker)

        # 상담 서식/구분
        self.tmpl_combo = QComboBox()
        templates = self.db.list_form_templates(self.current_profile["id"])
        for template in templates:
            self.tmpl_combo.addItem(template["name"], template["id"])
        template_row = QHBoxLayout()
        template_row.addWidget(self.tmpl_combo, stretch=1)
        apply_template_btn = QPushButton("양식 불러오기")
        apply_template_btn.clicked.connect(self.apply_selected_template)
        template_row.addWidget(apply_template_btn)
        form_layout.addRow("상담 서식 구분:", template_row)
        layout.addLayout(form_layout)

        # 상담 본문
        layout.addWidget(QLabel("상담 상세 기록 및 개입 내용 (*):"))
        self.content_text = QTextEdit()
        self.content_text.setAcceptRichText(True)
        self.content_text.setPlaceholderText(
            "상담 및 개입 내용을 상세하게 입력하세요.\n\n"
            "예시:\n"
            "[상담 개요] 대상자 거주지 방문 면담 실시.\n"
            "[주요 호소] 최근 무릎 통증으로 인해 거동이 불편하여 식사 준비에 큰 어려움을 겪고 계심.\n"
            "[사정 및 개입] 긴급 밑반찬 지원 서비스 주 2회 연계 결정, 관할 보건소 방문간호팀 의뢰 예정."
        )
        self.content_text.setFont(QFont("Malgun Gothic", 10))
        layout.addWidget(self.content_text, stretch=1)

        if self.tmpl_combo.count():
            self.apply_selected_template()

        # 버튼
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 상담 이력에 저장")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                padding: 9px 22px;
                font-weight: bold;
                border-radius: 6px;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #4338CA; }
        """)
        save_btn.clicked.connect(self.save_record)

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                padding: 9px 16px;
                border-radius: 6px;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #E2E8F0; }
        """)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def save_record(self):
        content = self.content_text.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "확인", "상담 기록 본문 내용을 입력해 주세요.")
            return

        cid = self.client_combo.currentData()
        sdate = self.date_input.text().strip() or datetime.now().strftime("%Y-%m-%d")
        tmpl = self.tmpl_combo.currentText()
        worker = self.worker_input.text().strip() or "담당복지사"
        template_id = self.tmpl_combo.currentData()
        template = self.db.get_form_template(template_id, self.current_profile["id"]) if template_id else None

        data = {
            "client_id": cid,
            "session_date": sdate,
            "template_name": tmpl,
            "template_id": template_id,
            "template_snapshot": self.db.make_template_snapshot(template),
            "owner_id": self.current_profile["id"],
            "detail_level": "직접수기작성",
            "raw_memo": content,
            "ai_result": content,
            "result_html": self.content_text.toHtml(),
            "worker_name": worker
        }

        self.db.add_counseling_record(data)
        QMessageBox.information(self, "저장 완료", "수기 상담 기록이 성공적으로 등록되었습니다!")
        self.accept()

    def apply_selected_template(self):
        """선택한 개인 양식의 빈 구조를 수기 작성란에 적용합니다."""
        template_id = self.tmpl_combo.currentData()
        if not template_id:
            return
        template = self.db.get_form_template(template_id, self.current_profile["id"])
        if not template:
            return
        existing = self.content_text.toPlainText().strip() if hasattr(self, "content_text") else ""
        if existing:
            reply = QMessageBox.question(
                self,
                "양식 다시 불러오기",
                "현재 작성 중인 내용을 선택한 양식으로 바꾸시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        client_id = self.client_combo.currentData()
        client = self.db.get_client(client_id) if client_id else None
        metadata = {
            "상담일자": self.date_input.text().strip(),
            "작성자": self.worker_input.text().strip(),
            "대상자명": client.get("masked_name", "") if client else "",
            "상담방법": "",
        }
        base_form_html = template.get("form_html", "") or build_form_html(
            template.get("name", "상담 기록지"),
            template.get("guide", ""),
        )
        base_form_html = inject_approval_line(
            base_form_html,
            self.db.get_approval_line(self.current_profile["id"]),
        )
        form_html = fill_form_html(base_form_html, metadata=metadata)
        self.content_text.setHtml(form_html)


class TextViewerDialog(QDialog):
    """직접 작성한 서류/메모 전문 뷰어 및 수정 다이얼로그"""
    def __init__(self, title: str, file_path: str, parent=None, db=None, doc_id=None):
        super().__init__(parent)
        self.db, self.doc_id = db, doc_id
        self.title = title
        self.file_path = file_path
        self.setWindowTitle(f"📄 서류 열람 - {title}")
        self.resize(640, 560)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 상단 툴바
        top_bar = QHBoxLayout()
        t_label = QLabel(f"📄 {self.title}")
        t_label.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        t_label.setStyleSheet("color: #0F172A;")

        copy_btn = QPushButton("📋 본문 복사")
        copy_btn.setStyleSheet("background-color: #EEF2FF; color: #4338CA; border: 1px solid #C7D2FE; border-radius: 4px; padding: 5px 12px; font-weight: bold;")
        copy_btn.clicked.connect(self.copy_content)

        open_ext_btn = QPushButton("🖥️ 외부 메모장으로 열기")
        open_ext_btn.setStyleSheet("background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 4px; padding: 5px 12px;")
        open_ext_btn.clicked.connect(self.open_external)

        top_bar.addWidget(t_label)
        top_bar.addStretch()
        top_bar.addWidget(copy_btn)
        top_bar.addWidget(open_ext_btn)
        layout.addLayout(top_bar)

        # 본문 에디터
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setStyleSheet("border: 1px solid #CBD5E1; border-radius: 6px; padding: 10px; background-color: #FFFFFF;")
        layout.addWidget(self.editor, stretch=1)

        # 파일 내용 읽기
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.editor.setPlainText(f.read())
            except Exception as e:
                self.editor.setPlainText(f"파일을 읽는 중 오류가 발생했습니다:\n{str(e)}")

        # 하단 저장/닫기 버튼
        btn_bar = QHBoxLayout()
        save_change_btn = QPushButton("💾 수정 내용 저장")
        save_change_btn.setStyleSheet("background-color: #4F46E5; color: white; padding: 7px 18px; font-weight: bold; border-radius: 4px;")
        save_change_btn.clicked.connect(self.save_changes)

        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet("background-color: #F1F5F9; padding: 7px 14px; border-radius: 4px;")
        close_btn.clicked.connect(self.accept)

        btn_bar.addStretch()
        btn_bar.addWidget(save_change_btn)
        btn_bar.addWidget(close_btn)
        layout.addLayout(btn_bar)

    def copy_content(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.editor.toPlainText())
        QMessageBox.information(self, "복사 완료", "본문이 클립보드에 복사되었습니다.")

    def open_external(self):
        if os.path.exists(self.file_path):
            open_system_file(self.file_path)

    def save_changes(self):
        try:
            if self.db is not None and self.doc_id is not None:
                with self.db.get_connection() as conn:
                    row = conn.execute('SELECT * FROM documents WHERE id=?', (self.doc_id,)).fetchone()
                if not row:
                    raise ValueError('이미 삭제된 서류입니다.')
                self.db.update_attachment(self.doc_id, row['title'], row['doc_type'], row['notes'], text=self.editor.toPlainText())
                with self.db.get_connection() as conn:
                    updated = conn.execute('SELECT file_name FROM documents WHERE id=?', (self.doc_id,)).fetchone()
                self.file_path = self.db.get_document_full_path(updated['file_name'])
            else:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    f.write(self.editor.toPlainText())
            QMessageBox.information(self, "저장 완료", "서류 내용이 성공적으로 수정 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "저장 오류", f"수정 저장 중 오류가 발생했습니다:\n{str(e)}")
