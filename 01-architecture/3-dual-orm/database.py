# 출처: AI 상담 챗봇 서비스 (2025.06, Django + FastAPI 계열) — FastAPI 쪽 동기 SQLAlchemy 엔진. 호스트명으로 운영 · 로컬을 분기하고 Django 와 같은 MySQL 을 바라본다
import os
import socket

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# EC2/로컬 분기 — 서버 호스트명 규칙으로 운영 환경을 판별했다.
# (원본은 자격증명이 코드에 직접 있었다. 여기서는 환경변수 참조로 바꿨다.)
hostname = socket.gethostname()
if hostname.startswith("ip-"):
    MYSQL_USER = os.getenv("PROD_MYSQL_USER")
    MYSQL_PASSWORD = os.getenv("PROD_MYSQL_PASSWORD")
    MYSQL_HOST = os.getenv("PROD_MYSQL_HOST")
else:
    MYSQL_USER = os.getenv("LOCAL_MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("LOCAL_MYSQL_PASSWORD")
    MYSQL_HOST = "127.0.0.1"

MYSQL_DB = "db_chatbot"  # Django 의 settings.DATABASES 와 같은 스키마
MYSQL_PORT = 3306

SQLALCHEMY_DATABASE_URL = (
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
)

# 동기용 엔진 — 이 단계까지는 비동기 드라이버를 쓰지 않았다
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

# 세션 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모델 베이스
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
