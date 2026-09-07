# 출처: 전시관 AI 안내 서비스 (2026.03~) — 앱 전체가 공유하는 Redis 서비스 인스턴스 하나 + Pub/Sub · 패턴 삭제 추가
# 이전에는 요청마다 새 클라이언트(=새 커넥션 풀)를 만들어 연결이 계속 늘었다. 모듈 끝에서 한 번 만들어 import 해 쓴다.
import redis.asyncio as redis

from app.core.config.settings import settings


class RedisService:
    """
    Redis 접근을 단순화하기 위한 공통 서비스 클래스
    - Redis를 DB처럼 쓰지 않고
    - 캐시 / 상태 관리 / 동시성 제어 용도로만 사용
    """

    def __init__(self, host: str = None, port: int = None):
        self._host = host or settings.redis_host
        self._port = port or settings.redis_port
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        # 첫 접근 때 한 번만 생성. redis.asyncio.Redis 는 내부에 커넥션 풀을 갖고 있어
        # 이 객체를 공유하면 풀도 공유된다.
        if not self._client:
            self._client = redis.Redis(
                host=self._host, port=self._port, decode_responses=True
            )
        return self._client

    # ---------- Key - Value ----------
    # 단일 값 + TTL. 인증 코드 · 토큰 · 외부 API 응답 캐시 · 임시 플래그
    async def set(self, key: str, value: str, expire: int = 300):
        await self.client.set(key, value, ex=expire)

    async def get(self, key: str):
        return await self.client.get(key)

    async def delete(self, key: str):
        await self.client.delete(key)

    async def exists(self, key: str):
        return await self.client.exists(key)

    # ---------- Hash ----------
    async def hset(self, name: str, mapping: dict):
        await self.client.hset(name, mapping=mapping)

    async def hgetall(self, name: str):
        return await self.client.hgetall(name)

    # ---------- Set ----------
    # 중복 없는 집합. 온라인 유저 목록 · 처리 중인 작업 · 이미 처리한 ID
    async def sadd(self, name: str, member):
        await self.client.sadd(name, member)

    async def srem(self, name: str, member):
        await self.client.srem(name, member)

    async def smembers(self, name: str):
        return await self.client.smembers(name)

    # ---------- Lock ----------
    # 여러 요청/서버 환경에서 "동시에 하나만 실행돼야 하는 코드" 보호용
    async def lock(self, name: str, timeout: int = 10):
        """
        Redis 기반 분산 락 획득. 호출한 쪽에서 반드시 release — try/finally 권장.
        timeout: 락 유지 시간 (초)
        """
        lock = await self.client.lock(name, timeout=timeout)
        await lock.acquire()
        return lock

    # =====================================================
    # Pub / Sub
    # =====================================================
    # 워커 간 실시간 이벤트 전달 용도
    #
    # 사용 예:
    # - 모바일 → 키오스크 업로드 완료 알림 (SSE 중계)
    # =====================================================

    async def publish(self, channel: str, message: str) -> int:
        """channel에 message 발행"""
        return await self.client.publish(channel, message)

    async def subscribe(self, channel: str):
        """
        channel 구독 — pubsub 객체 반환
        호출 후 pubsub.listen()으로 메시지 수신
        """
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    # =====================================================
    # Pattern Delete
    # =====================================================

    async def delete_pattern(self, pattern: str):
        """
        패턴에 매칭되는 모든 키 삭제
        예: delete_pattern("mobile:artwork:42:*")  — 작품 수정 시 언어별 캐시 일괄 무효화
        """
        keys = await self.client.keys(pattern)
        if keys:
            await self.client.delete(*keys)


# 모듈 단위 싱글턴 — 라우터 · 서비스 · 워커가 전부 이 하나를 import 한다
redis_service = RedisService()
