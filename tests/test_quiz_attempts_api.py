import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, QuizAttempt, SkillNode
from backend.routers import quiz, quiz_attempts


class QuizAttemptsApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        app = FastAPI()
        app.include_router(quiz_attempts.router)
        app.include_router(quiz.router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[quiz_attempts.get_db] = override_get_db
        app.dependency_overrides[quiz.get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.engine.dispose()

    def add_node(self, node_id="node-1", status="learning", mastery=42.0):
        db = self.SessionLocal()
        try:
            db.add(
                SkillNode(
                    id=node_id,
                    name=f"Topic {node_id}",
                    description="A topic for quiz attempts.",
                    parent_ids=[],
                    doc_id="doc-1",
                    status=status,
                    mastery=mastery,
                )
            )
            db.commit()
        finally:
            db.close()

    def get_node(self, node_id="node-1"):
        db = self.SessionLocal()
        try:
            return db.query(SkillNode).filter(SkillNode.id == node_id).first()
        finally:
            db.close()

    def valid_payload(self, node_id="node-1", question_id_prefix="q"):
        return {
            "node_id": node_id,
            "question_type": "multiple_choice",
            "score": 50.0,
            "correct_count": 1,
            "total": 2,
            "results": [
                {
                    "question_id": f"{question_id_prefix}1",
                    "question": "Question 1",
                    "user_answer": "A",
                    "correct_answer": "A",
                    "is_correct": True,
                    "explanation": "Correct.",
                },
                {
                    "question_id": f"{question_id_prefix}2",
                    "question": "Question 2",
                    "user_answer": "B",
                    "correct_answer": "A",
                    "is_correct": False,
                    "explanation": "A is correct.",
                },
            ],
        }

    def create_attempt(self, node_id="node-1", question_id_prefix="q"):
        response = self.client.post(
            "/api/quiz/attempts",
            json=self.valid_payload(node_id=node_id, question_id_prefix=question_id_prefix),
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_create_attempt_missing_node_returns_404(self):
        response = self.client.post("/api/quiz/attempts", json=self.valid_payload())

        self.assertEqual(response.status_code, 404)

    def test_create_attempt_success(self):
        self.add_node()

        response = self.client.post("/api/quiz/attempts", json=self.valid_payload())

        self.assertIn(response.status_code, (200, 201))
        data = response.json()
        self.assertEqual(data["node_id"], "node-1")
        self.assertEqual(data["score"], 50.0)
        self.assertEqual(data["correct_count"], 1)
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)
        self.assertFalse(data["items"][1]["is_correct"])

    def test_create_attempt_rejects_score_below_zero(self):
        self.add_node()
        payload = self.valid_payload()
        payload["score"] = -1

        response = self.client.post("/api/quiz/attempts", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_attempt_rejects_score_above_100(self):
        self.add_node()
        payload = self.valid_payload()
        payload["score"] = 101

        response = self.client.post("/api/quiz/attempts", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_attempt_rejects_non_positive_total(self):
        self.add_node()
        payload = self.valid_payload()
        payload["total"] = 0

        response = self.client.post("/api/quiz/attempts", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_attempt_rejects_negative_correct_count(self):
        self.add_node()
        payload = self.valid_payload()
        payload["correct_count"] = -1

        response = self.client.post("/api/quiz/attempts", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_attempt_rejects_correct_count_above_total(self):
        self.add_node()
        payload = self.valid_payload()
        payload["correct_count"] = 3

        response = self.client.post("/api/quiz/attempts", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_attempt_rejects_empty_results(self):
        self.add_node()
        payload = self.valid_payload()
        payload["results"] = []

        response = self.client.post("/api/quiz/attempts", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_list_attempts_success(self):
        self.add_node()
        self.create_attempt()

        response = self.client.get("/api/quiz/attempts")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["node_id"], "node-1")

    def test_list_attempts_filters_by_node_id(self):
        self.add_node("node-1")
        self.add_node("node-2")
        self.create_attempt("node-1", "a")
        self.create_attempt("node-2", "b")

        response = self.client.get("/api/quiz/attempts", params={"node_id": "node-2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["node_id"], "node-2")

    def test_list_attempts_validates_limit_and_offset(self):
        limit_response = self.client.get("/api/quiz/attempts", params={"limit": 0})
        offset_response = self.client.get("/api/quiz/attempts", params={"offset": -1})

        self.assertEqual(limit_response.status_code, 422)
        self.assertEqual(offset_response.status_code, 422)

    def test_get_attempt_detail_success(self):
        self.add_node()
        created = self.create_attempt()

        response = self.client.get(f"/api/quiz/attempts/{created['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])
        self.assertEqual(len(response.json()["items"]), 2)
        self.assertEqual(response.json()["items"][0]["question"], "Question 1")

    def test_get_missing_attempt_returns_404(self):
        response = self.client.get("/api/quiz/attempts/not-exists")

        self.assertEqual(response.status_code, 404)

    def test_wrong_questions_only_returns_incorrect_items(self):
        self.add_node()
        self.create_attempt()

        response = self.client.get("/api/quiz/wrong-questions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        item = response.json()["items"][0]
        self.assertEqual(item["question_id"], "q2")
        self.assertEqual(item["user_answer"], "B")
        self.assertEqual(item["correct_answer"], "A")

    def test_wrong_questions_filters_by_node_id(self):
        self.add_node("node-1")
        self.add_node("node-2")
        self.create_attempt("node-1", "a")
        self.create_attempt("node-2", "b")

        response = self.client.get("/api/quiz/wrong-questions", params={"node_id": "node-2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["node_id"], "node-2")
        self.assertEqual(response.json()["items"][0]["question_id"], "b2")

    def test_create_attempt_does_not_update_skill_node_mastery(self):
        self.add_node(mastery=37.0)

        response = self.client.post("/api/quiz/attempts", json=self.valid_payload())
        node = self.get_node()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(node.mastery, 37.0)

    def test_create_attempt_does_not_update_skill_node_status(self):
        self.add_node(status="available")

        response = self.client.post("/api/quiz/attempts", json=self.valid_payload())
        node = self.get_node()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(node.status, "available")

    def test_existing_quiz_submit_behavior_is_unchanged(self):
        response = self.client.post(
            "/api/quiz/submit",
            json={
                "answers": [
                    {"question_id": "q1", "answer": "A", "correct_answer": "A"},
                    {"question_id": "q2", "answer": "B", "correct_answer": "A"},
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["score"], 50.0)
        self.assertEqual(response.json()["correct_count"], 1)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(len(response.json()["results"]), 2)


if __name__ == "__main__":
    unittest.main()
