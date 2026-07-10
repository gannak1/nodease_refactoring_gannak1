import logging
from pathlib import Path

import pytest

from apps.gateway.services.storage import (
    LocalStorageService,
    S3StorageService,
    StorageDeleteError,
    StorageReferenceError,
)


class _FailingS3Client:
    def __init__(self, message: str) -> None:
        self.message = message

    def delete_object(self, **_kwargs) -> None:
        raise RuntimeError(self.message)


class _CaptureS3Client:
    def __init__(self) -> None:
        self.calls = []

    def delete_object(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _s3_storage(client=None) -> S3StorageService:
    storage = object.__new__(S3StorageService)
    storage.bucket_name = "knowledge-bucket"
    storage.region = "region"
    storage.s3_client = client or _CaptureS3Client()
    return storage


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
