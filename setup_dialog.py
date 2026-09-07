"""
데이터 저장소 초기 설정 및 컴퓨터 이전 복원 다이얼로그 (setup_dialog.py)
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QRadioButton, QButtonGroup,
    QGroupBox, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import config
from database import Database

class StorageSetupDialog(QDialog):
    def __init__(self, parent=None, is_change_mode=False):
        super().__init__(parent)
        self.is_change_mode = is_change_mode
        self.setWindowTitle("데이터 저장 폴더 변경" if is_change_mode else "초기 데이터 저장소 설정 및 시작")
        self.resize(580, 420)
        self.restored_from_backup = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # 타이틀 & 안내
        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #0F172A; border-radius: 6px; padding: 12px;")
        h_layout = QVBoxLayout(header_frame)
        
        t_label = QLabel("📁 스마트 복지관 로컬 데이터 저장소 설정")
        t_label.setFont(QFont("Malgun Gothic", 13, QFont.Weight.Bold))
        t_label.setStyleSheet("color: #FFFFFF;")
        
        d_label = QLabel("모든 대상자 인적사항, AI 상담일지, 증빙 서류는 외부 서버가 아닌\n귀하의 컴퓨터 로컬 폴더에만 안전하게 100% 저장됩니다.")
        d_label.setStyleSheet("color: #94A3B8; font-size: 11px; line-height: 140%;")
        h_layout.addWidget(t_label)
        h_layout.addWidget(d_label)
        layout.addWidget(header_frame)

        # 옵션 그룹
        self.btn_group = QButtonGroup(self)

        # 옵션 1: 신규 폴더 지정
        self.radio_new = QRadioButton("1. 로컬 데이터 저장 폴더 지정 (새로 시작하기 / 권장)")
        self.radio_new.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        self.radio_new.setChecked(True)
        self.btn_group.addButton(self.radio_new)
        layout.addWidget(self.radio_new)

        new_box = QFrame()
        new_box.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px;")
        new_box_layout = QHBoxLayout(new_box)
        
        current_data_dir = config.get_data_dir()
        self.folder_input = QLineEdit(current_data_dir)
        self.folder_browse_btn = QPushButton("폴더 선택...")
        self.folder_browse_btn.setStyleSheet("padding: 5px 12px; background-color: #ECEFF1; border: 1px solid #CFD8DC; border-radius: 4px;")
        self.folder_browse_btn.clicked.connect(self.browse_folder)
        new_box_layout.addWidget(self.folder_input)
        new_box_layout.addWidget(self.folder_browse_btn)
        layout.addWidget(new_box)

        # 옵션 2: 백업 파일에서 복원
        if not self.is_change_mode:
            self.radio_restore = QRadioButton("2. 다른 컴퓨터의 전체 백업 파일(.zip)을 불러와서 시작")
            self.radio_restore.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
            self.btn_group.addButton(self.radio_restore)
            layout.addWidget(self.radio_restore)

            res_box = QFrame()
            res_box.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px;")
            res_box_layout = QHBoxLayout(res_box)
            self.zip_input = QLineEdit()
            self.zip_input.setPlaceholderText("백업 압축 파일(*.zip)을 선택하세요...")
            self.zip_browse_btn = QPushButton("백업 파일 찾기...")
            self.zip_browse_btn.setStyleSheet("padding: 5px 12px; background-color: #ECEFF1; border: 1px solid #CFD8DC; border-radius: 4px;")
            self.zip_browse_btn.clicked.connect(self.browse_zip)
            res_box_layout.addWidget(self.zip_input)
            res_box_layout.addWidget(self.zip_browse_btn)
            layout.addWidget(res_box)

        layout.addStretch()

        # 하단 버튼
        btn_layout = QHBoxLayout()
        confirm_text = "설정 완료 및 시작" if not self.is_change_mode else "폴더 변경 적용"
        self.confirm_btn = QPushButton(confirm_text)
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                padding: 10px 22px;
                font-weight: bold;
                border-radius: 6px;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #4338CA; }
        """)
        self.confirm_btn.clicked.connect(self.on_confirm)

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                padding: 10px 18px;
                border-radius: 6px;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #E2E8F0; }
        """)
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.confirm_btn)
        if self.is_change_mode:
            btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "데이터 저장 폴더 선택", self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)
            self.radio_new.setChecked(True)

    def browse_zip(self):
        zip_file, _ = QFileDialog.getOpenFileName(self, "백업 압축 파일 선택", "", "백업 압축 파일 (*.zip)")
        if zip_file:
            self.zip_input.setText(zip_file)
            self.radio_restore.setChecked(True)

    def on_confirm(self):
        target_dir = self.folder_input.text().strip()
        if not target_dir:
            QMessageBox.warning(self, "확인", "데이터를 저장할 폴더 경로를 지정해 주세요.")
            return

        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"폴더를 생성할 수 없습니다:\n{str(e)}")
            return

        # 백업 복원 모드인 경우
        if not self.is_change_mode and self.radio_restore.isChecked():
            zip_path = self.zip_input.text().strip()
            if not zip_path or not os.path.exists(zip_path):
                QMessageBox.warning(self, "확인", "유효한 백업 파일(.zip)을 선택해 주세요.")
                return
            
            ok, msg, meta = Database.restore_from_backup_zip(zip_path, target_dir)
            if not ok:
                QMessageBox.critical(self, "복원 실패", msg)
                return
            
            self.restored_from_backup = True
            clients_cnt = meta.get("total_clients", "여러")
            docs_cnt = meta.get("total_docs", "여러")
            QMessageBox.information(
                self, "복원 성공",
                f"성공적으로 복원되었습니다!\n(대상자 {clients_cnt}명, 서류 {docs_cnt}건 복원 완료)\n저장 위치: {target_dir}"
            )

        # 설정 저장
        config.set_data_dir(target_dir)
        self.accept()
