from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any, AsyncGenerator
import json
import httpx

from ..models.database import get_db, SkillNode, LearningProgress
from ..services.lightrag_client import LightRAGClient

router = APIRouter(prefix="/api/learning", tags=["learning"])

lightrag_client = LightRAGClient()

@router.get("/query")
async def query_knowledge(query: str, mode: str = "mix", include_references: bool = False):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    result = await lightrag_client.query(query, mode, include_references)
    return {
        "query": query,
        "mode": mode,
        "response": result.get("response", ""),
        "references": result.get("references", [])
    }

@router.post("/query/stream")
async def query_knowledge_stream(request: dict):
    query = request.get("query", "")
    mode = request.get("mode", "mix")
    include_references = request.get("include_references", False)

    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{lightrag_client.base_url}/query/stream",
                    json={
                        "query": query,
                        "mode": mode,
                        "include_references": include_references,
                        "stream": True
                    }
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            yield line + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="application/x-ndjson"
    )

@router.get("/progress")
async def get_learning_progress(db: Session = Depends(get_db)):
    nodes = db.query(SkillNode).all()
    
    total_nodes = len(nodes)
    completed_nodes = len([n for n in nodes if n.status == "completed"])
    learning_nodes = len([n for n in nodes if n.status == "learning"])
    available_nodes = len([n for n in nodes if n.status == "available"])
    
    if total_nodes > 0:
        overall_progress = (completed_nodes / total_nodes) * 100
        avg_mastery = sum(n.mastery for n in nodes) / total_nodes
    else:
        overall_progress = 0.0
        avg_mastery = 0.0
    
    return {
        "summary": {
            "total_nodes": total_nodes,
            "completed_nodes": completed_nodes,
            "learning_nodes": learning_nodes,
            "available_nodes": available_nodes,
            "locked_nodes": total_nodes - completed_nodes - learning_nodes - available_nodes,
            "overall_progress": overall_progress,
            "average_mastery": avg_mastery
        },
        "nodes": [
            {
                "id": node.id,
                "name": node.name,
                "status": node.status,
                "mastery": node.mastery
            }
            for node in nodes
        ]
    }

@router.get("/progress/{node_id}")
async def get_node_progress(node_id: str, db: Session = Depends(get_db)):
    progress = db.query(LearningProgress).filter(LearningProgress.node_id == node_id).first()
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    
    return {
        "node_id": node_id,
        "node_name": node.name,
        "node_status": node.status,
        "mastery": node.mastery,
        "progress": {
            "study_time": progress.study_time if progress else 0,
            "quiz_scores": progress.quiz_scores if progress else [],
            "last_visit": progress.last_visit if progress else None
        }
    }
