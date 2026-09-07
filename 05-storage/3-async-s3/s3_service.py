# 출처: 전시관 AI 안내 서비스 (2026.03~) — 동기 boto3 를 aioboto3 로 교체. 업로드 · 삭제 · 복사가 await 로 이벤트 루프를 비켜 준다
# 클라이언트는 첫 호출 때 한 번 열어 재사용하고, 앱 종료 시 aclose() 로 닫는다.
import aioboto3
from botocore.exceptions import ClientError

from app.core.config.settings import settings

# 객체 공개 URL 의 앞부분. 예: https://my-bucket.s3.<region>.<S3 도메인>
_PUBLIC_BASE = settings.s3_public_base_url


def key_from_url(url: str) -> str:
    """S3 공개 URL → 객체 key.

    서비스 20곳에 흩어져 있던 `url.split(".com/")[-1]` 을 모은 것 — 로직은 동일하다.
    버킷 도메인이 바뀌면(CloudFront 등) 이 함수만 고치면 된다.
    """
    return (url or "").split(".com/")[-1]


class S3Service:
    def __init__(self):
        self._session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        self._client = None
        self._client_cm = None
        self.bucket_name = settings.s3_bucket_name  # 예: my-bucket
        self.region = settings.aws_region

    async def _client_get(self):
        # aioboto3 의 client() 는 비동기 컨텍스트 매니저다. 요청마다 열고 닫으면 느리므로
        # 처음 한 번 __aenter__ 로 열어 두고 같은 클라이언트를 계속 쓴다.
        if self._client is None:
            self._client_cm = self._session.client("s3")
            self._client = await self._client_cm.__aenter__()
        return self._client

    async def aclose(self):
        if self._client_cm is not None:
            await self._client_cm.__aexit__(None, None, None)
            self._client = None
            self._client_cm = None

    # 1. Create (Upload)
    async def upload_file(self, file_content: bytes, object_name: str, content_type: str = "image/png"):
        """파일을 S3에 업로드하고 접근 가능한 URL을 반환합니다."""
        try:
            client = await self._client_get()
            await client.put_object(
                Bucket=self.bucket_name,
                Key=object_name,
                Body=file_content,
                ContentType=content_type,
            )
            return f"{_PUBLIC_BASE}/{object_name}"
        except ClientError as e:
            print(f"S3 Upload Error: {e}")
            return None

    # 2. Delete
    async def delete_file(self, object_name: str):
        """S3에서 파일을 삭제합니다."""
        try:
            client = await self._client_get()
            await client.delete_object(Bucket=self.bucket_name, Key=object_name)
            return True
        except ClientError as e:
            print(f"S3 Delete Error: {e}")
            return False

    # 3. Copy (같은 버킷 내 키 변경)
    async def copy_file(self, source_key: str, target_key: str):
        """S3 객체를 같은 버킷 내 다른 키로 복사하고 새 URL을 반환합니다."""
        try:
            client = await self._client_get()
            await client.copy_object(
                Bucket=self.bucket_name,
                CopySource={"Bucket": self.bucket_name, "Key": source_key},
                Key=target_key,
            )
            return f"{_PUBLIC_BASE}/{target_key}"
        except ClientError as e:
            print(f"S3 Copy Error: {e}")
            return None

    # 4. 오래된 객체 정리 — 배치에서 호출
    async def delete_older_than(self, prefix: str, cutoff, key_pattern=None) -> int:
        """접두사 아래에서 cutoff(UTC aware datetime)보다 오래된 객체만 삭제하고 개수를 반환.

        객체별 업로드 시각(LastModified)으로 판단한다 — 폴더 단위로 지우면 방금 발급받아
        보고 있는 사람의 파일까지 함께 사라진다(같은 날짜 폴더를 공유하므로).
        """
        deleted = 0
        try:
            client = await self._client_get()
            token = None
            while True:
                kw = {"Bucket": self.bucket_name, "Prefix": prefix}
                if token:
                    kw["ContinuationToken"] = token
                resp = await client.list_objects_v2(**kw)
                old = [
                    {"Key": o["Key"]}
                    for o in resp.get("Contents", [])
                    if o.get("LastModified")
                    and o["LastModified"] < cutoff
                    and (key_pattern is None or key_pattern.search(o["Key"]))
                ]
                # S3 delete_objects는 한 번에 1000개까지
                for i in range(0, len(old), 1000):
                    chunk = old[i:i + 1000]
                    await client.delete_objects(Bucket=self.bucket_name, Delete={"Objects": chunk})
                    deleted += len(chunk)
                if not resp.get("IsTruncated"):
                    break
                token = resp.get("NextContinuationToken")
        except ClientError as e:
            print(f"S3 Delete Older Error: {e}")
        return deleted


# 앱 전체가 하나를 공유한다 (세션 · 클라이언트 재사용)
s3_service = S3Service()
