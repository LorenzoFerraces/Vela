"""Cloudflare R2 object storage (S3-compatible API)."""

from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.exceptions import ObjectStorageError
from app.core.storage.object_storage import ObjectStorage


class CloudflareR2ObjectStorage(ObjectStorage):
    """Upload and delete objects in a Cloudflare R2 bucket."""

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base_url: str,
    ) -> None:
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    async def put_object(
        self, *, key: str, body: bytes, content_type: str
    ) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError("Could not upload avatar. Try again later.") from exc

    async def delete_object(self, *, key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError("Could not delete avatar. Try again later.") from exc

    def public_url(self, *, key: str, cache_bust: str | None = None) -> str:
        base = f"{self._public_base_url}/{key.lstrip('/')}"
        if cache_bust is None:
            return base
        query = urlencode({"v": cache_bust})
        return f"{base}?{query}"
