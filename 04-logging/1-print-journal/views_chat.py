# 출처: AI 상담 챗봇 서비스 (초기 Django 계열, 2025.03) — 뷰 안에 남아 있던 print 디버그. 표준 출력이 그대로 systemd 저널로 갔다
# 원본은 Django 세션에 대화를 쌓는 뷰 파일 하나. 이 조각은 print 가 어디에 어떤 값으로 박혀 있었는지만 남겼다.
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv
from openai import OpenAI
# ...

from .models import data_chatbot_v1

load_dotenv()
client = OpenAI()  # 키는 환경변수에서 읽는다 (값을 코드에 두지 않는다)


@csrf_exempt
def index(request):
    chat_history = request.POST.get("chat_history", "")
    # ... (생략) 카테고리 조회, 시스템 프롬프트 조립
    assistant_message = ""

    request.session['messages'].append({"role": "assistant", "content": assistant_message})
    request.session.modified = True
    # 시스템 프롬프트를 포함한 대화 전체가 그대로 표준 출력으로 나갔다
    print(request.session['messages'])

    if chat_history == '':
        # 세션 키 같은 식별 값도 그대로 찍혔다 — 저널에 남는다
        print("SESSION_KEY:", request.session.session_key)
        request.session['count'] = 0
        request.session['gpt_version'] = ""
        request.session['log_id'] = ""

        db_data = data_chatbot_v1.objects.first()
        print("db_data.category_name :", db_data.category_name)
        print("db_data.category_data_only :", db_data.category_data_only)

        if db_data.category_data_only == "only_file":
            print("어시스턴트 실행")
            # ... (생략) 어시스턴트 스레드 생성, 스레드 ID 세션 저장

    # ... (생략)
    return JsonResponse({"assistant_message": assistant_message})


@csrf_exempt
def gpt(request, user_message, category_name):
    # 진입 · 인자 확인용 print — 동시에 여러 요청이 들어오면 어느 줄이 어느 요청인지 알 수 없다
    print("GPT 들어옴")
    print("GPT user_message", user_message)
    print("GPT category_name", category_name)
    print("SESSION_KEY in gpt:", request.session.session_key)

    if 'messages' not in request.session:
        print("세션에 'messages' 키가 없어서 새로 생성합니다.")
        request.session['messages'] = []
        request.session.modified = True

    # ... (생략) OpenAI 스트리밍 호출, 청크마다 세션 저장
    assistant_message = ""
    return assistant_message
