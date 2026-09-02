# 출처: AI 글쓰기 검토 서비스 (2025.07) — 토큰에는 사용자 ID 와 역할만 담고, 화면이 필요한 회사 · 부서 정보는 httpOnly 가 아닌 별도 쿠키로 나눴다. 비밀번호는 HMAC-SHA256
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.repository.common import auth_repository

hash_key = settings.hash_key
jwt_secret = settings.jwt_secret


def hmac_sha256(password: str, key: str = hash_key) -> str:
    """비밀번호 해시. 서버 키를 섞은 HMAC-SHA256 — 다음 단계에서 Argon2 로 바뀐다."""
    return hmac.new(key.encode(), password.encode(), hashlib.sha256).hexdigest()


def create_jwt_token(user, response):
    # 토큰에는 식별자와 역할만 — 이전 단계처럼 닉네임 · 이메일 · 이미지를 넣지 않는다
    payload = {
        "sub": str(user.user_id),
        "role": str(user.user_role.value),
        "type": "access",
        "exp": datetime.now(ZoneInfo("Asia/Seoul")) + timedelta(hours=1),
    }
    access_token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

    refresh_payload = {
        "sub": str(user.user_id),
        "role": str(user.user_role.value),
        "type": "refresh",
        "exp": datetime.now(ZoneInfo("Asia/Seoul")) + timedelta(hours=6),
    }
    refresh_token = jwt.encode(refresh_payload, settings.jwt_secret, algorithm="HS256")

    secure_flag = settings.env == "prod"

    # 화면이 바로 읽어야 하는 정보는 별도 쿠키 — httponly=False 라서 스크립트가 읽는다.
    # 자격증명이 아니라 표시용이므로 토큰과 분리했다.
    user_info = {
        "id": user.id,
        "user_id": user.user_id,
        "user_name": user.user_name,
        "user_email": user.user_email,
        "user_role": user.user_role.value,
        "company_name": user.company.company_name if user.user_role.value != "super" and user.company else "",
        "company_id": user.company.id if user.user_role.value != "super" and user.company else "",
        "department_name": user.department.department_name if user.department else "",
        "department_id": user.department_id,
    }
    encoded_info = base64.b64encode(json.dumps(user_info).encode()).decode()

    response.set_cookie(key="user_info", value=encoded_info, httponly=False, secure=secure_flag, samesite="Lax", max_age=3600, path="/")
    response.set_cookie(key="access_token", value=access_token, httponly=True, secure=secure_flag, samesite="Lax", max_age=3600)
    response.set_cookie(key="refresh_token", value=refresh_token, httponly=True, secure=secure_flag, samesite="Lax", max_age=21600)


async def authenticate_user(request: Request, db: Session):
    body = json.loads(await request.body())
    user_id = body.get("user_id")
    password = body.get("password")

    user = await auth_repository.get_user_by_user_id(user_id, db)
    if not user or user.password != hmac_sha256(password):
        return JSONResponse(status_code=401, content={"message": "Invalid credentials"})

    response = JSONResponse(status_code=200, content={"message": "Login successful"})
    create_jwt_token(user, response)
    return response


def verify_access_token(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Access token not found")
    return verify_token(token, "access")


# refresh_token으로 access_token 재발급 — 이번에는 DB 에서 사용자를 다시 읽어 토큰 · 정보 쿠키를 모두 새로 굽는다
async def rotate_access_token(request: Request, db: Session) -> JSONResponse:
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return JSONResponse(content={"error": "No refresh token"}, status_code=401)

    payload = verify_token(refresh_token, "refresh")
    user_obj = await auth_repository.get_user_by_user_id(payload.get("sub"), db)
    if not user_obj:
        raise HTTPException(status_code=404, detail="User not found")

    response = JSONResponse(status_code=200, content={"message": "Token refreshed successfully"})
    create_jwt_token(user_obj, response)
    return response


def verify_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
