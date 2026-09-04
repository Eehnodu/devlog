# 출처: 전시관 AI 안내 서비스 (2026.06) — 1대다 단체 방. 안내원 · 참여자 소켓이 같은 방 딕셔너리를 고치므로 asyncio 락으로 보호하고, 안내원이 끊기면 유예 시간 뒤에 방을 정리한다
import asyncio

from fastapi import WebSocket

from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class DocentLiveService:
    # 참여자 전원이 튕긴다 → 10분 안에 돌아오면 그대로 이어진다.
    # 의도적 종료는 force_cleanup 이 따로 처리한다.
    DOCENT_GRACE_SECONDS = 600

    def __init__(self):
        self._rooms: dict[str, dict] = {}  # code -> {"docent": ws, "visitors": {id: {"ws", "lang"}}}
        self._cleanup_tasks: dict[str, asyncio.Task] = {}
        self._force_closed: set[str] = set()  # 명시적 종료된 방 코드
        # 도슨트가 안내 중인 방 — 그 사이 참여자 마이크를 막는다
        self._speaking: dict[str, bool] = {}
        # 여러 코루틴(안내원 소켓, 참여자 소켓 여러 개, 정리 태스크)이 _rooms 를 함께 고친다.
        # await 사이에 상태가 바뀌는 것을 막기 위해 방 상태를 만질 때는 항상 이 락 안에서.
        self._lock = asyncio.Lock()

    def _spawn(self, coro, label: str) -> asyncio.Task:
        async def _wrapped():
            try:
                await coro
            except Exception as e:
                logger.error("[%s] background task error: %s", label, e)
        return asyncio.create_task(_wrapped())

    def _ensure_room(self, code: str):
        if code not in self._rooms:
            self._rooms[code] = {"docent": None, "visitors": {}}

    def _docent_online(self, code: str) -> bool:
        return self._rooms.get(code, {}).get("docent") is not None

    def _get_visitors(self, code: str) -> dict:
        return self._rooms.get(code, {}).get("visitors", {})

    # ── WS 핸들러 (안내원) ───────────────────────────────────

    async def docent_connect(self, websocket: WebSocket, redis_service, gemini_docent_service):
        await websocket.accept()
        docent_id = websocket.user_id  # 로그인 데코레이터가 심어 준 값

        code = await redis_service.get(f"docent:docent:{docent_id}")  # 방 코드는 Redis 에
        if not code:
            await websocket.close(code=4004, reason="세션 코드 없음")
            return

        async with self._lock:
            # 재연결이면 예약된 방 정리를 취소한다
            if code in self._cleanup_tasks:
                self._cleanup_tasks.pop(code).cancel()
                logger.info("[docent] 재연결 — cleanup 취소 code=%s", code)
            self._ensure_room(code)
            self._rooms[code]["docent"] = websocket

        await websocket.send_json({"type": "connected", "code": code})
        await self._broadcast_all(code, {"type": "docent_joined"}, exclude_ws=websocket)

        try:
            # ... (안내원 발화 수신 → 참여자 언어별 번역 전송, 생략)
            pass
        finally:
            async with self._lock:
                room = self._rooms.get(code)
                if room:
                    room["docent"] = None

                if code in self._force_closed:  # 의도적 종료면 유예 없이 끝
                    self._force_closed.discard(code)
                    return

            # 도슨트가 나간 채로 참여자 마이크가 잠겨 있으면 안 된다
            await self._set_speaking(code, False)
            await self._broadcast_all(code, {"type": "docent_left"})

            async def _delayed_cleanup():
                await asyncio.sleep(self.DOCENT_GRACE_SECONDS)
                async with self._lock:
                    if self._docent_online(code):  # 유예 중 돌아왔으면 그대로 둔다
                        return
                    visitors_snapshot = list(self._get_visitors(code).values())

                logger.info("[docent] grace period 만료 — 방 파괴 code=%s", code)
                # 소켓 close 는 락 밖에서 — await 가 길어질 수 있다
                for info in visitors_snapshot:
                    try:
                        await info["ws"].close(code=1000, reason="DOCENT_EXIT")
                    except Exception:
                        pass
                await redis_service.delete(f"docent:room:{code}")
                async with self._lock:
                    self._rooms.pop(code, None)
                    self._cleanup_tasks.pop(code, None)
                    self._speaking.pop(code, None)

            async with self._lock:
                self._cleanup_tasks[code] = self._spawn(_delayed_cleanup(), "docent.cleanup")

    # ── WS 핸들러 (방문자) ───────────────────────────────────

    async def visitor_connect(self, websocket: WebSocket, redis_service, gemini_docent_service):
        await websocket.accept()
        code = websocket.query_params.get("code", "").upper()
        lang = websocket.query_params.get("lang", "en")

        if not await redis_service.exists(f"docent:room:{code}"):
            await websocket.close(code=4004, reason="유효하지 않은 코드")
            return

        # 참여자 번호는 Redis 카운터로 — 워커가 여럿이어도 번호가 겹치지 않는다
        visitor_id = str(await redis_service.client.incr(f"docent:visitor_counter:{code}"))

        async with self._lock:
            self._ensure_room(code)
            self._rooms[code]["visitors"][visitor_id] = {"ws": websocket, "lang": lang}

        await websocket.send_json({"type": "connected", "visitor_id": visitor_id})
        # ... (참여자 발화 수신 · 지난 대화 재생, 생략)

    async def _broadcast_all(self, code: str, message: dict, exclude_ws: WebSocket | None = None):
        async with self._lock:
            targets = [v["ws"] for v in self._get_visitors(code).values()]
            docent = self._rooms.get(code, {}).get("docent")
        if docent and docent is not exclude_ws:
            targets.append(docent)
        for ws in targets:
            if ws is exclude_ws:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def _set_speaking(self, code: str, value: bool):
        async with self._lock:
            self._speaking[code] = value
        await self._broadcast_all(code, {"type": "speaking", "value": value})
