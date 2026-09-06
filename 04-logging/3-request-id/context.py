# 출처: 풀스택 베이스 템플릿 (2026.04~) — 요청 ID 를 담는 컨텍스트 변수. 스레드 로컬이 아니라 contextvars 라 코루틴 사이에서 섞이지 않는다
from contextvars import ContextVar

# 기본값 "-" : 요청 바깥(기동 · 워커)에서 찍힌 줄은 req:- 로 보인다
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str:
    return request_id_var.get()
