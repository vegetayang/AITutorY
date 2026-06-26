import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, SkillNode
from backend.routers import skill_tree


class KnowledgeTreeApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        app = FastAPI()
        app.include_router(skill_tree.router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[skill_tree.get_db] = override_get_db
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

    def test_graph_returns_nodes_and_edges_fields(self):
        self.add_node("node-1", "Root", status="completed", mastery=80)
        self.add_node("node-2", "Child", status="available", mastery=20, parent_ids=["node-1"])

        response = self.client.get("/api/skill-tree/graph")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["nodes"]), 2)
        self.assertEqual(
            data["edges"],
            [{"source": "node-1", "target": "node-2", "type": "prerequisite"}],
        )
        child = next(node for node in data["nodes"] if node["id"] == "node-2")
        self.assertEqual(child["title"], "Child")
        self.assertEqual(child["level"], 2)

    def test_graph_supports_status_filter(self):
        self.add_node("node-1", "Completed", status="completed", mastery=80)
        self.add_node("node-2", "Available", status="available", mastery=20, parent_ids=["node-1"])

        response = self.client.get("/api/skill-tree/graph", params={"status": "available"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([node["id"] for node in data["nodes"]], ["node-2"])
        self.assertEqual(data["edges"], [])

    def test_stats_returns_correct_counts(self):
        self.add_node("node-1", "Completed", status="completed", mastery=90, doc_id="doc-1")
        self.add_node("node-2", "Learning", status="learning", mastery=50, doc_id="doc-1")
        self.add_node("node-3", "Available", status="available", mastery=10, doc_id="doc-1")
        self.add_node("node-4", "Locked", status="locked", mastery=0, doc_id="doc-2")

        response = self.client.get("/api/skill-tree/stats", params={"doc_id": "doc-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "total_nodes": 3,
                "completed_nodes": 1,
                "learning_nodes": 1,
                "available_nodes": 1,
                "locked_nodes": 0,
                "average_mastery": 50.0,
            },
        )

    def test_empty_data_returns_empty_graph_and_zero_stats(self):
        graph_response = self.client.get("/api/skill-tree/graph", params={"doc_id": "missing-doc"})
        stats_response = self.client.get("/api/skill-tree/stats", params={"doc_id": "missing-doc"})

        self.assertEqual(graph_response.status_code, 200)
        self.assertEqual(graph_response.json(), {"nodes": [], "edges": []})
        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(
            stats_response.json(),
            {
                "total_nodes": 0,
                "completed_nodes": 0,
                "learning_nodes": 0,
                "available_nodes": 0,
                "locked_nodes": 0,
                "average_mastery": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
