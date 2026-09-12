"""Security: password hashing, JWT, HttpOnly cookie delivery, role guard.

Design (per scope decisions):
- bcrypt password hashes stored in Postgres; never plaintext.
- JWT delivered as HttpOnly Secure SameSite=Lax cookie (CSRF-mitigated),
  rather than bearer-in-localStorage.
- Two roles: operator / admin. Promotion approval requires operator+.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext

from .config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/auth", tags=["auth"])

# ---- in-memory user store (dev/prod-seeded). Swap with DB repo for persistence.
# Seeded users are provided by the DB seed script in a real setup; for the demo
# these bootstrapped credentials come from env.
USERS: dict[str, dict] = {}


def seed_users() -> None:
    s = get_settings()
    for role, (user, pw) in {
        "operator": (os.getenv("SEED_OPERATOR_USER", "operator"),
                     os.getenv("SEED_OPERATOR_PASSWORD", "operator-pass")),
        "admin": (os.getenv("SEED_ADMIN_USER", "admin"),
                  os.getenv("SEED_ADMIN_PASSWORD", "admin-pass")),
    }.items():
        USERS[user] = {
            "username": user,
            "role": role,
            "password_hash": pwd_context.hash(pw),
            "active": True,
        }


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _token(claims: dict) -> str:
    s = get_settings()
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def create_access_token(username: str, role: str) -> str:
    s = get_settings()
    claims = {
        "sub": username,
        "username": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.auth_token_ttl_minutes),
    }
    return _token(claims)


def decode_token(token: str) -> dict:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


# ---- dependencies -----------------------------------------------------------
def get_token_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get("access_token")


def get_current_user(request: Request) -> dict:
    token = get_token_from_cookie(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    claims = decode_token(token)
    user = USERS.get(claims.get("username"))
    if not user or not user["active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or inactive user")
    return user


def require_role(*roles: str):
    def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user
    return dep


# ---- endpoints ---------------------------------------------------------------
@router.post("/token")
def login(form: OAuth2PasswordRequestForm = Depends(), response: Response = None):
    user = USERS.get(form.username)
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = create_access_token(user["username"], user["role"])
    if response:
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
            samesite="lax",
            max_age=get_settings().auth_token_ttl_minutes * 60,
            path="/",
        )
    return {"username": user["username"], "role": user["role"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "role": user["role"]}
