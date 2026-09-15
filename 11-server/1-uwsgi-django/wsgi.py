# 출처: AI 상담 챗봇 서비스 (초기 Django 계열, 2025.04) — WSGI 진입점. 동기 진입점이라 스트리밍 · WebSocket 을 쓸 수 없었다
"""
WSGI config for chatbotProject project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chatbotProject.settings')

# uWSGI 가 이 객체를 가져다 요청을 넘긴다. 워커 하나가 응답을 끝낼 때까지 점유된다
application = get_wsgi_application()
