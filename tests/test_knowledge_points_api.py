import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, SkillNode
from backend.routers import knowledge_points


class KnowledgePointsApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        app = FastAPI()
        app.include_router(knowledge_points.router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[knowledge_points.get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.engine.dispose()

    def add_node(
        self,
        node_id,
        name,
        status="available",
        mastery=0.0,
        doc_id="doc-1",
        parent_ids=None,
        description="description",
    ):
        db = self.SessionLocal()
        try:
            db.add(
                SkillNode(
                    id=node_id,
                    name=name,
                    description=description,
                    parent_ids=parent_ids or [],
                    doc_id=doc_id,
                    status=status,
                    mastery=mastery,
                )
            )
            db.commit()
        finally:
            db.close()

    def test_list_returns_expected_structure(self):
        self.add_node("node-1", "Intro", mastery=70)

        response = self.client.get("/api/knowledge-points")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["limit"], 100)
        self.assertEqual(data["offset"], 0)
        self.assertIn("items", data)
        item = data["items"][0]
        self.assertEqual(
            set(item.keys()),
            {"id", "title", "description", "status", "mastery", "level", "doc_id"},
        )
        self.assertEqual(item["title"], "Intro")

    def test_list_supports_status_filter(self):
        self.add_node("node-1", "Available", status="available")
        self.add_node("node-2", "Completed", status="completed")

        response = self.client.get("/api/knowledge-points", params={"status": "available"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["id"], "node-1")
        self.assertEqual(data["items"][0]["status"], "available")

    def test_list_supports_doc_id_filter(self):
        self.add_node("node-1", "Doc One", doc_id="doc-1")
        self.add_node("node-2", "Doc Two", doc_id="doc-2")

        response = self.client.get("/api/knowledge-points", params={"doc_id": "doc-2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["doc_id"], "doc-2")

    def test_list_supports_level_filter(self):
        self.add_node("node-1", "Root")
        self.add_node("node-2", "Child", parent_ids=["node-1"])

        response = self.client.get("/api/knowledge-points", params={"level": 1})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["id"], "node-1")
        self.assertEqual(data["items"][0]["level"], 1)

    def test_list_empty_data_returns_stable_structure(self):
        response = self.client.get("/api/knowledge-points", params={"doc_id": "missing-doc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"items": [], "total": 0, "limit": 100, "offset": 0},
        )

    def test_detail_missing_node_returns_404(self):
        response = self.client.get("/api/knowledge-points/missing-node")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Knowledge point not found")

    def test_detail_returns_prerequisites_and_dependents(self):
        self.add_node("node-1", "Root")
        self.add_node("node-2", "Child", parent_ids=["node-1"])
        self.add_node("node-3", "Grandchild", parent_ids=["node-2"])

        response = self.client.get("/api/knowledge-points/node-2")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["prerequisites"], [{"id": "node-1", "title": "Root"}])
        self.assertEqual(data["dependents"], [{"id": "node-3", "title": "Grandchild"}])

    def test_status_patch_updates_legal_status(self):
        self.add_node("node-1", "Intro", status="available", mastery=35)

        response = self.client.patch("/api/knowledge-points/node-1/status", json={"status": "learning"})
        detail_response = self.client.get("/api/knowledge-points/node-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "learning")
        self.assertEqual(response.json()["mastery"], 35)
        self.assertEqual(detail_response.json()["status"], "learning")

    def test_status_patch_rejects_invalid_status(self):
        self.add_node("node-1", "Intro")

        response = self.client.patch("/api/knowledge-points/node-1/status", json={"status": "invalid"})

        self.assertEqual(response.status_code, 422)

    def test_summary_returns_description_as_summary(self):
        self.add_node("node-1", "Intro", description="Short summary", mastery=65)

        response = self.client.get("/api/knowledge-points/node-1/summary")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": "node-1",
                "title": "Intro",
                "summary": "Short summary",
                "status": "available",
                "mastery": 65,
            },
        )

    def test_invalid_parent_ids_do_not_break_detail(self):
        self.add_node("node-1", "Intro", parent_ids="not-json,")

        response = self.client.get("/api/knowledge-points/node-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prerequisites"], [])
        self.assertEqual(response.json()["dependents"], [])


if __name__ == "__main__":
    unittest.main()
