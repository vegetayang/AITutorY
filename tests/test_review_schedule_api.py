from datetime import datetime, timedelta
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, ReviewSchedule, SkillNode
from backend.routers import review


class ReviewScheduleApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        app = FastAPI()
        app.include_router(review.router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[review.get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.engine.dispose()

    def add_node(self, node_id="node-1", status="learning", mastery=42.0):
        db = self.SessionLocal()
        try:
            db.add(
                SkillNode(
                    id=node_id,
                    name="Review Topic",
                    description="A topic for review scheduling.",
                    parent_ids=[],
                    doc_id="doc-1",
                    status=status,
                    mastery=mastery,
                )
            )
            db.commit()
        finally:
            db.close()

    def add_schedule(
        self,
        node_id="node-1",
        next_review_at=None,
        last_reviewed_at=None,
        interval_days=1,
        review_count=0,
        ease_factor=2.5,
        last_score=None,
    ):
        now = datetime(2026, 6, 26, 12, 0, 0)
        db = self.SessionLocal()
        try:
            schedule = ReviewSchedule(
                id=f"schedule-{node_id}",
                node_id=node_id,
                interval_days=interval_days,
                ease_factor=ease_factor,
                review_count=review_count,
                last_score=last_score,
                last_reviewed_at=last_reviewed_at,
                next_review_at=next_review_at or (now + timedelta(days=1)),
                created_at=now,
                updated_at=now,
            )
            db.add(schedule)
            db.commit()
        finally:
            db.close()

    def get_node(self, node_id="node-1"):
        db = self.SessionLocal()
        try:
            return db.query(SkillNode).filter(SkillNode.id == node_id).first()
        finally:
            db.close()

    def test_init_missing_node_returns_404(self):
        response = self.client.post("/api/review/missing-node/init")

        self.assertEqual(response.status_code, 404)

    def test_init_existing_node_returns_200(self):
        self.add_node()

        response = self.client.post("/api/review/node-1/init")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["node_id"], "node-1")
        self.assertEqual(response.json()["interval_days"], 1)
        self.assertEqual(response.json()["ease_factor"], 2.5)
        self.assertEqual(response.json()["review_count"], 0)

    def test_init_is_idempotent(self):
        self.add_node()

        first = self.client.post("/api/review/node-1/init")
        second = self.client.post("/api/review/node-1/init")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["node_id"], second.json()["node_id"])
        self.assertEqual(second.json()["review_count"], 0)

    def test_record_missing_node_returns_404(self):
        response = self.client.post("/api/review/missing-node/record", json={"score": 80})

        self.assertEqual(response.status_code, 404)

    def test_record_rejects_score_below_zero(self):
        self.add_node()

        response = self.client.post("/api/review/node-1/record", json={"score": -1})

        self.assertEqual(response.status_code, 422)

    def test_record_rejects_score_above_100(self):
        self.add_node()

        response = self.client.post("/api/review/node-1/record", json={"score": 101})

        self.assertEqual(response.status_code, 422)

    def test_record_updates_review_count_score_and_next_review_at(self):
        self.add_node()
        reviewed_at = "2026-06-26T12:00:00"

        response = self.client.post(
            "/api/review/node-1/record",
            json={"score": 90, "reviewed_at": reviewed_at},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["review_count"], 1)
        self.assertEqual(data["last_score"], 90)
        self.assertEqual(data["interval_days"], 2)
        self.assertEqual(data["last_reviewed_at"], reviewed_at)
        self.assertEqual(data["next_review_at"], "2026-06-28T12:00:00")

    def test_record_auto_creates_schedule_when_missing(self):
        self.add_node()

        response = self.client.post(
            "/api/review/node-1/record",
            json={"score": 70, "reviewed_at": "2026-06-26T12:00:00"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["node_id"], "node-1")
        self.assertEqual(response.json()["review_count"], 1)

    def test_get_schedule_missing_node_returns_404(self):
        response = self.client.get("/api/review/missing-node")

        self.assertEqual(response.status_code, 404)

    def test_get_schedule_missing_schedule_returns_stable_404(self):
        self.add_node()

        response = self.client.get("/api/review/node-1")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Review schedule not found"})

    def test_due_list_returns_due_items(self):
        self.add_node("due-node")
        self.add_node("future-node")
        self.add_schedule("due-node", next_review_at=datetime(2026, 6, 26, 10, 0, 0))
        self.add_schedule("future-node", next_review_at=datetime(2026, 6, 28, 10, 0, 0))

        response = self.client.get("/api/review/due", params={"as_of": "2026-06-26T12:00:00"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["node_id"], "due-node")

    def test_due_list_validates_limit_and_offset(self):
        limit_response = self.client.get("/api/review/due", params={"limit": 0})
        offset_response = self.client.get("/api/review/due", params={"offset": -1})

        self.assertEqual(limit_response.status_code, 422)
        self.assertEqual(offset_response.status_code, 422)

    def test_curve_returns_points(self):
        self.add_node()
        self.add_schedule(
            "node-1",
            interval_days=2,
            last_reviewed_at=datetime(2026, 6, 26, 12, 0, 0),
            next_review_at=datetime(2026, 6, 28, 12, 0, 0),
        )

        response = self.client.get("/api/review/node-1/curve", params={"days": 3})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["node_id"], "node-1")
        self.assertEqual(data["interval_days"], 2)
        self.assertEqual(len(data["points"]), 4)
        self.assertEqual(data["points"][0]["retention"], 100.0)
        self.assertLess(data["points"][1]["retention"], data["points"][0]["retention"])

    def test_curve_rejects_zero_days(self):
        self.add_node()
        self.add_schedule("node-1")

        response = self.client.get("/api/review/node-1/curve", params={"days": 0})

        self.assertEqual(response.status_code, 422)

    def test_curve_rejects_days_above_90(self):
        self.add_node()
        self.add_schedule("node-1")

        response = self.client.get("/api/review/node-1/curve", params={"days": 91})

        self.assertEqual(response.status_code, 422)

    def test_record_does_not_update_skill_node_mastery(self):
        self.add_node(mastery=37.0)

        response = self.client.post(
            "/api/review/node-1/record",
            json={"score": 100, "reviewed_at": "2026-06-26T12:00:00"},
        )
        node = self.get_node()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(node.mastery, 37.0)

    def test_record_does_not_update_skill_node_status(self):
        self.add_node(status="learning")

        response = self.client.post(
            "/api/review/node-1/record",
            json={"score": 100, "reviewed_at": "2026-06-26T12:00:00"},
        )
        node = self.get_node()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(node.status, "learning")


if __name__ == "__main__":
    unittest.main()
