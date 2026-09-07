# 출처: AI 캐릭터 대화 서비스 (2025.11~2026.01) — WebSocket 대화 세션을 Redis 해시에 저장, TTL 3600초
# 지침 · 요약 · 대화 이력 · 로그 ID 를 필드로 나눠 담고, 저장할 때마다 만료 시간을 다시 건다.
import json

import redis.asyncio as redis


class RedisService:
    """
    Redis 접근을 단순화하기 위한 공통 서비스 클래스
    - 캐시 / 상태 관리 / 락 전용
    """

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        # 처음 쓸 때 한 번 연결. redis.asyncio 클라이언트는 내부에 커넥션 풀을 가진다.
        if not self._client:
            self._client = redis.Redis(
                host=self._host,
                port=self._port,
                decode_responses=True,
            )
        return self._client

    # ---------- Key - Value ----------
    async def set(self, key: str, value: str, expire: int = 300):
        """key에 value 저장 + TTL 설정 (기본 300초)"""
        await self.client.set(key, value, ex=expire)

    async def get(self, key: str):
        return await self.client.get(key)

    async def delete(self, key: str):
        await self.client.delete(key)

    # ---------- Hash ----------
    # 하나의 엔티티에 속한 여러 필드를 묶어서 관리할 때 사용. 부분 업데이트가 가능하다.
    async def hset(self, name: str, mapping: dict):
        await self.client.hset(name, mapping=mapping)

    async def hgetall(self, name: str):
        return await self.client.hgetall(name)

    async def hget(self, name: str, field: str):
        return await self.client.hget(name, field)

    # ... (생략) Set · Lock

    # =================== ws session ===================
    # WebSocket 한 연결 = 세션 하나. 서버 메모리 대신 Redis 에 두어
    # 재배포 · 워커 증설과 무관하게 같은 세션을 이어 갈 수 있다.

    async def get_ws_session(self, session_id: str) -> dict | None:
        key = f"ws:session:{session_id}"
        data = await self.client.hgetall(key)
        if not data:
            return None

        return {
            "instruction": data.get("instruction"),
            "summary": data.get("summary", ""),
            "history": json.loads(data.get("history", "[]")),
            "log_id": int(data["log_id"]) if data.get("log_id") else None,
        }

    async def set_ws_session(self, session_id: str, session: dict, ttl: int = 3600):
        key = f"ws:session:{session_id}"

        await self.client.hset(
            key,
            mapping={
                "instruction": session["instruction"],
                "summary": session.get("summary", ""),
                "history": json.dumps(session.get("history", [])),  # 리스트는 JSON 문자열로
                "log_id": session.get("log_id") or "",
            },
        )
        await self.client.expire(key, ttl)  # 저장할 때마다 1시간 연장 — 대화가 이어지면 살아 있다

    async def delete_ws_session(self, session_id: str):
        key = f"ws:session:{session_id}"
        await self.client.delete(key)
