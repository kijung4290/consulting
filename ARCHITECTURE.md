# 코드 구조

이 프로그램은 인터넷 전송 없이 기관 PC에서 실행되는 PyQt6 데스크톱 앱입니다.

## 모듈 책임

- `app.py`: 메인 창, 업무 메뉴 4화면 전환, 사용자 작업 흐름 조정.
  메뉴와 화면 인덱스는 모듈 상단의 `NAV_MENUS`, `PAGE_*`, 화면 안의 탭은 `CLIENT_TAB_*`,
  `DOCS_TAB_*`, `DATA_TAB_*` 상수로 한 곳에서 관리한다
- `counseling_workspace.py`: 상담 작성 UI, 사용자·대상자별 임시 저장과 복구, 생성 중 편집 상태
- `case_management.py`: 진행단계, 사정, 개입계획, 모니터링, 서비스 연계 작업판
- `counseling_report.py`: 대상자·양식·기간별 상담일지 조회와 인쇄·PDF 출력
- `template_manager.py`: 작업자별 서류 양식 생성·편집·복사·초기화·JSON 입출력
- `form_designer.py`: 검색·드래그 가능한 복지서식 블록 팔레트, 보기 배율과 선택 복제·삭제를 지원하는 리치 문서 캔버스
- `form_document.py`: 표 양식·우측 상단 결재라인 HTML 생성, 자동 입력칸과 AI 결과의 셀 배치
- `ui_theme.py`: 색상·타이포그래피·버튼 역할과 공통 페이지 머리말
- `workers.py`: 모델 다운로드, 모델 로드, AI 생성을 수행하는 백그라운드 작업
- `client_context.py`: 대상자별 누적 맥락을 로컬 AI로 갱신하는 백그라운드 작업.
  현재 단계와 자료 진행률을 공개해 사이드바 `AI 작업 상태`와 사례관리 맥락 탭이 함께 보여준다.
  자료마다 지문(`digests`)을 남겨, 프로그램을 켠 뒤 새로 저장·업로드한 자료만 기존 요약에
  이어 붙인다. 자료가 지워졌을 때만 전체를 다시 읽는다.
  `[맥락 다시 갱신]`은 `mode='selected'`와 고른 자료 목록(`selection`)을 남기고,
  그 회차만 고른 자료로 요약을 새로 쓴다.
  프로그램을 켜기 전부터 밀려 있던 대기 건은 자동으로 돌리지 않는다(`ContextController.deferred`)
- `database.py`: 대상자·상담·서류 저장과 백업·복원
- `dialogs.py`: 대상자, 서류, 수기 상담 등 보조 대화상자
- `anonymizer.py`: AI 입력 전 개인정보 패턴 비식별화
- `engine.py`: llama.cpp 기반 로컬 모델 실행
- `prompts.py`: 상담 서식과 프롬프트 구성
- `config.py`: 데이터 저장 위치 설정

## 데이터 흐름

1. 사용자가 대상자와 상담 메모를 입력합니다.
2. 마스킹 옵션이 켜져 있으면 `Anonymizer`가 성명·주민번호·연락처 등을 치환합니다.
3. `GenerationWorker`가 로컬 `InferenceEngine`에서 상담일지 초안을 생성합니다.
4. 현재 작업자의 개인 양식을 적용하고, 사용자가 결과를 검토해 저장하면 양식 스냅샷과 함께 SQLite에 기록합니다.
5. 사례관리 작업판에서 사정·목표·일정·서비스 연계를 대상자 이력으로 누적합니다.
6. 전체 백업 시 SQLite backup API로 사례관리 데이터를 포함한 DB 스냅샷과 첨부 서류를 ZIP으로 묶습니다.

## 보안 주의사항

“로컬 처리”는 AI 입력이 외부 서버로 전송되지 않는다는 뜻입니다. 현재 SQLite DB와 첨부 파일 자체는 암호화되지 않으므로 기관 PC 계정 보호, 디스크 암호화(BitLocker 등), 접근 권한 설정과 별도 백업 매체 관리가 필요합니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
