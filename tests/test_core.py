import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from anonymizer import Anonymizer
from database import Database
from form_document import build_form_html, fill_form_html, inject_approval_line
from prompts import TEMPLATES


class AnonymizerTests(unittest.TestCase):
    def test_masks_common_personal_information(self):
        text = "홍길동 800101-1234567, 010-1234-5678로 연락"
        masked, stats = Anonymizer().anonymize(text, client_name="홍길동")

        self.assertNotIn("홍길동", masked)
        self.assertNotIn("1234567", masked)
        self.assertNotIn("1234-5678", masked)
        self.assertEqual(stats["성명"], 1)
        self.assertEqual(stats["주민번호"], 1)
        self.assertEqual(stats["연락처"], 1)


class FormDocumentTests(unittest.TestCase):
    def test_builds_table_form_and_places_generated_sections_in_cells(self):
        guide = """[출력 양식]
### [가정방문 기록지]
1. **방문 목적**:
2. **상담 내용**:
3. **향후 계획**:
"""
        form_html = build_form_html("가정방문", guide)
        completed = fill_form_html(
            form_html,
            metadata={"대상자명": "김OO님", "상담일자": "2026-09-04", "작성자": "박복지사"},
            generated_text="""### [가정방문 기록지]
1. **방문 목적**: 정기 안부 확인
2. **상담 내용**: 식사와 복약 상태를 확인함
3. **향후 계획**: 다음 주 재방문 예정
""",
        )

        self.assertIn("<table", completed)
        self.assertIn("김OO님", completed)
        self.assertIn("식사와 복약 상태를 확인함", completed)
        self.assertNotIn("{{상담 내용}}", completed)

    def test_injects_custom_approval_line_before_document_title(self):
        form_html = build_form_html("상담일지", "### [상담일지]\n1. **상담 내용**:")
        completed = inject_approval_line(form_html, [
            {"title": "담당", "name": "박복지"},
            {"title": "팀장", "name": "김팀장"},
            {"title": "국장", "name": ""},
        ])

        self.assertIn("결재", completed)
        self.assertIn("김팀장", completed)
        self.assertLess(completed.index("approval-line"), completed.index("<h2"))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dashboard_returns_recent_ai_result_and_totals(self):
        client_id = self.db.add_client({"name": "김복지", "risk_level": "고위기"})
        self.db.add_counseling_record({
            "client_id": client_id,
            "session_date": "2026-09-03",
            "template_name": "일반 상담일지",
            "ai_result": "식사 지원 상태를 확인하고 다음 방문을 계획함",
        })

        stats = self.db.get_dashboard_stats()

        self.assertEqual(stats["total_clients"], 1)
        self.assertEqual(stats["high_risk_clients"], 1)
        self.assertEqual(stats["total_counselings"], 1)
        self.assertEqual(stats["recent_records"][0]["ai_result"], "식사 지원 상태를 확인하고 다음 방문을 계획함")

    def test_case_management_workflow(self):
        client_id = self.db.add_client({"name": "사례대상"})

        self.db.save_case_profile(client_id, "개입", "식생활 지원 진행 중")
        profile = self.db.get_case_profile(client_id)
        self.assertEqual(profile["stage"], "개입")

        self.db.add_assessment(client_id, {"경제": 2, "건강": 3}, "건강 위험 우선 개입")
        assessment = self.db.list_assessments(client_id)[0]
        self.assertEqual(assessment["scores"]["건강"], 3)

        goal_id = self.db.add_goal(client_id, "식사 안정", "밑반찬 서비스 연계", "2026-10-01")
        self.db.update_goal_progress(goal_id, 50, "진행")
        self.assertEqual(self.db.list_goals(client_id)[0]["progress"], 50)

        task_id = self.db.add_monitoring_task(client_id, "전화 확인", "2026-09-10", "서비스 수령 확인")
        stats = self.db.get_dashboard_stats()
        self.assertIn("overdue_monitoring", stats)
        self.assertIn("upcoming_monitoring", stats)
        self.db.complete_monitoring_task(task_id)
        self.assertEqual(self.db.list_monitoring_tasks(client_id)[0]["status"], "완료")

        resource_id = self.db.add_resource("원주 푸드뱅크", "생계", "033-000-0000", "식품 지원")
        link_id = self.db.add_service_link(client_id, resource_id, "밑반찬 지원", "2026-09-03")
        self.db.update_service_link_status(link_id, "제공 중", "주 2회 제공")
        service = self.db.list_service_links(client_id)[0]
        self.assertEqual(service["resource_name"], "원주 푸드뱅크")
        self.assertEqual(service["status"], "제공 중")

    def test_search_counseling_records_by_client_template_and_period(self):
        first_client = self.db.add_client({"name": "조회대상"})
        second_client = self.db.add_client({"name": "다른대상"})
        for client_id, date, template, content in (
            (first_client, "2026-01-10", "전화 상담", "첫 번째"),
            (first_client, "2026-02-15", "가정방문", "두 번째"),
            (first_client, "2026-03-20", "전화 상담", "세 번째"),
            (second_client, "2026-02-20", "전화 상담", "다른 대상 기록"),
        ):
            self.db.add_counseling_record({
                "client_id": client_id,
                "session_date": date,
                "template_name": template,
                "ai_result": content,
            })

        records = self.db.search_counseling_records(
            client_id=first_client,
            template_name="전화 상담",
            date_from="2026-01-01",
            date_to="2026-02-28",
        )

        self.assertEqual([record["ai_result"] for record in records], ["첫 번째"])
        self.assertIn("전화 상담", self.db.list_counseling_templates())

    def test_user_templates_are_personal_copies_and_record_keeps_snapshot(self):
        first_profile = self.db.get_current_profile()
        self.db.ensure_builtin_templates(first_profile["id"], TEMPLATES)
        first_templates = self.db.list_form_templates(first_profile["id"])
        self.assertEqual(len(first_templates), len(TEMPLATES))
        self.assertTrue(all("<table" in item["form_html"] for item in first_templates))

        second_profile_id = self.db.create_profile("박복지사")
        self.db.ensure_builtin_templates(second_profile_id, TEMPLATES)
        second_templates = self.db.list_form_templates(second_profile_id)
        self.db.save_approval_line(first_profile["id"], [
            {"title": "담당", "name": "첫 사용자"},
            {"title": "부장", "name": ""},
        ])
        self.assertEqual([step["title"] for step in self.db.get_approval_line(first_profile["id"])], ["담당", "부장"])
        self.assertEqual([step["title"] for step in self.db.get_approval_line(second_profile_id)], ["담당", "팀장", "관장"])

        first_general = next(
            item for item in first_templates if item["source_key"] == "상담일지 (사례관리양식)"
        )
        second_general = next(
            item for item in second_templates if item["source_key"] == "상담일지 (사례관리양식)"
        )
        self.db.save_form_template(first_profile["id"], {
            **first_general,
            "description": "첫 사용자만 수정한 설명",
        }, template_id=first_general["id"])

        self.assertEqual(
            self.db.get_form_template(first_general["id"], first_profile["id"])["description"],
            "첫 사용자만 수정한 설명",
        )
        self.assertNotEqual(
            self.db.get_form_template(second_general["id"], second_profile_id)["description"],
            "첫 사용자만 수정한 설명",
        )

        snapshot = self.db.make_template_snapshot(
            self.db.get_form_template(first_general["id"], first_profile["id"])
        )
        record_id = self.db.add_counseling_record({
            "template_name": snapshot["name"],
            "template_id": snapshot["id"],
            "template_snapshot": snapshot,
            "owner_id": first_profile["id"],
            "ai_result": "작성 결과",
        })
        record = next(item for item in self.db.list_counseling_records() if item["id"] == record_id)
        self.assertIn("첫 사용자만 수정한 설명", record["template_snapshot"])
        self.assertEqual(record["owner_id"], first_profile["id"])

    def test_full_backup_contains_readable_database_snapshot(self):
        self.db.add_client({"name": "이상담"})
        backup_path = os.path.join(self.temp_dir.name, "backup.zip")

        ok, message = self.db.create_full_backup_zip(backup_path)

        self.assertTrue(ok, message)
        with tempfile.TemporaryDirectory() as extract_dir, zipfile.ZipFile(backup_path) as archive:
            archive.extract("welfare_saas.db", extract_dir)
            snapshot = os.path.join(extract_dir, "welfare_saas.db")
            with closing(sqlite3.connect(snapshot)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        self.assertEqual(count, 1)

    def test_restore_rejects_path_traversal(self):
        archive_path = os.path.join(self.temp_dir.name, "unsafe.zip")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("welfare_saas.db", b"not-a-real-db")
            archive.writestr("documents/../../outside.txt", "unsafe")

        with tempfile.TemporaryDirectory() as restore_dir:
            ok, message, _ = Database.restore_from_backup_zip(archive_path, restore_dir)
            self.assertFalse(ok)
            self.assertIn("안전하지 않은", message)
            self.assertFalse(os.path.exists(os.path.join(restore_dir, "..", "outside.txt")))

    def test_restore_rejects_invalid_database_without_overwriting_current_data(self):
        archive_path = os.path.join(self.temp_dir.name, "invalid-db.zip")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("welfare_saas.db", b"not-a-real-db")

        current_id = self.db.add_client({"name": "보존대상"})
        ok, message, _ = Database.restore_from_backup_zip(archive_path, self.temp_dir.name)

        self.assertFalse(ok)
        self.assertIn("SQLite", message)
        self.assertEqual(self.db.get_client(current_id)["name"], "보존대상")

    def test_existing_database_is_migrated_for_personal_templates(self):
        with tempfile.TemporaryDirectory() as old_data_dir:
            old_db_path = os.path.join(old_data_dir, "welfare_saas.db")
            with closing(sqlite3.connect(old_db_path)) as conn:
                conn.execute("""
                    CREATE TABLE counseling_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id INTEGER,
                        session_date TEXT NOT NULL,
                        template_name TEXT NOT NULL,
                        detail_level TEXT DEFAULT '표준',
                        raw_memo TEXT,
                        ai_result TEXT NOT NULL,
                        worker_name TEXT DEFAULT '담당복지사',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    INSERT INTO counseling_records (session_date, template_name, ai_result)
                    VALUES ('2026-09-01', '기존 양식', '기존 기록')
                """)
                conn.commit()

            migrated = Database(old_data_dir)
            with migrated.get_connection() as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(counseling_records)")}
                profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(worker_profiles)")}
                record = conn.execute("SELECT * FROM counseling_records").fetchone()

            self.assertTrue(
                {"template_id", "template_snapshot", "owner_id", "result_html"}.issubset(columns)
            )
            self.assertEqual(record["ai_result"], "기존 기록")
            self.assertIsNotNone(record["owner_id"])
            self.assertIn("approval_line_json", profile_columns)


if __name__ == "__main__":
    unittest.main()
