# 출처: 전시관 AI 안내 서비스 (2026.08) — 추가 학습 데이터를 임베딩해 벡터 텍스트 컬럼에 저장, 콘텐츠 해시로 변경을 감지해 수정된 행만 재임베딩 · 메모리 캐시 갱신
# 관리형 벡터 스토어 대신 자체 테이블에 벡터를 두고, 검색은 프로세스 메모리의 행렬로 한다.

import hashlib
import json
import logging

import numpy as np
from sqlalchemy import Column, ForeignKey, Integer, String, Text, func, select, update

from app.core.database.base import Base

logger = logging.getLogger(__name__)


# ── 모델 ────────────────────────────────────────────────────────────────
class Species(Base):
    __tablename__ = "tb_species"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("tb_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=True)
    description = Column(Text, nullable=False)
    embedding = Column(Text, nullable=False)              # JSON 직렬화한 벡터 (3072차원)
    content_hash = Column(String(64), nullable=True)      # description 의 SHA-256 — 변경 감지용


# ── 저장소 ───────────────────────────────────────────────────────────────
class SpeciesRepository:
    def __init__(self, db):
        self.db = db

    async def update_by_id(self, id: int, name: str | None, description: str, embedding: str, content_hash: str) -> None:
        await self.db.execute(
            update(Species).where(Species.id == id)
            .values(name=name, description=description, embedding=embedding, content_hash=content_hash)
        )
        await self.db.commit()

    async def count_and_checksum(self, agent_id: int) -> tuple[int, int]:
        """(건수, 내용 체크섬) — 캐시 신선도 판정용.

        건수만 보면 '수정'(건수 불변)이 감지되지 않으므로 content_hash 의 CRC32 합을 함께 본다.
        추가 · 삭제 · 교체 · 수정 어느 경우든 값이 바뀐다. 한 쿼리로 계산.
        """
        result = await self.db.execute(
            select(func.count(), func.coalesce(func.sum(func.crc32(Species.content_hash)), 0))
            .select_from(Species).where(Species.agent_id == agent_id)
        )
        count, checksum = result.one()
        return int(count), int(checksum)

    # ... (생략: get_by_agent · add_for_agent · replace_for_agent)


# ── 서비스: 수정된 행만 다시 임베딩 ───────────────────────────────────────
class SpeciesService:
    def __init__(self, species_repo: SpeciesRepository, embedding_service):
        self.species_repo = species_repo
        self.embedding_service = embedding_service

    async def update_species(self, id: int, agent_id: int, name: str | None, description: str):
        new_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
        # 설명이 그대로면 임베딩 호출을 건너뛴다 (임베딩도 과금 · 기록 대상)
        current = await self.species_repo.get_by_id(id)
        if current and current.content_hash == new_hash and current.name == name:
            return {"id": id, "reembedded": False}

        from app.core.utils.usage import set_usage_target
        set_usage_target(agent_id, "species", id)  # 사용량을 이 고객사의 '추가 학습데이터' 로 귀속

        embed_text = f"{name}\n{description}" if name else description
        vectors = await self.embedding_service.embed_documents([embed_text])
        await self.species_repo.update_by_id(
            id, name=name, description=description,
            embedding=json.dumps(vectors[0]), content_hash=new_hash,
        )
        return {"id": id, "reembedded": True}


# ── 검색용 메모리 캐시 ─────────────────────────────────────────────────────
# agent_id -> {"key": (count, checksum), "items": [...], "matrix": np.ndarray}
# 1500개 × 3072차원 ≈ 18MB. 매 세션 재로드를 피하려고 프로세스 메모리에 캐시한다.
_SPECIES_CACHE: dict[int, dict] = {}


async def load_species(db, agent_id: int) -> tuple[list[dict], "np.ndarray | None"]:
    """agent 의 종 데이터 + 임베딩 행렬을 (캐시와 함께) 로드한다. 없으면 ([], None)."""
    repo = SpeciesRepository(db)
    count, checksum = await repo.count_and_checksum(agent_id)
    if count == 0:
        return [], None

    cached = _SPECIES_CACHE.get(agent_id)
    if cached and cached.get("key") == (count, checksum):
        return cached["items"], cached["matrix"]

    rows = await repo.get_by_agent(agent_id)
    items, vectors = [], []
    for r in rows:
        if not r.embedding:
            continue
        vectors.append(json.loads(r.embedding))
        items.append({"id": r.id, "name": r.name, "description": r.description})

    matrix = np.asarray(vectors, dtype=np.float32) if vectors else None
    _SPECIES_CACHE[agent_id] = {"key": (count, checksum), "items": items, "matrix": matrix}
    return items, matrix
