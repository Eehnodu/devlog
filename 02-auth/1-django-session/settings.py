# 출처: AI 상담 챗봇 서비스 (2025.02~04, 초기 Django 계열) — Django 세션 로그인. 위젯이 고객사 페이지 iframe 안에서 돌기 때문에 세션 쿠키를 SameSite=None + Secure 로 열어 두었다
import socket

hostname = socket.gethostname()

# 서버 호스트명 규칙으로 운영 · 로컬을 분기했다 (환경변수 파일은 아직 없었다)
if hostname.startswith("ip-"):  # EC2 서버일 경우
    DEBUG = False
    ALLOWED_HOSTS = ["*"]
    CSRF_COOKIE_SECURE = True  # HTTPS 환경에서만 쿠키 전송
    CSRF_USE_SESSIONS = True  # CSRF 토큰을 쿠키 대신 세션에 보관
else:
    DEBUG = True
    ALLOWED_HOSTS = ["127.0.0.1"]
    CSRF_COOKIE_SECURE = False
    CSRF_USE_SESSIONS = False  # CSRF 토큰을 세션이 아닌 쿠키에서 관리

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",  # 관리자 로그인은 Django 인증 프레임워크를 그대로 사용
    "django.contrib.sessions",
    "corsheaders",
    "gpt",
    # ... (생략)
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # iframe 임베드 때문에 클릭재킹 방지 미들웨어는 꺼 두었다
    # 'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "corsheaders.middleware.CorsMiddleware",  # cors 오류 삭제를 위해
    # ... (생략)
]

# iframe 접근 허용할 사이트 — 고객사 홈페이지 도메인을 적었다
CSP_FRAME_SRC = ("'self'", "https://example.com/")
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

# 세션 쿠키가 다른 도메인의 iframe 안에서도 전송되도록.
# SameSite=None 은 Secure 가 함께 있어야 브라우저가 받아 준다.
SESSION_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SECURE = True

AUTH_USER_MODEL = "gpt.data_chatbot_user"  # user_id 로 로그인하는 커스텀 관리자 모델
