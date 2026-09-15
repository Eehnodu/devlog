# 출처: AI 상담 챗봇 서비스 (Django + FastAPI 계열, 2025.06) — Django 옆에 새로 붙인 FastAPI 진입점. 대화 API 만 여기서 받는다
from fastapi import FastAPI
from database import Base, engine  # SQLAlchemy 기반
from routers import chatbot_v3  # 기존 라우터
from middlewares.register import register_middlewares
from config.settings import Settings

app = FastAPI()

settings = Settings()

register_middlewares(app)  # CORS · 보안 헤더
print(settings.cors_origins)  # 기동 확인용 print 가 아직 남아 있던 시기

# DB 테이블 자동 생성 (초기 개발 시만 사용, 운영 시 Alembic 권장)
# Django 마이그레이션이 만든 테이블을 SQLAlchemy 모델로 다시 선언해 같은 DB 를 본다
Base.metadata.create_all(bind=engine)

# 라우터 등록 — Nginx 가 이 접두사만 8001 로 보낸다
app.include_router(chatbot_v3.router, prefix="/chatbot_v3_api/chatbot_v3")
