# 출처: 복지관 ERP (2026.08) — 로그인 2단계. 비밀번호가 맞아도 로그인 토큰을 주지 않고 5분짜리 표식만 준 뒤, 등록된 번호로 보낸 인증번호를 확인했을 때 토큰을 발급한다
# 원본은 auth_token.py(표식) · auth_service.py(발송 · 확인) · auth_router.py(엔드포인트) 세 파일이다.
import random
from datetime import timedelta

import jwt
from fastapi import APIRouter, HTTPException

from app.core.config.settings import settings
from app.core.database.base import now_kst
from app.core.provider.http.endpoint import with_provider
from app.core.provider.http.service import ServiceProvider
from app.core.utils.response import fail, success
from app.module.user.user import PHONE_EXEMPT_ROLES

# ---- auth_token.py ----
# 계정 인증은 끝났고 휴대폰 인증만 남은 상태의 표식. 오래 살면 2단계를 건너뛸 틈이 생기므로 짧게.
PENDING_TOKEN_TTL = timedelta(minutes=5)


def create_pending_token(user, purpose: str = "phone") -> str:
    """로그인 토큰이 아니다 — 쿠키로 내리지 않고 응답 본문으로만 준다."""
    payload = {
        "sub": str(user.id),
        "type": "pending",
        "purpose": purpose,
        "exp": now_kst() + PENDING_TOKEN_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_pending_token(token: str, purpose: str = "phone") -> int:
    """표식에서 계정 id를 꺼낸다. 만료·위조·용도 불일치면 401."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="PENDING_TOKEN_EXPIRED")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="PENDING_TOKEN_INVALID")

    if payload.get("type") != "pending" or payload.get("purpose") != purpose:
        raise HTTPException(status_code=401, detail="PENDING_TOKEN_INVALID")
    return int(payload["sub"])


# ---- auth_service.py ----
CODE_TTL_SECONDS = 60  # 인증번호 유효 시간 — 화면에 남은 초를 세어 보여 준다
CODE_LENGTH = 6
RESEND_COOLDOWN_SECONDS = 30  # 같은 계정으로 계속 시도해 문자를 퍼붓는 것을 막는다


def _code_key(user_id: int) -> str:
    return f"login:phone:code:{user_id}"


def _cooldown_key(user_id: int) -> str:
    return f"login:phone:cooldown:{user_id}"


def mask_phone(phone: str | None) -> str:
    """가운데 자리를 가린 번호 — 계정만 뚫려도 번호가 새지 않게."""
    parts = (phone or "").split("-")
    return f"{parts[0]}-{'*' * len(parts[1])}-{parts[2]}" if len(parts) == 3 else ""


class AuthService:
    # ... (생성자 · 비밀번호 검증 생략)
    async def send_phone_code(self, request, sms_service, redis_service) -> dict:
        """1단계 표식으로 계정을 찾아 그 계정에 등록된 번호로 보낸다.
        번호는 화면이 보낸 값을 쓰지 않는다 — 남의 계정으로 로그인해 놓고 자기 번호로 받아갈 수 있다."""
        account = await self._pending_account(request)

        if not account.phone:
            fail("등록된 휴대폰 번호가 없습니다. 관리자에게 문의해 주세요.", "PHONE_NOT_REGISTERED")
        if await redis_service.get(_cooldown_key(account.id)):
            fail(f"잠시 후 다시 시도해 주세요. ({RESEND_COOLDOWN_SECONDS}초)", "RESEND_TOO_SOON")

        code = f"{random.randrange(10 ** (CODE_LENGTH - 1), 10 ** CODE_LENGTH)}"
        await sms_service.send(account.phone, f"[Client] 인증번호 {code} 를 입력해 주세요.")

        # 인증번호와 재발송 쿨다운은 Redis 에 TTL 로 — 워커가 여럿이어도 같은 값을 본다
        await redis_service.set(_code_key(account.id), code, expire=CODE_TTL_SECONDS)
        await redis_service.set(_cooldown_key(account.id), "1", expire=RESEND_COOLDOWN_SECONDS)
        return {"sent": True, "expiresIn": CODE_TTL_SECONDS}

    async def verify_phone(self, request, redis_service):
        """표식과 인증번호를 확인하고 계정을 돌려준다.
        맞았든 틀렸든 인증번호는 한 번 쓰면 지운다 — 남겨 두면 같은 번호로 계속 시도해 볼 수 있다."""
        body = await request.json()
        code = (body.get("code") or "").strip()
        account = await self._pending_account(request, body)

        if not code:
            fail("인증번호를 입력해 주세요.", "CODE_REQUIRED")
        saved = await redis_service.get(_code_key(account.id))
        if not saved:
            fail("인증번호가 만료되었습니다. 다시 발송해 주세요.", "CODE_EXPIRED")

        await redis_service.delete(_code_key(account.id))
        if saved != code:
            fail("인증번호가 일치하지 않습니다.", "CODE_MISMATCH")

        await self.user_repo.touch_last_login(account)
        return account

    async def _pending_account(self, request, body: dict | None = None):
        """1단계 표식에서 계정을 꺼낸다. 두 경로가 함께 쓴다."""
        if body is None:
            body = await request.json()

        pending = (body.get("pendingToken") or "").strip()
        if not pending:
            fail("로그인을 처음부터 다시 진행해 주세요.", "PENDING_TOKEN_REQUIRED")

        user_id = read_pending_token(pending)
        account = await self.user_repo.get_user_by_id(user_id)
        if not account or not account.active:
            fail("로그인을 처음부터 다시 진행해 주세요.", "PENDING_TOKEN_INVALID")
        return account


# ---- auth_router.py ----
router = APIRouter()


@router.post("/login")
@with_provider
async def login(p: ServiceProvider):
    user, _ = await p.auth_service.login(p.request)  # 아이디 · 비밀번호(Argon2) 확인

    # 시스템 관리자만 2단계를 건너뛴다 — 문자 장애 때도 점검하러 들어갈 통로
    if user.role in PHONE_EXEMPT_ROLES:
        response = success({"skipPhone": True}, message="user login successful")
        await p.auth_service.token_util.create_jwt_token(user, response, "user")
        return response

    # 여기서는 로그인 토큰을 주지 않는다 — 지금 주면 화면만 2단계에 있고 실제로는 들어가진 상태가 된다
    return success(
        {"maskedPhone": mask_phone(user.phone), "pendingToken": create_pending_token(user)},
        message="계정 인증이 완료되었습니다. 휴대폰 인증을 진행해 주세요.",
    )


@router.post("/login/phone/send")
@with_provider
async def login_phone_send(p: ServiceProvider):
    """로그인 2단계 — 계정에 등록된 번호로 인증번호를 보낸다."""
    result = await p.auth_service.send_phone_code(p.request, p.sms_service, p.redis_service)
    return success(result, message="인증번호를 보냈습니다.")


@router.post("/login/phone")
@with_provider
async def login_phone(p: ServiceProvider):
    """로그인 2단계 — 휴대폰 본인 인증을 통과하면 이때 토큰을 발급한다."""
    user = await p.auth_service.verify_phone(p.request, p.redis_service)
    response = success(message="user login successful")
    await p.auth_service.token_util.create_jwt_token(user, response, "user")
    return response
