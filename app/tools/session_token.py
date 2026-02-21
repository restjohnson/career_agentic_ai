from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Header, HTTPException


_ALG = "HS256"

def mint_session_token(session_id: str) -> str:
    """Create a signed JWT that conatins the session id (sid) 
    which would be kept in the client's memory
    """
    secret = os.environ["SESSION_JWT_SECRET"]
    ttl_min = int(os.getenv("SESSION_TTL_MIN", "120"))

    now = datetime.now(timezone.utc)
    payload = {
        "sid": session_id, 
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_min)).timestamp()),
        "typ": "session",
    }
    return jwt.encode(payload, secret, algorithm=_ALG)

def verify_session_token(token: str) -> str:
    """
    validate the JWT and resturn the session id. on failure, return http excption
    """
    secret = os.environ["SESSION_JWT_SECRET"]
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session toke expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    if payload.get("typ") != "session":
        raise HTTPException(status_code=401, detail="Invalid token type")
    
    sid = payload.get("sid")

    if not sid:
        raise HTTPException(status_code=401, detail="Missing session id in token")
    
    return sid

def get_session_id(authorization: str = Header(...)) -> str:
    """
    fastapi dependecy. requires: authroization: bearer <token>
    return the session id
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detial="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    return verify_session_token(token)
