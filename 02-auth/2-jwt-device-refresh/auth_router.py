# 출처: AI 아바타 모의 면접 서비스 (2025.05) — 구글 · 카카오 OAuth 를 라이브러리 없이 직접 호출(코드 → 토큰 → 사용자 정보), 게스트 로그인, 리프레시 엔드포인트
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services import user_service

router = APIRouter()

KAKAO_TOKEN_URI = "https://kauth.kakao.com/oauth/token"
KAKAO_USER_INFO_URI = "https://kapi.kakao.com/v2/user/me"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@router.post("/google")
async def google_login(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    code = body.get("code")  # 프론트가 구글 로그인 창에서 받아 온 인가 코드
    device_info = body.get("device_info")
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code not provided.")

    token_data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        # 1) 인가 코드 → 구글 액세스 토큰
        token_resp = await client.post(GOOGLE_TOKEN_URL, data=token_data)
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=500, detail="Access token missing")

        # 2) 구글 액세스 토큰 → 사용자 정보
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()

        email = userinfo.get("email")
        name = userinfo.get("name")
        picture = userinfo.get("picture", "")

    # 3) 우리 DB 사용자 조회/생성 → 우리 JWT 발급 → 리프레시 토큰 DB 저장
    db_user = user_service.get_or_create_user(db, email, name, "google", picture)
    access_jwt, refresh_jwt = user_service.create_and_save_tokens(db, db_user, device_info)

    user_data = {
        "id": db_user.id,
        "nickname": name,
        "email": email,
        "profile_image": picture,
        "created_at": db_user.created_at.isoformat(),
    }
    response = JSONResponse(content=user_data)
    return user_service.set_auth_cookies(response, access_jwt, refresh_jwt)


# 카카오도 같은 흐름: 코드 → 토큰 URI → 사용자 정보 URI → 우리 JWT
# ... (kakao_login 생략)


@router.post("/guest-login")
async def guest_login(request: Request, db: Session = Depends(get_db)):
    """회원가입 없이 체험할 수 있게 게스트 계정을 만들고 같은 형식의 토큰을 준다."""
    device_info = request.headers.get("User-Agent", "unknown")

    access_token, refresh_token, guest_id = user_service.create_guest_tokens(db, device_info)

    payload = user_service.verify_token(access_token, expected_type="access")
    guest_user = {
        "id": guest_id,
        "nickname": payload.get("nickname"),
        "email": payload.get("email"),
        "created_at": datetime.now().isoformat(),
    }
    response = JSONResponse(content={"message": "guest login success", "user": guest_user})
    return user_service.set_auth_cookies(response, access_token, refresh_token)


# access_token 재발급 — 프론트 공용 훅이 401 을 받으면 여기를 부른 뒤 원래 요청을 한 번 다시 보낸다
@router.post("/refresh")
async def refresh_token(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    refresh_token = request.cookies.get("refresh_token")
    device_info = body.get("device_info")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token not found")

    return user_service.rotate_access_token(db, refresh_token, device_info)


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    device_info = body.get("device_info")
    return user_service.logout_user(db, request, device_info)
