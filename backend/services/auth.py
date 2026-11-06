import hashlib
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from pwdlib import PasswordHash
from backend.db import get_db
from backend.models import User, Session, now

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash('unusable-placeholder-password')
def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()
def current_user(request: Request, db=Depends(get_db)):
    session = db.get(Session, token_hash(request.cookies.get('mivo_session', '')))
    if not session or session.expires <= now(): raise HTTPException(401, 'Please sign in')
    user = db.get(User, session.user_id)
    if not user: raise HTTPException(401, 'Please sign in')
    return user

def merchant(user=Depends(current_user)):
    if user.role != 'merchant': raise HTTPException(403, 'Merchant account required')
    return user
