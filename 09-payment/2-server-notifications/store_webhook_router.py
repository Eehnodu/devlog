# 출처: 팬 플랫폼 서비스 (2026.06) — 구글 RTDN(Pub/Sub 푸시) · 애플 서버 알림 수신 라우터. 알림은 "무언가 바뀌었다" 는 신호로만 쓰고 원본은 다시 조회한다
# 두 스토어 모두 실패 응답을 주면 재시도하므로, 처리 실패도 예외를 삼키고 200 을 돌려준다.

import base64
import json
import logging

from fastapi import APIRouter

from app.core.config.settings import settings
from app.core.provider.http.endpoint import with_provider
from app.core.provider.http.service import ServiceProvider
from app.module.infra.apple.apple_verify_service import verify_apple_notification

router = APIRouter()
logger = logging.getLogger(__name__)

PACKAGE_NAME = settings.app_bundle_id


# ── 구글: Real-time Developer Notifications ────────────────────────────
@router.post("/aos/rtdn")
@with_provider
async def receive_rtdn(p: ServiceProvider):
    """Google Play 실시간 개발자 알림 (Pub/Sub Push) 수신."""
    try:
        body = await p.request.json()
        data_b64 = body.get("message", {}).get("data", "")
        if not data_b64:
            return {}

        payload = json.loads(base64.b64decode(data_b64).decode())
        sub_notif = payload.get("subscriptionNotification")
        if not sub_notif:
            return {}

        notification_type = sub_notif.get("notificationType")
        purchase_token = sub_notif.get("purchaseToken")
        subscription_id = sub_notif.get("subscriptionId")  # 스토어 구독 상품 ID
        logger.info("[RTDN] type=%s, subscription=%s", notification_type, subscription_id)

        if not purchase_token:
            return {}

        # 알림 본문의 값은 쓰지 않는다 — 핸들러가 purchase_token 으로 스토어에 다시 물어 확정한다
        if notification_type == 2:  # SUBSCRIPTION_RENEWED
            await p.billing_service.handle_rtdn_renewal(purchase_token, subscription_id, p.google_play_service)
        elif notification_type in (3, 13):  # SUBSCRIPTION_CANCELED / EXPIRED
            await p.billing_service.handle_rtdn_cancel(purchase_token)

    except Exception as e:
        logger.warning("[RTDN] error: %s", e)
    return {}


# ── 애플: App Store Server Notifications ───────────────────────────────
@router.post("/ios/notification")
@with_provider
async def receive_apple_notification(p: ServiceProvider):
    """App Store Connect 에 등록된 URL 로 애플이 POST 요청을 보낸다.
    항상 200 반환 — 실패 시 애플이 재시도하므로 예외를 삼켜야 한다."""
    try:
        body = await p.request.json()
        signed_payload = body.get("signedPayload", "")
        if not signed_payload:
            return {}

        # JWS 서명 검증 → 위조 요청은 여기서 예외로 거부됨 (핸들러까지 못 감)
        notification_type, subtype, txn_info = verify_apple_notification(signed_payload)
        logger.info("[ASSN] type=%s subtype=%s", notification_type, subtype)

        if notification_type == "DID_RENEW":
            await p.billing_service.handle_apple_renewal(txn_info or {})
        elif notification_type in ("EXPIRED", "GRACE_PERIOD_EXPIRED"):
            await p.billing_service.handle_apple_expired(txn_info or {})
        elif notification_type == "DID_CHANGE_RENEWAL_STATUS":
            if subtype == "AUTO_RENEW_DISABLED":
                await p.billing_service.handle_apple_cancel(txn_info or {})
        # SUBSCRIBED, DID_FAIL_TO_RENEW, REFUND 등은 로그만

    except Exception as e:
        # 검증 실패(위조 의심) 포함 — 애플 재시도를 위해 항상 200 유지, 로그만 남김
        logger.warning("[ASSN] rejected/error: %s", e)

    return {}
