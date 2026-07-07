"""Blob store — large immutable payloads (traces, seed sets, evidence packs).

The row keeps metadata + a content-addressed pointer (`blob_uri` + `sha256`);
the bytes live here. `LocalBlob` writes under a local dir (default); `S3Blob`
targets MinIO/S3 via boto3.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..config import settings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BlobStore(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes) -> tuple[str, str]:
        """Return (uri, sha256)."""

    @abstractmethod
    async def get(self, uri: str) -> bytes: ...

    async def put_json(self, key: str, obj: Any) -> tuple[str, str]:
        return await self.put(key, json.dumps(obj, default=str).encode())

    async def get_json(self, uri: str) -> Any:
        return json.loads(await self.get(uri))


class LocalBlob(BlobStore):
    def __init__(self, root: str = ".eeof-blobs") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._root / key.lstrip("/")

    async def put(self, key: str, data: bytes) -> tuple[str, str]:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return f"file://{p.resolve()}", sha256_hex(data)

    async def get(self, uri: str) -> bytes:
        path = uri[len("file://"):] if uri.startswith("file://") else str(self._path(uri))
        return Path(path).read_bytes()


class S3Blob(BlobStore):
    """MinIO / S3 via boto3. Requires extra: infra."""

    def __init__(self) -> None:
        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
        )
        self._bucket = settings.s3_bucket

    def ensure_bucket(self) -> None:
        import botocore.exceptions

        try:
            self._client.create_bucket(Bucket=self._bucket)
        except botocore.exceptions.ClientError:
            pass

    async def put(self, key: str, data: bytes) -> tuple[str, str]:
        import asyncio

        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data
        )
        return f"s3://{self._bucket}/{key}", sha256_hex(data)

    async def get(self, uri: str) -> bytes:
        import asyncio

        key = uri.split(f"s3://{self._bucket}/", 1)[-1]
        resp = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        return resp["Body"].read()


_blob: BlobStore | None = None


def get_blob() -> BlobStore:
    global _blob
    if _blob is None:
        _blob = LocalBlob() if settings.is_local else S3Blob()
    return _blob
