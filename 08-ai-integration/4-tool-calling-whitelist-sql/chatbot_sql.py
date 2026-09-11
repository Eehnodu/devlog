# 출처: 복지관 ERP (2026.08) — 챗봇이 직접 쓴 SELECT 문을 허용 테이블 · 금지 단어 · 금지 컬럼 · 단일 문장 네 가지로 검사한 뒤에만 실행
"""
정해진 도구만으로는 "A 조건인 사람 중 B 에 해당하는 사람" 같은 교차 질문을
전부 예상해 만들 수 없다. 그래서 승인된 표 안에서 SQL 을 쓰게 하되,
파서를 붙이는 대신 화이트리스트로 막는다 — 허용 표 목록이 짧고 고정이라
"무엇을 막을까" 보다 "무엇만 허용할까" 로 접근하는 편이 확실하다.
"""

import re

from sqlalchemy import text

# 허용 표 → 허용 컬럼. 목록에 없는 표는 조회하지 않는다 (실제 목록은 21개 표 · 191개 컬럼)
ALLOWED: dict[str, tuple[str, ...]] = {
    "tb_users": ("code", "name", "sex", "phone", "reg_date", "status", "benefit_type", "note"),
    "tb_user_services": ("user_id", "biz_type"),
    "tb_helpers": ("name", "sex", "phone", "hire_date", "leave_date", "status"),
    "tb_matchings": ("user_id", "helper_id", "start_date", "end_date", "status"),
    # ... (생략)
}

# 표에는 있지만 챗봇에는 절대 열지 않는 컬럼 — 판정 점수 · 좌표 · 비밀번호
BANNED_COLUMNS = (
    "judge_mohw", "judge_metro", "judge_local", "judge_etc",
    "score_econ", "score_med", "score_psy", "score_sw", "score_extra",
    "lat", "lng", "password",
)

# 쓰기 · 구조 변경 · 파일 접근 · 시스템 스키마를 뜻하는 낱말. 하나라도 있으면 실행하지 않는다
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
    r"call|load|outfile|infile|dumpfile|handler|prepare|execute|lock|unlock|"
    r"set|into|rename|analyze|optimize|kill|shutdown|information_schema|"
    r"performance_schema)\b",
    re.I,
)

# FROM · JOIN 뒤에 오는 표 이름
TABLE_REF = re.compile(r"\b(?:from|join)\s+`?([a-zA-Z_]\w*)`?", re.I)

# WITH 절에서 만든 임시 이름 (실제 표가 아니라 검사에서 뺀다)
CTE_NAME = re.compile(r"\b(\w+)\s+as\s*\(", re.I)

COMMENT = re.compile(r"(--[^\n]*|/\*.*?\*/|#[^\n]*)", re.S)


def check(sql: str) -> str | None:
    """실행해도 되는 SELECT 인지 본다. 문제가 있으면 사유를, 없으면 None 을."""
    cleaned = COMMENT.sub(" ", sql or "").strip().rstrip(";").strip()
    if not cleaned:
        return "SQL이 비어 있습니다."

    # 1) 단일 문장
    if ";" in cleaned:
        return "문장은 하나만 보낼 수 있습니다. 세미콜론으로 잇지 마세요."

    if not re.match(r"^(select|with)\b", cleaned, re.I):
        return "SELECT 또는 WITH로 시작하는 조회만 실행할 수 있습니다."

    # 2) 금지 단어
    found = FORBIDDEN.search(cleaned)
    if found:
        return f"허용되지 않는 구문입니다: {found.group(0)}"

    # 3) 허용 표
    tables = {t.lower() for t in TABLE_REF.findall(cleaned)}
    aliases = {a.lower() for a in CTE_NAME.findall(cleaned)}
    unknown = sorted(t for t in tables - aliases if t not in ALLOWED)
    if unknown:
        return f"조회할 수 없는 표입니다: {', '.join(unknown)}. 허용된 표: {', '.join(ALLOWED)}"

    # 4) 금지 컬럼
    for column in BANNED_COLUMNS:
        if re.search(rf"\b{column}\b", cleaned, re.I):
            return f"조회할 수 없는 컬럼입니다: {column}"

    # 표에 없는 컬럼은 DB 가 오류를 내고 그 내용이 AI 에게 전달된다.
    # 여기서는 표 단위까지만 막고 컬럼 오타는 DB 오류에 맡긴다
    return None


def strip(sql: str) -> str:
    """주석과 끝 세미콜론을 걷어낸 실행용 문장."""
    return COMMENT.sub(" ", sql).strip().rstrip(";")


async def run(sql: str, db, max_rows: int, to_plain) -> dict:
    problem = check(sql)
    if problem:
        return {"error": problem}

    statement = strip(sql)
    try:
        result = await db.execute(text(statement))
        rows = [{k: to_plain(v) for k, v in row.items()} for row in result.mappings().all()]
    except Exception as e:
        # 컬럼 오타 · 문법 오류는 그대로 알려 준다. AI 가 고쳐서 다시 부른다
        return {"error": f"조회에 실패했습니다: {str(e).splitlines()[0][:300]}"}

    truncated = len(rows) > max_rows
    output = {
        "sql": statement,
        "rowCount": len(rows[:max_rows]),
        "rows": rows[:max_rows],
        "truncated": truncated,
    }
    if truncated:
        output["note"] = f"{max_rows}행까지만 돌려줍니다. GROUP BY로 집계해 다시 조회하세요."
    return output
