# 출처: 전시관 AI 안내 서비스 (2026.03~) — 관람객 앱의 작품 목록 응답을 JSON 문자열로 Redis 에 10일간 캐시
# 전시 · 언어 · 페이지가 키에 들어가고, 관리자가 작품을 고치면 패턴 삭제로 그 전시의 캐시를 한 번에 비운다.
import json
import logging

from fastapi import Request

from app.core.utils.response import fail, success
from app.module.artwork.artwork_repository import ArtworkRepository
from app.module.infra.redis.redis_service import RedisService

logger = logging.getLogger(__name__)


class ArtworkService:
    CACHE_TTL = 864000  # 10일 — 전시 기간 동안 작품 설명은 거의 바뀌지 않는다

    def __init__(self, artwork_repo: ArtworkRepository, redis_service: RedisService):
        self.artwork_repo = artwork_repo
        self.redis_service = redis_service

    # =========================   MOBILE   =========================
    async def get_artworks_mobile(self, request: Request):
        qp = request.query_params
        exhibition_id = qp.get("exhibition_id")
        agent_id = qp.get("agent_id")
        lang_code = qp.get("lang", "ko")
        page = int(qp.get("page", 1))
        page_size = int(qp.get("page_size", 20))

        # 조회 조건이 전부 키에 들어간다 — 조건이 하나라도 다르면 다른 캐시
        cache_key = f"mobile:artwork:{exhibition_id or 'agent'}:{agent_id}:{lang_code}:{page}:{page_size}"
        cached = await self.redis_service.get(cache_key)
        if cached:
            return success(json.loads(cached))

        try:
            artworks, total = await self.artwork_repo.get_artworks_mobile(
                int(exhibition_id) if exhibition_id else None, lang_code, page, page_size, agent_id=agent_id
            )
            # 섹션 헤더 메타 — 전시 모드에서만 (agent 전체 모드는 섹션 개념 없음)
            sections = (
                await self.artwork_repo.get_mobile_section_meta(int(exhibition_id), lang_code)
                if exhibition_id
                else []
            )
            data = {
                "sections": sections,
                "artworks": [
                    {
                        "id": a.id,
                        "title": a.artworklangs[0].title if a.artworklangs else None,
                        "description": a.artworklangs[0].description if a.artworklangs else None,
                        "audio_duration": a.artworklangs[0].audio_duration if a.artworklangs else None,
                        "audio_path": a.artworklangs[0].audio_path if a.artworklangs else None,
                        "images": [{"id": img.id, "url": img.url} for img in a.artworkimages],
                    }
                    for a in artworks
                ],
                "total": total,
                "has_next": (page * page_size) < total,
            }
            await self.redis_service.set(cache_key, json.dumps(data), expire=self.CACHE_TTL)
            return success(data)
        except Exception as e:
            logger.error(f"Failed to get artworks mobile: {e}")
            return fail("Failed to get artworks mobile", "FAILED_TO_GET_ARTWORKS_MOBILE", 500)

    # =========================   ADMIN   =========================
    async def _invalidate_artwork_caches(self, exhibition_id: int):
        """관리자가 작품을 추가 · 수정 · 삭제하면 그 전시의 언어 · 페이지별 캐시를 전부 비운다."""
        await self.redis_service.delete_pattern(f"mobile:artwork:{exhibition_id}:*")

    async def update_artwork(self, request: Request):
        body = await request.json()
        artwork_id = int(body.get("artwork_id"))
        exhibition_id = int(body.get("exhibition_id"))

        # ... (생략) DB 갱신, 번역 · 음성 재생성 큐 적재
        await self._invalidate_artwork_caches(exhibition_id)
        return success({"id": artwork_id})
