# 사회복지 상담기록 AI · 1.1.0

Windows / Linux Mint·Ubuntu에서 사용하는 PyQt6 데스크톱 프로그램입니다.
상담 메모는 로컬 Gemma 모델로 정리하며, 직접 서류 작성은 AI 모델 없이도 사용할 수 있습니다.

## 업무 메뉴

좌측 업무 메뉴는 현장에서 실제로 나누어 쓰는 네 가지 일로만 구성합니다.

| 메뉴 | 담는 일 |
| --- | --- |
| 대상자 관리 | 업무 현황 요약(KPI·빠른 실행), 대상자 등록·검색·위기도, 확인할 일정, 최근 상담, 최근 서류 |
| 사례관리 | 대상자별 AI 맥락, 작성 서류 현황·내용 확인, 욕구·위기도 사정, 목표·개입계획, 모니터링 일정, 서비스 연계 |
| 서류작성 및 보관함 | 상담일지 작성, 사례관리 14종 서류 작성·이어쓰기, 모든 서류의 검색·열람·수정 |
| 데이터 관리 | 서류 양식 편집·결재라인, 데이터 백업·복원, 저장 위치 |

## 주요 기능

- 대상자 관리, 상담기록, 첨부 서류, 백업·복원
- 사례관리 7단계와 14종 서류양식 연결
- 대상자별 서류 작성·이어쓰기·임시저장·작성완료
- 이전 서류 내용 불러오기, 작성 당시 양식 보존, PDF 출력
- 개인 양식 편집과 사용자별 결재라인
- 욕구사정, 목표·개입계획, 모니터링 일정, 서비스 연계

단계별 서류의 AI 직접 작성·평가 자동 집계는 아직 지원하지 않습니다.
SQLite와 첨부 서류는 암호화되지 않으므로 PC 및 저장 폴더의 접근 권한을 관리하세요.

## 설치

자세한 안내: [Windows / Linux 설치·배포](docs/설치_배포.md)

Windows 설치본은 WelfareAI-Setup-1.1.0.exe입니다.
GitHub 소스로 실행할 경우 Python 3.11 이상과 C++ 빌드 환경이 필요할 수 있습니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Linux Mint / Ubuntu에서는 설치 안내의 시스템 패키지 준비 후 실행하세요.

```bash
bash install_linux.sh
bash run_linux.sh
```

Git에는 개인 설정·상담 데이터·모델·가상환경·빌드 결과를 포함하지 않습니다.
모델은 앱의 다운로드 기능 또는 별도 models 폴더로 준비합니다.
업데이트 전 전체 백업을 만들고, 업데이트 후 기존 데이터 폴더를 선택하세요.

## 배포 빌드

Windows에서 PyInstaller 및 Inno Setup 6을 설치한 후:

```powershell
.\.venv\Scripts\python.exe build_package.py --platform all
```

installer_output/버전-빌드시각/에 Windows 설치본과 Linux 소스 설치 패키지를 만듭니다.
models 폴더에 모델이 있으면 양쪽 패키지에 포함합니다. 이전 빌드는 보존합니다.
Linux 패키지는 소스 기반이며 최초 의존성 설치에는 인터넷이 필요합니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Linux 실기기 검증은 별도로 필요합니다.

## 코드와 사용 안내

- [상담 업무 중심 UI·UX 개선 및 실행 안내](docs/UI_UX_개선_20260908.md)

- [코드 구조](ARCHITECTURE.md)
- [사례관리 서류 진행](docs/사례관리_서류진행.md)
- [14종 양식 안내](docs/사례관리양식.md)
- app.py: 메인 화면과 상담 작성
- case_management.py / case_forms.py: 사례관리 작업판과 서류 작성
- case_form_templates.py / template_manager.py: 양식 정의와 편집
- database.py: 로컬 저장과 백업
- engine.py / workers.py: 로컬 AI 실행
