# 출처: 전시관 AI 안내 서비스 (2026.03~) — 휴대폰에서 올린 사진을 키오스크 화면에 즉시 띄우는 Pub/Sub → SSE 중계
# 키오스크는 채널을 구독한 채 SSE 로 대기하고, 휴대폰 업로드가 끝나면 서비스가 같은 채널에 발행한다. 워커가 달라도 Redis 가 이어 준다.
import json
import os
import uuid

import aiofiles
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.config.settings import settings
from app.core.utils.response import fail, success
from app.module.infra.redis.redis_service import redis_service

router = APIRouter()


# ---------------- 구독하는 쪽 (키오스크) ----------------
@router.get("/upload/subscribe")
async def subscribe_upload(request: Request, url: str):
    redis = redis_service
    channel = f"palette:upload:{url}"

    # 이미 업로드된 결과가 있으면 바로 반환 — 구독 전에 발행이 끝난 경우를 놓치지 않기 위한 보조 키
    cached = await redis.get(f"palette:upload:result:{url}")

    async def event_stream():
        if cached:
            yield f"data: {cached}\n\n"
            return

        pubsub = await redis.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    break  # 한 건 받으면 끝. 키오스크가 다음 화면으로 넘어간다
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------- 발행하는 쪽 (휴대폰 업로드 서비스) ----------------
class PaletteService:
    def __init__(self, agent_repo, redis):
        self.agent_repo = agent_repo
        self.redis = redis

    async def upload_palette_image(self, request):
        url = request.query_params.get("url")
        token = request.query_params.get("token")
        agent = await self.agent_repo.get_agent_by_url(url)
        if not agent:
            return fail("agent does not exists", "AGENT_DOES_NOT_EXISTS", 404)

        if not token or not self._validate_token(url, token):
            return fail("invalid or expired token", "INVALID_TOKEN", 403)

        form = await request.form()
        image = form.get("image")
        if not image:
            return fail("image is required", "IMAGE_REQUIRED", 400)

        ext = os.path.splitext(image.filename)[1] or ".jpg"
        filename = f"{uuid.uuid4()}{ext}"
        save_dir = settings.MEDIA_ROOT / "palette"
        save_dir.mkdir(parents=True, exist_ok=True)

        content = await image.read()
        async with aiofiles.open(save_dir / filename, "wb") as f:
            await f.write(content)

        image_url = f"/media/palette/{filename}"
        payload = json.dumps({"imageUrl": image_url})

        # 구독 중인 키오스크에 바로 전달하고, 아직 구독 전이었다면 10분간 결과 키로 받아 가게 한다
        await self.redis.publish(f"palette:upload:{url}", payload)
        await self.redis.set(f"palette:upload:result:{url}", payload, expire=600)

        return success({"imageUrl": image_url})

    def _validate_token(self, url: str, token: str) -> bool:
        # ... (생략) QR 에 실린 1회성 토큰 검증
        return True
