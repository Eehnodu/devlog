# 출처: AI 아바타 모의 면접 서비스 (2025.05) — 첫 JWT. 액세스 1시간 · 리프레시 6시간을 httpOnly 쿠키로 내리고, 리프레시 토큰은 기기 정보와 함께 DB 에 저장해 기기별 재발급 · 로그아웃을 한다
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.crud import user_crud

JWT_SECRET = settings.jwt_secret


# access_token 생성 — 이 단계에서는 닉네임 · 이메일 · 프로필 이미지를 토큰에 그대로 넣었다
def create_access_token(nickname: str, email: str, profile_image: str) -> str:
    payload = {
        "type": "access",
        "nickname": nickname,
        "email": email,
        "profile_image": profile_image,
        "exp": datetime.now(ZoneInfo("Asia/Seoul")) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# refresh_token 생성
def create_refresh_token(nickname: str, email: str, profile_image: str) -> str:
    payload = {
        "type": "refresh",
        "nickname": nickname,
        "email": email,
        "profile_image": profile_image,
        "exp": datetime.now(ZoneInfo("Asia/Seoul")) + timedelta(hours=6),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# 토큰 검증 — 종류(access/refresh)가 맞는지도 본다
def verify_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# 응답 객체에 Access/Refresh 쿠키 설정
def set_auth_cookies(response: JSONResponse, access_token: str, refresh_token: str) -> JSONResponse:
    secure_flag = settings.env == "prod"

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,  # 스크립트에서 읽을 수 없게
        secure=secure_flag,
        samesite="Lax",
        max_age=3600,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure_flag,
        samesite="Lax",
        # 쿠키 수명(7일)이 토큰 수명(6시간)보다 길다 — 뒤 단계에서 둘을 맞추게 된다
        max_age=60 * 60 * 24 * 7,
    )
    return response


def create_guest_tokens(db: Session, device_info: str):
    """게스트 토큰 — 회원가입 없이 체험할 수 있도록 UUID 계정을 만들어 같은 토큰을 준다."""
    guest_uuid = str(uuid.uuid4())
    guest_user = user_crud.get_or_create_user(
        db, email=guest_uuid, name=guest_uuid, social="guest", role="guest"
    )
    access_token, refresh_token = create_and_save_tokens(db, guest_user, device_info)
    return access_token, refresh_token, guest_user.id


def create_and_save_tokens(db: Session, user, device_info: str):
    access_token = create_access_token(user.user_name, user.user_id, user.profile_image)
    refresh_token = create_refresh_token(user.user_name, user.user_id, user.profile_image)

    # 리프레시 토큰을 (사용자, 기기) 단위로 DB 에 저장 — 기기별 로그아웃 · 재발급의 근거
    user_crud.save_refresh_token(db=db, user_id=user.id, token=refresh_token, device_info=device_info)
    return access_token, refresh_token


# 요청의 access_token 쿠키를 검증하여 사용자 인증 (라우터에서 Depends 로 사용)
def verify_access_token(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Access token not found")
    return verify_token(token, "access")


# refresh_token으로 access_token 재발급
def rotate_access_token(db: Session, refresh_token: str, device_info: str) -> JSONResponse:
    payload = verify_token(refresh_token, "refresh")
    email = payload.get("email")

    db_user = user_crud.get_user_by_email(db, email)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # 쿠키의 리프레시 토큰이 이 기기로 저장된 것과 같은지 확인
    db_refresh_token = user_crud.get_refresh_token_by_user(db, user_id=db_user.id, device_info=device_info)
    if not db_refresh_token or db_refresh_token.refresh_token != refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token mismatch")

    new_access = create_access_token(payload.get("nickname"), email, payload.get("profile_image"))
    response = JSONResponse(content={"access_token": new_access})
    response.set_cookie(key="access_token", value=new_access, httponly=True, samesite="Lax", max_age=3600)
    return response


# 로그아웃 시 refresh_token DB에서 삭제 + 쿠키 제거
def logout_user(db: Session, request: Request, device_info: str) -> JSONResponse:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=["HS256"])
            user = user_crud.get_user_by_email(db, payload.get("email"))
            if user:
                user_crud.delete_refresh_token(db, user.id, device_info)  # 이 기기만 로그아웃
        except jwt.InvalidTokenError:
            pass

    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response
