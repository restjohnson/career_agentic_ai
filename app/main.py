from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from app.api.session import router as session_router
from app.api.runs import router as runs_router


app = FastAPI()
app.include_router(session_router)
app.include_router(runs_router)

@app.get("/health")
def health():
    return {"ok": True}
