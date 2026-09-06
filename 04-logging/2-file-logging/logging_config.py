# 출처: AI 글쓰기 검토 서비스 (2025.09) — 앱 로그를 파일 하나로 모으고, 핸들러는 루트 로거에만 두는 첫 설정
# 당시 설정 파일이 남아 있지 않아 운영 기준(일 단위 회전 · Uvicorn 로거 교체 · 접근 로거 WARNING)대로 다시 적었다.
import logging
import os
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "/var/log/app")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    # 앱 로그만 파일로. 자정마다 새 파일, 14일 보관
    file_handler = TimedRotatingFileHandler(
        LOG_FILE, when="midnight", backupCount=14, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # 콘솔 핸들러는 남긴다 — systemd 저널에서도 바로 볼 수 있게
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 핸들러는 루트 로거에만 단다. 모듈 로거는 전파만 하면 같은 줄이 두 번 찍히지 않는다
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Uvicorn 은 자기 핸들러를 따로 들고 온다 — 떼어내고 우리 핸들러로 교체, 루트로는 전파하지 않는다
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.addHandler(file_handler)
        uv.addHandler(console_handler)
        uv.propagate = False

    # 접근 로그는 Nginx 가 남기므로 앱에서는 WARNING 이상만
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.setLevel(logging.WARNING)
    access.propagate = False


def get_logger(name: str) -> logging.Logger:
    # 모듈에서는 get_logger(__name__) 으로 받아 쓴다. 핸들러를 직접 달지 않는다
    return logging.getLogger(name)
