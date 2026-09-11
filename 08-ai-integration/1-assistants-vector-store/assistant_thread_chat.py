# 출처: AI 상담 챗봇 서비스 (2025.03) — 스레드 + 어시스턴트 실행 스트림을 세션에 적재, 응답 끝에 출처 각주(전각 괄호)를 정규식으로 제거
# WSGI 동기 뷰라 진짜 스트리밍이 안 되던 시기. 청크마다 세션을 강제 저장하고 클라이언트가 폴링으로 읽었다.

import os
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI

from .models import data_chatbot_v1

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 출처 각주는 【4:0†source】 처럼 전각 괄호로 온다. 처음엔 아스키 괄호 [..] 로 잘못 잡아 그대로 노출됐다.
CITATION = re.compile(r"【.*?†.*?】")


def index(request):
    if request.method == "POST":
        user_message = request.POST.get("user_message")
        chat_history = request.POST.get("chat_history")
        category_name = request.POST.get("categoryName")
        db_data = data_chatbot_v1.objects.get(category_name=category_name)

        # 최초 진입: 빈 스레드를 만들어 세션에 스레드 ID 를 보관
        if chat_history == "":
            request.session["gpt_version"] = db_data.gpt_version
            request.session["log_id"] = ""
            if db_data.category_data_only == "only_file":
                empty_thread = client.beta.threads.create()
                request.session["thread_id"] = empty_thread.id
                request.session.modified = True
                return JsonResponse({"assistant_message": db_data.category_hi_msg, "chat_history": "true", "file": "true"})
            # ... (생략: 파일 없는 카테고리 초기화)

        # 파일 기반 카테고리: 스레드에 메시지를 넣고 어시스턴트 실행을 스트림으로 받는다
        if db_data.category_data_only == "only_file":
            client.beta.threads.messages.create(
                request.session["thread_id"],
                role="user",
                content=user_message,
            )
            stream = client.beta.threads.runs.create(
                thread_id=request.session["thread_id"],
                assistant_id=db_data.assistant_id,
                stream=True,
            )

            message_stream = ""
            for event in stream:
                if event.event == "thread.message.delta" and event.data.delta.content:
                    for block in event.data.delta.content:
                        if block.type == "text":
                            message_stream += block.text.value
                            # 청크마다 세션에 저장 → 폴링 엔드포인트가 읽어 간다 (청크마다 DB 쓰기가 생기는 구조)
                            request.session["message_stream"] = message_stream
                            request.session.modified = True
                            request.session.save()

            assistant_message = CITATION.sub("", message_stream)
            # ... (생략: 대화 로그 누적 저장)
            return JsonResponse({"assistant_message": assistant_message, "chat_history": "true", "file": "true"})

        # ... (생략: 파일 없는 카테고리는 Chat Completions 스트림 → 같은 세션 적재)
    return JsonResponse({"error": "Invalid request method"}, status=400)


@csrf_exempt
def get_message_stream(request):
    """클라이언트가 100ms 간격으로 호출하는 폴링 엔드포인트."""
    request.session.load()
    message_stream = request.session.get("message_stream", "")
    return JsonResponse({"assistant_message": CITATION.sub("", message_stream)})
