from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from app.transaction.object_storage import (
    LocalOrderObjectStore,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    S3OrderObjectStore,
)


def test_local_object_storage_roundtrip_and_path_isolation(tmp_path) -> None:
    store = LocalOrderObjectStore(tmp_path)
    store.put("tenant/order/file.txt", b"local-object", "text/plain")

    target = store.download_target("tenant/order/file.txt", "file.txt", "text/plain")
    assert target.local_path is not None
    assert target.local_path.read_bytes() == b"local-object"
    assert target.redirect_url is None
    assert store.read("tenant/order/file.txt") == b"local-object"

    with pytest.raises(ObjectAlreadyExistsError):
        store.put("tenant/order/file.txt", b"duplicate", "text/plain")
    with pytest.raises(ValueError, match="超出私有根目录"):
        store.put("../escape.txt", b"escape", "text/plain")

    store.delete("tenant/order/file.txt")
    with pytest.raises(ObjectNotFoundError):
        store.download_target("tenant/order/file.txt", "file.txt", "text/plain")


def test_local_object_storage_healthcheck_accepts_writable_parent(tmp_path) -> None:
    store = LocalOrderObjectStore(tmp_path / "objects")

    assert store.healthcheck() is True


@pytest.mark.skipif(
    not os.getenv("KGB_MINIO_TEST_ENDPOINT"),
    reason="KGB_MINIO_TEST_ENDPOINT is required for the MinIO integration test",
)
def test_minio_object_storage_roundtrip_and_presigned_download() -> None:
    store = S3OrderObjectStore(
        endpoint_url=os.environ["KGB_MINIO_TEST_ENDPOINT"],
        access_key=os.getenv("KGB_MINIO_ACCESS_KEY", "kaigongba"),
        secret_key=os.getenv("KGB_MINIO_SECRET_KEY", "kaigongba-dev-only"),
        bucket=os.getenv("KGB_MINIO_BUCKET", "kaigongba-order-files"),
        region="us-east-1",
        signed_url_seconds=300,
    )
    key = f"integration-test/{uuid4().hex}/evidence.txt"
    try:
        assert store.healthcheck() is True
        store.put(key, b"private-minio-object", "text/plain")
        with pytest.raises(ObjectAlreadyExistsError):
            store.put(key, b"duplicate", "text/plain")

        target = store.download_target(key, "evidence.txt", "text/plain")
        assert target.local_path is None
        assert target.redirect_url
        with httpx.Client(trust_env=False) as client:
            response = client.get(target.redirect_url)
        assert response.status_code == 200
        assert response.content == b"private-minio-object"
        assert store.read(key) == b"private-minio-object"
    finally:
        store.delete(key)

    with pytest.raises(ObjectNotFoundError):
        store.download_target(key, "evidence.txt", "text/plain")
