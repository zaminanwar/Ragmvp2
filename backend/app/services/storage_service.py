"""MinIO object storage service for document files."""

import io
import uuid

from minio import Minio

from app.config import get_settings


class StorageService:
    """Handles file storage in MinIO (S3-compatible)."""

    def __init__(self):
        settings = get_settings()
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_use_ssl,
        )
        self._bucket = settings.minio_bucket

    async def ensure_bucket(self):
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def upload_file(
        self,
        content: bytes,
        filename: str,
        workspace_id: uuid.UUID,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload file and return storage path."""
        file_id = uuid.uuid4()
        storage_path = f"{workspace_id}/{file_id}/{filename}"

        self._client.put_object(
            self._bucket,
            storage_path,
            io.BytesIO(content),
            length=len(content),
            content_type=content_type,
        )
        return storage_path

    def download_file(self, storage_path: str) -> bytes:
        """Download file content."""
        response = self._client.get_object(self._bucket, storage_path)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete_file(self, storage_path: str):
        """Delete a file."""
        self._client.remove_object(self._bucket, storage_path)
