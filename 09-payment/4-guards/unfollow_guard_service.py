# 출처: 팬 플랫폼 서비스 (2026.08) — 언팔로우 API 가 유료 구독 행을 지우던 경로에 서버 409 방어. 프론트 모달과 이중 방어
# 스토어 결제는 계속되는데 앱 쪽 구독 행만 사라지면 유저는 돈을 내면서 혜택을 못 받는다.

from app.core.database.base import now_kst
from app.core.utils.response import fail


class BillingService:
    def __init__(self, billing_repo):
        self.billing_repo = billing_repo

    async def follow(self, user_id: int, creator_id: int) -> dict:
        """팔로우 = 무료 등급(tier 0) 구독 행 생성."""
        free_sub_id = await self.billing_repo.get_free_subscription_id(creator_id)
        if not free_sub_id:
            fail("no subscription for creator", "SUBSCRIPTION_NOT_FOUND", 404)

        existing = await self.billing_repo.get_user_subs_by_creator(user_id, creator_id)
        if existing:
            return {"creator_id": creator_id, "following": True}

        await self.subscribe(user_id, free_sub_id)
        return {"creator_id": creator_id, "following": True}

    async def unfollow(self, user_id: int, creator_id: int) -> dict:
        # 유료 구독(tier>0) 이 기간 내 유효하면 인앱 언팔로우 불가 — 스토어 결제는 계속되는데
        # 앱 구독 행만 사라진다. 스토어 해지 후(만료 뒤) 언팔로우 가능. 프론트는 스토어 안내 모달로 분기.
        row = await self.billing_repo.get_user_sub_tier_and_end(user_id, creator_id)
        if row and (row.tier or 0) > 0 and row.end_date and row.end_date.date() >= now_kst().date():
            fail(
                "유료 구독 중에는 앱에서 해지할 수 없습니다. 스토어에서 구독을 해지해 주세요.",
                "PAID_SUBSCRIPTION_ACTIVE",
                409,
            )
        await self.billing_repo.delete_user_subs_by_creator(user_id, creator_id)
        return {"creator_id": creator_id, "following": False}

    async def subscribe(self, user_id: int, subscription_id: int) -> dict:
        # ... (생략)
        raise NotImplementedError
