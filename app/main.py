from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from app.api.session import router as session_router

app = FastAPI()
app.include_router(session_router)

@app.get("/health")
def health():
    return {"ok": True}
