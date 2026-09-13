# 출처: 팬 플랫폼 서비스 (2026.06) — 알림 수신 후 스토어 원본 재조회로 갱신 처리, 주문 ID unique + 구매 토큰 조회로 중복 지급 차단
# 구매 확인 요청은 클라이언트 · 알림 재전송 · 동시 탭 어디서 들어와도 한 번만 지급돼야 한다.

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core.config.settings import settings
from app.core.database.base import KST, now_kst
from app.core.utils.response import fail

logger = logging.getLogger(__name__)


def _iso_to_kst_naive(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST).replace(tzinfo=None)


class BillingService:
    def __init__(self, billing_repo):
        self.billing_repo = billing_repo

    # ── 클라이언트 구매 확인 (소모품) ──────────────────────────────────
    async def grant_credit_from_aos_purchase(self, user_id: int, product_id: str, order_id: str,
                                             purchase_token: str, store_service) -> dict:
        # 1. 주문 ID 중복 체크 (빠른 거부)
        if await self.billing_repo.get_credit_purchase_by_order_id(order_id):
            fail("이미 처리된 결제입니다.", "DUPLICATE_PURCHASE", 409)

        # 2. 스토어 API 검증 — 클라이언트 값이 아니라 스토어 응답을 믿는다
        purchase_data = await store_service.verify_product_purchase(settings.app_bundle_id, product_id, purchase_token)
        if purchase_data.get("purchaseState") != 0:
            fail("완료되지 않은 결제입니다.", "INVALID_PURCHASE_STATE", 400)
        if purchase_data.get("consumptionState") == 1:
            fail("이미 소비된 결제입니다.", "ALREADY_CONSUMED", 400)

        # 3. 상품 · 유저
        credit_product = await self.billing_repo.get_credit_by_store_id(product_id, "google")
        if not credit_product:
            fail("크레딧 상품을 찾을 수 없습니다.", "PRODUCT_NOT_FOUND", 404)
        user = await self.billing_repo.get_user_by_id(user_id)
        if not user:
            fail("user not found", "USER_NOT_FOUND", 404)

        credit_amount = (credit_product.amount or 0) + (credit_product.bonus or 0)
        purchase_time_ms = purchase_data.get("purchaseTimeMillis")
        # tz 미지정 fromtimestamp 는 서버 로컬 TZ → DB 는 naive KST 규약이라 변환 후 tz 제거
        purchased_at = (
            datetime.fromtimestamp(int(purchase_time_ms) / 1000, tz=KST).replace(tzinfo=None)
            if purchase_time_ms else now_kst()
        )
        # 결제 금액 · 통화 — 스토어 응답의 지역 코드로 지역 정가 조회 (지급 시점 값을 행에 남긴다)
        amount, currency = await self._resolve_credit_amount(credit_product.id, region_code=purchase_data.get("regionCode"))

        # 4. 구매 행 + 크레딧 지급 + 원장 기록을 한 트랜잭션으로
        # 중복 체크(1번)와 insert 사이에 동시 요청이 끼면 order_id unique 위반이 난다.
        # 그대로 두면 500 → 깔끔한 409(DUPLICATE) 로 변환한다.
        try:
            purchase = await self.billing_repo.create_credit_purchase(
                user_id=user_id, credit_product_id=credit_product.id, provider="google_play",
                product_id=product_id, order_id=order_id, purchase_token=purchase_token,
                credit_amount=credit_amount, purchased_at=purchased_at,
                amount=amount, currency=currency, consumed=False,
            )
            new_balance = await self.billing_repo.add_credits(user, credit_amount, credit_product.id)  # commit 포함
        except IntegrityError:
            await self.billing_repo.db.rollback()
            fail("이미 처리된 결제입니다.", "DUPLICATE_PURCHASE", 409)

        # 5. 소비 처리 — 지급은 이미 확정됐으므로 consume 실패해도 요청은 성공시킨다.
        #    실패하면 미소비로 남겨 주기 배치가 재시도한다 (환불 창 3일 안에서만).
        if await self._try_consume(store_service, product_id, purchase_token):
            await self.billing_repo.mark_credit_purchase_consumed(purchase.id)
        else:
            logger.error("[consume] FAILED — 미소비로 남김, 배치 재시도 예정. user=%s order_id=%s", user_id, order_id)

        return {"credit_amount": credit_amount, "balance": new_balance}

    async def _try_consume(self, store_service, product_id: str, purchase_token: str, attempts: int = 2) -> bool:
        for i in range(attempts):
            try:
                await store_service.consume_product_purchase(settings.app_bundle_id, product_id, purchase_token)
                return True
            except Exception as e:
                logger.warning("[consume] attempt %s/%s failed: %s", i + 1, attempts, e)
        return False

    # ── 서버 알림: 구독 갱신 ──────────────────────────────────────────
    async def handle_rtdn_renewal(self, purchase_token: str, subscription_id: str, store_service) -> None:
        """RTDN 구독 갱신(type=2) 처리 — 만료일 연장 + 월 크레딧 지급."""
        # 알림 본문이 아니라 스토어 원본을 다시 조회한다
        subs_data = await store_service.verify_subscription(settings.app_bundle_id, purchase_token)
        line_items = subs_data.get("lineItems", [])
        if not line_items or not line_items[0].get("expiryTime"):
            logger.warning("[RTDN] renewal: no lineItems, token=%s", purchase_token[:20])
            return
        end_date = _iso_to_kst_naive(line_items[0]["expiryTime"])

        # 현재 토큰 또는 이전 토큰(linkedPurchaseToken — 플랜 변경 시 토큰이 바뀐다)으로 구독 행 조회
        user_subs = await self.billing_repo.get_user_subs_by_purchase_token(purchase_token)
        if not user_subs and subs_data.get("linkedPurchaseToken"):
            user_subs = await self.billing_repo.get_user_subs_by_purchase_token(subs_data["linkedPurchaseToken"])
        if not user_subs:
            logger.warning("[RTDN] renewal: user_subs not found, token=%s", purchase_token[:20])
            return

        # 알림의 subscriptionId 는 상품 그룹 ID — DB 에는 base plan ID 가 저장돼 있어 응답의 basePlanId 로 찾는다
        base_plan_id = line_items[0].get("offerDetails", {}).get("basePlanId", "")
        subscription = await self.billing_repo.get_subscription_by_store_id(base_plan_id or subscription_id, "google")

        user_subs.end_date = end_date
        user_subs.purchase_token = purchase_token
        user_subs.resubscribe = True
        user_subs.voice_seconds_used = 0  # 새 구독 주기 리셋

        # 갱신 이력 + 크레딧 지급 — 같은 end_date 가 이미 있으면 재전송된 알림이므로 건너뛴다
        existing = await self.billing_repo.get_renewal_by_user_sub_enddate(
            user_subs.user_id, subscription.id if subscription else None, end_date,
        )
        if not existing:
            await self.billing_repo.create_renewal(
                user_id=user_subs.user_id, user_subs_id=user_subs.id,
                subscription_id=subscription.id if subscription else None,
                purchase_token=purchase_token, provider=user_subs.provider, end_date=end_date,
            )
            if subscription and (subscription.monthly_credit or 0) > 0:
                user = await self.billing_repo.get_user_by_id(user_subs.user_id)
                if user:
                    await self.billing_repo.grant_credits(
                        user, subscription.monthly_credit, "subscription", subscription.id, "구독 월 크레딧",
                    )
        else:
            logger.info("[RTDN] renewal dedup skip: user_id=%s, end_date=%s", user_subs.user_id, end_date)

        await self.billing_repo.db.commit()

    async def handle_rtdn_cancel(self, purchase_token: str) -> None:
        """RTDN 구독 취소 · 만료(type=3, 13) — 자동 갱신 플래그만 내린다. 만료일까지는 혜택 유지."""
        user_subs = await self.billing_repo.get_user_subs_by_purchase_token(purchase_token)
        if not user_subs:
            return
        user_subs.resubscribe = False
        await self.billing_repo.db.commit()

    # ... (생략: _resolve_credit_amount · handle_apple_renewal · handle_apple_expired · handle_apple_cancel)
