# 출처: AI 상담 챗봇 서비스 (2025.04, 초기 Django 계열) — 관리자만 로그인한다. Django 의 authenticate/login 과 서버 세션을 그대로 쓰고, 대화 위젯 쪽은 인증이 없다
import json

from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render


# 로그인 공통
def admin(request):
    if request.method == "POST":
        # JSON 데이터로부터 아이디와 비밀번호를 추출
        try:
            data = json.loads(request.body)
            user_id = data.get("userId")
            password = data.get("password")
        except json.JSONDecodeError:
            return JsonResponse({"status": "fail", "message": "Invalid JSON data."}, status=400)

        # 사용자 인증 — 비밀번호 해시 · 비교는 Django 기본(PBKDF2)에 맡긴다
        user = authenticate(request, user_id=user_id, password=password)

        if user is not None:
            if user.is_active:
                # 로그인 처리 — 서버 세션에 사용자 ID 가 기록되고 세션 쿠키가 내려간다
                login(request, user)

                # 세션 만료 시간 설정 (브라우저 닫으면 세션 만료)
                request.session.set_expiry(0)

                # is_superuser 여부에 따라 프론트가 다른 관리자 화면으로 보낸다
                return JsonResponse({"status": "success", "is_superuser": user.is_superuser})
            else:
                return JsonResponse({"status": "fail", "message": "Account is inactive."})
        else:
            return JsonResponse({"status": "fail", "message": "Invalid id or password."})

    return render(request, "v1/index.html")


# 관리자 화면 — 세션이 없으면 로그인 페이지로 리다이렉트
@login_required(login_url="/chatbot_v1/login/")
def index(request):
    return render(request, "v1/index_admin.html")


@login_required(login_url="/chatbot_v1/login/")
def data_list_log(request):
    # ... (로그 목록 조회, 생략)
    return render(request, "v1/log_list.html")
