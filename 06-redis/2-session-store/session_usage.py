# 출처: AI 캐릭터 대화 서비스 (2025.11~2026.01) — 대화 서비스가 Redis 세션을 만들고 · 읽고 · 지우는 쪽
# 세션이 이미 있으면 그대로 쓰고, 없을 때만 캐릭터 설정을 DB 에서 읽어 지침을 조립한다.
from app.module.character.character_repository import CharacterRepository
from app.module.infra.redis_service import RedisService


class GPTService:
    def __init__(self, repo: CharacterRepository, redis: RedisService):
        self.repo = repo
        self.redis = redis

    # 세션 생성
    async def create_session_storage(self, session_id, character_id):
        session = await self.redis.get_ws_session(session_id)
        if session:
            return session  # 재접속 — 이전 대화가 Redis 에 살아 있다

        character = await self.repo.get_character_by_id(character_id)

        asset_id = None
        for cp in character.parts:
            if cp.part:
                asset_id = cp.part.asset_id
                break

        emotions = []
        if asset_id is not None:
            emotions = await self.repo.get_asset_emotions(asset_id)

        instruction = await self.build_instruction(
            character.name,
            character.characteristic,
            character.voice,
            character.worldbuilding,
            character.job,
            character.agent,
            emotions,
        )

        session = {
            "instruction": instruction,
            "history": [],
            "summary": "",
            "log_id": None,
        }

        await self.redis.set_ws_session(session_id, session)
        return session

    # 세션 초기화
    async def clear_session(self, session_id):
        await self.redis.delete_ws_session(session_id)
        return True

    # 한 턴 처리 — 읽고, 이력을 붙이고, 다시 저장
    async def chat_turn(self, session_id: str, user_text: str) -> str:
        session = await self.redis.get_ws_session(session_id)
        if not session:
            raise ValueError("session expired")

        # ... (생략) instruction + summary + history 로 응답 생성
        answer = await self._generate(session, user_text)

        session["history"].append({"role": "user", "content": user_text})
        session["history"].append({"role": "assistant", "content": answer})

        # 이력이 길어지면 앞부분을 요약으로 접는다
        if len(session["history"]) > 20:
            session["summary"] = await self._summarize(session)
            session["history"] = session["history"][-6:]

        await self.redis.set_ws_session(session_id, session)  # TTL 도 함께 연장
        return answer

    async def build_instruction(self, name, characteristic, voice, worldbuilding, job, agent, emotions=None):
        # ... (생략) 캐릭터 성격 · 말투 · 세계관을 한 지침 문자열로
        return ""

    async def _generate(self, session: dict, user_text: str) -> str:
        # ... (생략)
        return ""

    async def _summarize(self, session: dict) -> str:
        # ... (생략)
        return ""
