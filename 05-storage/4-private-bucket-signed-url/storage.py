# 출처: 복지관 ERP (2026.08) — 서비스가 부르는 저장소 파사드. 버킷 설정이 비어 있으면 로컬 디스크, 채워져 있으면 S3
# 서비스는 "상대 경로 문자열" 만 주고받고, 그 경로가 DB 에 들어간다. 동기 I/O 라 호출부가 asyncio.to_thread() 로 감싼다.
"""
업로드 파일 저장소.

**저장 위치는 `.env` 의 버킷 값 하나로 갈린다 — 코드는 건드리지 않는다.**

    local_s3_bucket 비어 있음  → MEDIA_ROOT 하위 로컬 디스크 (개발)
    prod_s3_bucket  채워짐     → S3                          (배포)

    save_file()   저장하고 상대 경로 반환
    remove_file() 상대 경로로 삭제
    read_file()   상대 경로의 내용을 bytes로 읽기
    file_url()    상대 경로 → 브라우저가 받을 URL
"""

import os
import re
import uuid

from app.core.config.settings import settings
from app.core.utils import s3
from app.core.utils.response import fail

# main.py 에서 StaticFiles로 마운트한 경로와 맞춰야 한다 (로컬 모드에서만 쓰인다)
MEDIA_URL_PREFIX = "/media"

# 저장 경로 세그먼트 허용 패턴 (영숫자로 시작 + 영숫자/./_/-)
_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _safe_subdir(subdir: str) -> str:
    """
    저장 경로 검증.

    지금은 서버가 정한 값만 들어오지만, 나중에 클라이언트가 경로를 지정하게 되면
    MEDIA_ROOT·버킷 밖으로 벗어나는 입력이 들어올 수 있다. 블랙리스트(`..` 차단)로는
    제어문자·공백 세그먼트가 새므로 화이트리스트로 검사한다.
    """
    cleaned = (subdir or "").replace("\\", "/").strip().strip("/")
    parts = cleaned.split("/") if cleaned else []
    if not parts or not all(_SEGMENT_RE.fullmatch(p) for p in parts):
        fail("잘못된 저장 경로입니다.", "INVALID_PATH")
    return "/".join(parts)


def save_file(subdir: str, data: bytes, ext: str = "") -> str:
    """
    subdir 하위에 저장하고 상대 경로를 반환한다.

    원본 파일명은 쓰지 않는다 — 한글·공백·중복·경로 조작 문제를 한 번에 피하려고
    uuid로 새 이름을 만든다. 원본 파일명이 필요하면 호출한 쪽이 DB에 따로 보관한다.
    """
    safe = _safe_subdir(subdir)
    stored = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    rel_path = f"{safe}/{stored}"

    if s3.is_enabled():
        s3.put_bytes(rel_path, data)
    else:
        directory = settings.MEDIA_ROOT / safe
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / stored, "wb") as f:
            f.write(data)

    return rel_path


def read_file(relative_path: str) -> bytes:
    """
    저장된 파일 내용을 읽는다.
    파일이 없으면 두 모드 모두 FileNotFoundError 를 낸다 (호출부가 같게 처리하도록).
    """
    if not relative_path:
        raise FileNotFoundError("경로가 비어 있습니다.")

    normalized = relative_path.replace("\\", "/")
    if not s3.is_enabled():
        return (settings.MEDIA_ROOT / normalized).read_bytes()

    try:
        return s3.get_bytes(normalized)
    except Exception as e:
        # boto3 의 NoSuchKey / 404 를 FileNotFoundError 로 통일한다
        if s3.is_not_found(e):
            raise FileNotFoundError(normalized) from e
        raise


def remove_file(relative_path: str) -> None:
    """이미 없는 파일이어도 조용히 넘어간다 — DB 삭제까지 막을 이유가 없다."""
    if not relative_path:
        return

    normalized = relative_path.replace("\\", "/")
    try:
        if s3.is_enabled():
            s3.delete_key(normalized)
        else:
            os.remove(settings.MEDIA_ROOT / normalized)
    except Exception:
        pass


def is_remote() -> bool:
    """
    저장소가 S3인지.

    다운로드를 어떻게 내보낼지가 갈린다 — S3는 서명 URL에 파일명을 실을 수 있지만,
    로컬의 /media 정적 경로에는 Content-Disposition을 붙일 수 없다.
    """
    return s3.is_enabled()


def file_url(relative_path: str, download_name: str = "") -> str:
    """
    브라우저가 받아갈 URL.

    S3 모드에서는 서명 URL(6시간), 로컬 모드에서는 정적 경로.
    받는 이름이 중요한 곳은 이 함수 대신 서버가 파일을 직접 내보낸다 (is_remote() 로 분기).
    """
    if not relative_path:
        return ""

    normalized = relative_path.replace("\\", "/")
    if s3.is_enabled():
        return s3.object_url(normalized, download_name or None)
    return f"{MEDIA_URL_PREFIX}/{normalized}"


# ---- 호출 예 (서비스 쪽) ----
# import asyncio
# path = await asyncio.to_thread(save_file, "chatbot/created", data, "docx")   # 저장
# url  = file_url(path, download_name="상담 보고서.docx")                          # 열람 링크
