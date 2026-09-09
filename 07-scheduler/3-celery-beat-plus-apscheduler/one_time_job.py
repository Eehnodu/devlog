# 출처: 세탁 서비스 앱 (2025.03~04) — 관리자가 예약한 푸시 알림 한 건을 APScheduler 의 date 트리거로 등록 · 취소 · 수정
# 작업 ID 를 예약 행에 함께 저장해 두어, 나중에 그 ID 로 잡을 지우거나 같은 ID 로 다시 등록한다.
import json
import uuid
from datetime import datetime

from django.http import JsonResponse
from django.utils import timezone

from basic.firebase_client import send_multicast_fcm
from basic.models import PushNotification, User
from basic.scheduler import scheduler


# ---------------- scheduler.py ----------------
def register_one_time_job(func, run_time, job_id, args=None):
    scheduler.add_job(
        func,
        "date",  # 한 번만 — 그 시각이 지나면 잡스토어에서 사라진다
        run_date=run_time,
        args=args or [],
        id=job_id,
        replace_existing=True,  # 같은 ID 로 다시 부르면 덮어쓴다 → "수정" 이 이걸로 된다
    )
    print(f"작업 등록됨: {job_id}, 실행 시간: {run_time}")


# ---------------- views_admin.py ----------------
def send_scheduled_push(fcm_token_list, content, url, image_url, send_time):
    """예약된 시간에 푸시 알림을 보내는 함수 — 스케줄러가 부른다"""
    send_multicast_fcm(fcm_token_list, content, url, image_url)


def _collect_fcm_token_list(ids):
    fcm_token_list = []
    for user_id in ids:
        user = User.objects.filter(id=user_id).first()
        if user and user.fcm_token:  # 토큰이 존재하는 경우만 추가
            fcm_token_list.append(user.fcm_token)
    return fcm_token_list


def create_push_alarm(request):
    content = request.POST.get("content")
    url = request.POST.get("url")
    sent_at = request.POST.get("sent_at")
    ids = json.loads(request.POST.get("ids"))
    fcm_token_list = _collect_fcm_token_list(ids)

    if sent_at == "즉시 발송":
        sent_at_parsed = timezone.now()
    else:
        sent_at_parsed = datetime.strptime(sent_at, "%Y-%m-%d %H:%M")

    image_url = None  # ... (생략) 첨부 이미지 저장

    if not fcm_token_list:
        return JsonResponse({"error": "받을 사람이 없습니다."}, status=400)

    if sent_at == "즉시 발송":
        send_multicast_fcm(fcm_token_list, content, url, image_url)
        PushNotification.objects.create(content=content, url=url, sent_at=sent_at_parsed)
        return JsonResponse({"success": "푸시 알림이 성공적으로 전송되었습니다."})

    job_id = f"push_{uuid.uuid4().hex}"  # 고유한 job_id 생성

    register_one_time_job(
        func=send_scheduled_push,
        run_time=sent_at_parsed,
        job_id=job_id,
        args=[fcm_token_list, content, url, image_url, sent_at_parsed],
    )

    # 작업 ID 를 예약 행에 같이 저장 — 취소 · 수정 때 이 값으로 잡을 찾는다
    PushNotification.objects.create(
        content=content,
        url=url,
        sent_at=sent_at_parsed,
        job_id=job_id,
    )

    if not scheduler.running:
        scheduler.start()

    return JsonResponse({"success": "푸시 알림이 예약되었습니다.", "job_id": job_id})


def edit_push_alarm(request, id):
    push = PushNotification.objects.get(id=id)
    reserved_job_id = push.job_id

    # 기존 잡을 먼저 지운다 (이미 실행돼 없을 수도 있으니 예외는 삼킨다)
    if reserved_job_id:
        try:
            scheduler.remove_job(reserved_job_id)
        except Exception as e:
            print(f"기존 job 제거 중 오류: {e}")

    content = request.POST.get("content")
    url = request.POST.get("url")
    sent_at = request.POST.get("sent_at")
    ids = json.loads(request.POST.get("ids"))
    fcm_token_list = _collect_fcm_token_list(ids)
    sent_at_parsed = datetime.strptime(sent_at, "%Y-%m-%d %H:%M")
    image_url = None

    # 같은 ID 로 다시 등록 → 예약 행의 job_id 는 그대로 유지된다
    register_one_time_job(
        func=send_scheduled_push,
        run_time=sent_at_parsed,
        job_id=reserved_job_id,
        args=[fcm_token_list, content, url, image_url, sent_at_parsed],
    )

    push.content = content
    push.url = url
    push.sent_at = sent_at_parsed
    push.job_id = reserved_job_id
    push.save()

    return JsonResponse({"success": "예약이 수정되었습니다."})


def delete_push(request, id):
    push = PushNotification.objects.get(id=id)
    job_id = push.job_id

    scheduler.remove_job(job_id)  # 잡스토어(DB)에서 제거 → 발송되지 않는다
    print(f"작업 {job_id} 삭제 완료")

    push.delete()
    return JsonResponse({"success": "예약이 취소되었습니다."})
