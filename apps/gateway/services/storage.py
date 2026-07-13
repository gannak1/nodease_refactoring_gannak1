import errno
import logging
import os
import shutil
import tempfile
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote

import boto3
from fastapi import UploadFile

from apps.gateway.core.config import settings
from apps.gateway.services.storage_reference import (
    StorageDeleteError,
    StorageReferenceError,
    build_upload_object_key,
    build_upload_object_name,
    resolve_local_delete_path,
    resolve_s3_delete_key,
)

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_UPLOAD_DIR = "/app/uploads"
FALLBACK_LOCAL_UPLOAD_DIR = str(Path(__file__).resolve().parents[3] / "uploads")
_LOCAL_STORAGE_FALLBACK_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}
_local_storage_root_lock = threading.Lock()
_resolved_default_local_upload_dir: str | None = None


def _prepare_writable_directory(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    resolved_directory = str(Path(directory).resolve())
    with tempfile.NamedTemporaryFile(
        dir=resolved_directory,
        prefix=".nodease-storage-probe-",
        delete=True,
    ) as probe:
        probe.write(b"ready")
        probe.flush()
    return resolved_directory


def _resolve_default_local_upload_dir() -> str:
    global _resolved_default_local_upload_dir

    if _resolved_default_local_upload_dir is not None:
        return _resolved_default_local_upload_dir

    with _local_storage_root_lock:
        if _resolved_default_local_upload_dir is not None:
            return _resolved_default_local_upload_dir

        try:
            selected_root = _prepare_writable_directory(DEFAULT_LOCAL_UPLOAD_DIR)
        except OSError as exc:
            if exc.errno not in _LOCAL_STORAGE_FALLBACK_ERRNOS:
                raise
            selected_root = _prepare_writable_directory(
                FALLBACK_LOCAL_UPLOAD_DIR
            )

        _resolved_default_local_upload_dir = selected_root
        return selected_root


class StorageService(ABC):
    @abstractmethod
    def upload(self, file: UploadFile) -> str:
        """
        파일을 저장소에 업로드하고 접근 경로(또는 키)를 반환합니다.
        """
        pass

    @abstractmethod
    def delete(self, file_path: str):
        """
        저장소에서 파일을 삭제합니다.
        """
        pass


class LocalStorageService(StorageService):
    def __init__(self, upload_dir: str | None = None):
        self.upload_dir = (
            _prepare_writable_directory(upload_dir)
            if upload_dir is not None
            else _resolve_default_local_upload_dir()
        )

    def upload(self, file: UploadFile) -> str:
        unique_filename = build_upload_object_name(file.filename)
        file_path = os.path.join(self.upload_dir, unique_filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 포인터 초기화 (다른 곳에서 다시 읽을 수 있도록)
        file.file.seek(0)

        return file_path

    def delete(self, file_path: str):
        target = resolve_local_delete_path(file_path, upload_root=self.upload_dir)
        if target.exists() or target.is_symlink():
            if target.is_dir():
                raise StorageReferenceError("storage_reference_invalid")
            target.unlink()

    def generate_presigned_upload_url(
        self,
        filename: str,
        content_type: str,
        user_id: str,
        expires_in: int = 3600,
    ) -> dict:
        """
        LocalStorage를 사용하는 경우 Presigned URL을 지원하지 않으므로,
        프론트엔드에서 직접 백엔드로 업로드하도록 유도하는 응답을 반환하거나,
        적절한 예외를 던져서 핸들링하도록 합니다.

        여기서는 None을 반환하여 프론트엔드가 일반 업로드를 수행하도록 합니다.
        (프론트엔드 로직에 따라 수정 필요할 수 있음)
        """
        # 로컬 모드에서는 Presigned URL 생성이 불가능
        # 프론트엔드가 이 응답을 보고 "일반 업로드"로 전환하도록 신호를 줍니다.
        return {"use_backend_proxy": True, "url": None, "key": None, "method": None}


class S3StorageService(StorageService):
    def __init__(self):
        self.bucket_name = settings.S3_BUCKET_NAME
        self.region = settings.AWS_REGION
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=self.region,
        )

        if not self.bucket_name:
            raise ValueError("S3_BUCKET_NAME is not set. ")

    def upload(self, file: UploadFile) -> str:
        s3_key = build_upload_object_key(file.filename)

        try:
            self.s3_client.upload_fileobj(
                file.file,
                self.bucket_name,
                s3_key,
                ExtraArgs={
                    "ContentType": file.content_type or "application/octet-stream",
                    "ContentDisposition": "inline",
                },
            )
        except Exception as e:
            logger.error(f"S3 Upload failed: {e}")
            raise e
        finally:
            # 포인터 초기화
            try:
                file.file.seek(0)
            except ValueError:
                # 이미 닫힌 파일인 경우 무시
                pass

        # S3 URL
        encoded_key = quote(s3_key, safe="/")
        return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{encoded_key}"

    def generate_presigned_upload_url(
        self,
        filename: str,
        content_type: str,
        user_id: str,
        expires_in: int = 3600,  # 1시간 유효
    ) -> dict:
        """
        S3 Presigned URL 생성 (프론트엔드 직접 업로드용)

        Args:
            filename: 원본 파일명
            content_type: MIME 타입 (예: application/pdf)
            user_id: 사용자 ID (폴더 분리용)
            expires_in: URL 유효 시간 (초)

        Returns:
            dict: {
                "url": Presigned URL,
                "key": S3 key,
                "method": "PUT"
            }
        """
        s3_key = build_upload_object_key(filename, user_id=user_id)

        try:
            # Presigned URL 생성 (PUT 방식)
            presigned_url = self.s3_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": s3_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )

            return {
                "url": presigned_url,
                "key": s3_key,
                "method": "PUT",
            }
        except Exception as e:
            logger.error(f"Presigned URL generation failed: {e}")
            raise e

    def delete(self, file_path: str):
        key = resolve_s3_delete_key(
            file_path,
            bucket_name=self.bucket_name,
            region=self.region,
        )

        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
        except Exception:
            # Callers own the cleanup policy and safe logging boundary. Do not
            # expose provider exception text, bucket names, or object keys here.
            raise StorageDeleteError("storage_delete_failed") from None


def get_storage_service() -> StorageService:
    # 환경변수가 없거나 None일 경우 기본값 LOCAL로 처리
    mode = (settings.STORAGE_TYPE or "LOCAL").upper()

    if mode == "LOCAL":
        return LocalStorageService()
    elif mode == "CLOUD":
        return S3StorageService()
    else:
        # 지원되지 않는 모드인 경우 경고 후 기본값(LOCAL) 사용
        logger.warning(f"Unknown STORAGE_TYPE '{mode}', falling back to LOCAL")
        return LocalStorageService()
