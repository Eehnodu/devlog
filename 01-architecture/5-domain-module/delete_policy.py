# 출처: 복지관 ERP (2026.08) — 관계마다 삭제 정책을 다르게 선언한다: 부속은 CASCADE, 기록이 있으면 RESTRICT, 단순 참조는 SET NULL
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database.base import Base, now_kst


class Counseling(Base):
    """상담일지. 대상자(이용자)가 지워져도 기록은 남아야 하므로 RESTRICT."""

    __tablename__ = "tb_counselings"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    log_date = Column(Date, nullable=False, index=True)  # 상담일지 등록일자
    title = Column(String(100), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("tb_personnel_users.id", ondelete="RESTRICT"),  # 기록이 있는 이용자는 삭제 불가
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)
    result = Column(Text, nullable=True)

    # 작성자(tb_users.id). 표시용 이름은 조회 시 조인해서 가져온다.
    created_by = Column(Integer, ForeignKey("tb_users.id"), nullable=True)

    created_at = Column(DateTime, default=now_kst)
    updated_at = Column(DateTime, default=now_kst, onupdate=now_kst)
    deleted_at = Column(DateTime, nullable=True)

    files = relationship(
        "CounselingFile",
        back_populates="counseling",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CounselingFile(Base):
    """상담일지 첨부 — 상담일지에 딸린 부속이므로 함께 지워진다(CASCADE)."""

    __tablename__ = "tb_counseling_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    counseling_id = Column(
        Integer,
        ForeignKey("tb_counselings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)  # 업로드 당시 원본 파일명
    path = Column(String(255), nullable=False)  # storage 상대 경로
    size = Column(Integer, nullable=True)  # bytes
    created_at = Column(DateTime, default=now_kst)

    counseling = relationship("Counseling", back_populates="files")


class AccountingEntry(Base):
    """회계 기록. 계정과목은 RESTRICT, 재원(예산) 참조는 SET NULL.

    삭제는 소프트 딜리트다. 회계 기록이라 물리 삭제하면 감사 추적이 끊긴다.
    """

    __tablename__ = "tb_accounting_entries"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    type = Column(String(10), nullable=False, index=True)  # income | expense

    account_id = Column(
        Integer,
        ForeignKey("tb_budget_accounts.id", ondelete="RESTRICT"),  # 기록이 달린 계정과목은 삭제 불가
        nullable=False,
        index=True,
    )

    description = Column(String(200), nullable=False)
    # 원 단위. 천원 단위 입력값에 1000을 곱해 넣는다
    amount = Column(BigInteger, nullable=False)

    # 지출일 때 어느 수입(예산)에서 집행하는지. 수입 행에서는 비어 있다
    budget_source_id = Column(
        Integer,
        ForeignKey("tb_budget_accounts.id", ondelete="SET NULL"),  # 재원이 사라져도 기록은 남고 참조만 비운다
        nullable=True,
    )

    created_by = Column(Integer, ForeignKey("tb_users.id"), nullable=True)
    created_at = Column(DateTime, default=now_kst)
    updated_at = Column(DateTime, default=now_kst, onupdate=now_kst)
    deleted_at = Column(DateTime, nullable=True)
