# 출처: 팬 플랫폼 서비스 (2026.07) — 선차감 후 생성이 최종 실패하면 환불을 먼저 커밋하고, 그 다음에야 알림을 보낸다. 요청 거절 환불도 원장 1행
# 알림 발송이 실패해도 환불은 남아야 한다. 두 작업을 한 트랜잭션에 묶으면 알림 오류가 환불까지 되돌린다.

import logging

from app.core.database.base import task_session
from app.module.billing.billing import CreditLedger

logger = logging.getLogger(__name__)


# ── 워커: 생성 실패 → 환불 → 알림 ───────────────────────────────────────
async def _send_failure_notification(user_id: int, content_id: int, charged_amount: int) -> None:
    from app.module.billing.billing_repository import BillingRepository
    from app.module.infra.fcm.fcm_service import FCMService
    from app.module.infra.fcm import templates
    from app.module.notification.notification_repository import NotificationRepository
    from app.module.user.user_repository import UserRepository
    from app.module.content.content_service import clear_generating

    # 최종 실패 — 재시도가 남지 않았으므로 생성 중 표시를 푼다
    await clear_generating(user_id, content_id)

    try:
        async with task_session() as db:
            user_repo = UserRepository(db)
            user = await user_repo.get_user_by_id(user_id)
            if user and charged_amount > 0:
                await BillingRepository(db).grant_credits(
                    user=user,
                    amount=charged_amount,
                    ref_type="content_generate_ref",   # 20자 이내 — 원장 컬럼 길이 사고 이후 축약된 값
                    ref_id=content_id,
                    description="콘텐츠 생성 실패 크레딧 복구",
                )
                # 환불을 먼저 확정 — 이후 알림 발송이 실패해도 환불은 유지
                await db.commit()
                logger.info("[content_task] credit refunded user_id=%s amount=%s", user_id, charged_amount)

            fcm_service = FCMService(user_repo, NotificationRepository(db))
            await fcm_service.send_to_user(user_id, templates.content_failed())
            await db.commit()
    except Exception as e:
        logger.error("[content_task] failure notification error user_id=%s: %s", user_id, e)


# ── 서비스: 요청 거절 → 환불 원장 ───────────────────────────────────────
class UserRequestService:
    def __init__(self, request_repo, user_repo, fcm_service=None):
        self.request_repo = request_repo
        self.user_repo = user_repo
        self.fcm_service = fcm_service

    async def reject(self, creator_ids: list[int], request_id: int, reason: str):
        request = await self._verify_ownership(creator_ids, request_id)

        # 크레딧 환불 + 원장 기록 — 요청 행에 스냅샷된 크레딧 비용을 그대로 되돌린다
        user = await self.user_repo.get_user_by_id(request.user_id)
        if user:
            user.credit += request.credit_cost
            self.request_repo.db.add(CreditLedger(
                user_id=request.user_id,
                type="refund",
                amount=request.credit_cost,
                balance_after=user.credit,
                ref_type="user_request",
                ref_id=request.id,
                description=f"{request.request_type} 요청 거절 환불",
            ))
            await self.request_repo.db.commit()   # 환불 먼저 확정

        result = await self.request_repo.update_status(
            request, status="rejected", rejected_reason=(reason or "").strip() or None
        )
        # ... (생략: 거절 알림 발송 — 실패해도 위 환불은 유지)
        return result

    async def _verify_ownership(self, creator_ids, request_id):
        # ... (생략)
        raise NotImplementedError
