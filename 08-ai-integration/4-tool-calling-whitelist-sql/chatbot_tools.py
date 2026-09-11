# 출처: 복지관 ERP (2026.08) — 챗봇 도구 정의(스키마로 인자를 묶은 읽기 전용 조회 19종 + 자유 SELECT 도구 1종)와 실행기
"""
AI 가 직접 SQL 을 쓰게 하지 않는다 — 미리 정해 둔 조회만 골라 쓰게 하고,
파라미터도 스키마로 묶는다. 그래야 조회 범위를 우리가 통제할 수 있다.

  - 전부 읽기 전용이다. 쓰기 · 삭제 도구는 두지 않는다.
  - 목록 조회는 한 번에 돌려주는 행 수를 제한한다.
  - 정해진 도구로 안 풀리는 교차 질문만 run_query 로 열어 두고, 그쪽은 chatbot_sql 이 검사한다.
"""

from sqlalchemy import text

from app.module.chatbot import chatbot_sql
from app.module.chatbot.chatbot_schema import schema_text

MAX_ROWS = 50

TOOLS = [
    {
        "name": "search_users",
        "description": (
            "이용자 명단을 조회한다. 한 사람의 전체 항목이 필요하면 get_user_detail 을 쓴다. "
            "사용자가 조건을 말하지 않았으면 어떤 인자도 넣지 말고 전체를 조회하라."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "이름 일부"},
                "status": {"type": "string", "enum": ["접수", "대기", "이용중", "종결"]},
            },
        },
    },
    # ... (생략: get_user_detail · search_helpers · list_matchings · accounting_summary 등 17종)
    {
        "name": "run_query",
        "description": (
            "위 도구로 풀 수 없는 질문에 SELECT 문을 직접 써서 조회한다.\n"
            "- 여러 표를 엮어야 하는 질문, 인원 · 건수 · 합계를 세는 질문에 쓴다 (COUNT · GROUP BY 로 DB 가 세게).\n"
            "- SELECT 또는 WITH 로 시작하는 문장 하나만. 아래 목록에 없는 표 · 컬럼을 쓰면 거부된다.\n"
            "- 최대 50행. 거부되면 오류 내용을 보고 고쳐서 다시 호출하면 된다.\n\n"
            + schema_text()  # 허용 표 · 컬럼 · 조인 관계를 문장으로 풀어 도구 설명에 넣는다
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "실행할 SELECT문"},
                "purpose": {"type": "string", "description": "이 조회로 무엇을 확인하려는지 한 줄"},
            },
            "required": ["sql"],
        },
    },
]

# 도구 이름 → (파라미터 바인딩 SQL, 받는 인자 키). `:key IS NULL OR ...` 패턴으로 빈 조건을 통과시킨다
_USERS = """
SELECT u.code AS 코드, u.name AS 이름, u.status AS 상태, u.benefit_type AS 급여유형
FROM tb_users u
WHERE u.deleted_at IS NULL
  AND (:keyword IS NULL OR u.name LIKE :keyword_like)
  AND (:status IS NULL OR u.status = :status)
ORDER BY u.name
LIMIT :limit
"""
_QUERIES = {
    "search_users": (_USERS, ("keyword", "status")),
    # ... (생략)
}
_LIKE_KEYS = {"keyword", "category", "user_name", "name"}


def _params(args: dict, keys: tuple) -> dict:
    params: dict = {"limit": MAX_ROWS}
    for key in keys:
        raw = args.get(key)
        value = raw if isinstance(raw, (int, bool)) else (str(raw or "").strip() or None)
        params[key] = value
        if key in _LIKE_KEYS:
            params[f"{key}_like"] = f"%{value}%" if value else None
    return params


def _validate(name: str, args: dict) -> dict | None:
    """enum 으로 정해 둔 값이 아닌 게 오면 오류로 돌려준다.
    조용히 0행을 주면 AI 가 "그런 자료가 없다" 고 단정해 버린다. 허용값을 알려 주면 다시 호출한다."""
    schema = next((t["input_schema"] for t in TOOLS if t["name"] == name), None)
    if not schema:
        return None
    for key, spec in (schema.get("properties") or {}).items():
        allowed = spec.get("enum")
        value = args.get(key)
        if allowed and value and value not in allowed:
            return {"error": f"{key} 값이 올바르지 않습니다: {value!r}.", "allowed": {key: allowed}}
    for key in schema.get("required") or []:
        if not str(args.get(key) or "").strip():
            return {"error": f"{key}는 반드시 넣어야 합니다."}
    return None


async def run(name: str, args: dict, db) -> dict:
    """도구 하나를 실행하고 결과를 그대로 돌려준다.
    실패해도 예외를 올리지 않는다 — AI 에게 오류 내용을 전달해 다른 도구로 다시 시도하게 한다."""
    invalid = _validate(name, args)
    if invalid:
        return invalid

    if name == "run_query":
        return await chatbot_sql.run(args.get("sql") or "", db, MAX_ROWS, _plain)

    try:
        if name not in _QUERIES:
            return {"error": f"알 수 없는 도구입니다: {name}"}
        statement, keys = _QUERIES[name]
        params = _params(args, keys)
        result = await db.execute(text(statement), params)
        rows = [{k: _plain(v) for k, v in r.items()} for r in result.mappings().all()]

        # 조건을 뺐을 때 몇 건인지도 함께 준다. 이게 없으면 AI 가 자기가 건 필터를 잊고 "전체가 N건" 이라고 답한다
        applied = {k: v for k, v in params.items() if k != "limit" and v}
        return {
            "appliedFilters": applied or "없음 (전체 조회)",
            "rowCount": len(rows),
            "rows": rows,
            "truncated": len(rows) >= MAX_ROWS,
        }
    except Exception as e:
        return {"error": f"조회에 실패했습니다: {e}"}


def _plain(value):
    """날짜 · Decimal 등을 JSON 으로 보낼 수 있는 값으로."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value if isinstance(value, (int, float, str, bool)) or value is None else str(value)
