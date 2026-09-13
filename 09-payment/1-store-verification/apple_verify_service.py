# 출처: 팬 플랫폼 서비스 (2026.06) — 애플 인앱결제: 서버 알림 JWS 를 루트 인증서 체인으로 검증(운영 먼저, 실패 시 샌드박스), 거래 · 구독은 스토어 서버 API 로 재조회
# 웹훅 URL 은 외부에서 알면 누구나 호출할 수 있으므로 서명이 애플 루트로 이어지는지 먼저 본다.

import logging
from functools import lru_cache

import httpx
from fastapi import HTTPException

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

BUNDLE_ID = settings.app_bundle_id
APP_APPLE_ID = settings.app_apple_id  # App Store Connect 의 앱 숫자 ID (서명 검증에 필요)


# ── App Store Server Notification 서명 검증 ─────────────────────────
@lru_cache(maxsize=1)
def _root_cert_bytes() -> bytes:
    """애플 루트 인증서(DER) 를 bytes 로 로드. 공개 인증서라 저장소에 함께 둔다."""
    path = settings.BASE_DIR / "app" / "core" / "config" / "AppleRootCA-G3.cer"
    return path.read_bytes()


@lru_cache(maxsize=2)
def _verifier(environment):
    """환경별 SignedDataVerifier. 애플은 운영 · 샌드박스 알림을 같은 URL 로 보낸다."""
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
    return SignedDataVerifier(
        root_certificates=[_root_cert_bytes()],
        enable_online_checks=False,   # OCSP 온라인 폐기 확인은 생략 (웹훅 응답 신뢰성 우선)
        environment=environment,
        bundle_id=BUNDLE_ID,
        app_apple_id=APP_APPLE_ID,
    )


def verify_apple_notification(signed_payload: str):
    """App Store Server Notification(JWS) 을 검증 · 디코딩한다.

    서명이 애플 루트로 이어지고 bundle_id / app_apple_id 가 일치할 때만 통과.
    위조 · 변조 페이로드는 VerificationException 으로 거부된다.
    운영 → 샌드박스 순으로 시도 (환경은 verify 내부에서 대조됨).

    반환: (notification_type, subtype, txn_info) — txn_info 는 핸들러가 쓰는 dict.
    """
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import VerificationException

    last_exc = None
    decoded = None
    for env in (Environment.PRODUCTION, Environment.SANDBOX):
        try:
            decoded = _verifier(env).verify_and_decode_notification(signed_payload)
            break
        except VerificationException as e:
            last_exc = e
    if decoded is None:
        raise last_exc

    # 거래 정보도 같은 verifier 로 검증 · 디코딩
    txn_info = None
    data = decoded.data
    if data and data.signedTransactionInfo:
        env = data.environment or Environment.PRODUCTION
        txn = _verifier(env).verify_and_decode_signed_transaction(data.signedTransactionInfo)
        txn_info = {
            "productId": txn.productId,
            "originalTransactionId": txn.originalTransactionId,
            "expiresDate": txn.expiresDate,
            "purchaseDate": txn.purchaseDate,
        }

    return decoded.rawNotificationType, decoded.rawSubtype, txn_info


# ── 스토어 서버 API 재조회 ─────────────────────────────────────────────
def _decode_signed_payload(jws: str) -> dict:
    """스토어 서버 API 가 돌려준 JWS 페이로드 디코딩. (TLS 로 애플에서 직접 받은 응답이라 여기서는 서명 재검증을 하지 않는다)"""
    import base64
    import json
    try:
        parts = jws.split(".")
        if len(parts) < 2:
            return {}
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        return json.loads(base64.b64decode(padded).decode("utf-8"))
    except Exception:
        return {}


class AppleStoreService:
    def _get_token(self) -> str:
        """App Store Connect API 용 ES256 JWT — 키 ID · 발급자 ID · 개인키는 설정에서 읽는다."""
        # ... (생략: jwt.encode(..., algorithm="ES256"), 20분 캐시)
        raise NotImplementedError

    async def verify_iap_transaction(self, transaction_id: str) -> dict:
        """소모성 인앱 구매 검증. 운영 → 샌드박스 자동 폴백."""
        token = self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            for base in (
                "https://api.storekit.itunes.apple.com",
                "https://api.storekit-sandbox.itunes.apple.com",
            ):
                resp = await client.get(
                    f"{base}/inApps/v2/transactions/{transaction_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.is_success:
                    return _decode_signed_payload(resp.json().get("signedTransactionInfo", ""))
        raise HTTPException(status_code=400, detail="Apple transaction not found")

    async def verify_iap_subscription(self, original_transaction_id: str) -> dict:
        """구독 검증. 운영 → 샌드박스 자동 폴백. status 1=active 2=expired 4=grace_period"""
        token = self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            for base in (
                "https://api.storekit.itunes.apple.com",
                "https://api.storekit-sandbox.itunes.apple.com",
            ):
                resp = await client.get(
                    f"{base}/inApps/v1/subscriptions/{original_transaction_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.is_success:
                    last_txn = resp.json().get("data", [{}])[0].get("lastTransactions", [{}])[0]
                    return {
                        "status": last_txn.get("status"),
                        "transaction_info": _decode_signed_payload(last_txn.get("signedTransactionInfo", "")),
                        "renewal_info": _decode_signed_payload(last_txn.get("signedRenewalInfo", "")),
                    }
        raise HTTPException(status_code=400, detail="Apple subscription not found")
