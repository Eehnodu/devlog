# 출처: 복지관 ERP (2026.08) — OpenAI · Claude 두 공급자를 같은 메서드 시그니처로 감싸고, 설정값 하나로 바꿔 끼우는 서비스 프로바이더 프로퍼티
# 호출부(챗봇 · 설문 요약 · 매칭 설명)는 공급자를 모른다. 파일 ID 접두사 · 파일 검색 지원 여부 같은 차이는 클래스 속성으로 노출한다.

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.core.config.settings import settings
from app.core.utils.response import fail

MAX_TOKENS = 4096


# ── 서비스 프로바이더 (요청마다 생성, lazy) ──────────────────────────────
class ServiceProvider:
    def __init__(self, request, db):
        self.request = request
        self.db = db
        self._ai_service = None

    @property
    def ai_service(self):
        """`.env` 의 ai_provider 값으로 고른다 (claude | openai, 기본 claude).
        두 클래스는 메서드 이름 · 인자 · 반환 형식이 같아 호출부 수정 없이 바꿀 수 있다."""
        if not self._ai_service:
            provider = settings.ai_provider
            if provider == "openai":
                self._ai_service = OpenAIService()
            else:
                self._ai_service = ClaudeService()
        return self._ai_service

    # ... (생략: chatbot_service 등은 self.ai_service 를 주입받는다)


# ── Claude 구현 ─────────────────────────────────────────────────────────
class ClaudeService:
    """Anthropic Claude API 래퍼."""

    # 저장해 둔 file_id 가 어느 공급자 것인지 가리는 접두사. Anthropic 은 file_011..., OpenAI 는 file-...
    FILE_ID_PREFIX = "file_"
    # 관리형 벡터스토어가 없어 자료는 매 요청 원문을 통째로 넣는다
    SUPPORTS_FILE_SEARCH = False

    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.claude_api_key)

    async def ask(
        self,
        question: str,
        *,
        model: str | None = None,
        guideline: str | None = None,
        documents: list | None = None,
        files: list | None = None,
        containers: list | None = None,
        history: list[dict] | None = None,
        search_store: str | None = None,  # OpenAI 전용 — 받기만 하고 쓰지 않는다
    ) -> dict:
        """질문 하나에 대한 답변과 출처. returns: {"answer": str, "sources": [...]}"""
        messages: list[dict] = []
        reference_message = self._build_reference_message(documents or [], files, containers)
        if reference_message:
            messages.append(reference_message)
        for turn in history or []:
            role, content = turn.get("role"), (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})

        try:
            response = await self.client.messages.create(
                model=self.resolve_model(model),
                max_tokens=MAX_TOKENS,
                system=self._build_system(guideline),
                messages=messages,
            )
        except Exception as e:
            fail(f"Claude 호출에 실패했습니다: {e}", "CLAUDE_REQUEST_FAILED", 502)

        # 안전 정책에 의해 거부되면 content 가 비어 있으므로 먼저 확인한다
        if response.stop_reason == "refusal":
            fail("요청이 안전 정책에 의해 거부되었습니다.", "CLAUDE_REFUSAL")

        answer = "".join(block.text for block in response.content if block.type == "text").strip()
        return {"answer": answer, "sources": self._collect_citations(response.content)}

    # ... (생략: resolve_model · _build_system · _build_reference_message · _collect_citations · ask_json · converse)


# ── OpenAI 구현 ─────────────────────────────────────────────────────────
def file_search_tool(store_id: str) -> dict:
    return {"type": "file_search", "vector_store_ids": [store_id]}


class OpenAIService:
    """OpenAI Responses API 래퍼. ClaudeService 와 바꿔 끼울 수 있다."""

    FILE_ID_PREFIX = "file-"
    # 자료를 벡터스토어에 색인해 두고 검색해서 쓸 수 있다
    SUPPORTS_FILE_SEARCH = True

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def ask(
        self,
        question: str,
        *,
        model: str | None = None,
        guideline: str | None = None,
        documents: list | None = None,
        files: list | None = None,
        containers: list | None = None,
        history: list[dict] | None = None,
        search_store: str | None = None,
    ) -> dict:
        """같은 시그니처. search_store 가 있으면 벡터스토어에서 자료를 찾아 쓴다."""
        messages: list[dict] = []
        reference = self._build_reference_message(documents or [], files, containers)
        if reference:
            messages.append(reference)
        for turn in history or []:
            role, content = turn.get("role"), (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})

        try:
            response = await self.client.responses.create(
                model=self.resolve_model(model),
                instructions=self._instructions(guideline),
                input=self._to_input(messages),
                tools=[file_search_tool(search_store)] if search_store else None,
                max_output_tokens=MAX_TOKENS,
            )
        except Exception as e:
            fail(f"OpenAI 호출에 실패했습니다: {e}", "OPENAI_REQUEST_FAILED", 502)

        return {"answer": self._answer_of(response), "sources": self._citations_of(response)}

    # ... (생략: resolve_model · _instructions · _to_input · _answer_of · _citations_of · ask_json · converse)
