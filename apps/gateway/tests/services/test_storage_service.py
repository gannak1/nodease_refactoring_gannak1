import errno
import logging
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.gateway.services import storage as storage_module
from apps.gateway.services.storage import (
    LocalStorageService,
    S3StorageService,
    StorageConfigurationError,
    StorageDeleteError,
    StorageOperationError,
    StorageReferenceError,
)


@pytest.fixture(autouse=True)
def _reset_default_local_storage_root(monkeypatch):
    monkeypatch.setattr(
        storage_module,
        "_resolved_default_local_upload_dir",
        None,
    )


class _FailingS3Client:
    def __init__(self, message: str) -> None:
        self.message = message

    def delete_object(self, **_kwargs) -> None:
        raise RuntimeError(self.message)

    def upload_fileobj(self, *_args, **_kwargs) -> None:
        raise RuntimeError(self.message)

    def generate_presigned_url(self, *_args, **_kwargs):
        raise RuntimeError(self.message)


class _CaptureS3Client:
    def __init__(self) -> None:
        self.calls = []
        self.upload_calls = []
        self.presigned_calls = []

    def delete_object(self, **kwargs) -> None:
        self.calls.append(kwargs)

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None) -> None:
        self.upload_calls.append(
            {
                "fileobj": fileobj,
                "bucket": bucket,
                "key": key,
                "extra_args": ExtraArgs,
            }
        )

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned_calls.append(
            {
                "operation": operation,
                "params": Params,
                "expires_in": ExpiresIn,
            }
        )
        return "https://signed.example/upload"


def _s3_storage(client=None) -> S3StorageService:
    storage = object.__new__(S3StorageService)
    storage.bucket_name = "knowledge-bucket"
    storage.region = "region"
    storage.s3_client = client or _CaptureS3Client()
    return storage


def test_unknown_storage_type_fails_closed_without_logging_config_value(
    monkeypatch,
    caplog,
):
    unexpected_value = "provider-specific-raw-value"
    monkeypatch.setattr(storage_module.settings, "STORAGE_TYPE", unexpected_value)

    with pytest.raises(
        StorageConfigurationError,
        match="^storage_configuration_invalid$",
    ):
        storage_module.get_storage_service()

    assert unexpected_value not in caplog.text


@pytest.mark.parametrize(
    ("bucket", "region"),
    [
        (None, "region-1"),
        ("nodease-documents", None),
    ],
)
def test_s3_storage_rejects_incomplete_configuration_before_provider_setup(
    monkeypatch,
    bucket,
    region,
):
    provider_calls = []
    monkeypatch.setattr(storage_module.settings, "S3_BUCKET_NAME", bucket)
    monkeypatch.setattr(storage_module.settings, "AWS_REGION", region)
    monkeypatch.setattr(
        storage_module.boto3,
        "client",
        lambda *_args, **_kwargs: provider_calls.append("called"),
    )

    with pytest.raises(
        StorageConfigurationError,
        match="^storage_configuration_invalid$",
    ):
        S3StorageService()

    assert provider_calls == []


def test_s3_delete_raises_safe_typed_error_without_provider_details(caplog):
    sensitive_value = "private-bucket/customer-contract.pdf"
    storage = object.__new__(S3StorageService)
    storage.bucket_name = "private-bucket"
    storage.region = "region"
    storage.s3_client = _FailingS3Client(sensitive_value)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StorageDeleteError, match="^storage_delete_failed$") as exc:
            storage.delete("s3://private-bucket/uploads/customer-contract.pdf")

    assert exc.value.__cause__ is None
    assert sensitive_value not in str(exc.value)
    assert sensitive_value not in caplog.text


