from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.api.session import router as session_router
from app.api.runs import router as runs_router
from app.api.evidence import router as evidence_router


app = FastAPI()

# Middleware to allow CORS for the frontend running on localhost:5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(runs_router)
app.include_router(evidence_router)

@app.get("/health")
def health():
    return {"ok": True}
