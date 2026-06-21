"""TikTok Content Posting API v2 — photo carousel uploader."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import structlog

log = structlog.get_logger(__name__)

_BASE = "https://open.tiktokapis.com/v2"


@dataclass
class PostResult:
    publish_id: str
    tiktok_post_id: Optional[str] = None


class TikTokPoster:
    """
    Posts 6-slide photo carousels via TikTok Content Posting API v2.

    Requires TIKTOK_ACCESS_TOKEN (and optionally TIKTOK_OPEN_ID) in .env.
    The user must complete the OAuth flow once to obtain these tokens:
      https://developers.tiktok.com/doc/content-posting-api-get-started

    Privacy levels: PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS | SELF_ONLY
    Use SELF_ONLY for testing; switch to PUBLIC_TO_EVERYONE for real posts.
    """

    def __init__(self, access_token: str, open_id: str = ""):
        self._token = access_token
        self._open_id = open_id
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def post_carousel(
        self,
        slide_paths: list[Path],
        caption: str,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> PostResult:
        """
        Upload slides and publish as a TikTok photo carousel post.

        Steps:
          1. Init post  → TikTok returns publish_id + per-image upload URLs
          2. PUT each slide image to its upload URL
          3. Poll status until PUBLISH_COMPLETE → return tiktok_post_id
        """
        publish_id, upload_list = self._init_post(slide_paths, caption, privacy_level)
        log.info("tiktok.post_initialized", publish_id=publish_id, slides=len(upload_list))

        path_by_name = {p.name: p for p in slide_paths}
        for item in upload_list:
            fname = item["file_name"]
            path = path_by_name.get(fname)
            if path is None:
                raise FileNotFoundError(f"Slide not found for TikTok upload: {fname}")
            self._upload_photo(item["upload_url"], path)
            log.info("tiktok.slide_uploaded", file=fname)

        tiktok_post_id = self._poll_status(publish_id)
        log.info("tiktok.post_published", publish_id=publish_id, post_id=tiktok_post_id)
        return PostResult(publish_id=publish_id, tiktok_post_id=tiktok_post_id)

    # ── Private helpers ───────────────────────────────────────────────────

    def _init_post(
        self,
        slide_paths: list[Path],
        caption: str,
        privacy_level: str,
    ) -> tuple[str, list[dict]]:
        body = {
            "post_info": {
                "title": caption[:2200],
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_stitch": False,
                "disable_comment": False,
                "auto_add_music": True,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "photo_images": [{"file_name": p.name} for p in slide_paths],
                "photo_cover_index": 0,
            },
            "media_type": "PHOTO",
        }
        with httpx.Client(headers=self._headers, timeout=30) as client:
            resp = client.post(f"{_BASE}/post/publish/content/init/", json=body)
        resp.raise_for_status()
        data = resp.json()
        err = data.get("error", {})
        if err.get("code", "ok") != "ok":
            raise RuntimeError(f"TikTok init error: {err.get('message', err)}")
        publish_id: str = data["data"]["publish_id"]
        upload_list: list[dict] = data["data"]["photo_upload_list"]
        return publish_id, upload_list

    @staticmethod
    def _upload_photo(upload_url: str, path: Path) -> None:
        content = path.read_bytes()
        content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        resp = httpx.put(
            upload_url,
            content=content,
            headers={
                "Content-Type": content_type,
                "Content-Length": str(len(content)),
            },
            timeout=120,
        )
        resp.raise_for_status()

    def _poll_status(self, publish_id: str, max_wait: int = 120) -> Optional[str]:
        """Poll until PUBLISH_COMPLETE or timeout. Returns TikTok post ID."""
        body = {"publish_id": publish_id}
        deadline = time.monotonic() + max_wait
        with httpx.Client(headers=self._headers, timeout=30) as client:
            while time.monotonic() < deadline:
                resp = client.post(f"{_BASE}/post/publish/status/fetch/", json=body)
                resp.raise_for_status()
                data = resp.json()
                status = data.get("data", {}).get("status", "")
                if status == "PUBLISH_COMPLETE":
                    ids = data["data"].get("publicaly_available_post_id", [])
                    return ids[0] if ids else publish_id
                if status in ("FAILED", "PUBLISH_ERROR"):
                    reason = data.get("data", {}).get("fail_reason", "unknown")
                    raise RuntimeError(f"TikTok publish failed: {reason}")
                time.sleep(5)
        log.warning("tiktok.poll_timeout", publish_id=publish_id)
        return None


def get_poster_from_settings() -> Optional[TikTokPoster]:
    """Return a TikTokPoster if credentials are configured, else None."""
    from src.config import get_settings
    s = get_settings()
    if not s.TIKTOK_ACCESS_TOKEN:
        return None
    return TikTokPoster(access_token=s.TIKTOK_ACCESS_TOKEN, open_id=s.TIKTOK_OPEN_ID)
