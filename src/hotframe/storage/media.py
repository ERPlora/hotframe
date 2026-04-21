# SPDX-License-Identifier: Apache-2.0
"""
Media storage service — local filesystem or S3.

Provides a unified API for storing and retrieving user-uploaded files.
Each app/module gets its own subdirectory under MEDIA_ROOT.

Usage::

    from hotframe.storage.media import MediaStorage

    storage = MediaStorage()  # reads from settings

    # Save a file
    path = await storage.save("avatars", "user-123.jpg", file_content)
    # → "avatars/user-123.jpg"

    # Get URL
    url = storage.url("avatars/user-123.jpg")
    # → "/media/avatars/user-123.jpg" (local) or "https://s3.../avatars/user-123.jpg" (S3)

    # Read
    content = await storage.read("avatars/user-123.jpg")

    # Delete
    await storage.delete("avatars/user-123.jpg")

    # List files in a directory
    files = await storage.list_files("avatars")

    # Check exists
    exists = await storage.exists("avatars/user-123.jpg")
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MediaStorage:
    """Unified media file storage.

    Supports local filesystem and S3 backends.
    Backend is determined by ``settings.MEDIA_STORAGE``.
    """

    def __init__(self, settings: Any | None = None) -> None:
        if settings is None:
            from hotframe.config.settings import get_settings

            settings = get_settings()

        self._storage_type = settings.MEDIA_STORAGE
        self._media_root = Path(settings.MEDIA_ROOT).resolve()
        self._media_url = settings.MEDIA_URL
        self._s3_bucket = getattr(settings, "MEDIA_S3_BUCKET", "")
        self._aws_region = getattr(settings, "AWS_REGION", "us-east-1")

        # Ensure local media root exists
        if self._storage_type == "local":
            self._media_root.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, module_or_app_name: str, media_path: str = "") -> str:
        """Get the media subdirectory for an app/module.

        Args:
            module_or_app_name: The app or module name.
            media_path: Explicit media_path from config. If empty, uses the name.

        Returns:
            The subdirectory name (e.g. "facturas", "customers").
        """
        return media_path or module_or_app_name

    async def save(self, subdir: str, filename: str, content: bytes) -> str:
        """Save a file to storage.

        Args:
            subdir: Subdirectory (e.g. "avatars", "facturas").
            filename: File name (e.g. "user-123.jpg").
            content: File content as bytes.

        Returns:
            Relative path (e.g. "avatars/user-123.jpg").
        """
        rel_path = f"{subdir}/{filename}"

        if self._storage_type == "s3":
            await self._s3_put(rel_path, content)
        else:
            full_path = self._media_root / subdir / filename
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)

        logger.debug("Saved media file: %s", rel_path)
        return rel_path

    async def read(self, rel_path: str) -> bytes | None:
        """Read a file from storage.

        Returns None if the file does not exist.
        """
        if self._storage_type == "s3":
            return await self._s3_get(rel_path)

        full_path = self._media_root / rel_path
        if full_path.exists():
            return full_path.read_bytes()
        return None

    async def delete(self, rel_path: str) -> bool:
        """Delete a file from storage. Returns True if deleted."""
        if self._storage_type == "s3":
            return await self._s3_delete(rel_path)

        full_path = self._media_root / rel_path
        if full_path.exists():
            full_path.unlink()
            logger.debug("Deleted media file: %s", rel_path)
            return True
        return False

    async def exists(self, rel_path: str) -> bool:
        """Check if a file exists in storage."""
        if self._storage_type == "s3":
            return await self._s3_exists(rel_path)

        return (self._media_root / rel_path).exists()

    async def list_files(self, subdir: str) -> list[str]:
        """List all files in a subdirectory.

        Returns relative paths (e.g. ["avatars/a.jpg", "avatars/b.png"]).
        """
        if self._storage_type == "s3":
            return await self._s3_list(subdir)

        dir_path = self._media_root / subdir
        if not dir_path.exists():
            return []

        files = []
        for f in sorted(dir_path.iterdir()):
            if f.is_file():
                files.append(f"{subdir}/{f.name}")
        return files

    def url(self, rel_path: str) -> str:
        """Get the URL for a media file.

        Local: /media/avatars/user-123.jpg
        S3: https://{bucket}.s3.{region}.amazonaws.com/{rel_path}
        """
        if self._storage_type == "s3" and self._s3_bucket:
            return f"https://{self._s3_bucket}.s3.{self._aws_region}.amazonaws.com/{rel_path}"

        return f"{self._media_url}{rel_path}"

    async def delete_directory(self, subdir: str) -> int:
        """Delete all files in a subdirectory. Returns count of files deleted.

        Used during module uninstall to clean up media files.
        """
        if self._storage_type == "s3":
            return await self._s3_delete_prefix(subdir)

        dir_path = self._media_root / subdir
        if not dir_path.exists():
            return 0

        count = sum(1 for f in dir_path.rglob("*") if f.is_file())
        shutil.rmtree(dir_path)
        logger.info("Deleted media directory %s (%d files)", subdir, count)
        return count

    # ------------------------------------------------------------------
    # S3 backend (lazy — only loads aioboto3 when needed)
    # ------------------------------------------------------------------

    async def _s3_put(self, key: str, content: bytes) -> None:
        try:
            import aioboto3  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "aioboto3 is required for S3 media storage. Install it with: pip install aioboto3"
            ) from None

        session = aioboto3.Session()
        async with session.client("s3", region_name=self._aws_region) as s3:
            await s3.put_object(Bucket=self._s3_bucket, Key=key, Body=content)

    async def _s3_get(self, key: str) -> bytes | None:
        import aioboto3

        session = aioboto3.Session()
        async with session.client("s3", region_name=self._aws_region) as s3:
            try:
                response = await s3.get_object(Bucket=self._s3_bucket, Key=key)
                return await response["Body"].read()
            except Exception:
                return None

    async def _s3_delete(self, key: str) -> bool:
        import aioboto3

        session = aioboto3.Session()
        async with session.client("s3", region_name=self._aws_region) as s3:
            try:
                await s3.delete_object(Bucket=self._s3_bucket, Key=key)
                return True
            except Exception:
                return False

    async def _s3_exists(self, key: str) -> bool:
        import aioboto3

        session = aioboto3.Session()
        async with session.client("s3", region_name=self._aws_region) as s3:
            try:
                await s3.head_object(Bucket=self._s3_bucket, Key=key)
                return True
            except Exception:
                return False

    async def _s3_list(self, prefix: str) -> list[str]:
        import aioboto3

        session = aioboto3.Session()
        async with session.client("s3", region_name=self._aws_region) as s3:
            try:
                response = await s3.list_objects_v2(Bucket=self._s3_bucket, Prefix=prefix + "/")
                return [obj["Key"] for obj in response.get("Contents", [])]
            except Exception:
                return []

    async def _s3_delete_prefix(self, prefix: str) -> int:
        files = await self._s3_list(prefix)
        for key in files:
            await self._s3_delete(key)
        return len(files)


# Singleton
_storage: MediaStorage | None = None


def get_media_storage() -> MediaStorage:
    """Return cached singleton media storage instance."""
    global _storage
    if _storage is None:
        _storage = MediaStorage()
    return _storage


def reset_media_storage() -> None:
    """Reset cached storage (for testing)."""
    global _storage
    _storage = None
