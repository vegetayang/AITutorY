from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
import json

from ..models.database import get_db, SkillNode, LearningProgress
from ..services.lightrag_client import LightRAGClient
from ..services.skill_tree_builder import SkillTreeBuilder

router = APIRouter(prefix="/api/skill-tree", tags=["skill_tree"])

lightrag_client = LightRAGClient()
skill_tree_builder = SkillTreeBuilder(lightrag_client)

def parse_parent_ids(parent_ids) -> List[str]:
    if parent_ids is None:
        return []
    if isinstance(parent_ids, str):
        try:
            return json.loads(parent_ids)
        except:
            return []
    if isinstance(parent_ids, list):
        return parent_ids
    return []

def get_node_parent_ids(node: SkillNode) -> List[str]:
    for field_name in ("parent_ids", "prerequisite_ids", "prerequisites", "dependencies"):
        if hasattr(node, field_name):
            parent_ids = parse_parent_ids(getattr(node, field_name))
            if parent_ids:
                return [str(parent_id) for parent_id in parent_ids]

    if hasattr(node, "parent_id"):
        parent_id = getattr(node, "parent_id")
        if parent_id is not None:
            return [str(parent_id)]

    return []

def calculate_node_level(node: SkillNode, nodes_by_id: Dict[str, SkillNode], seen: set | None = None) -> int:
    if hasattr(node, "level"):
        level = getattr(node, "level")
        if level is not None:
            return level

    seen = seen or set()
    node_id = str(node.id)
    if node_id in seen:
        return 1

    parent_levels = []
    for parent_id in get_node_parent_ids(node):
        parent = nodes_by_id.get(str(parent_id))
        if parent:
            parent_levels.append(calculate_node_level(parent, nodes_by_id, seen | {node_id}))

    if not parent_levels:
        return 1

    return max(parent_levels) + 1

def apply_skill_node_filters(query, doc_id: str | None = None, status: str | None = None):
    if doc_id is not None:
        query = query.filter(SkillNode.doc_id == doc_id)
    if status is not None:
        query = query.filter(SkillNode.status == status)
    return query

@router.get("/graph")
async def get_skill_tree_graph(
    doc_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    query = apply_skill_node_filters(db.query(SkillNode), doc_id=doc_id, status=status)
    skill_nodes = query.all()
    nodes_by_id = {str(node.id): node for node in skill_nodes}

    nodes = [
        {
            "id": node.id,
            "title": node.name,
            "description": node.description,
            "level": calculate_node_level(node, nodes_by_id),
            "status": node.status,
            "mastery": node.mastery,
            "doc_id": node.doc_id,
        }
        for node in skill_nodes
    ]

    edges = []
    for node in skill_nodes:
        target_id = str(node.id)
        for parent_id in get_node_parent_ids(node):
            source_id = str(parent_id)
            if source_id in nodes_by_id:
                edges.append(
                    {
                        "source": parent_id,
                        "target": node.id,
                        "type": "prerequisite",
                    }
                )

    return {"nodes": nodes, "edges": edges}

@router.get("/stats")
async def get_skill_tree_stats(doc_id: str | None = None, db: Session = Depends(get_db)):
    query = apply_skill_node_filters(db.query(SkillNode), doc_id=doc_id)
    skill_nodes = query.all()

    total_nodes = len(skill_nodes)
    completed_nodes = len([node for node in skill_nodes if node.status == "completed"])
    learning_nodes = len([node for node in skill_nodes if node.status == "learning"])
    available_nodes = len([node for node in skill_nodes if node.status == "available"])
    locked_nodes = len([node for node in skill_nodes if node.status == "locked"])
    average_mastery = sum(node.mastery or 0 for node in skill_nodes) / total_nodes if total_nodes else 0

    return {
        "total_nodes": total_nodes,
        "completed_nodes": completed_nodes,
        "learning_nodes": learning_nodes,
        "available_nodes": available_nodes,
        "locked_nodes": locked_nodes,
        "average_mastery": average_mastery,
    }

@router.get("/nodes")
async def get_all_skill_nodes(db: Session = Depends(get_db)):
    nodes = db.query(SkillNode).all()
    return [
        {
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "parent_ids": node.parent_ids,
            "doc_id": node.doc_id,
            "status": node.status,
            "mastery": node.mastery,
            "created_at": node.created_at,
            "updated_at": node.updated_at
        }
        for node in nodes
    ]

@router.get("/nodes/{node_id}")
async def get_skill_node(node_id: str, db: Session = Depends(get_db)):
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    return {
        "id": node.id,
        "name": node.name,
        "description": node.description,
        "parent_ids": node.parent_ids,
        "doc_id": node.doc_id,
        "status": node.status,
        "mastery": node.mastery,
        "created_at": node.created_at,
        "updated_at": node.updated_at
    }

@router.get("/nodes/{node_id}/learning-content")
async def get_learning_content(node_id: str, db: Session = Depends(get_db)):
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    
    content = await skill_tree_builder.generate_learning_content(node.name, node.description)
    
    if node.status == "available":
        node.status = "learning"
        node.updated_at = datetime.utcnow()
        db.commit()
    
    return {
        "node_id": node_id,
        "node_name": node.name,
        "content": content
    }

@router.post("/nodes/{node_id}/complete")
async def complete_skill_node(node_id: str, db: Session = Depends(get_db)):
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    
    node.status = "completed"
    node.mastery = max(node.mastery, 70.0)
    node.updated_at = datetime.utcnow()
    
    all_nodes = db.query(SkillNode).all()
    unlocked_nodes = []
    
    for n in all_nodes:
        if n.status == "locked":
            parent_ids = parse_parent_ids(n.parent_ids)
            
            if node_id in parent_ids:
                all_parents_completed = True
                for parent_id in parent_ids:
                    parent = db.query(SkillNode).filter(SkillNode.id == parent_id).first()
                    if not parent or parent.status != "completed":
                        all_parents_completed = False
                        break
                
                if all_parents_completed:
                    n.status = "available"
                    n.updated_at = datetime.utcnow()
                    unlocked_nodes.append(n.id)
    
    db.commit()
    
    return {
        "status": "success",
        "node_id": node_id,
        "message": "Skill node marked as completed",
        "unlocked_nodes": unlocked_nodes
    }

@router.put("/nodes/{node_id}/mastery")
async def update_mastery(
    node_id: str,
    mastery: float = Query(..., ge=0.0, le=100.0),
    db: Session = Depends(get_db),
):
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    
    node.mastery = mastery
    node.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "status": "success",
        "node_id": node_id,
        "mastery": mastery
    }
