from datetime import datetime
from typing import List
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models.database import get_db, QuizAttempt, QuizAttemptItem, SkillNode

router = APIRouter(prefix="/api/quiz", tags=["quiz-attempts"])


class QuizAttemptResultRequest(BaseModel):
    question_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    user_answer: str = Field(..., min_length=1)
    correct_answer: str = Field(..., min_length=1)
    is_correct: bool
    explanation: str = ""


class CreateQuizAttemptRequest(BaseModel):
    node_id: str = Field(..., min_length=1)
    question_type: str = Field("mixed", min_length=1)
    score: float = Field(..., ge=0, le=100)
    correct_count: int = Field(..., ge=0)
    total: int = Field(..., gt=0)
    results: List[QuizAttemptResultRequest] = Field(..., min_length=1)


def serialize_attempt_summary(attempt: QuizAttempt) -> dict:
    return {
        "id": attempt.id,
        "node_id": attempt.node_id,
        "question_type": attempt.question_type,
        "score": attempt.score,
        "correct_count": attempt.correct_count,
        "total": attempt.total,
        "created_at": attempt.created_at,
    }


def serialize_attempt_detail(attempt: QuizAttempt, items: List[QuizAttemptItem]) -> dict:
    data = serialize_attempt_summary(attempt)
    data["updated_at"] = attempt.updated_at
    data["items"] = [
        {
            "id": item.id,
            "question_id": item.question_id,
            "question": item.question,
            "user_answer": item.user_answer,
            "correct_answer": item.correct_answer,
            "is_correct": item.is_correct,
            "explanation": item.explanation or "",
            "created_at": item.created_at,
        }
        for item in items
    ]
    return data


@router.post("/attempts")
async def create_quiz_attempt(
    request: CreateQuizAttemptRequest,
    db: Session = Depends(get_db),
):
    node = db.query(SkillNode).filter(SkillNode.id == request.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Skill node not found")
    if request.correct_count > request.total:
        raise HTTPException(status_code=422, detail="correct_count cannot exceed total")

    now = datetime.utcnow()
    attempt = QuizAttempt(
        id=str(uuid.uuid4()),
        node_id=request.node_id,
        question_type=request.question_type,
        score=request.score,
        correct_count=request.correct_count,
        total=request.total,
        created_at=now,
        updated_at=now,
    )
    db.add(attempt)

    items = []
    for result in request.results:
        item = QuizAttemptItem(
            id=str(uuid.uuid4()),
            attempt_id=attempt.id,
            question_id=result.question_id,
            question=result.question,
            user_answer=result.user_answer,
            correct_answer=result.correct_answer,
            is_correct=result.is_correct,
            explanation=result.explanation or "",
            created_at=now,
        )
        db.add(item)
        items.append(item)

    db.commit()
    return serialize_attempt_detail(attempt, items)


@router.get("/attempts")
async def list_quiz_attempts(
    node_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(QuizAttempt)
    if node_id is not None:
        query = query.filter(QuizAttempt.node_id == node_id)

    total = query.count()
    attempts = (
        query.order_by(QuizAttempt.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [serialize_attempt_summary(attempt) for attempt in attempts],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/attempts/{attempt_id}")
async def get_quiz_attempt(
    attempt_id: str,
    db: Session = Depends(get_db),
):
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")

    items = (
        db.query(QuizAttemptItem)
        .filter(QuizAttemptItem.attempt_id == attempt_id)
        .order_by(QuizAttemptItem.created_at.asc())
        .all()
    )
    return serialize_attempt_detail(attempt, items)


@router.get("/wrong-questions")
async def list_wrong_questions(
    node_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(QuizAttemptItem, QuizAttempt)
        .join(QuizAttempt, QuizAttemptItem.attempt_id == QuizAttempt.id)
        .filter(QuizAttemptItem.is_correct.is_(False))
    )
    if node_id is not None:
        query = query.filter(QuizAttempt.node_id == node_id)

    total = query.count()
    rows = (
        query.order_by(QuizAttemptItem.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "attempt_id": attempt.id,
                "node_id": attempt.node_id,
                "question_id": item.question_id,
                "question": item.question,
                "user_answer": item.user_answer,
                "correct_answer": item.correct_answer,
                "explanation": item.explanation or "",
                "created_at": item.created_at,
            }
            for item, attempt in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
