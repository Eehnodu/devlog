# 출처: 풀스택 베이스 템플릿 (2026.04~) — 새 프로젝트가 그대로 가져가는 Redis 서비스. 자료구조별 최소 메서드 + 분산 락
# ServiceProvider 가 요청 시점에 lazy 로 만들어 주입한다. Redis 를 DB 처럼 쓰지 않고 캐시 · 상태 · 동시성 제어에만 쓴다는 원칙을 주석으로 남겼다.
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
        if not self._client:
            self._client = redis.Redis(
                host=self._host, port=self._port, decode_responses=True
            )
        return self._client

    # =====================================================
    # Key - Value (String)
    # =====================================================
    # 단일 값 + TTL이 필요한 경우 사용
    # - 인증 코드 / OTP · 토큰 · 외부 API 응답 캐시 · 임시 플래그
    # =====================================================

    async def set(self, key: str, value: str, expire: int = 300):
        """key에 value 저장 + TTL 설정 (기본 300초)"""
        await self.client.set(key, value, ex=expire)

    async def get(self, key: str):
        return await self.client.get(key)

    async def delete(self, key: str):
        await self.client.delete(key)

    async def exists(self, key: str):
        """1: 존재 / 0: 없음"""
        return await self.client.exists(key)

    # =====================================================
    # Hash
    # =====================================================
    # 하나의 엔티티에 속한 여러 필드를 묶어서 관리할 때 사용
    # - 유저 상태 캐시 · 세션 메타데이터 · 작업 상태(progress, status 등)
    # 특징: 부분 업데이트 가능, 동시성에 비교적 안전
    # =====================================================

    async def hset(self, name: str, mapping: dict):
        await self.client.hset(name, mapping=mapping)

    async def hgetall(self, name: str):
        return await self.client.hgetall(name)

    async def hget(self, name: str, field: str):
        return await self.client.hget(name, field)

    # =====================================================
    # Set
    # =====================================================
    # 중복 없는 집합(상태/소속/처리 여부)을 관리할 때 사용
    # - 온라인 유저 목록 · 처리 중인 작업 목록 · 이미 처리한 ID 기록 (멱등성)
    # 특징: 중복 자동 제거, add / remove 가 여러 번 호출돼도 안전
    # =====================================================

    async def sadd(self, name: str, member):
        await self.client.sadd(name, member)

    async def srem(self, name: str, member):
        """멤버가 없어도 에러 없이 통과 — finally 블록에서 쓰기 좋음"""
        await self.client.srem(name, member)

    async def smembers(self, name: str):
        """멤버 수가 많을 경우 사용 주의 — 운영/디버깅/소규모 집합용"""
        return await self.client.smembers(name)

    # =====================================================
    # Lock
    # =====================================================
    # 여러 요청/서버 환경에서 "동시에 하나만 실행돼야 하는 코드" 보호용
    # - 중복 실행되면 안 되는 초기화 로직 · cache miss 시 단일 채우기
    # =====================================================

    async def lock(self, name: str, timeout: int = 10):
        """
        Redis 기반 분산 락 획득

        주의:
        - 호출한 쪽에서 반드시 release 필요
        - try/finally 패턴 권장

        timeout:
        - 락 유지 시간 (초)
        """
        lock = await self.client.lock(name, timeout=timeout)
        await lock.acquire()
        return lock


# ---- ServiceProvider 등록 (core/provider/http/service.py) ----
# @property
# def redis_service(self):
#     if not self._redis_service:
#         self._redis_service = RedisService()
#     return self._redis_service
