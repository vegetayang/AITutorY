import httpx
import os
from typing import Optional, Dict, Any, List

class LightRAGClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("LIGHTRAG_BASE_URL") or "http://localhost:9621").rstrip("/")
        self.client = httpx.AsyncClient(timeout=300.0)
    
    async def upload_document(self, file_path: str):
        with open(file_path, "rb") as f:
            files = {"file": f}
            response = await self.client.post(
                f"{self.base_url}/documents/upload",
                files=files
            )
            return response.json()
    
    async def insert_text(self, text: str):
        response = await self.client.post(
            f"{self.base_url}/documents/text",
            json={"text": text}
        )
        return response.json()
    
    async def query(self, query: str, mode: str = "mix", include_references: bool = False):
        response = await self.client.post(
            f"{self.base_url}/query",
            json={
                "query": query,
                "mode": mode,
                "include_references": include_references
            }
        )
        return response.json()
    
    async def query_data(self, query: str, mode: str = "local"):
        response = await self.client.post(
            f"{self.base_url}/query/data",
            json={
                "query": query,
                "mode": mode
            }
        )
        return response.json()
    
    async def get_knowledge_graph(self, label: str, max_depth: int = 3, max_nodes: int = 100):
        response = await self.client.get(
            f"{self.base_url}/graphs",
            params={
                "label": label,
                "max_depth": max_depth,
                "max_nodes": max_nodes
            }
        )
        return response.json()
    
    async def search_labels(self, q: str, limit: int = 50):
        response = await self.client.get(
            f"{self.base_url}/graph/label/search",
            params={"q": q, "limit": limit}
        )
        return response.json()
    
    async def get_documents_paginated(
        self,
        page: int = 1,
        page_size: int = 50,
        status_filter: Optional[str] = None,
        sort_field: str = "updated_at",
        sort_direction: str = "desc"
    ) -> Dict[str, Any]:
        response = await self.client.post(
            f"{self.base_url}/documents/paginated",
            json={
                "page": page,
                "page_size": page_size,
                "status_filter": status_filter,
                "sort_field": sort_field,
                "sort_direction": sort_direction
            }
        )
        return response.json()
    
    async def get_documents(self) -> Dict[str, Any]:
        response = await self.client.get(f"{self.base_url}/documents")
        return response.json()
    
    async def get_pipeline_status(self) -> Dict[str, Any]:
        response = await self.client.get(f"{self.base_url}/documents/pipeline_status")
        return response.json()
    
    async def get_document_status_counts(self) -> Dict[str, Any]:
        response = await self.client.get(f"{self.base_url}/documents/status_counts")
        return response.json()
    
    async def get_track_status(self, track_id: str) -> Dict[str, Any]:
        response = await self.client.get(f"{self.base_url}/documents/track_status/{track_id}")
        return response.json()
    
    async def delete_document(self, doc_id: str) -> Dict[str, Any]:
        response = await self.client.request(
            "DELETE",
            f"{self.base_url}/documents/delete_document",
            json={"doc_ids": [doc_id]}
        )
        return response.json()
    
    async def close(self):
        await self.client.aclose()
