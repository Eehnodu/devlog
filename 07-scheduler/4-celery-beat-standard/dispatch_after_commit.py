# 출처: 팬 플랫폼 서비스 (2026.05~) — 요청 경로에서 큐에 넣는 순서: DB 에 "대기" 행을 먼저 커밋한 뒤 Celery 태스크를 부른다
# 워커가 먼저 깨어나 행을 못 찾는 경쟁을 피하고, 큐 적재가 실패해도 대기 상태가 남아 다음 보충 배치가 주워 간다.
import logging

from app.module.content.content_repository import ContentRepository

logger = logging.getLogger(__name__)

# 등록 시 미리 번역해 두는 언어 목록 (예시)
AUTO_TRANSLATE_LANGUAGES = ["en", "ja", "zh", "es", "fr"]


class ContentService:
    def __init__(self, content_repo: ContentRepository):
        self.content_repo = content_repo

    async def create_content(self, request) -> dict:
        body = await request.json()
        content = await self.content_repo.create(
            title=body.get("title"),
            description=body.get("description"),
        )
        await self.content_repo.db.commit()  # 콘텐츠 행이 먼저 확정된다

        # 번역 대상 콘텐츠(제목/설명이 있는 경우)에 자동 번역 트리거
        if content and (content.title or content.description):
            await self.dispatch_auto_translate(content.id)

        return {"id": content.id}

    async def dispatch_auto_translate(self, content_id: int) -> None:
        """콘텐츠 제목/설명(한국어)을 나머지 언어로 번역 — 백그라운드(Celery)로 트리거."""
        # 1) 언어별 번역 행을 "pending" 으로 먼저 만든다 (레포지토리가 커밋까지 한다)
        for lang in AUTO_TRANSLATE_LANGUAGES:
            await self.content_repo.upsert_translation(content_id, lang, {"status": "pending"})

        # 2) 그 다음에 큐에 넣는다. 워커는 pending 행을 찾아 completed / failed 로 바꾼다.
        try:
            from app.worker.translation_task import translate_content

            translate_content.delay(content_id)
        except Exception as e:
            # 브로커 장애로 여기까지 못 가도 pending 행은 남는다 → 1분마다 도는 보충 배치가 주워 간다
            logger.error(f"[content dispatch_auto_translate] celery dispatch failed content_id={content_id}: {e}")

    async def dispatch_retranslate(self, content_id: int, language: str) -> None:
        """특정 언어만 재번역 — 관리자가 결과를 보고 다시 요청할 때."""
        await self.content_repo.upsert_translation(content_id, language, {"status": "pending"})
        try:
            from app.worker.translation_task import translate_content

            translate_content.delay(content_id, [language])
        except Exception as e:
            logger.error(f"[content dispatch_retranslate] celery dispatch failed content_id={content_id} lang={language}: {e}")


# ---- 같은 원칙이 실시간 알림에도 적용된다 (user_request_service.py) ----
#
#     message = await self.mate_repo.append_message(thread_id=thread.id, role="celebrity", content=text)
#     # 인용 링크(response_message_id)를 먼저 커밋한 뒤 push 해야,
#     # 팬이 소켓 수신 직후 요청 목록을 다시 조회할 때 링크가 매칭된다.
#     await self.request_repo.update_status(request, status="fulfilled", response_message_id=message.id)
#     await broadcast_chat_message(thread.id, message)
#     await notify_user_unread(request.user_id)
