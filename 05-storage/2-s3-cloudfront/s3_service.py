# 출처: AI 캐릭터 대화 서비스 (2025.11~2026.01) — S3 첫 도입. 업로드는 S3 키로, 열람 URL 은 CloudFront 도메인으로 조립
# 클라이언트가 동기 boto3 라서 비동기 서비스 안에서 호출하면 그 동안 이벤트 루프가 멈춘다 (3단계에서 교체).
import boto3

from app.core.config.settings import settings


class S3Service:
    def __init__(self):
        self.cloudfront_domain = settings.cloudfront_domain  # 예: cdn.example.com
        self.client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        self.bucket = settings.aws_s3_bucket  # 예: my-bucket

    def upload_file(self, key: str, body: bytes, content_type: str):
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def delete_file(self, key: str):
        self.client.delete_object(
            Bucket=self.bucket,
            Key=key,
        )

    def build_asset_url(
        self,
        user_id: int,
        asset_id: int,
        category: str,
        sub_key: str,
        file_name: str,
    ) -> str:
        # DB 에는 file_name 만 저장하고, URL 은 규칙에 따라 매번 조립한다.
        # CDN 도메인이 바뀌어도 DB 를 고칠 일이 없다.
        return (
            f"https://{self.cloudfront_domain}/assets/"
            f"{user_id}/"
            f"{asset_id}/"
            f"{category}/"
            f"{sub_key}/"
            f"{file_name}"
        )
