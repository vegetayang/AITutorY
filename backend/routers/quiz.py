from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Literal
import uuid
from datetime import datetime
from pydantic import BaseModel, Field

from ..models.database import get_db, SkillNode, QuizRecord, LearningProgress
from ..services.lightrag_client import LightRAGClient
from ..services.quiz_generator import QuizGenerator

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

lightrag_client = LightRAGClient()
quiz_generator = QuizGenerator(lightrag_client)

QuestionType = Literal["multiple_choice", "short_answer", "mixed"]


class GenerateNodeQuizRequest(BaseModel):
    num_questions: int = Field(3, ge=1, le=20)
    question_type: QuestionType = "multiple_choice"


class SubmittedAnswer(BaseModel):
    question_id: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    correct_answer: str | None = None


class SubmitQuizRequest(BaseModel):
    answers: List[SubmittedAnswer] = Field(..., min_length=1)


def get_node_title(node: SkillNode) -> str:
    return getattr(node, "title", None) or getattr(node, "name", None) or ""


def get_node_description(node: SkillNode) -> str:
    return getattr(node, "description", None) or ""


def build_fallback_question(
    node: SkillNode,
    index: int,
    question_type: QuestionType,
) -> Dict[str, Any]:
    title = get_node_title(node)
    description = get_node_description(node) or f"Key concept: {title}"
    effective_type = question_type
    if question_type == "mixed":
        effective_type = "multiple_choice" if index % 2 == 1 else "short_answer"

    if effective_type == "short_answer":
        return {
            "id": f"q{index}",
            "type": "short_answer",
            "question": f"Briefly explain the key idea of {title}.",
            "options": [],
            "correct_answer": description,
            "explanation": f"A good answer should mention: {description}",
        }

    return {
        "id": f"q{index}",
        "type": "multiple_choice",
        "question": f"Which option best describes {title}?",
        "options": [
            description,
            f"An unrelated concept to {title}",
            "A deployment configuration detail",
            "A user interface style rule",
        ],
        "correct_answer": "A",
        "explanation": f"{title} is described as: {description}",
    }


async def generate_node_questions(
    node: SkillNode,
    num_questions: int,
    question_type: QuestionType,
) -> List[Dict[str, Any]]:
    return [
        build_fallback_question(node, index, question_type)
        for index in range(1, num_questions + 1)
    ]


def grade_submitted_answers(answers: List[SubmittedAnswer]) -> Dict[str, Any]:
    results = []
    correct_count = 0

    for item in answers:
        correct_answer = item.correct_answer
        is_correct = correct_answer is not None and item.answer == correct_answer
        if is_correct:
            correct_count += 1

        results.append(
            {
                "question_id": item.question_id,
                "is_correct": is_correct,
                "answer": item.answer,
                "correct_answer": correct_answer,
            }
        )

    total = len(answers)
    score = (correct_count / total * 100) if total else 0.0
    return {
        "score": score,
        "correct_count": correct_count,
        "total": total,
        "results": results,
    }


@router.post("/generate-node/{node_id}")
async def generate_node_quiz(
    node_id: str,
    request: GenerateNodeQuizRequest,
    db: Session = Depends(get_db),
):
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")

    try:
        questions = await generate_node_questions(
            node=node,
            num_questions=request.num_questions,
            question_type=request.question_type,
        )
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to generate quiz")

    return {
        "node_id": node.id,
        "title": get_node_title(node),
        "num_questions": request.num_questions,
        "question_type": request.question_type,
        "questions": questions,
        "fallback": True,
    }


@router.post("/submit")
async def submit_quiz_answers(request: SubmitQuizRequest):
    return grade_submitted_answers(request.answers)

@router.get("/generate/{node_id}")
async def generate_quiz(node_id: str, num_questions: int = 5, db: Session = Depends(get_db)):
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    
    questions = await quiz_generator.generate_quiz(node.name, node.description, num_questions)
    
    return {
        "node_id": node_id,
        "node_name": node.name,
        "questions": questions
    }

@router.post("/submit/{node_id}")
async def submit_quiz(node_id: str, questions: List[Dict[str, Any]], user_answers: Dict[str, str], db: Session = Depends(get_db)):
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    
    grading_result = await quiz_generator.grade_quiz(questions, user_answers)
    
    quiz_record = QuizRecord(
        id=str(uuid.uuid4()),
        node_id=node_id,
        questions=questions,
        answers=user_answers,
        score=grading_result["score"],
        created_at=datetime.utcnow()
    )
    db.add(quiz_record)
    
    progress = db.query(LearningProgress).filter(LearningProgress.node_id == node_id).first()
    if not progress:
        progress = LearningProgress(
            id=str(uuid.uuid4()),
            node_id=node_id,
            quiz_scores=[grading_result["score"]],
            mastery=grading_result["score"]
        )
    else:
        progress.quiz_scores.append(grading_result["score"])
        recent_scores = progress.quiz_scores[-5:]
        progress.mastery = sum(recent_scores) / len(recent_scores)
        progress.last_visit = datetime.utcnow()
    db.add(progress)
    
    node.mastery = progress.mastery
    if node.mastery >= 60 and node.status in ["available", "learning"]:
        node.status = "completed"
        
        all_nodes = db.query(SkillNode).all()
        for n in all_nodes:
            if n.status == "locked" and node_id in (n.parent_ids or []):
                parents_completed = True
                for parent_id in (n.parent_ids or []):
                    parent = db.query(SkillNode).filter(SkillNode.id == parent_id).first()
                    if not parent or parent.status != "completed":
                        parents_completed = False
                        break
                if parents_completed:
                    n.status = "available"
    
    node.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "status": "success",
        "node_id": node_id,
        "quiz_record_id": quiz_record.id,
        "grading_result": grading_result,
        "new_mastery": node.mastery,
        "new_status": node.status
    }

@router.get("/records/{node_id}")
async def get_quiz_records(node_id: str, db: Session = Depends(get_db)):
    records = db.query(QuizRecord).filter(QuizRecord.node_id == node_id).order_by(QuizRecord.created_at.desc()).all()
    return [
        {
            "id": record.id,
            "node_id": record.node_id,
            "score": record.score,
            "created_at": record.created_at,
            "questions_count": len(record.questions) if record.questions else 0
        }
        for record in records
    ]
