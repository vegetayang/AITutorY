from datetime import datetime, timedelta
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models.database import ReviewSchedule, SkillNode, get_db


router = APIRouter(prefix="/api/review", tags=["review"])


class ReviewRecordRequest(BaseModel):
    score: float = Field(..., ge=0, le=100)
    reviewed_at: datetime | None = None


def utcnow() -> datetime:
    return datetime.utcnow()


def get_node_or_404(db: Session, node_id: str) -> SkillNode:
    node = db.query(SkillNode).filter(SkillNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    return node


def get_schedule(db: Session, node_id: str) -> ReviewSchedule | None:
    return db.query(ReviewSchedule).filter(ReviewSchedule.node_id == node_id).first()


def get_schedule_or_404(db: Session, node_id: str) -> ReviewSchedule:
    schedule = get_schedule(db, node_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Review schedule not found")
    return schedule


def get_node_title(node: SkillNode) -> str:
    return getattr(node, "title", None) or getattr(node, "name", None) or ""


def create_schedule(db: Session, node: SkillNode, now: datetime | None = None) -> ReviewSchedule:
    current_time = now or utcnow()
    schedule = ReviewSchedule(
        id=str(uuid.uuid4()),
        node_id=node.id,
        interval_days=1,
        ease_factor=2.5,
        review_count=0,
        last_score=None,
        last_reviewed_at=None,
        next_review_at=current_time + timedelta(days=1),
        created_at=current_time,
        updated_at=current_time,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def get_or_create_schedule(db: Session, node: SkillNode, now: datetime | None = None) -> ReviewSchedule:
    schedule = get_schedule(db, node.id)
    if schedule:
        return schedule
    return create_schedule(db, node, now=now)


def apply_review_result(schedule: ReviewSchedule, score: float, reviewed_at: datetime) -> None:
    interval_days = schedule.interval_days or 1
    ease_factor = schedule.ease_factor or 2.5
    first_review = (schedule.review_count or 0) == 0

    if score < 60:
        next_interval = 1
        next_ease = max(1.3, ease_factor - 0.2)
    elif score < 85:
        next_interval = 1 if first_review else max(1, round(interval_days * ease_factor))
        next_ease = ease_factor
    else:
        next_interval = 2 if first_review else max(2, round(interval_days * (ease_factor + 0.15)))
        next_ease = min(3.0, ease_factor + 0.1)

    schedule.interval_days = next_interval
    schedule.ease_factor = next_ease
    schedule.review_count = (schedule.review_count or 0) + 1
    schedule.last_score = score
    schedule.last_reviewed_at = reviewed_at
    schedule.next_review_at = reviewed_at + timedelta(days=next_interval)
    schedule.updated_at = reviewed_at


def serialize_schedule(schedule: ReviewSchedule, node: SkillNode | None = None) -> dict:
    data = {
        "node_id": schedule.node_id,
        "interval_days": schedule.interval_days,
        "ease_factor": schedule.ease_factor,
        "review_count": schedule.review_count,
        "last_score": schedule.last_score,
        "last_reviewed_at": schedule.last_reviewed_at,
        "next_review_at": schedule.next_review_at,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }
    if node is not None:
        data["title"] = get_node_title(node)
        data["mastery"] = node.mastery
        data["status"] = node.status
    return data


@router.get("/due")
async def get_due_reviews(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    as_of: datetime | None = None,
    db: Session = Depends(get_db),
):
    due_at = as_of or utcnow()
    query = (
        db.query(ReviewSchedule, SkillNode)
        .join(SkillNode, ReviewSchedule.node_id == SkillNode.id)
        .filter(ReviewSchedule.next_review_at <= due_at)
        .order_by(ReviewSchedule.next_review_at.asc())
    )
    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    return {
        "items": [serialize_schedule(schedule, node) for schedule, node in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "as_of": due_at,
    }


@router.post("/{node_id}/init")
async def init_review_schedule(node_id: str, db: Session = Depends(get_db)):
    node = get_node_or_404(db, node_id)
    schedule = get_or_create_schedule(db, node)
    return serialize_schedule(schedule, node)


@router.post("/{node_id}/record")
async def record_review(node_id: str, request: ReviewRecordRequest, db: Session = Depends(get_db)):
    node = get_node_or_404(db, node_id)
    reviewed_at = request.reviewed_at or utcnow()
    schedule = get_or_create_schedule(db, node, now=reviewed_at)

    apply_review_result(schedule, request.score, reviewed_at)
    db.commit()
    db.refresh(schedule)

    return serialize_schedule(schedule, node)


@router.get("/{node_id}")
async def get_review_schedule(node_id: str, db: Session = Depends(get_db)):
    node = get_node_or_404(db, node_id)
    schedule = get_schedule_or_404(db, node_id)
    return serialize_schedule(schedule, node)


@router.get("/{node_id}/curve")
async def get_review_curve(
    node_id: str,
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    node = get_node_or_404(db, node_id)
    schedule = get_schedule_or_404(db, node_id)
    start = schedule.last_reviewed_at or utcnow()
    strength = max(schedule.interval_days or 1, 1)
    points = []

    for day in range(days + 1):
        retention = math.exp(-day / strength) * 100
        points.append(
            {
                "day": day,
                "date": (start + timedelta(days=day)).date().isoformat(),
                "retention": round(retention, 2),
            }
        )

    return {
        "node_id": node.id,
        "interval_days": schedule.interval_days,
        "last_reviewed_at": schedule.last_reviewed_at,
        "next_review_at": schedule.next_review_at,
        "points": points,
    }