def test_s3_upload_raises_safe_typed_error_without_provider_details(caplog):
    sensitive_value = "provider-private-storage-detail"
    storage = _s3_storage(_FailingS3Client(sensitive_value))
    upload = SimpleNamespace(
        filename="policy.pdf",
        file=BytesIO(b"document"),
        content_type="application/pdf",
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(
            StorageOperationError,
            match="^storage_upload_failed$",
        ) as exc_info:
            storage.upload(upload)

    assert exc_info.value.__cause__ is None
    assert sensitive_value not in str(exc_info.value)
    assert sensitive_value not in caplog.text
    assert upload.file.tell() == 0


def test_s3_presign_raises_safe_typed_error_without_provider_details(caplog):
    sensitive_value = "provider-private-storage-detail"
    storage = _s3_storage(_FailingS3Client(sensitive_value))

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(
            StorageOperationError,
            match="^storage_presign_failed$",
        ) as exc_info:
            storage.generate_presigned_upload_url(
                filename="policy.pdf",
                content_type="application/pdf",
                user_id="user-123",
            )

    assert exc_info.value.__cause__ is None
    assert sensitive_value not in str(exc_info.value)
    assert sensitive_value not in caplog.text


def test_s3_delete_preserves_nested_object_key():
    storage = _s3_storage()

    storage.delete(
        "https://knowledge-bucket.s3.region.amazonaws.com/uploads/nested/doc.pdf"
    )

    assert storage.s3_client.calls == [
        {"Bucket": "knowledge-bucket", "Key": "uploads/nested/doc.pdf"},
    ]


def test_s3_delete_decodes_url_encoded_key_once():
    storage = _s3_storage()

    storage.delete(
        "https://knowledge-bucket.s3.region.amazonaws.com/"
        "uploads/policy%20guide-%EC%8B%A0%EC%9E%85.pdf"
    )

    assert storage.s3_client.calls == [
        {
            "Bucket": "knowledge-bucket",
            "Key": "uploads/policy guide-신입.pdf",
        }
    ]


def test_s3_backend_upload_key_round_trips_through_delete_validator():
    storage = _s3_storage()
    upload = SimpleNamespace(
        filename="신입 정책 guide.pdf",
        file=BytesIO(b"document"),
        content_type="application/pdf",
    )

    reference = storage.upload(upload)
    storage.delete(reference)

    generated_key = storage.s3_client.upload_calls[0]["key"]
    assert generated_key.startswith("uploads/")
    assert storage.s3_client.calls == [
        {"Bucket": "knowledge-bucket", "Key": generated_key}
    ]
    assert "%EC%8B%A0%EC%9E%85" in reference


def test_s3_presigned_upload_key_round_trips_through_delete_validator():
    storage = _s3_storage()

    result = storage.generate_presigned_upload_url(
        filename="policy.pdf",
        content_type="application/pdf",
        user_id="user-123",
    )
    storage.delete(result["key"])

    generated_key = storage.s3_client.presigned_calls[0]["params"]["Key"]
    assert generated_key.startswith("uploads/user-123/")
    assert result["key"] == generated_key
    assert storage.s3_client.calls == [
        {"Bucket": "knowledge-bucket", "Key": generated_key}
    ]


@pytest.mark.parametrize(
    "filename",
    [
        "folder/../policy.pdf",
        "folder\\policy.pdf",
        ".",
        "..",
        "bad\x00name.pdf",
        "",
    ],
)
def test_s3_upload_paths_reject_non_canonical_filename(filename):
    storage = _s3_storage()
    upload = SimpleNamespace(
        filename=filename,
        file=BytesIO(b"document"),
        content_type="application/pdf",
    )

    with pytest.raises(StorageReferenceError, match="^storage_reference_invalid$"):
        storage.upload(upload)
    with pytest.raises(StorageReferenceError, match="^storage_reference_invalid$"):
        storage.generate_presigned_upload_url(
            filename=filename,
            content_type="application/pdf",
            user_id="user-123",
        )

    assert storage.s3_client.upload_calls == []
    assert storage.s3_client.presigned_calls == []


def test_s3_delete_supports_configured_bucket_path_style_url():
    storage = _s3_storage()

    storage.delete(
        "https://s3.region.amazonaws.com/knowledge-bucket/uploads/nested/doc.pdf"
    )

    assert storage.s3_client.calls == [
        {"Bucket": "knowledge-bucket", "Key": "uploads/nested/doc.pdf"}
    ]


@pytest.mark.parametrize(
    "reference",
    [
        "s3://other-bucket/uploads/doc.pdf",
        "https://other.example/uploads/doc.pdf",
        "http://knowledge-bucket.s3.region.amazonaws.com/uploads/doc.pdf",
        "https://knowledge-bucket.s3.region.amazonaws.com/private/doc.pdf",
        "https://knowledge-bucket.s3.region.amazonaws.com/uploads/../private.pdf",
        "https://knowledge-bucket.s3.region.amazonaws.com/uploads/doc.pdf?token=value",
        "https://knowledge-bucket.s3.region.amazonaws.com:invalid/uploads/doc.pdf",
        "uploads\\doc.pdf",
        "",
    ],
)
def test_s3_delete_rejects_untrusted_reference_without_provider_call(reference):
    storage = _s3_storage()

    with pytest.raises(StorageReferenceError, match="^storage_reference_invalid$"):
        storage.delete(reference)

    assert storage.s3_client.calls == []


def test_local_delete_allows_only_files_inside_upload_root(tmp_path):
    upload_root = tmp_path / "uploads"
    storage = LocalStorageService(str(upload_root))
    target = upload_root / "nested" / "document.txt"
    target.parent.mkdir()
    target.write_text("document", encoding="utf-8")

    storage.delete(str(target))

    assert not target.exists()


def test_local_upload_path_round_trips_through_delete_validator(tmp_path):
    upload_root = tmp_path / "uploads"
    storage = LocalStorageService(str(upload_root))
    upload = SimpleNamespace(
        filename="policy guide.pdf",
        file=BytesIO(b"document"),
    )

    reference = storage.upload(upload)
    assert Path(reference).is_file()

    storage.delete(reference)

    assert not Path(reference).exists()


def test_local_upload_rejects_non_canonical_filename(tmp_path):
    storage = LocalStorageService(str(tmp_path / "uploads"))
    upload = SimpleNamespace(
        filename="folder/../policy.pdf",
        file=BytesIO(b"document"),
    )

    with pytest.raises(StorageReferenceError, match="^storage_reference_invalid$"):
        storage.upload(upload)


def test_local_storage_uses_container_directory_when_writable(monkeypatch, tmp_path):
    container_dir = tmp_path / "container-uploads"
    fallback_dir = tmp_path / "project-uploads"
    original_makedirs = storage_module.os.makedirs

    monkeypatch.setattr(
        storage_module,
        "DEFAULT_LOCAL_UPLOAD_DIR",
        str(container_dir),
        raising=False,
    )
    monkeypatch.setattr(
        storage_module,
        "FALLBACK_LOCAL_UPLOAD_DIR",
        str(fallback_dir),
        raising=False,
    )

    def create_container_directory(path, exist_ok=False):
        assert path == str(container_dir)
        return original_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(storage_module.os, "makedirs", create_container_directory)

    storage = LocalStorageService()

    assert storage.upload_dir == str(container_dir)
    assert container_dir.is_dir()
    assert not fallback_dir.exists()


def test_local_storage_falls_back_when_container_directory_is_not_writable(
    monkeypatch, tmp_path
):
    container_dir = tmp_path / "container-uploads"
    fallback_dir = tmp_path / "project-uploads"
    original_makedirs = storage_module.os.makedirs

    monkeypatch.setattr(
        storage_module,
        "DEFAULT_LOCAL_UPLOAD_DIR",
        str(container_dir),
        raising=False,
    )
    monkeypatch.setattr(
        storage_module,
        "FALLBACK_LOCAL_UPLOAD_DIR",
        str(fallback_dir),
        raising=False,
    )

    def create_or_reject_directory(path, exist_ok=False):
        if path == str(container_dir):
            raise OSError(errno.EROFS, "Read-only file system")
        assert path == str(fallback_dir)
        return original_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(storage_module.os, "makedirs", create_or_reject_directory)

    storage = LocalStorageService()

    assert storage.upload_dir == str(fallback_dir)
    assert fallback_dir.is_dir()


def test_local_storage_falls_back_when_existing_container_directory_is_unwritable(
    monkeypatch,
    tmp_path,
):
    container_dir = tmp_path / "container-uploads"
    fallback_dir = tmp_path / "project-uploads"
    container_dir.mkdir()
    original_prepare = storage_module._prepare_writable_directory

    monkeypatch.setattr(
        storage_module,
        "DEFAULT_LOCAL_UPLOAD_DIR",
        str(container_dir),
        raising=False,
    )
    monkeypatch.setattr(
        storage_module,
        "FALLBACK_LOCAL_UPLOAD_DIR",
        str(fallback_dir),
        raising=False,
    )

    def prepare_or_reject(path):
        if path == str(container_dir):
            raise OSError(errno.EACCES, "Permission denied")
        return original_prepare(path)

    monkeypatch.setattr(
        storage_module,
        "_prepare_writable_directory",
        prepare_or_reject,
    )

    storage = LocalStorageService()

    assert storage.upload_dir == str(fallback_dir.resolve())
    assert fallback_dir.is_dir()


def test_default_local_storage_root_remains_stable_across_instances(
    monkeypatch,
    tmp_path,
):
    container_dir = tmp_path / "container-uploads"
    fallback_dir = tmp_path / "project-uploads"
    original_prepare = storage_module._prepare_writable_directory
    primary_attempts = 0

    monkeypatch.setattr(
        storage_module,
        "DEFAULT_LOCAL_UPLOAD_DIR",
        str(container_dir),
        raising=False,
    )
    monkeypatch.setattr(
        storage_module,
        "FALLBACK_LOCAL_UPLOAD_DIR",
        str(fallback_dir),
        raising=False,
    )

    def fail_primary_once(path):
        nonlocal primary_attempts
        if path == str(container_dir):
            primary_attempts += 1
            raise OSError(errno.EROFS, "Read-only file system")
        return original_prepare(path)

    monkeypatch.setattr(
        storage_module,
        "_prepare_writable_directory",
        fail_primary_once,
    )
    first = LocalStorageService()

    monkeypatch.setattr(
        storage_module,
        "_prepare_writable_directory",
        lambda path: original_prepare(path),
    )
    second = LocalStorageService()

    assert first.upload_dir == str(fallback_dir.resolve())
    assert second.upload_dir == first.upload_dir
    assert primary_attempts == 1
    assert not container_dir.exists()


def test_local_storage_writability_probe_leaves_no_file(tmp_path):
    upload_root = tmp_path / "uploads"

    storage = LocalStorageService(str(upload_root))

    assert storage.upload_dir == str(upload_root.resolve())
    assert list(upload_root.glob(".nodease-storage-probe-*")) == []


def test_local_storage_does_not_fallback_from_explicit_directory_failure(
    monkeypatch, tmp_path
):
    explicit_dir = tmp_path / "explicit-uploads"

    def reject_explicit_directory(path, exist_ok=False):
        assert path == str(explicit_dir)
        raise OSError(errno.EROFS, "Read-only file system")

    monkeypatch.setattr(
        storage_module.os,
        "makedirs",
        reject_explicit_directory,
    )

    with pytest.raises(OSError) as exc:
        LocalStorageService(str(explicit_dir))

    assert exc.value.errno == errno.EROFS


def test_local_delete_rejects_path_outside_upload_root(tmp_path):
    upload_root = tmp_path / "uploads"
    storage = LocalStorageService(str(upload_root))
    outside = tmp_path / "outside.txt"
    outside.write_text("must remain", encoding="utf-8")

    with pytest.raises(StorageReferenceError, match="^storage_reference_invalid$"):
        storage.delete(str(outside))

    assert outside.read_text(encoding="utf-8") == "must remain"


def test_local_delete_rejects_symlink_escape_when_supported(tmp_path):
    upload_root = tmp_path / "uploads"
    storage = LocalStorageService(str(upload_root))
    outside = tmp_path / "outside.txt"
    outside.write_text("must remain", encoding="utf-8")
    link = upload_root / "outside-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not available in this environment")

    with pytest.raises(StorageReferenceError, match="^storage_reference_invalid$"):
        storage.delete(str(link))

    assert outside.read_text(encoding="utf-8") == "must remain"
    assert Path(link).is_symlink()
