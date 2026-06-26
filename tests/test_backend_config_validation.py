import asyncio
import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import learning, skill_tree
from backend.services.lightrag_client import LightRAGClient


app = FastAPI()
app.include_router(learning.router)
app.include_router(skill_tree.router)


class BackendConfigValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_lightrag_base_url_uses_environment_variable(self):
        with mock.patch.dict(os.environ, {"LIGHTRAG_BASE_URL": "http://lightrag.test:9000/"}, clear=False):
            client = LightRAGClient()

        try:
            self.assertEqual(client.base_url, "http://lightrag.test:9000")
        finally:
            asyncio.run(client.close())

    def test_mastery_below_zero_returns_422(self):
        response = self.client.put("/api/skill-tree/nodes/node-1/mastery", params={"mastery": -0.1})

        self.assertEqual(response.status_code, 422)

    def test_mastery_above_100_returns_422(self):
        response = self.client.put("/api/skill-tree/nodes/node-1/mastery", params={"mastery": 100.1})

        self.assertEqual(response.status_code, 422)

    def test_empty_stream_query_returns_400(self):
        response = self.client.post("/api/learning/query/stream", json={"query": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Query cannot be empty")


if __name__ == "__main__":
    unittest.main()
