from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import create_tables
from app.core.security import create_initial_admin
from app.api import auth, admin, projects, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await create_initial_admin()
    yield


app = FastAPI(
    title="AIA — Agence IA Automatisée",
    version="1.0.0",
    description="Multi-agent AI platform for automated software project analysis.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(ws.router, tags=["websocket"])


@app.get("/")
async def root():
    return {"message": "AIA Backend v1.0", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}
