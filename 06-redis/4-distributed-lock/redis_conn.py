# 출처: 팬 플랫폼 서비스 (2026.05~) — 웹 서버용 전역 클라이언트와, Celery 태스크 전용 "이번 루프에서만 쓰는" 커넥션을 나눈 것
# 전역 클라이언트는 처음 사용된 이벤트 루프에 묶인다. 태스크마다 새 루프를 만드는 Celery 에서 그대로 쓰면 두 번째부터 죽은 루프의 커넥션을 잡는다.
import os
from contextlib import asynccontextmanager

import redis.asyncio as redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

SESSION_TTL = int(os.getenv("SESSION_TTL", "3600"))

# FastAPI 프로세스가 공유하는 클라이언트 (루프가 하나라 문제 없음)
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
)


@asynccontextmanager
async def redis_conn():
    """이번 이벤트 루프에서만 쓰는 새 커넥션. 다 쓰면 닫는다.

    전역 redis_client 는 커넥션 풀이 '처음 사용된 이벤트 루프'에 묶인다. FastAPI 는 루프가
    하나라 문제가 없지만, Celery 태스크는 asyncio.run() 으로 매번 새 루프를 만들기 때문에
    두 번째 실행부터 죽은 루프의 커넥션을 잡아 예외가 난다(조용히 스킵되기 쉽다).
    워커에서 Redis 를 쓸 때는 반드시 이걸 쓸 것.
    """
    client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
    )
    try:
        yield client
    finally:
        try:
            await client.aclose()
        except Exception:
            pass  # 종료 실패는 무시 — 루프와 함께 정리된다
