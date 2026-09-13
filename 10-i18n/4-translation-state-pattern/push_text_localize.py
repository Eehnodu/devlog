# 출처: 팬 플랫폼 서비스 (2026.06~08) — 푸시 문구는 언어별 사전, 호칭 · 조사처럼 특정 언어에만 있는 요소는 그 언어 템플릿 안에서만 다룬다
# 한국어 "{}님" · 일본어 "{}さん" · 영어 "{}" — 변수는 이름 하나이고, 존칭은 각 언어 템플릿이 가진다.
# 한국어 조사(아/야 · 은/는 · 을/를)는 이름의 받침을 보고 고른다. 갈아 끼우기만 하면 "[이름]아" 가 "민수아" 로 나가는 버그가 있었다.

import re
from dataclasses import dataclass

# ── 언어별 사전 — 키: 언어 코드, 값: {푸시 종류: (title, body)}. body 의 "{}" 는 이름 치환 자리 ──
PUSH_TEXT: dict[str, dict[str, tuple[str, str]]] = {
    "ko": {
        "request_accepted": ("요청 수락",   "{}님이 요청을 수락했어요!"),
        "live_start":       ("라이브 시작", "{}님의 라이브가 시작됐어요"),
        "inquiry_answered": ("문의 답변 도착", "1:1 문의에 답변이 등록됐어요."),
    },
    "en": {
        "request_accepted": ("Request Accepted", "{} accepted your request!"),
        "live_start":       ("Live Started",     "{}'s live has started."),
        "inquiry_answered": ("Inquiry Answered", "Your inquiry has been answered."),
    },
    "ja": {
        "request_accepted": ("リクエストが承認されました", "{}さんがリクエストを承認しました！"),
        "live_start":       ("ライブ開始",                 "{}さんのライブが始まりました。"),
        "inquiry_answered": ("お問い合わせへの回答",       "1:1お問い合わせに回答が登録されました。"),
    },
    # ... (생략: 나머지 17개 언어)
}

_KO = PUSH_TEXT["ko"]  # ko 를 정규(폴백) 사전으로 사용


@dataclass(frozen=True)
class PushTemplate:
    title: str
    body: str
    data_type: str
    setting_type: str                       # "message" | "marketing"
    text_key: str | None = None             # PUSH_TEXT 키 — 있으면 발송 시 유저 언어로 title/body 재조립
    text_arg: str | None = None             # body "{}" 치환 값 (크리에이터 이름 등)
    dynamic_title: bool = False             # True 면 title 은 언어 무관 동적 값(이름)
    name_by_lang: dict[str, str] | None = None  # 이름의 언어별 번역 맵 — 문구와 이름의 언어가 섞이지 않게


def resolve_name(template: PushTemplate, lang: str | None) -> str | None:
    """유저 언어에 맞는 이름. name_by_lang 우선 → ko 폴백 → text_arg."""
    if template.name_by_lang:
        return template.name_by_lang.get(lang or "ko") or template.name_by_lang.get("ko") or template.text_arg
    return template.text_arg


def localize(template: PushTemplate, lang: str | None) -> tuple[str, str]:
    """유저 언어에 맞는 (title, body). 없는 언어 · 키는 ko 로 폴백."""
    name = resolve_name(template, lang)
    if not template.text_key:
        # 관리자 입력 공지 · 채팅 미리보기 등은 원문 그대로. 제목이 이름이면 언어별 이름으로만 바꾼다
        title = name if (template.dynamic_title and name) else template.title
        return title, template.body
    texts = PUSH_TEXT.get(lang or "ko", _KO)
    title, body = texts.get(template.text_key) or _KO[template.text_key]
    arg = name if name is not None else template.text_arg
    if arg is not None:
        body = body.format(arg)   # 존칭(님 · さん) 은 이미 그 언어 템플릿에 들어 있다
    if template.dynamic_title:
        title = name if name else template.title
    return title, body


# ── 한국어 전용: 받침에 따라 조사를 고른다 (시나리오 대사의 "[이름]" 토큰 치환에 쓴다) ──
# `받침 있을 때 / 없을 때` 순. 키는 작가가 어느 쪽을 적어도 받도록 둘 다 넣는다.
_PARTICLES: dict[str, tuple[str, str]] = {
    "아": ("아", "야"), "야": ("아", "야"),
    "은": ("은", "는"), "는": ("은", "는"),
    "이": ("이", "가"), "가": ("이", "가"),
    "을": ("을", "를"), "를": ("을", "를"),
    "과": ("과", "와"), "와": ("과", "와"),
    "으로": ("으로", "로"), "로": ("으로", "로"),
}
# 긴 것부터 봐야 `으로` 가 `로` 에 먹히지 않는다
_KEYS = "|".join(sorted(_PARTICLES, key=len, reverse=True))


def has_final_consonant(word: str) -> bool:
    """마지막 글자에 받침이 있는가. 한글이 아니면 없는 것으로 본다 — 영문 · 숫자 이름에는 `야` · `는` 쪽이 자연스럽다."""
    word = (word or "").strip()
    if not word:
        return False
    code = ord(word[-1])
    if not 0xAC00 <= code <= 0xD7A3:
        return False
    return (code - 0xAC00) % 28 != 0


def apply_name(text: str, token: str, value: str) -> str:
    """`text` 안의 `token` 을 `value` 로 바꾸고, 뒤에 붙은 조사도 골라 준다.

    조사가 안 붙은 `[이름]` 은 이름만 들어간다. `[이름] 씨` 처럼 사이가 띄어져 있으면
    조사로 보지 않는다 — `씨` · `님` 은 받침과 무관한 말이라 그대로 두면 된다.
    """
    if not text or token not in text:
        return text
    final = has_final_consonant(value)
    pattern = re.compile(f"{re.escape(token)}({_KEYS})?")

    def pick(match: re.Match) -> str:
        particle = match.group(1)
        return value + (_PARTICLES[particle][0 if final else 1] if particle else "")

    return pattern.sub(pick, text)
