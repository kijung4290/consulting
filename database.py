"""
사회복지 스마트 사례관리 SaaS - 로컬 SQLite 데이터베이스 및 통합 압축 백업 모듈
- 지정된 로컬 폴더(data_dir)에 데이터베이스(welfare_saas.db) 및 서류(documents/) 저장
- 컴퓨터 이전용 원클릭 전체 압축 백업 (.zip) 생성
- 새 컴퓨터에서 원클릭 전체 복원 (.zip 추출 및 DB 재연결)
- 컴퓨터 간 이동 시에도 경로가 깨지지 않도록 서류 파일 상대경로 기반 관리
"""

import os
import json
import sqlite3
import shutil
import tempfile
import zipfile
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from form_document import build_form_html
from prompts import DEFAULT_TEMPLATE_NAME, RETIRED_TEMPLATE_KEYS

class Database:
    def __init__(self, data_dir: str):
        self.data_dir = os.path.abspath(data_dir)
        self.db_path = os.path.join(self.data_dir, "welfare_saas.db")
        self.docs_dir = os.path.join(self.data_dir, "documents")

        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.docs_dir, exist_ok=True)
        self.init_tables()

    @contextmanager
    def get_connection(self):
        """트랜잭션 종료 후 파일 핸들까지 확실히 닫는 DB 연결 컨텍스트."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_tables(self):
        """데이터베이스 테이블 생성 및 초기화"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. 대상자 (Clients) 테이블
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                masked_name TEXT,
                birth_date TEXT,
                gender TEXT,
                phone TEXT,
                address TEXT,
                welfare_type TEXT DEFAULT '일반',       -- 기초수급, 차상위, 일반, 긴급지원대상
                risk_level TEXT DEFAULT '일반',         -- 고위기, 중위기, 저위기, 일반
                household_type TEXT DEFAULT '독거노인',   -- 독거노인, 한부모, 장애인, 조손, 1인가구, 다문화, 일반
                intake_date TEXT,                       -- 최초 접수일
                memo TEXT,                              -- 특이사항 및 요약 메모
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 2. 상담 기록 (Counseling Records) 테이블
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS counseling_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                session_date TEXT NOT NULL,             -- 상담 일자 (YYYY-MM-DD)
                template_name TEXT NOT NULL,            -- 13대 서식명
                template_id INTEGER,                    -- 사용자별 서류 양식 ID
                template_snapshot TEXT DEFAULT '',      -- 작성 당시 양식 JSON 스냅샷
                owner_id INTEGER,                       -- 작성 작업자 프로필 ID
                detail_level TEXT DEFAULT '표준',
                raw_memo TEXT,                          -- 원본 거친 메모
                ai_result TEXT NOT NULL,                -- 생성된 최종 상담일지
                result_html TEXT DEFAULT '',            -- 표 서식을 포함한 상담일지 HTML
                worker_name TEXT DEFAULT '담당복지사',    -- 작성자
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
            """)

            # 3. 서류 및 파일 보관함 (Documents) 테이블 (상대 파일명 저장)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                title TEXT NOT NULL,                    -- 서류명
                doc_type TEXT NOT NULL,                 -- 초기면접지, 동의서, 소견서, 신청서 등
                file_name TEXT NOT NULL,                -- documents 폴더 내 상대 파일명
                file_size INTEGER DEFAULT 0,
                notes TEXT,                             -- 비고
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
            """)

            # 4. 사례관리 진행단계
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_profiles (
                client_id INTEGER PRIMARY KEY,
                stage TEXT NOT NULL DEFAULT '접수',
                stage_note TEXT DEFAULT '',
                opened_at TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS case_form_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                    owner_id INTEGER NOT NULL REFERENCES worker_profiles(id),
                    source_key TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    record_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '작성중',
                    template_snapshot TEXT NOT NULL,
                    fields_json TEXT NOT NULL DEFAULT '{}',
                    result_html TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_case_forms_client ON case_form_records(client_id, source_key, id)")

            # 5. 욕구·위기도 사정 스냅샷
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                assessed_at TEXT NOT NULL,
                scores_json TEXT NOT NULL,
                summary TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
            """)

            # 6. 목표·개입계획
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                action_plan TEXT DEFAULT '',
                due_date TEXT,
                status TEXT DEFAULT '진행',
                progress INTEGER DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
            """)

            # 7. 모니터링 일정
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitoring_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                due_date TEXT NOT NULL,
                notes TEXT DEFAULT '',
                status TEXT DEFAULT '예정',
                completed_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
            """)

            # 8. 지역자원과 서비스 연계
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS welfare_resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT '기타',
                contact TEXT DEFAULT '',
                description TEXT DEFAULT '',
                eligibility TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                resource_id INTEGER,
                service_name TEXT NOT NULL,
                requested_date TEXT NOT NULL,
                status TEXT DEFAULT '의뢰',
                result TEXT DEFAULT '',
                next_check_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE,
                FOREIGN KEY (resource_id) REFERENCES welfare_resources (id) ON DELETE SET NULL
            )
            """)

            # 9. 로컬 작업자 프로필 및 사용자별 서류 양식
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS worker_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                approval_line_json TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS form_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '상담기록',
                description TEXT DEFAULT '',
                guide TEXT NOT NULL,
                form_html TEXT DEFAULT '',
                example_input TEXT DEFAULT '',
                source_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES worker_profiles (id) ON DELETE CASCADE,
                UNIQUE (owner_id, name)
            )
            """)

            # 기존 데이터베이스도 데이터 손실 없이 새 컬럼을 사용할 수 있게 자동 마이그레이션합니다.
            self._ensure_column(conn, "counseling_records", "template_id", "INTEGER")
            self._ensure_column(conn, "counseling_records", "template_snapshot", "TEXT DEFAULT ''")
            self._ensure_column(conn, "counseling_records", "owner_id", "INTEGER")
            self._ensure_column(conn, "counseling_records", "result_html", "TEXT DEFAULT ''")
            self._ensure_column(conn, "counseling_records", "updated_at", "TEXT DEFAULT ''")
            self._ensure_column(conn, "documents", "updated_at", "TEXT DEFAULT ''")
            self._ensure_column(conn, "form_templates", "form_html", "TEXT DEFAULT ''")
            self._ensure_column(conn, "worker_profiles", "approval_line_json", "TEXT DEFAULT ''")

            cursor.execute("INSERT OR IGNORE INTO worker_profiles (name) VALUES ('기본 사용자')")
            default_profile_id = cursor.execute(
                "SELECT id FROM worker_profiles WHERE name = '기본 사용자'"
            ).fetchone()[0]
            cursor.execute(
                "INSERT OR IGNORE INTO app_preferences (key, value) VALUES ('current_profile_id', ?)",
                (str(default_profile_id),),
            )
            cursor.execute(
                "UPDATE counseling_records SET owner_id = ? WHERE owner_id IS NULL",
                (default_profile_id,),
            )

            # 성능 최적화 인덱스 생성
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clients_risk ON clients(risk_level);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_client ON counseling_records(client_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_date ON counseling_records(session_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_client ON documents(client_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_type ON documents(doc_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assessments_client ON case_assessments(client_id, assessed_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_goals_client ON case_goals(client_id, status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_due ON monitoring_tasks(status, due_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_links_client ON service_links(client_id, status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_templates_owner ON form_templates(owner_id, updated_at);")
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_templates_owner_source
                ON form_templates(owner_id, source_key)
                WHERE source_key IS NOT NULL
            """)

            from client_context import initialize_context
            initialize_context(conn)
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, declaration: str) -> None:
        """기존 설치본의 테이블에 새 컬럼이 없을 때만 안전하게 추가합니다."""
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {declaration}")

    # ================= [대상자 CRUD] =================
    def add_client(self, data: Dict[str, Any]) -> int:
        name = data.get("name", "").strip()
        masked = data.get("masked_name", "")
        if not masked and name:
            masked = name[0] + "OO님" if len(name) <= 3 else name[0] + "OO" + name[-1] + "님"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO clients (name, masked_name, birth_date, gender, phone, address, 
                                welfare_type, risk_level, household_type, intake_date, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                masked,
                data.get("birth_date", ""),
                data.get("gender", "미상"),
                data.get("phone", ""),
                data.get("address", ""),
                data.get("welfare_type", "일반"),
                data.get("risk_level", "일반"),
                data.get("household_type", "독거노인"),
                data.get("intake_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("memo", "")
            ))
            conn.commit()
            return cursor.lastrowid

    def update_client(self, client_id: int, data: Dict[str, Any]) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE clients SET 
                name = ?, masked_name = ?, birth_date = ?, gender = ?, phone = ?, address = ?,
                welfare_type = ?, risk_level = ?, household_type = ?, intake_date = ?, memo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """, (
                data.get("name"),
                data.get("masked_name"),
                data.get("birth_date"),
                data.get("gender"),
                data.get("phone"),
                data.get("address"),
                data.get("welfare_type"),
                data.get("risk_level"),
                data.get("household_type"),
                data.get("intake_date"),
                data.get("memo"),
                client_id
            ))
            conn.commit()
            return cursor.rowcount > 0

    def delete_client(self, client_id: int) -> bool:
        """대상자 삭제 (해당 대상자의 서류 파일 실물 삭제 및 상담 이력 연계 삭제)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. 대상자의 서류 첨부 파일 실물 삭제
            cursor.execute("SELECT file_name FROM documents WHERE client_id = ?", (client_id,))
            for row in cursor.fetchall():
                fname = row["file_name"]
                if fname:
                    fpath = self.get_document_full_path(fname)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except Exception:
                            pass

            # 2. 대상자 레코드 삭제 (ON DELETE CASCADE로 서류 및 상담기록 연쇄 삭제)
            cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_client(self, client_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_clients(self, keyword: str = "", risk_filter: str = "전체", welfare_filter: str = "전체") -> List[Dict[str, Any]]:
        query = "SELECT * FROM clients WHERE 1=1"
        params = []

        if keyword:
            query += " AND (name LIKE ? OR masked_name LIKE ? OR phone LIKE ? OR address LIKE ?)"
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw])

        if risk_filter and risk_filter != "전체":
            query += " AND risk_level = ?"
            params.append(risk_filter)

        if welfare_filter and welfare_filter != "전체":
            query += " AND welfare_type = ?"
            params.append(welfare_filter)

        query += " ORDER BY id DESC"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    # ================= [상담 기록 CRUD] =================
    def add_counseling_record(self, data: Dict[str, Any]) -> int:
        template_snapshot = data.get("template_snapshot", "")
        if isinstance(template_snapshot, dict):
            template_snapshot = json.dumps(template_snapshot, ensure_ascii=False)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO counseling_records (
                client_id, session_date, template_name, template_id, template_snapshot, owner_id,
                detail_level, raw_memo, ai_result, result_html, worker_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("client_id"),
                data.get("session_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("template_name", DEFAULT_TEMPLATE_NAME),
                data.get("template_id"),
                template_snapshot,
                data.get("owner_id"),
                data.get("detail_level", "표준"),
                data.get("raw_memo", ""),
                data.get("ai_result", ""),
                data.get("result_html", ""),
                data.get("worker_name", "담당복지사")
            ))
            conn.commit()
            return cursor.lastrowid

    # ================= [작업자 프로필·사용자별 서류 양식] =================
    def create_profile(self, name: str) -> int:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("사용자 이름을 입력해 주세요.")
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("INSERT INTO worker_profiles (name) VALUES (?)", (clean_name,))
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 사용자가 이미 있습니다.") from exc
            return cursor.lastrowid

    def list_profiles(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM worker_profiles ORDER BY id").fetchall()
            return [dict(row) for row in rows]

    def get_profile(self, profile_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM worker_profiles WHERE id = ?", (profile_id,)).fetchone()
            return dict(row) if row else None

    def get_current_profile(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT p.* FROM worker_profiles p
                JOIN app_preferences a ON a.key = 'current_profile_id'
                WHERE CAST(a.value AS INTEGER) = p.id
            """).fetchone()
            if row:
                return dict(row)
            row = conn.execute("SELECT * FROM worker_profiles ORDER BY id LIMIT 1").fetchone()
            if not row:
                cursor = conn.execute("INSERT INTO worker_profiles (name) VALUES ('기본 사용자')")
                row = conn.execute("SELECT * FROM worker_profiles WHERE id = ?", (cursor.lastrowid,)).fetchone()
            conn.execute(
                "INSERT OR REPLACE INTO app_preferences (key, value) VALUES ('current_profile_id', ?)",
                (str(row["id"]),),
            )
            return dict(row)

    def set_current_profile(self, profile_id: int) -> None:
        if not self.get_profile(profile_id):
            raise ValueError("선택한 사용자를 찾을 수 없습니다.")
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_preferences (key, value) VALUES ('current_profile_id', ?)",
                (str(profile_id),),
            )

    def get_approval_line(self, profile_id: int) -> List[Dict[str, str]]:
        """사용자별 결재 직위·결재자명 목록을 반환합니다."""
        profile = self.get_profile(profile_id)
        if not profile:
            return []
        raw_value = profile.get("approval_line_json", "")
        if raw_value:
            try:
                steps = json.loads(raw_value)
                cleaned = [
                    {
                        "title": str(step.get("title", "")).strip(),
                        "name": str(step.get("name", "")).strip(),
                    }
                    for step in steps
                    if isinstance(step, dict) and str(step.get("title", "")).strip()
                ]
                if cleaned:
                    return cleaned[:8]
            except (TypeError, json.JSONDecodeError):
                pass
        return [
            {"title": "담당", "name": profile.get("name", "")},
            {"title": "팀장", "name": ""},
            {"title": "관장", "name": ""},
        ]

    def save_approval_line(self, profile_id: int, steps: List[Dict[str, str]]) -> None:
        """최대 8칸의 사용자 맞춤형 결재라인을 로컬 프로필에 저장합니다."""
        if not self.get_profile(profile_id):
            raise ValueError("결재라인을 저장할 사용자를 찾을 수 없습니다.")
        cleaned = []
        for step in steps:
            title = str(step.get("title", "")).strip()
            if not title:
                continue
            cleaned.append({"title": title, "name": str(step.get("name", "")).strip()})
        if not cleaned:
            raise ValueError("결재 직위를 한 개 이상 입력해 주세요.")
        if len(cleaned) > 8:
            raise ValueError("결재라인은 최대 8칸까지 만들 수 있습니다.")
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE worker_profiles SET approval_line_json = ? WHERE id = ?",
                (json.dumps(cleaned, ensure_ascii=False), profile_id),
            )

    def ensure_builtin_templates(self, owner_id: int, templates: Dict[str, Dict[str, str]]) -> int:
        """작업자에게 기본 양식의 개인 사본을 최초 한 번만 구성합니다."""
        inserted = 0
        with self.get_connection() as conn:
            # 이전 기본 양식은 목록에서 제거하되 수정본은 복구용으로 보관합니다.
            # 상담기록 및 작성 당시 template_snapshot은 변경하지 않습니다.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retired_form_templates (
                    template_id INTEGER PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    snapshot TEXT NOT NULL,
                    retired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            retired = [key for key in RETIRED_TEMPLATE_KEYS if key not in templates]
            if retired:
                marks = ','.join('?' for _ in retired)
                rows = conn.execute(
                    f"SELECT * FROM form_templates WHERE owner_id = ? AND source_key IN ({marks})",
                    [owner_id, *retired],
                ).fetchall()
                for row in rows:
                    conn.execute(
                        "INSERT OR REPLACE INTO retired_form_templates (template_id, owner_id, snapshot) VALUES (?, ?, ?)",
                        (row['id'], owner_id, json.dumps(dict(row), ensure_ascii=False)),
                    )
                    conn.execute("DELETE FROM form_templates WHERE id = ? AND owner_id = ?", (row['id'], owner_id))
            for name, info in templates.items():
                form_html = info.get("form_html") or build_form_html(name, info.get("guide", ""))
                try:
                    cursor = conn.execute("""
                        INSERT OR IGNORE INTO form_templates (
                            owner_id, name, category, description, guide, form_html, example_input, source_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        owner_id,
                        name,
                        info.get("category", "상담기록"),
                        info.get("description", ""),
                        info.get("guide", ""),
                        form_html,
                        info.get("example_input", ""),
                        name,
                    ))
                    inserted += max(cursor.rowcount, 0)
                    conn.execute("""
                        UPDATE form_templates SET form_html = ?
                        WHERE owner_id = ? AND source_key = ?
                          AND (form_html IS NULL OR TRIM(form_html) = '')
                    """, (form_html, owner_id, name))
                except sqlite3.IntegrityError:
                    # 같은 이름의 사용자 제작 양식이 이미 있으면 그 내용을 존중합니다.
                    continue
        return inserted

    def list_form_templates(self, owner_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM form_templates
                WHERE owner_id = ?
                ORDER BY CASE WHEN source_key IS NULL THEN 1 ELSE 0 END, id
            """, (owner_id,)).fetchall()
            return [dict(row) for row in rows]

    def get_form_template(self, template_id: int, owner_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM form_templates WHERE id = ?"
        params: List[Any] = [template_id]
        if owner_id is not None:
            query += " AND owner_id = ?"
            params.append(owner_id)
        with self.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return dict(row) if row else None

    def save_form_template(self, owner_id: int, data: Dict[str, Any], template_id: Optional[int] = None) -> int:
        name = data.get("name", "").strip()
        guide = data.get("guide", "").strip()
        if not name:
            raise ValueError("양식 이름을 입력해 주세요.")
        if not guide:
            raise ValueError("양식 구조 및 작성 지침을 입력해 주세요.")
        form_html = data.get("form_html", "").strip() or build_form_html(name, guide)
        with self.get_connection() as conn:
            try:
                if template_id is None:
                    cursor = conn.execute("""
                        INSERT INTO form_templates (
                            owner_id, name, category, description, guide, form_html, example_input, source_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    """, (
                        owner_id, name, data.get("category", "상담기록").strip() or "상담기록",
                        data.get("description", "").strip(), guide, form_html,
                        data.get("example_input", "").strip(),
                    ))
                    return cursor.lastrowid

                existing = conn.execute(
                    "SELECT id FROM form_templates WHERE id = ? AND owner_id = ?",
                    (template_id, owner_id),
                ).fetchone()
                if not existing:
                    raise ValueError("수정할 양식을 찾을 수 없습니다.")
                conn.execute("""
                    UPDATE form_templates SET
                        name = ?, category = ?, description = ?, guide = ?, form_html = ?, example_input = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND owner_id = ?
                """, (
                    name, data.get("category", "상담기록").strip() or "상담기록",
                    data.get("description", "").strip(), guide, form_html,
                    data.get("example_input", "").strip(),
                    template_id, owner_id,
                ))
                return template_id
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 양식이 이미 있습니다.") from exc

    def delete_form_template(self, template_id: int, owner_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM form_templates WHERE id = ? AND owner_id = ?",
                (template_id, owner_id),
            )
            return cursor.rowcount > 0

    def duplicate_form_template(self, template_id: int, owner_id: int) -> int:
        source = self.get_form_template(template_id, owner_id)
        if not source:
            raise ValueError("복사할 양식을 찾을 수 없습니다.")
        existing_names = {item["name"] for item in self.list_form_templates(owner_id)}
        base_name = f"{source['name']} - 복사본"
        new_name = base_name
        sequence = 2
        while new_name in existing_names:
            new_name = f"{base_name} {sequence}"
            sequence += 1
        return self.save_form_template(owner_id, {
            "name": new_name,
            "category": source["category"],
            "description": source["description"],
            "guide": source["guide"],
            "form_html": source.get("form_html", ""),
            "example_input": source["example_input"],
        })

    def reset_form_template(self, template_id: int, owner_id: int, defaults: Dict[str, Dict[str, str]]) -> bool:
        current = self.get_form_template(template_id, owner_id)
        if not current or not current.get("source_key") or current["source_key"] not in defaults:
            return False
        info = defaults[current["source_key"]]
        form_html = info.get("form_html") or build_form_html(current["source_key"], info.get("guide", ""))
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE form_templates SET
                    name = ?, category = ?, description = ?, guide = ?, form_html = ?, example_input = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND owner_id = ?
            """, (
                current["source_key"], info.get("category", "상담기록"),
                info.get("description", ""), info.get("guide", ""), form_html,
                info.get("example_input", ""),
                template_id, owner_id,
            ))
        return True

    @staticmethod
    def make_template_snapshot(template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not template:
            return {}
        return {
            "id": template.get("id"),
            "name": template.get("name", ""),
            "category": template.get("category", ""),
            "description": template.get("description", ""),
            "guide": template.get("guide", ""),
            "form_html": template.get("form_html", ""),
            "source_key": template.get("source_key"),
        }

    def list_counseling_records(self, client_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if client_id:
                cursor.execute("""
                SELECT r.*, c.name as client_name, c.masked_name 
                FROM counseling_records r
                LEFT JOIN clients c ON r.client_id = c.id
                WHERE r.client_id = ?
                ORDER BY r.session_date DESC, r.id DESC LIMIT ?
                """, (client_id, limit))
            else:
                cursor.execute("""
                SELECT r.*, c.name as client_name, c.masked_name 
                FROM counseling_records r
                LEFT JOIN clients c ON r.client_id = c.id
                ORDER BY r.session_date DESC, r.id DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def search_counseling_records(
        self,
        client_id: Optional[int] = None,
        template_name: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> List[Dict[str, Any]]:
        """대상자·양식·기간 조건으로 출력용 상담일지를 조회합니다."""
        query = """
            SELECT r.*, c.name AS client_name, c.masked_name
            FROM counseling_records r
            LEFT JOIN clients c ON c.id = r.client_id
            WHERE 1=1
        """
        params = []
        if client_id is not None:
            query += " AND r.client_id = ?"
            params.append(client_id)
        if template_name:
            query += " AND r.template_name = ?"
            params.append(template_name)
        if date_from:
            query += " AND r.session_date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND r.session_date <= ?"
            params.append(date_to)
        query += " ORDER BY r.session_date ASC, r.id ASC"
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def list_counseling_templates(self) -> List[str]:
        """실제로 저장된 상담 양식 목록을 반환합니다."""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT DISTINCT template_name FROM counseling_records
                WHERE template_name IS NOT NULL AND TRIM(template_name) != ''
                ORDER BY template_name
            """).fetchall()
            return [row[0] for row in rows]

    def delete_counseling_record(self, record_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM counseling_records WHERE id = ?", (record_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ================= [사례관리] =================
    def list_case_forms(self, client_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM case_form_records WHERE client_id = ? ORDER BY record_date DESC, id DESC",
                (client_id,),
            )]

    def save_case_form(self, client_id: int, owner_id: int, data: Dict[str, Any], record_id=None) -> int:
        if data.get('status') not in ('작성중', '작성완료'):
            raise ValueError('작성 상태를 확인해 주세요.')
        datetime.strptime(data['record_date'], '%Y-%m-%d')
        values = (data['source_key'], data['stage'], data['record_date'], data['status'],
                  json.dumps(data['template_snapshot'], ensure_ascii=False),
                  json.dumps(data['fields'], ensure_ascii=False), data['result_html'])
        with self.get_connection() as conn:
            if record_id is None:
                return conn.execute("""
                    INSERT INTO case_form_records
                    (source_key, stage, record_date, status, template_snapshot, fields_json, result_html, client_id, owner_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (*values, client_id, owner_id)).lastrowid
            cursor = conn.execute("""
                UPDATE case_form_records SET source_key=?, stage=?, record_date=?, status=?,
                template_snapshot=?, fields_json=?, result_html=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND client_id=? AND owner_id=?
            """, (*values, record_id, client_id, owner_id))
            if cursor.rowcount != 1:
                raise ValueError('본인이 작성한 해당 대상자의 서류만 수정할 수 있습니다.')
            return record_id

    def get_case_profile(self, client_id: int) -> Dict[str, Any]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM case_profiles WHERE client_id = ?", (client_id,)).fetchone()
            return dict(row) if row else {
                "client_id": client_id, "stage": "접수", "stage_note": "", "opened_at": ""
            }

    def save_case_profile(self, client_id: int, stage: str, stage_note: str = "") -> None:
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO case_profiles (client_id, stage, stage_note, opened_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    stage = excluded.stage,
                    stage_note = excluded.stage_note,
                    updated_at = CURRENT_TIMESTAMP
            """, (client_id, stage, stage_note, datetime.now().strftime("%Y-%m-%d")))

    def add_assessment(self, client_id: int, scores: Dict[str, int], summary: str = "", assessed_at: str = "") -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO case_assessments (client_id, assessed_at, scores_json, summary)
                VALUES (?, ?, ?, ?)
            """, (
                client_id,
                assessed_at or datetime.now().strftime("%Y-%m-%d"),
                json.dumps(scores, ensure_ascii=False),
                summary,
            ))
            return cursor.lastrowid

    def list_assessments(self, client_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM case_assessments WHERE client_id = ?
                ORDER BY assessed_at DESC, id DESC
            """, (client_id,)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["scores"] = json.loads(item.pop("scores_json"))
                except (json.JSONDecodeError, TypeError):
                    item["scores"] = {}
                result.append(item)
            return result

    def add_goal(self, client_id: int, title: str, action_plan: str, due_date: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO case_goals (client_id, title, action_plan, due_date)
                VALUES (?, ?, ?, ?)
            """, (client_id, title, action_plan, due_date))
            return cursor.lastrowid

    def list_goals(self, client_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM case_goals WHERE client_id = ?
                ORDER BY CASE status WHEN '진행' THEN 0 WHEN '보류' THEN 1 ELSE 2 END, due_date, id DESC
            """, (client_id,)).fetchall()
            return [dict(row) for row in rows]

    def update_goal_progress(self, goal_id: int, progress: int, status: str) -> bool:
        progress = max(0, min(100, int(progress)))
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE case_goals SET progress = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (progress, status, goal_id))
            return cursor.rowcount > 0

    def delete_goal(self, goal_id: int) -> bool:
        with self.get_connection() as conn:
            return conn.execute("DELETE FROM case_goals WHERE id = ?", (goal_id,)).rowcount > 0

    def add_monitoring_task(self, client_id: int, task_type: str, due_date: str, notes: str = "") -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO monitoring_tasks (client_id, task_type, due_date, notes)
                VALUES (?, ?, ?, ?)
            """, (client_id, task_type, due_date, notes))
            return cursor.lastrowid

    def list_monitoring_tasks(self, client_id: Optional[int] = None, include_completed: bool = True) -> List[Dict[str, Any]]:
        query = """
            SELECT m.*, c.name AS client_name FROM monitoring_tasks m
            JOIN clients c ON c.id = m.client_id WHERE 1=1
        """
        params = []
        if client_id is not None:
            query += " AND m.client_id = ?"
            params.append(client_id)
        if not include_completed:
            query += " AND m.status != '완료'"
        query += " ORDER BY CASE m.status WHEN '예정' THEN 0 ELSE 1 END, m.due_date, m.id DESC"
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def complete_monitoring_task(self, task_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE monitoring_tasks SET status = '완료', completed_at = ? WHERE id = ?
            """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
            return cursor.rowcount > 0

    def delete_monitoring_task(self, task_id: int) -> bool:
        with self.get_connection() as conn:
            return conn.execute("DELETE FROM monitoring_tasks WHERE id = ?", (task_id,)).rowcount > 0

    def add_resource(self, name: str, category: str, contact: str = "", description: str = "", eligibility: str = "") -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO welfare_resources (name, category, contact, description, eligibility)
                VALUES (?, ?, ?, ?, ?)
            """, (name, category, contact, description, eligibility))
            return cursor.lastrowid

    def list_resources(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT * FROM welfare_resources WHERE active = 1 ORDER BY category, name
            """).fetchall()]

    def add_service_link(self, client_id: int, resource_id: Optional[int], service_name: str,
                         requested_date: str, status: str = "의뢰", result: str = "",
                         next_check_date: str = "") -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO service_links
                    (client_id, resource_id, service_name, requested_date, status, result, next_check_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (client_id, resource_id, service_name, requested_date, status, result, next_check_date))
            return cursor.lastrowid

    def list_service_links(self, client_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT s.*, r.name AS resource_name FROM service_links s
                LEFT JOIN welfare_resources r ON r.id = s.resource_id
                WHERE s.client_id = ? ORDER BY s.requested_date DESC, s.id DESC
            """, (client_id,)).fetchall()
            return [dict(row) for row in rows]

    def update_service_link_status(self, link_id: int, status: str, result: str = "") -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE service_links SET status = ?, result = ? WHERE id = ?", (status, result, link_id))
            return cursor.rowcount > 0

    def delete_service_link(self, link_id: int) -> bool:
        with self.get_connection() as conn:
            return conn.execute("DELETE FROM service_links WHERE id = ?", (link_id,)).rowcount > 0

    # ================= [서류 및 파일 관리 (상대 경로)] =================
    def add_document(self, client_id: Optional[int], title: str, doc_type: str, src_file_path: str, notes: str = "") -> int:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"doc_{timestamp}_{os.path.basename(src_file_path)}"
        dest_path = os.path.join(self.docs_dir, safe_filename)

        shutil.copy2(src_file_path, dest_path)
        file_size = os.path.getsize(dest_path)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO documents (client_id, title, doc_type, file_name, file_size, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (client_id, title, doc_type, safe_filename, file_size, notes))
            conn.commit()
            return cursor.lastrowid

    def add_text_document(self, client_id: Optional[int], title: str, doc_type: str, text_content: str, notes: str = "") -> int:
        """사용자가 직접 입력한 텍스트를 문서 파일(.txt)로 저장하고 서류 보관함에 등록"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip()
        if not safe_title:
            safe_title = "직접작성기록"
        safe_filename = f"doc_{timestamp}_{safe_title}.txt"
        dest_path = os.path.join(self.docs_dir, safe_filename)

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(f"=== {title} ===\n")
            f.write(f"작성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"서류구분: {doc_type}\n")
            if notes:
                f.write(f"비고: {notes}\n")
            f.write("=" * 40 + "\n\n")
            f.write(text_content)

        file_size = os.path.getsize(dest_path)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO documents (client_id, title, doc_type, file_name, file_size, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (client_id, title, doc_type, safe_filename, file_size, notes))
            conn.commit()
            return cursor.lastrowid

    def get_document_full_path(self, file_name: str) -> str:
        """상대 파일명을 현재 PC의 절대 파일 경로로 변환"""
        # DB 값이 손상되거나 외부에서 조작되어도 documents 밖을 가리키지 않게 제한합니다.
        return os.path.join(self.docs_dir, os.path.basename(file_name or ""))

    def list_documents(self, client_id: Optional[int] = None, doc_type: str = "전체", keyword: str = "") -> List[Dict[str, Any]]:
        """서류 목록 조회 (대상자별, 구분별, 검색어별 필터링 지원)"""
        query = """
        SELECT d.*, c.name as client_name, c.masked_name 
        FROM documents d
        LEFT JOIN clients c ON d.client_id = c.id
        WHERE 1=1
        """
        params = []
        if client_id is not None:
            if client_id == -1:
                query += " AND (d.client_id IS NULL OR d.client_id = 0)"
            else:
                query += " AND d.client_id = ?"
                params.append(client_id)

        if doc_type and "전체" not in doc_type and not doc_type.startswith("["):
            query += " AND d.doc_type = ?"
            params.append(doc_type)

        if keyword:
            query += " AND (d.title LIKE ? OR d.notes LIKE ? OR c.name LIKE ? OR c.masked_name LIKE ?)"
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw])

        query += " ORDER BY d.id DESC"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["full_path"] = self.get_document_full_path(item.get("file_name", ""))
                results.append(item)
            return results

    def list_document_registry(self, client_id=None, doc_type='전체', keyword=''):
        """첨부 파일과 작성 서류를 원본 복제 없이 함께 조회한다."""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT d.id, d.client_id, d.title, d.doc_type, d.notes, COALESCE(NULLIF(d.updated_at, ''), d.created_at) AS created_at,
                       d.file_size, 'attachment' AS source_type, '' AS status
                FROM documents d
                UNION ALL
                SELECT id, client_id, source_key, '사례관리 서류', stage, updated_at,
                       0, 'case_form', status FROM case_form_records
                UNION ALL
                SELECT id, client_id, template_name, '상담일지', raw_memo, COALESCE(NULLIF(updated_at, ''), created_at),
                       0, 'counseling', '저장완료' FROM counseling_records
                ORDER BY created_at DESC, id DESC
            """).fetchall()
            clients = {row['id']: dict(row) for row in conn.execute('SELECT id, name, masked_name FROM clients')}
        result = []
        for row in rows:
            item = dict(row)
            client = clients.get(item['client_id'], {})
            item.update(client_name=client.get('name', ''), masked_name=client.get('masked_name', ''))
            if client_id == -1 and item['client_id']:
                continue
            if client_id not in (None, -1) and item['client_id'] != client_id:
                continue
            if doc_type and '전체' not in doc_type and not doc_type.startswith('[') and doc_type not in (item['doc_type'], item['title']):
                continue
            if keyword and keyword.casefold() not in ' '.join(str(item.get(k) or '') for k in ('title', 'notes', 'client_name', 'masked_name')).casefold():
                continue
            result.append(item)
        return result

    def update_attachment(self, doc_id, title, doc_type, notes='', text=None, replacement=None):
        if not title.strip():
            raise ValueError('서류 제목을 입력해 주세요.')
        if text is not None and replacement:
            raise ValueError('본문 수정과 파일 교체는 한 번에 하나만 선택하세요.')
        new_path = None
        try:
            with self.get_connection() as conn:
                row = conn.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
                if not row:
                    raise ValueError('삭제되었거나 존재하지 않는 서류입니다.')
                filename = row['file_name']
                size = row['file_size']
                if text is not None or replacement:
                    suffix = os.path.splitext(replacement or filename)[1]
                    if text is not None and suffix.lower() != '.txt':
                        raise ValueError('본문 수정은 TXT 파일만 지원합니다.')
                    filename = f'doc_{uuid.uuid4().hex}{suffix}'
                    new_path = self.get_document_full_path(filename)
                    if replacement:
                        shutil.copy2(replacement, new_path)
                    else:
                        with open(new_path, 'w', encoding='utf-8') as stream:
                            stream.write(text)
                    size = os.path.getsize(new_path)
                conn.execute('UPDATE documents SET title=?, doc_type=?, notes=?, file_name=?, file_size=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                             (title.strip(), doc_type, notes, filename, size, doc_id))
        except Exception:
            if new_path and os.path.isfile(new_path):
                os.remove(new_path)
            raise
        if new_path:
            old_path = os.path.realpath(self.get_document_full_path(row['file_name']))
            with self.get_connection() as conn:
                referenced = conn.execute('SELECT 1 FROM documents WHERE file_name=?', (row['file_name'],)).fetchone()
            if not referenced and os.path.commonpath([old_path, os.path.realpath(self.docs_dir)]) == os.path.realpath(self.docs_dir):
                try:
                    if os.path.isfile(old_path):
                        os.remove(old_path)
                except OSError:
                    pass  # 열려 있는 이전 파일은 남기되 저장된 새 본문은 유지한다.

    def update_counseling_content(self, record_id, owner_id, title, session_date, worker_name, content, html):
        if not title.strip() or not content.strip():
            raise ValueError('제목과 상담 내용을 입력해 주세요.')
        datetime.strptime(session_date, '%Y-%m-%d')
        with self.get_connection() as conn:
            cursor = conn.execute("""UPDATE counseling_records SET template_name=?, session_date=?,
                worker_name=?, ai_result=?, result_html=?, raw_memo=?, detail_level='직접수기작성', updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND (owner_id=? OR owner_id IS NULL)""",
                (title.strip(), session_date, worker_name, content, html, content, record_id, owner_id))
            if cursor.rowcount != 1:
                raise ValueError('본인이 작성한 상담일지만 수정할 수 있습니다. 이전 버전의 작성자 미지정 기록은 수정 가능합니다.')

    def delete_registered_document(self, source_type, record_id, owner_id):
        if source_type == 'attachment':
            return self.delete_document(record_id)
        if source_type not in ('case_form', 'counseling'):
            raise ValueError('알 수 없는 서류 종류입니다.')
        table = 'case_form_records' if source_type == 'case_form' else 'counseling_records'
        permission = 'owner_id=?' if source_type == 'case_form' else '(owner_id=? OR owner_id IS NULL)'
        with self.get_connection() as conn:
            cursor = conn.execute(f'DELETE FROM {table} WHERE id=? AND {permission}', (record_id, owner_id))
            if cursor.rowcount != 1:
                raise ValueError('본인이 작성한 서류만 삭제할 수 있거나 이미 삭제된 기록입니다.')
        return True

    def delete_document(self, doc_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_name FROM documents WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            if row:
                full_p = os.path.realpath(self.get_document_full_path(row["file_name"]))
                other = conn.execute('SELECT 1 FROM documents WHERE file_name=? AND id<>?', (row['file_name'], doc_id)).fetchone()
                if not other and os.path.isfile(full_p):
                    if os.path.commonpath([full_p, os.path.realpath(self.docs_dir)]) != os.path.realpath(self.docs_dir):
                        raise ValueError('서류 저장 폴더 밖의 파일은 삭제할 수 없습니다.')
                    os.remove(full_p)

            cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ================= [대시보드 통계] =================
    def get_dashboard_stats(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM clients")
            total_clients = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM clients WHERE risk_level LIKE '%고위기%'")
            high_risk_clients = cursor.fetchone()[0]

            current_month = datetime.now().strftime("%Y-%m")
            cursor.execute("SELECT COUNT(*) FROM counseling_records WHERE session_date LIKE ?", (f"{current_month}%",))
            monthly_counselings = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM counseling_records")
            total_counselings = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM documents")
            total_docs = cursor.fetchone()[0]
            cursor.execute('SELECT (SELECT COUNT(*) FROM case_form_records) + (SELECT COUNT(*) FROM counseling_records)')
            total_docs += cursor.fetchone()[0]

            today = datetime.now().strftime("%Y-%m-%d")
            next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            cursor.execute("""
                SELECT COUNT(*) FROM monitoring_tasks
                WHERE status != '완료' AND due_date < ?
            """, (today,))
            overdue_monitoring = cursor.fetchone()[0]
            cursor.execute("""
                SELECT COUNT(*) FROM monitoring_tasks
                WHERE status != '완료' AND due_date BETWEEN ? AND ?
            """, (today, next_week))
            upcoming_monitoring = cursor.fetchone()[0]

            cursor.execute("""
            SELECT r.*, c.name as client_name, c.masked_name, c.risk_level
            FROM counseling_records r
            LEFT JOIN clients c ON r.client_id = c.id
            ORDER BY r.session_date DESC, r.id DESC LIMIT 5
            """)
            recent_records = [dict(r) for r in cursor.fetchall()]

            return {
                "total_clients": total_clients,
                "high_risk_clients": high_risk_clients,
                "monthly_counselings": monthly_counselings,
                "total_counselings": total_counselings,
                "total_docs": total_docs,
                "overdue_monitoring": overdue_monitoring,
                "upcoming_monitoring": upcoming_monitoring,
                "recent_records": recent_records
            }

    # ================= [컴퓨터 이전용 원클릭 전체 압축 백업 & 복원] =================
    def create_full_backup_zip(self, export_zip_path: str) -> Tuple[bool, str]:
        """
        데이터베이스(DB)와 모든 첨부 서류(documents/), 메타데이터를
        단 하나의 압축 파일(.zip)로 묶어 내보냅니다.
        (Windows ⇄ Linux 민트 간 100% 호환되도록 표준 POSIX '/' 경로로 정규화)
        """
        try:
            import platform, sys
            if not os.path.exists(self.db_path):
                return False, f"데이터베이스 파일({self.db_path})을 찾을 수 없습니다."

            stats = self.get_dashboard_stats()
            current_os = "Windows" if sys.platform.startswith("win") else ("macOS" if sys.platform == "darwin" else "Linux")
            metadata = {
                "backup_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_clients": stats["total_clients"],
                "total_records": stats["total_counselings"],
                "total_docs": stats["total_docs"],
                "version": "1.2.0",
                "origin_os": current_os,
                "platform_details": f"{platform.system()} {platform.release()}",
                "cross_platform_compatible": True
            }

            # WAL 모드에서 원본 .db를 그대로 복사하면 최근 변경이 빠질 수 있습니다.
            # SQLite backup API로 일관된 스냅샷을 만든 뒤 압축합니다.
            with tempfile.TemporaryDirectory(prefix="welfare_backup_") as temp_dir:
                snapshot_path = os.path.join(temp_dir, "welfare_saas.db")
                with self.get_connection() as source, closing(sqlite3.connect(snapshot_path)) as target:
                    source.backup(target)

                with zipfile.ZipFile(export_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    zipf.writestr("backup_info.json", json.dumps(metadata, ensure_ascii=False, indent=2))
                    zipf.write(snapshot_path, arcname="welfare_saas.db")

                    if os.path.exists(self.docs_dir):
                        for root, _, files in os.walk(self.docs_dir):
                            for file in files:
                                abs_file_path = os.path.join(root, file)
                                rel_path = os.path.relpath(abs_file_path, self.data_dir)
                                normalized_arcname = rel_path.replace("\\", "/")
                                zipf.write(abs_file_path, arcname=normalized_arcname)

            return True, f"성공 ({current_os} 환경, 대상자 {stats['total_clients']}명, 서류 {stats['total_docs']}건)"
        except Exception as e:
            return False, f"압축 백업 실패: {str(e)}"

    @staticmethod
    def restore_from_backup_zip(src_zip_path: str, target_data_dir: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        백업 압축 파일(.zip)을 풀어서 데이터 폴더에 복원합니다.
        - 전체 백업(DB+서류)의 경우: 루트 또는 하위 폴더 어디에 있든 welfare_saas.db와 서류를 자동 탐지하여 복원.
        - 서류 전용 백업인 경우: 기존 DB를 유지하면서 서류 파일들을 documents 폴더로 안전하게 복원.
        - Windows ⇄ Linux 간 역슬래시/슬래시 차이 완벽 자동 정규화 지원.
        """
        try:
            if not os.path.exists(src_zip_path):
                return False, "백업 파일을 찾을 수 없습니다.", {}

            os.makedirs(target_data_dir, exist_ok=True)
            target_docs_dir = os.path.join(target_data_dir, "documents")
            os.makedirs(target_docs_dir, exist_ok=True)

            with zipfile.ZipFile(src_zip_path, "r") as zipf:
                # 압축을 풀기 전에 전체 경로를 먼저 검사해 기존 DB가 바뀌는 일을 막습니다.
                for info in zipf.infolist():
                    normalized = info.filename.replace("\\", "/")
                    parts = [part for part in normalized.split("/") if part]
                    if normalized.startswith("/") or ".." in parts:
                        return False, "백업에 안전하지 않은 파일 경로가 포함되어 복원을 중단했습니다.", {}

                # 1. 메타데이터 읽기
                meta = {}
                for info in zipf.infolist():
                    fname = info.filename.replace("\\", "/")
                    if fname.endswith("backup_info.json") or fname.endswith("서류_목록_안내.json"):
                        try:
                            meta = json.loads(zipf.read(info).decode("utf-8"))
                            break
                        except Exception:
                            pass

                # 2. DB 파일 탐색 (루트뿐만 아니라 하위 폴더 내 어디에 있든 감지)
                db_member = None
                for member in zipf.infolist():
                    norm_name = member.filename.replace("\\", "/")
                    if norm_name.endswith("welfare_saas.db"):
                        db_member = member
                        break

                if not db_member:
                    # 임의의 .db 파일 검색 (단, 임시 파일 제외)
                    for member in zipf.infolist():
                        norm_name = member.filename.replace("\\", "/")
                        bname = os.path.basename(norm_name)
                        if norm_name.endswith(".db") and not bname.startswith((".", "~", "_")):
                            db_member = member
                            break

                # [케이스 A: 전체 통합 백업 (DB 발견됨)]
                if db_member:
                    # 임시 파일에서 무결성을 확인한 뒤에만 기존 DB와 원자적으로 교체합니다.
                    dest_db_path = os.path.join(target_data_dir, "welfare_saas.db")
                    temp_handle, temp_db_path = tempfile.mkstemp(
                        prefix="welfare_restore_",
                        suffix=".db",
                        dir=target_data_dir,
                    )
                    os.close(temp_handle)
                    try:
                        with zipf.open(db_member) as source, open(temp_db_path, "wb") as target:
                            shutil.copyfileobj(source, target)
                        with closing(sqlite3.connect(temp_db_path)) as restored_db:
                            integrity = restored_db.execute("PRAGMA integrity_check").fetchone()[0]
                        if integrity != "ok":
                            return False, "백업 데이터베이스의 무결성 검사에 실패했습니다.", meta
                        os.replace(temp_db_path, dest_db_path)
                    except sqlite3.DatabaseError:
                        return False, "백업에 올바른 SQLite 데이터베이스가 포함되어 있지 않습니다.", meta
                    finally:
                        if os.path.exists(temp_db_path):
                            os.remove(temp_db_path)

                    # 서류 파일들 추출
                    for member in zipf.infolist():
                        if member == db_member or member.is_dir():
                            continue
                        norm_name = member.filename.replace("\\", "/")
                        if norm_name.endswith("backup_info.json") or norm_name.endswith("서류_목록_안내.json"):
                            continue

                        bname = os.path.basename(norm_name)
                        if not bname:
                            continue

                        # documents/ 경로 처리
                        if "documents/" in norm_name:
                            sub_path = norm_name.split("documents/", 1)[1]
                            dest_doc_path = os.path.join(target_docs_dir, *sub_path.split("/"))
                        elif "/" in norm_name:
                            # 폴더/파일명 형태 (예: 홍길동/초기면접지.hwp)
                            dest_doc_path = os.path.join(target_docs_dir, bname)
                        else:
                            dest_doc_path = os.path.join(target_docs_dir, bname)

                        docs_root = os.path.realpath(target_docs_dir)
                        resolved_dest = os.path.realpath(dest_doc_path)
                        if os.path.commonpath([docs_root, resolved_dest]) != docs_root:
                            return False, "백업에 안전하지 않은 파일 경로가 포함되어 복원을 중단했습니다.", meta

                        os.makedirs(os.path.dirname(resolved_dest), exist_ok=True)
                        with zipf.open(member) as source, open(dest_doc_path, "wb") as target:
                            target.write(source.read())

                    return True, "데이터베이스 및 서류 파일이 성공적으로 복원되었습니다.", meta

                # [케이스 B: 서류 전용 백업 (.zip)]
                doc_extensions = ('.hwp', '.hwpx', '.pdf', '.docx', '.xlsx', '.jpg', '.png', '.txt')
                has_docs = any(m.filename.lower().endswith(doc_extensions) for m in zipf.infolist())
                if "서류_목록_안내.json" in [m.filename.replace("\\", "/") for m in zipf.infolist()] or has_docs:
                    doc_count = 0
                    for member in zipf.infolist():
                        if member.is_dir():
                            continue
                        norm_name = member.filename.replace("\\", "/")
                        if norm_name.endswith(".json"):
                            continue

                        bname = os.path.basename(norm_name)
                        if not bname:
                            continue

                        dest_doc_path = os.path.join(target_docs_dir, bname)
                        with zipf.open(member) as source, open(dest_doc_path, "wb") as target:
                            target.write(source.read())
                        doc_count += 1

                    meta["is_documents_only"] = True
                    meta["total_docs"] = doc_count
                    return True, f"서류 전용 백업 파일에서 총 {doc_count}건의 서류 파일이 성공적으로 복원되었습니다.", meta

                # [케이스 C: 유효하지 않은 압축 파일]
                return False, "유효한 복지관 백업 파일이 아닙니다.\n(압축 파일 내에 welfare_saas.db 데이터베이스 또는 서류 파일이 없습니다.)", {}

        except Exception as e:
            return False, f"복원 중 오류 발생: {str(e)}", {}

    def export_documents_only_zip(self, export_zip_path: str, client_id: Optional[int] = None) -> Tuple[bool, str, int]:
        """
        등록된 모든 첨부 서류(HWP, PDF, 이미지 등)를 대상자별 폴더 구조로 정리하여
        단 하나의 압축 파일(*.zip)로 깔끔하게 내보냅니다.
        """
        try:
            import platform, sys
            current_os = "Windows" if sys.platform.startswith("win") else ("macOS" if sys.platform == "darwin" else "Linux")
            docs = self.list_documents(client_id=client_id)
            
            manifest = []
            count = 0
            with zipfile.ZipFile(export_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for d in docs:
                    fname = d.get("file_name", "")
                    if fname:
                        full_p = self.get_document_full_path(fname)
                        if os.path.exists(full_p):
                            c_name = d.get("client_name") or "기관일반"
                            # 안전한 파일명 처리
                            safe_title = "".join(c for c in d.get("title", "서류") if c.isalnum() or c in (' ', '_', '-', '(', ')', '[', ']')).strip()
                            ext = os.path.splitext(fname)[1]
                            
                            # 대상자별 폴더/구분_제목.확장자 형태로 깔끔하게 저장
                            arc_filename = f"{c_name}/{d.get('doc_type', '기타')}_{safe_title}{ext}"
                            arc_filename = arc_filename.replace("\\", "/")
                            
                            zipf.write(full_p, arcname=arc_filename)
                            count += 1
                            manifest.append({
                                "id": d["id"],
                                "client_name": c_name,
                                "doc_type": d.get("doc_type"),
                                "title": d.get("title"),
                                "stored_path": arc_filename,
                                "created_at": d.get("created_at")
                            })

                # 안내 색인 파일(서류_목록_안내.json) 동봉
                meta = {
                    "backup_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "exported_os": current_os,
                    "total_documents": count,
                    "documents": manifest
                }
                zipf.writestr("서류_목록_안내.json", json.dumps(meta, ensure_ascii=False, indent=2))

            return True, f"성공 (총 {count}건의 서류 파일 압축 완료)", count
        except Exception as e:
            return False, f"서류 백업 실패: {str(e)}", 0
