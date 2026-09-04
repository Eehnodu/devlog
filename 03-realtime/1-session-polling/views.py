# 출처: AI 상담 챗봇 서비스 (2025.02, 초기 Django 계열) — 동기 WSGI 에서 스트리밍을 흉내 낸 방식. OpenAI 청크를 Django 세션에 쌓고, 별도 뷰가 세션을 읽어 돌려준다
import os

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI

from .models import data_chatbot_v1_log

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@csrf_exempt
def gpt(request, user_message, category_name):
    """메인 요청 — 응답이 끝날 때까지 이 뷰가 워커 하나를 붙잡고 있다."""
    request.session["messages"].append({"role": "user", "content": user_message})
    request.session.modified = True

    stream = client.chat.completions.create(
        model=request.session["gpt_version"],
        messages=request.session["messages"],
        stream=True,
    )

    message_stream = ""  # 빈 문자열로 초기화

    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            message_stream += chunk.choices[0].delta.content  # 각 chunk의 content를 누적

            request.session["message_stream"] = message_stream  # 누적된 메시지를 세션에 저장
            request.session.modified = True
            request.session.save()  # 강제로 세션을 저장합니다 — 청크마다 세션 테이블에 UPDATE 한 번

    # GPT의 메시지를 messages 리스트에 추가
    request.session["messages"].append({"role": "assistant", "content": request.session["message_stream"]})
    request.session.modified = True

    assistant_message = request.session["message_stream"]

    # 로그 저장 — 첫 발화면 새 행, 아니면 history 텍스트 뒤에 이어 붙임
    if request.session["log_id"] == "":
        log = data_chatbot_v1_log(
            date_time=timezone.now(),
            category_name=category_name,
            gpt_version=request.session["gpt_version"],
            history=f"[user_message] : {user_message}\n[assistant_message] : {assistant_message}\n",
        )
        log.save()
        request.session["log_id"] = log.id
    else:
        db_data_log = data_chatbot_v1_log.objects.get(id=request.session["log_id"])
        db_data_log.history += f"[user_message] : {user_message}\n[assistant_message] : {assistant_message}\n"
        db_data_log.save()

    return assistant_message


@csrf_exempt
def get_message_stream(request):
    """폴링 뷰 — 프론트가 100ms 마다 부른다. 세션을 다시 읽어 지금까지 쌓인 문자열을 돌려준다."""
    # 세션의 최신 상태를 로드합니다.
    request.session.load()

    # 세션에서 메시지 스트림을 가져옵니다.
    message_stream = request.session["message_stream"]

    # 메시지 스트림을 JSON으로 반환합니다.
    return JsonResponse({"assistant_message": message_stream})


@csrf_exempt
def get_message_stream_default(request):
    """메인 요청이 끝난 뒤 프론트가 불러 누적 문자열을 비운다."""
    request.session["message_stream"] = ""
    request.session.modified = True
    request.session.save()  # 강제로 세션을 저장합니다.
    return JsonResponse({"status": "success"})
