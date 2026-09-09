# 출처: 세탁 서비스 앱 (2025.02~04) — Django 앱이 뜰 때 APScheduler 를 백그라운드 스레드로 함께 띄우는 초기 구조
# 웹 프로세스마다 스케줄러가 하나씩 생긴다. 워커를 늘리자 같은 반복 작업이 프로세스 수만큼 돌았다.
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from django.apps import AppConfig
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore, register_events
from pytz import timezone

# ---------------- scheduler.py ----------------
# Scheduler + Timezone
seoul_tz = timezone("Asia/Seoul")
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")  # 작업 목록을 DB 테이블에 저장
register_events(scheduler)

# 초기에는 여기서 add_job(..., "interval", minutes=1) 로 반복 작업(72시간 미확인 자동 처리 ·
# 매장 정보 갱신 · 확인품 정보 갱신)을 등록했다. 프로세스마다 같은 잡이 등록돼 중복 실행되는 문제로
# 이후 반복 작업은 전부 Celery Beat 로 옮기고 이 파일에는 1회성 예약만 남았다 (3단계 참고).
# ... (생략)


def start_scheduler():
    """APScheduler 실행"""
    if not scheduler.running:
        scheduler.start()
        print("APScheduler started successfully")


# ---------------- apps.py ----------------
class BasicConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "basic"

    def ready(self):
        """Django 서버 실행 시 APScheduler 자동 시작"""
        # runserver 는 자동 재시작용 프로세스를 하나 더 띄운다. RUN_MAIN 은 실제 서빙 프로세스에만 설정된다.
        # 하지만 운영에서 워커가 N 개면 ready() 도 N 번 불려 스케줄러가 N 개 뜬다.
        if os.environ.get("RUN_MAIN") == "true":
            scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
            scheduler_thread.start()


# ---------------- management/commands/start_scheduler.py ----------------
class Command(BaseCommand):
    """웹 서버와 분리해 스케줄러만 따로 띄우려던 시도. 그래도 반복 작업 자체는 APScheduler 안에 있었다."""

    help = "Starts the APScheduler"

    def handle(self, *args, **kwargs):
        start_scheduler()
        self.stdout.write(self.style.SUCCESS("APScheduler started successfully"))
