import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, SkillNode
from backend.routers import quiz


class QuizApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        app = FastAPI()
        app.include_router(quiz.router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[quiz.get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.engine.dispose()

    def add_node(self, node_id="node-1", name="Linear Regression"):
        db = self.SessionLocal()
        try:
            db.add(
                SkillNode(
                    id=node_id,
                    name=name,
                    description="A supervised learning method for predicting continuous values.",
                    parent_ids=[],
                    doc_id="doc-1",
                    status="available",
                    mastery=0,
                )
            )
            db.commit()
        finally:
            db.close()

    def test_generate_node_returns_200_and_stable_structure(self):
        self.add_node()

        response = self.client.post(
            "/api/quiz/generate-node/node-1",
            json={"num_questions": 3, "question_type": "multiple_choice"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["node_id"], "node-1")
        self.assertEqual(data["title"], "Linear Regression")
        self.assertEqual(data["num_questions"], 3)
        self.assertEqual(data["question_type"], "multiple_choice")
        self.assertTrue(data["fallback"])
        self.assertEqual(len(data["questions"]), 3)
        self.assertEqual(data["questions"][0]["id"], "q1")

    def test_generate_node_missing_node_returns_404(self):
        response = self.client.post(
            "/api/quiz/generate-node/missing-node",
            json={"num_questions": 3, "question_type": "multiple_choice"},
        )

        self.assertEqual(response.status_code, 404)

    def test_generate_node_rejects_zero_questions(self):
        self.add_node()

        response = self.client.post(
            "/api/quiz/generate-node/node-1",
            json={"num_questions": 0, "question_type": "multiple_choice"},
        )

        self.assertEqual(response.status_code, 422)

    def test_generate_node_rejects_too_many_questions(self):
        self.add_node()

        response = self.client.post(
            "/api/quiz/generate-node/node-1",
            json={"num_questions": 21, "question_type": "multiple_choice"},
        )

        self.assertEqual(response.status_code, 422)

    def test_generate_node_rejects_bad_question_type(self):
        self.add_node()

        response = self.client.post(
            "/api/quiz/generate-node/node-1",
            json={"num_questions": 3, "question_type": "bad_type"},
        )

        self.assertEqual(response.status_code, 422)

    def test_generate_node_helper_error_returns_502(self):
        self.add_node()

        async def failing_generator(node, num_questions, question_type):
            raise RuntimeError("external failure should not leak")

        with mock.patch("backend.routers.quiz.generate_node_questions", failing_generator):
            response = self.client.post(
                "/api/quiz/generate-node/node-1",
                json={"num_questions": 3, "question_type": "multiple_choice"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Failed to generate quiz"})
        self.assertNotIn("external failure should not leak", str(response.json()))

    def test_submit_scores_answers(self):
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
        self.assertEqual(
            set(response.json().keys()),
            {"score", "correct_count", "total", "results"},
        )
        self.assertEqual(response.json()["score"], 50.0)
        self.assertEqual(response.json()["correct_count"], 1)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(len(response.json()["results"]), 2)
        self.assertTrue(response.json()["results"][0]["is_correct"])
        self.assertFalse(response.json()["results"][1]["is_correct"])

    def test_submit_rejects_empty_answers(self):
        response = self.client.post("/api/quiz/submit", json={"answers": []})

        self.assertIn(response.status_code, (400, 422))

    def test_submit_rejects_missing_question_id(self):
        response = self.client.post(
            "/api/quiz/submit",
            json={"answers": [{"answer": "A", "correct_answer": "A"}]},
        )

        self.assertIn(response.status_code, (400, 422))

    def test_submit_rejects_missing_answer(self):
        response = self.client.post(
            "/api/quiz/submit",
            json={"answers": [{"question_id": "q1", "correct_answer": "A"}]},
        )

        self.assertIn(response.status_code, (400, 422))

    def test_new_quiz_endpoints_do_not_call_lightrag(self):
        self.add_node()

        with mock.patch.object(quiz.lightrag_client, "query", side_effect=AssertionError("LightRAG called")):
            generate_response = self.client.post(
                "/api/quiz/generate-node/node-1",
                json={"num_questions": 1, "question_type": "short_answer"},
            )
            submit_response = self.client.post(
                "/api/quiz/submit",
                json={"answers": [{"question_id": "q1", "answer": "A", "correct_answer": "A"}]},
            )

        self.assertEqual(generate_response.status_code, 200)
        self.assertEqual(submit_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
