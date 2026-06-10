"""MinIO (S3-compatible) object storage adapter."""

import io

import structlog
from minio import Minio
from minio.error import S3Error

logger = structlog.get_logger()


class MinioStorage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str = "images",
        secure: bool = False,
    ) -> None:
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("minio_bucket_created", bucket=self.bucket)
        except S3Error as e:
            logger.error("minio_bucket_error", error=str(e))
            raise

    async def upload(self, file_bytes: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(
            self.bucket, object_name, io.BytesIO(file_bytes), len(file_bytes), content_type=content_type
        )
        logger.info("minio_object_uploaded", bucket=self.bucket, object=object_name, size=len(file_bytes))
        return self.get_url(object_name)

    def get_url(self, object_name: str) -> str:
        return self.client.presigned_get_object(self.bucket, object_name)
