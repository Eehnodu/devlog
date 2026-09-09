# 출처: 전시관 AI 안내 서비스 (2026.03~) — FastAPI 프로젝트의 Celery 앱 설정과 Beat 스케줄. 매일 자정 · 매시 정각 배치가 코드에 선언돼 있다
# 워커 메모리 · 재시작 · ack 시점 옵션에 이유를 주석으로 남겼다. 팬 플랫폼 서비스도 같은 설정 파일을 쓴다.
from celery import Celery
from celery.schedules import crontab

from app.core.config.settings import settings

celery_app = Celery(
    "worker",
    broker=f"redis://{settings.redis_host}:{settings.redis_port}/0",
    backend=f"redis://{settings.redis_host}:{settings.redis_port}/0",
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=False,
    worker_pool="prefork",
    worker_concurrency=2,  # 번역/TTS 태스크 최대 2개 병렬 처리 (메모리 안정성 우선)
    result_expires=3600,  # 태스크 결과 키 1시간 후 자동 삭제
    worker_max_tasks_per_child=20,           # 20 태스크 처리 후 워커 재시작 → 메모리 누수 차단
    worker_max_memory_per_child=300_000,     # 300MB 초과 시 워커 재시작 (KB 단위)
    worker_prefetch_multiplier=1,            # 큐에서 한 번에 1개씩만 가져감 → 한 워커가 미리 점유 X
    task_acks_late=True,                     # 작업 완료 후 ack → 워커 죽어도 메시지 손실 X
    task_reject_on_worker_lost=True,         # 워커 강제 종료 시 메시지 재큐잉
    task_soft_time_limit=300,                # 5분 후 SoftTimeLimitExceeded 발생
    task_time_limit=420,                     # 7분 후 hard kill
)

# 태스크 모듈은 여기서 명시적으로 import 해야 워커에 등록된다
from app.worker import compose_tasks, trans_tasks, tts_tasks  # noqa: E402, F401

celery_app.conf.beat_schedule = {
    "sweep-missing-artwork-audio": {
        "task": "app.worker.tts_tasks.sweep_missing_artwork_audio",
        "schedule": crontab(hour=0, minute=0),  # 매일 KST 자정 — 낮에 실패한 음성 합성 누락분을 밤에 보충
        "kwargs": {"limit": 200},
    },
    # 발급 신분증(관람객 사진 포함)은 24시간만 보관. 파일별 나이로 지우므로
    # 자주 돌수록 보관 시간이 정확해진다(매시 정각 → 최대 24~25시간).
    "sweep-old-id-cards": {
        "task": "app.worker.compose_tasks.sweep_old_id_cards",
        "schedule": crontab(minute=0),  # 매시 정각
        "kwargs": {"keep_hours": 24},
    },
}

# ---- 팬 플랫폼 서비스의 Beat 는 초 단위 간격형이다 (같은 파일 구조, 스케줄만 다름) ----
# beat_schedule = {
#     "dispatch-pending-notifications": {"task": "...notification_task.dispatch_pending", "schedule": 60.0},
#     "retry-unconsumed-purchases":     {"task": "...billing_task.retry_unconsumed_purchases", "schedule": 300.0},
#     "sweep-chat-ko":                  {"task": "...translation_task.sweep_chat_ko", "schedule": 60.0},
# }

# ---- systemd 는 웹 · 워커 · beat 를 각각 별도 유닛으로 띄운다 ----
# celery -A app.worker.celery worker --loglevel=info --concurrency=2
# celery -A app.worker.celery beat   --loglevel=info      # beat 는 반드시 1개만
