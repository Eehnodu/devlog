# 출처: AI 캐릭터 대화 서비스 (2025.11) — 관리자 · 사용자 세션을 쿠키 접두사(admin_/user_)와 토큰 안의 종류 클레임 두 겹으로 분리. HTTP 와 WebSocket 이 같은 검증 함수를 쓴다
import base64
import json
import uuid
from datetime import timedelta

import jwt
from fastapi import HTTPException

from app.core.config.settings import settings
from app.core.database.base import now_kst


class AuthToken:
    def __init__(self):
        self.jwt_secret = settings.jwt_secret
        self.algorithm = "HS256"
        self.env = getattr(settings, "env", "dev")
        # 프론트와 API 도메인이 다르므로 운영에서는 SameSite=None + Secure
        self.samesite = "None" if self.env == "prod" else "Lax"
        self.domain = settings.cookie_domain if self.env == "prod" else None
        self.secure = True if self.env == "prod" else False

    def _cookie_prefix(self, auth_type: str):
        # 같은 브라우저에서 관리자와 사용자로 동시에 로그인해도 쿠키가 서로를 덮어쓰지 않는다
        return "admin_" if auth_type == "admin" else "user_"

    # --- 공통 로직 분리 ---
    def _get_user_from_cookies(self, cookies, auth_type: str):
        prefix = self._cookie_prefix(auth_type)

        access_token = cookies.get(f"{prefix}access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="ACCESS_TOKEN_MISSING")

        try:
            payload = jwt.decode(access_token, self.jwt_secret, algorithms=[self.algorithm])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="ACCESS_TOKEN_EXPIRED")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="ACCESS_TOKEN_INVALID")

        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="INVALID_TOKEN_TYPE")

        # 두 번째 겹 — 쿠키 이름을 바꿔 끼워 넣어도 토큰 안의 종류가 다르면 거절
        if payload.get("user") != auth_type:
            raise HTTPException(status_code=401, detail="INVALID_TOKEN_TYPE")

        return int(payload["sub"]), payload["user"]

    # --- HTTP용 ---
    async def get_token_info(self, request, auth_type: str):
        return self._get_user_from_cookies(request.cookies, auth_type)

    # --- WebSocket용 --- 핸드셰이크에 실린 쿠키를 같은 함수로 검증한다
    async def get_token_info_ws(self, websocket, auth_type: str):
        return self._get_user_from_cookies(websocket.cookies, auth_type)

    async def create_jwt_token(self, user, response, type):
        now_kr = now_kst()
        prefix = self._cookie_prefix(type)

        access_payload = {
            "sub": str(user.id),
            "user": type,  # "user" | "admin"
            "type": "access",
            "exp": now_kr + timedelta(hours=1),
        }
        refresh_payload = {
            "sub": str(user.id),
            "user": type,
            "type": "refresh",
            "exp": now_kr + timedelta(hours=6),
        }

        access_token = jwt.encode(access_payload, self.jwt_secret, algorithm=self.algorithm)
        refresh_token = jwt.encode(refresh_payload, self.jwt_secret, algorithm=self.algorithm)

        session_info = {
            "auth_type": type,
            "id": user.id,
            "user_nickname": "admin" if type == "admin" else user.user_nickname,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
        # 프론트에서 읽어야 하므로 httponly=False
        encoded_info = base64.b64encode(json.dumps(session_info, ensure_ascii=False).encode("utf-8")).decode("utf-8")

        cookie_common = {"secure": self.secure, "samesite": self.samesite, "path": "/"}
        if self.domain:
            cookie_common["domain"] = self.domain

        response.set_cookie(key=f"{prefix}user_info", value=encoded_info, httponly=False, max_age=3600, **cookie_common)
        response.set_cookie(key=f"{prefix}access_token", value=access_token, httponly=True, max_age=3600, **cookie_common)
        response.set_cookie(key=f"{prefix}refresh_token", value=refresh_token, httponly=True, max_age=21600, **cookie_common)
        # 리프레시가 살아 있는지 프론트가 알 수 있게 내용 없는 표식 쿠키를 같은 수명으로 내린다
        response.set_cookie(
            key=f"{prefix}refresh_exp",
            value=jwt.encode({"uuid": str(uuid.uuid4())}, self.jwt_secret, algorithm=self.algorithm),
            max_age=21600,
            **cookie_common,
        )

    async def verify_refresh_by_type(self, request, auth_type: str):
        """지정된 auth_type의 refresh_token만 검증한다."""
        if auth_type not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="INVALID_AUTH_TYPE")

        prefix = self._cookie_prefix(auth_type)
        refresh_token = request.cookies.get(f"{prefix}refresh_token")
        if not refresh_token:
            raise HTTPException(status_code=401, detail="REFRESH_TOKEN_MISSING")

        try:
            payload = jwt.decode(refresh_token, self.jwt_secret, algorithms=[self.algorithm])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="REFRESH_TOKEN_EXPIRED")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="INVALID_REFRESH_TOKEN")

        if payload.get("type") != "refresh" or payload.get("user") != auth_type:
            raise HTTPException(status_code=401, detail="INVALID_REFRESH_PAYLOAD")

        return int(payload["sub"]), auth_type

    async def delete_token(self, response, auth_type: str):
        """토큰 삭제 및 로그아웃 처리 — 해당 접두사 쿠키만 지운다"""
        prefix = self._cookie_prefix(auth_type)
        cookie_common = {"secure": self.secure, "samesite": self.samesite, "path": "/"}
        if self.domain:
            cookie_common["domain"] = self.domain

        for name in ("access_token", "refresh_token", "user_info", "refresh_exp"):
            response.delete_cookie(f"{prefix}{name}", **cookie_common)
