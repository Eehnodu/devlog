# 출처: 팬 플랫폼 서비스 (2026.05) — 네이티브 앱(웹뷰)은 쿠키가 안 실리는 경우가 있어 쿠키 → 헤더 순서로 토큰을 찾는다. 리프레시 수명은 호출마다 지정
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
        self.env = settings.env
        self.secure = self.env in ("prod", "test")
        self.samesite = "None" if self.env in ("prod", "test") else "Lax"

    def _cookie_prefix(self, auth_type: str):
        # 이 프로젝트는 세션 종류가 넷(user / admin / agent / celebrity)이라 접두사도 넷
        if auth_type == "admin":
            return "admin_"
        if auth_type == "agent":
            return "agent_"
        if auth_type == "celebrity":
            return "celebrity_"
        return "user_"

    def _validate_token(self, token: str, expected_type: str, auth_type: str):
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.algorithm])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail=f"{expected_type.upper()}_TOKEN_EXPIRED")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail=f"{expected_type.upper()}_TOKEN_INVALID")

        if payload.get("type") != expected_type:
            raise HTTPException(status_code=401, detail="INVALID_TOKEN_TYPE")
        if payload.get("user") != auth_type:
            raise HTTPException(status_code=401, detail="INVALID_TOKEN_TYPE")
        return payload

    # --- HTTP용 (쿠키 → Authorization 헤더 순서로 확인) ---
    async def get_token_info(self, request, auth_type: str):
        prefix = self._cookie_prefix(auth_type)
        token = request.cookies.get(f"{prefix}access_token")

        # 네이티브 앱: Authorization 헤더 fallback
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            raise HTTPException(status_code=401, detail="ACCESS_TOKEN_MISSING")

        payload = self._validate_token(token, "access", auth_type)
        return int(payload["sub"]), payload["user"]

    # --- WebSocket용 (쿠키 우선, 쿼리 파라미터 fallback) ---
    async def get_token_info_ws(self, websocket, auth_type: str):
        prefix = self._cookie_prefix(auth_type)
        cookie_token = websocket.cookies.get(f"{prefix}access_token")
        # 네이티브 앱(iOS WKWebView)은 WS 핸드셰이크에 쿠키가 실리지 않으므로
        # 쿼리 파라미터로 access token 을 전달받는다 (검증 로직은 동일).
        token = cookie_token or websocket.query_params.get("token")
        if not token:
            raise HTTPException(status_code=401, detail="ACCESS_TOKEN_MISSING")
        payload = self._validate_token(token, "access", auth_type)
        return int(payload["sub"]), payload["user"]

    async def create_jwt_token(self, user, response, type, refresh_days: int = 1) -> dict:
        """리프레시 수명을 호출마다 지정한다(자동 로그인 체크 시 길게). 쿠키 수명 = 토큰 수명."""
        now_kr = now_kst()
        prefix = self._cookie_prefix(type)

        access_payload = {"sub": str(user.id), "user": type, "type": "access", "exp": now_kr + timedelta(hours=1)}
        refresh_payload = {"sub": str(user.id), "user": type, "type": "refresh", "exp": now_kr + timedelta(days=refresh_days)}

        access_token = jwt.encode(access_payload, self.jwt_secret, algorithm=self.algorithm)
        refresh_token = jwt.encode(refresh_payload, self.jwt_secret, algorithm=self.algorithm)

        cookie_common = {"secure": self.secure, "samesite": self.samesite, "path": "/"}
        refresh_max_age = refresh_days * 86400  # 토큰 exp 와 쿠키 max_age 를 같은 값에서 계산
        response.set_cookie(key=f"{prefix}access_token", value=access_token, httponly=True, max_age=3600, **cookie_common)
        response.set_cookie(key=f"{prefix}refresh_token", value=refresh_token, httponly=True, max_age=refresh_max_age, **cookie_common)
        response.set_cookie(
            key=f"{prefix}refresh_exp",
            value=jwt.encode({"uuid": str(uuid.uuid4())}, self.jwt_secret, algorithm=self.algorithm),
            max_age=refresh_max_age,
            **cookie_common,
        )

        # 네이티브 앱용 반환값 — 쿠키를 못 쓰는 클라이언트는 본문의 토큰을 저장해 헤더로 보낸다
        return {"access_token": access_token, "refresh_token": refresh_token}

    async def verify_refresh_by_type(self, request, auth_type: str):
        if auth_type not in ("user", "admin", "agent", "celebrity"):
            raise HTTPException(status_code=400, detail="INVALID_AUTH_TYPE")

        prefix = self._cookie_prefix(auth_type)
        refresh_token = request.cookies.get(f"{prefix}refresh_token")

        # 네이티브 앱: X-Refresh-Token 헤더 fallback
        if not refresh_token:
            refresh_token = request.headers.get("X-Refresh-Token")

        if not refresh_token:
            raise HTTPException(status_code=401, detail="REFRESH_TOKEN_MISSING")

        payload = self._validate_token(refresh_token, "refresh", auth_type)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="INVALID_REFRESH_PAYLOAD")

        return int(user_id), auth_type
