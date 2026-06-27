from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os

DATABASE_URL = "sqlite:///./data/aitutor.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class SkillNode(Base):
    __tablename__ = "skill_nodes"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(Text)
    parent_ids = Column(JSON)
    doc_id = Column(String, index=True)
    status = Column(String, default="locked")
    mastery = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class LearningProgress(Base):
    __tablename__ = "learning_progress"
    
    id = Column(String, primary_key=True, index=True)
    node_id = Column(String, index=True)
    study_time = Column(Integer, default=0)
    quiz_scores = Column(JSON, default=list)
    last_visit = Column(DateTime, default=datetime.utcnow)
    mastery = Column(Float, default=0.0)

class QuizRecord(Base):
    __tablename__ = "quiz_records"
    
    id = Column(String, primary_key=True, index=True)
    node_id = Column(String, index=True)
    questions = Column(JSON)
    answers = Column(JSON)
    score = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

class ReviewSchedule(Base):
    __tablename__ = "review_schedules"

    id = Column(String, primary_key=True, index=True)
    node_id = Column(String, ForeignKey("skill_nodes.id"), index=True, unique=True, nullable=False)
    interval_days = Column(Integer, default=1)
    ease_factor = Column(Float, default=2.5)
    review_count = Column(Integer, default=0)
    last_score = Column(Float, nullable=True)
    last_reviewed_at = Column(DateTime, nullable=True)
    next_review_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
