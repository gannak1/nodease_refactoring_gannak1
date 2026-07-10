import logging

import pytest

from apps.gateway.services.storage import S3StorageService, StorageDeleteError


class _FailingS3Client:
    def __init__(self, message: str) -> None:
        self.message = message

    def delete_object(self, **_kwargs) -> None:
        raise RuntimeError(self.message)


def test_s3_delete_raises_safe_typed_error_without_provider_details(caplog):
    sensitive_value = "private-bucket/customer-contract.pdf"
    storage = object.__new__(S3StorageService)
    storage.bucket_name = "private-bucket"
    storage.s3_client = _FailingS3Client(sensitive_value)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StorageDeleteError, match="^storage_delete_failed$") as exc:
            storage.delete("s3://private-bucket/customer-contract.pdf")

    assert exc.value.__cause__ is None
    assert sensitive_value not in str(exc.value)
    assert sensitive_value not in caplog.text


def test_s3_delete_preserves_nested_object_key():
    calls = []

    class _S3Client:
        def delete_object(self, **kwargs) -> None:
            calls.append(kwargs)

    storage = object.__new__(S3StorageService)
    storage.bucket_name = "knowledge-bucket"
    storage.s3_client = _S3Client()

    storage.delete("https://knowledge-bucket.s3.region.amazonaws.com/nested/doc.pdf")

    assert calls == [
        {"Bucket": "knowledge-bucket", "Key": "nested/doc.pdf"},
    ]
