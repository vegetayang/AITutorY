from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .models.database import init_db
from .routers import documents, skill_tree, quiz, learning, knowledge_points

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="AI Tutor API",
    description="AI辅助教学系统API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(skill_tree.router)
app.include_router(quiz.router)
app.include_router(learning.router)
app.include_router(knowledge_points.router)

@app.get("/")
async def root():
    return {
        "message": "AI Tutor API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
