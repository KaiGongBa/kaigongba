from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import get_settings


class ObjectAlreadyExistsError(RuntimeError):
    pass


class ObjectNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadTarget:
    local_path: Path | None = None
    redirect_url: str | None = None


class OrderObjectStore(Protocol):
    provider_name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def read(self, key: str) -> bytes: ...

    def download_target(self, key: str, filename: str, content_type: str) -> DownloadTarget: ...

    def healthcheck(self) -> bool: ...


class LocalOrderObjectStore:
    provider_name = "local_private"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(data)
        except FileExistsError as exc:
            raise ObjectAlreadyExistsError(key) from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def download_target(self, key: str, filename: str, content_type: str) -> DownloadTarget:
        del filename, content_type
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return DownloadTarget(local_path=path)

    def healthcheck(self) -> bool:
        if self.root.exists():
            return self.root.is_dir() and os.access(self.root, os.R_OK | os.W_OK | os.X_OK)
        existing_parent = next((parent for parent in self.root.parents if parent.exists()), None)
        return bool(existing_parent and os.access(existing_parent, os.W_OK | os.X_OK))

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("对象存储键超出私有根目录")
        return candidate


class S3OrderObjectStore:
    provider_name = "s3_private"

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        signed_url_seconds: int,
    ) -> None:
        import boto3

        self.bucket = bucket
        self.signed_url_seconds = signed_url_seconds
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if status in {409, 412}:
                raise ObjectAlreadyExistsError(key) from exc
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def read(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if status == 404:
                raise ObjectNotFoundError(key) from exc
            raise
        return response["Body"].read()

    def download_target(self, key: str, filename: str, content_type: str) -> DownloadTarget:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if status == 404:
                raise ObjectNotFoundError(key) from exc
            raise
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentType": content_type,
                "ResponseContentDisposition": f'attachment; filename="{_safe_filename(filename)}"',
            },
            ExpiresIn=self.signed_url_seconds,
        )
        return DownloadTarget(redirect_url=url)

    def healthcheck(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            return False
        return True


def get_order_object_store(provider_name: str | None = None) -> OrderObjectStore:
    settings = get_settings()
    selected = provider_name or settings.order_object_storage_provider
    if selected in {"local", "local_private"}:
        return LocalOrderObjectStore(settings.order_object_storage_dir)
    if selected in {"s3", "s3_private"}:
        return S3OrderObjectStore(
            endpoint_url=settings.order_object_storage_endpoint_url,
            access_key=settings.order_object_storage_access_key,
            secret_key=settings.order_object_storage_secret_key,
            bucket=settings.order_object_storage_bucket,
            region=settings.order_object_storage_region,
            signed_url_seconds=settings.order_object_storage_signed_url_seconds,
        )
    raise ValueError(f"不支持的订单对象存储 Provider：{selected}")


def _safe_filename(value: str) -> str:
    return Path(value).name.replace('"', "_").replace("\r", "_").replace("\n", "_")
