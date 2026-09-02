# 출처: 복지관 ERP (2026.08) — 토큰에 계정 등급(staff/admin/super)을 넣고, 관리자 전용 기능은 등급 데코레이터로 막는다. 화면 진입과 기능 권한을 분리
from functools import wraps

from fastapi import HTTPException

from app.module.auth.auth_token import AuthToken


def with_login(type: str = "user"):
    """
    로그인 필수 (기본: user)
    admin API에서는 with_login("admin") 사용

    ※ 세션 종류(user/admin)만 확인한다. 계정 등급(staff/admin/super)까지
      제한해야 하는 관리자 전용 API에는 with_role을 쓸 것.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(p, *args, **kwargs):
            token_util = AuthToken()
            try:
                # 이 프로젝트부터 토큰 검증이 등급(role)까지 세 값을 돌려준다
                user_id, auth_type, role = await token_util.get_token_info(p.request, type)
                p.request.user_id = user_id
                p.request.auth_type = auth_type
                p.request.role = role
            except HTTPException as e:
                raise e
            return await func(p, *args, **kwargs)
        return wrapper
    return decorator


def with_role(*roles: str, type: str = "admin"):
    """
    로그인 + 계정 등급 검사.

    /admin 영역 진입 자체는 등급과 무관하게 열려 있으므로,
    관리자 전용 기능은 이 데코레이터로 막는다.

    예) 챗봇 설정 — admin·super만 허용
        @with_provider
        @with_role(ROLE_ADMIN, ROLE_SUPER)
        async def get_settings(p): ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(p, *args, **kwargs):
            token_util = AuthToken()
            user_id, auth_type, role = await token_util.get_token_info(p.request, type)
            p.request.user_id = user_id
            p.request.auth_type = auth_type
            p.request.role = role

            # 등급은 토큰에서 읽는다 — 토큰은 로그인 시 DB 의 등급으로 구워졌고,
            # 요청 본문의 값은 믿지 않는다
            if role not in roles:
                raise HTTPException(status_code=403, detail="FORBIDDEN_ROLE")

            return await func(p, *args, **kwargs)
        return wrapper
    return decorator


# ---- 라우터 사용 예 (module/admin/admin_router.py) ----
# MANAGE_ROLES = (ROLE_ADMIN, ROLE_SUPER)
#
# @router.get("/users")
# @with_provider
# @with_role(*MANAGE_ROLES)     # 직원(staff) 세션은 403
# async def list_users(p): ...
