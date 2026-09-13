# 출처: 팬 플랫폼 서비스 (2026.06) — 구글 플레이 인앱결제: 상품 구매 검증 · 소모품 소비 · 구독 검증 · 구독 확인(acknowledge)
# 클라이언트가 보낸 구매 토큰을 믿지 않고, 서비스 계정 토큰으로 스토어 API 에 다시 물어 확인한다.

import asyncio
import time

import httpx
from fastapi import HTTPException

from app.core.config.settings import settings

BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"

_TOKEN_TTL = 3000  # 50분 (토큰 유효시간 1시간보다 여유있게)


class GooglePlayService:
    _cached_token: str | None = None
    _token_expires_at: float = 0

    async def _get_token(self) -> str:
        """서비스 계정 키 파일로 액세스 토큰 발급 — 프로세스 안에서 캐시."""
        if self._cached_token and time.time() < self._token_expires_at:
            return self._cached_token

        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleRequest

        cred_path = settings.google_play_credentials_path
        if not cred_path:
            raise HTTPException(status_code=500, detail="Google Play credentials not configured")

        def _fetch() -> str:
            credentials = service_account.Credentials.from_service_account_file(
                str(cred_path),
                scopes=["https://www.googleapis.com/auth/androidpublisher"],
            )
            credentials.refresh(GoogleRequest())  # 동기 호출 — 스레드로 넘겨 이벤트 루프를 막지 않는다
            return credentials.token

        token = await asyncio.to_thread(_fetch)
        GooglePlayService._cached_token = token
        GooglePlayService._token_expires_at = time.time() + _TOKEN_TTL
        return token

    async def verify_product_purchase(self, package_name: str, product_id: str, purchase_token: str) -> dict:
        """단일 상품 구매 검증 — purchaseState(0=구매 완료) / consumptionState(1=이미 소비) 를 돌려준다."""
        token = await self._get_token()
        url = f"{BASE_URL}/{package_name}/purchases/products/{product_id}/tokens/{purchase_token}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if not resp.is_success:
                raise HTTPException(status_code=resp.status_code, detail=f"Play API error: {resp.text}")
            return resp.json()

    async def consume_product_purchase(self, package_name: str, product_id: str, purchase_token: str) -> None:
        """단일 상품 소비 처리 — 같은 상품을 다시 살 수 있게 만들고 acknowledge 도 포함된다."""
        token = await self._get_token()
        url = f"{BASE_URL}/{package_name}/purchases/products/{product_id}/tokens/{purchase_token}:consume"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {token}"})
            if not resp.is_success:
                raise HTTPException(status_code=resp.status_code, detail=f"Play consume error: {resp.text}")

    async def verify_subscription(self, package_name: str, purchase_token: str) -> dict:
        """구독 구매 검증 — 서버 알림 수신 후 purchase_token 으로 구독 상태(만료 시각 · 플랜 · 지역) 를 다시 조회."""
        token = await self._get_token()
        url = f"{BASE_URL}/{package_name}/purchases/subscriptionsv2/tokens/{purchase_token}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if not resp.is_success:
                raise HTTPException(status_code=resp.status_code, detail=f"Play API error: {resp.text}")
            return resp.json()

    async def acknowledge_subscription(self, package_name: str, subscription_id: str, purchase_token: str) -> None:
        """구독 수신 확인 — 3일 안에 acknowledge 하지 않으면 스토어가 결제를 자동 취소한다."""
        token = await self._get_token()
        url = f"{BASE_URL}/{package_name}/purchases/subscriptions/{subscription_id}/tokens/{purchase_token}:acknowledge"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json={})
            if not resp.is_success:
                raise HTTPException(status_code=resp.status_code, detail=f"Play acknowledge error: {resp.text}")
