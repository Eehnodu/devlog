# 출처: AI 상담 챗봇 서비스 (초기 Django 계열, 2025.04) — 서버 호스트명으로 운영 · 로컬을 가르던 settings 조각. 자격증명은 전부 환경변수 참조로 바꿨다
import os
import socket
from pathlib import Path

import pymysql

# 서버의 호스트 이름을 가져옴 — EC2 기본 호스트명이 'ip-' 로 시작하는 것을 운영 판정에 썼다
hostname = socket.gethostname()
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")  # 원본은 코드에 값이 박혀 있었다

if hostname.startswith('ip-'):  # EC2 서버일 경우
    DEBUG = False
    ALLOWED_HOSTS = ["*"]
    CSRF_COOKIE_SECURE = True   # HTTPS 환경에서만 쿠키 전송
    CSRF_USE_SESSIONS = True
else:
    DEBUG = True
    ALLOWED_HOSTS = ["127.0.0.1"]
    CSRF_COOKIE_SECURE = False
    CSRF_USE_SESSIONS = False   # CSRF 토큰을 세션이 아닌 쿠키에서 관리

INSTALLED_APPS = [
    # ... (생략) django 기본 앱
    'gpt.apps.GptConfig',
    'csp',          # iframe 임베드 허용 도메인 제어
    'corsheaders',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # ... (생략)
    # 'django.middleware.clickjacking.XFrameOptionsMiddleware',  # iframe 위젯이라 꺼 둠
    'corsheaders.middleware.CorsMiddleware',
]
CSP_FRAME_SRC = ("'self'", 'https://www.example.com/')  # 위젯을 넣을 고객사 사이트
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

SESSION_COOKIE_SAMESITE = 'None'  # iframe 안에서 세션 쿠키가 살아야 한다
SESSION_COOKIE_SECURE = True

WSGI_APPLICATION = 'chatbotProject.wsgi.application'

pymysql.install_as_MySQLdb()

# DB 도 같은 호스트명 분기를 반복했다. 다만 당시 두 분기의 값은 같은 운영 DB 를 가리키고 있었다
if hostname.startswith('ip-'):  # EC2 서버일 경우
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv("DB_NAME"),
            'USER': os.getenv("DB_USER"),
            'PASSWORD': os.getenv("DB_PASSWORD"),
            'HOST': os.getenv("DB_HOST"),  # RDS 엔드포인트
            'PORT': '3306',
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    # 개발 서버 또는 로컬 환경의 설정
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv("DB_NAME"),
            'USER': os.getenv("DB_USER"),
            'PASSWORD': os.getenv("DB_PASSWORD"),
            'HOST': os.getenv("DB_HOST"),
            'PORT': '3306',
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

# ... (생략) 정적 파일 · 템플릿 · 시간대
