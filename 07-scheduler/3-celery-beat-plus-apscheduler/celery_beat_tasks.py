# 출처: 세탁 서비스 앱 (2025.03~04) — 반복 작업을 Celery Beat 로 옮긴 쪽. Beat 프로세스 하나가 시각을 재고 워커가 실행한다
# 주기는 DB 스케줄러(django_celery_beat)에 관리 명령으로 등록해, 코드 배포 없이 관리자 화면에서 켜고 끌 수 있게 했다.
import datetime
import os

from celery import Celery, shared_task
from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from basic.firebase_client import send_fcm_message
from basic.models import InspectionNotification, LaundryTransaction

# ---------------- celery.py ----------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "basicProject.settings")

app = Celery("basicProject")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# settings.py
# CELERY_BROKER_URL = "redis://localhost:6379/0"   # 이 프로젝트에서 Redis 는 브로커 전용
# CELERY_TIMEZONE = "Asia/Seoul"
# CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"


# ---------------- tasks.py ----------------
@shared_task
def check_inspection_timeouts_task():
    """확인 요청 후 72시간 응답이 없는 품목을 '진행(자동)' 으로 넘기고 푸시를 보낸다. 1분마다."""
    print("[Celery] 72시간 경과 확인 시작")
    try:
        deadline = now() - datetime.timedelta(hours=72)
        expired_list = InspectionNotification.objects.filter(
            sent_at__lte=deadline,
            inspect_status="진행(미)",
        )[:100]  # 배치 처리 제한

        for notification in expired_list:
            try:
                datetime_str = notification.unique_key[:14]
                sale_date = f"{datetime_str[:4]}-{datetime_str[4:6]}-{datetime_str[6:8]}"
                sale_time = f"{datetime_str[8:10]}:{datetime_str[10:12]}:{datetime_str[12:14]}"

                LaundryTransaction.objects.create(
                    user_phone=notification.user.phone,
                    sale_date=sale_date,
                    sale_time=sale_time,
                    tag_number=notification.tag_number,
                    action_mode=2,
                    response="Y",
                )

                notification.inspect_status = "진행(자동)"
                notification.checked_at = now()
                notification.save()

                if notification.user and notification.user.fcm_token:
                    send_fcm_message(
                        notification.user.fcm_token,
                        "확인품 세탁 진행(자동) 처리 알림",
                        f"{sale_date} {sale_time}에 접수된 품목이 세탁 진행(자동) 처리되었습니다.",
                        f"usage_detail/?date={sale_date}&time={sale_time}",
                    )
            except Exception as item_err:
                print(f"개별 처리 실패: {item_err}")

        print(f"[Celery] 완료: {len(expired_list)}건 처리됨")
    except Exception as e:
        print("[Celery] 전체 작업 실패:", e)


@shared_task
def update_store_info_task():
    """매장 정보를 외부 POS 에서 받아 갱신. 매일 05:00."""
    # ... (생략)


@shared_task
def update_confirmed_info_task():
    """확인품 정보 갱신. 매일 0 · 6 · 12 · 18시."""
    # ... (생략)


# ---------------- management/commands/register_beat_task.py ----------------
class Command(BaseCommand):
    help = "Celery Beat에 모든 주기성 작업 등록"

    def handle(self, *args, **kwargs):
        # 1. 72시간 확인 작업: 1분마다
        interval, _ = IntervalSchedule.objects.get_or_create(every=1, period=IntervalSchedule.MINUTES)
        PeriodicTask.objects.update_or_create(
            name="check_inspection_timeout_task",
            defaults={
                "interval": interval,
                "task": "basic.tasks.check_inspection_timeouts_task",
                "enabled": True,
            },
        )

        # 2. 매장 정보 업데이트: 매일 05:00
        cron_5am, _ = CrontabSchedule.objects.get_or_create(hour=5, minute=0)
        PeriodicTask.objects.update_or_create(
            name="update_store_info_task",
            defaults={
                "crontab": cron_5am,
                "task": "basic.tasks.update_store_info_task",
                "enabled": True,
            },
        )

        # 3. 확인품 정보: 매일 0, 6, 12, 18시
        for hour in [0, 6, 12, 18]:
            cron, _ = CrontabSchedule.objects.get_or_create(hour=hour, minute=0)
            PeriodicTask.objects.update_or_create(
                name=f"update_confirmed_info_task_{hour}",
                defaults={
                    "crontab": cron,
                    "task": "basic.tasks.update_confirmed_info_task",
                    "enabled": True,
                },
            )

        self.stdout.write(self.style.SUCCESS("Celery Beat 작업 전체 등록 완료!"))
