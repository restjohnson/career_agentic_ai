import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from app.api.session import router as session_router
from app.api.runs import router as runs_router
from app.api.evidence import router as evidence_router


app = FastAPI()

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(evidence_router, prefix="/api")

@app.get("/health")
def health():
    return {"ok": True}

# Serve React frontend — must be registered last so API routes take priority
_static = Path(__file__).parent.parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="frontend")
