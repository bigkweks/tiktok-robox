"""
Upload-Post API client — queues a carousel for TikTok posting.

Replaces Buffer, which stopped issuing new developer API apps. Upload-Post
holds its own approved TikTok Content Posting API access, so you never need
to register or get a TikTok developer app reviewed yourself.

HOW TO SET UP
─────────────
1. Sign up at https://www.upload-post.com (free to start, no card required)
2. Dashboard → User Profiles → create a profile per TikTok account you own
   (the profile *name* you choose is what you'll put in each Account's
   "Upload-Post profile" field in this app)
3. Click the profile → Connect TikTok → log in and authorize. That's the
   entire OAuth dance — Upload-Post handles it, nothing to build.
4. Dashboard → API Keys → Generate New API Key
5. Add to your .env:
      UPLOAD_POST_API_KEY=your_key_here
6. TikTok posting requires a paid Upload-Post plan (their free tier covers
   every other platform only) — see https://www.upload-post.com/pricing/

Docs: https://docs.upload-post.com/
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests
import structlog

log = structlog.get_logger(__name__)

_API_BASE = "https://api.upload-post.com/api"
_REQUEST_TIMEOUT = 60


class UploadPostError(Exception):
    pass


class UploadPostClient:
    """
    Minimal Upload-Post API client. Instantiate with an API key and call
    queue_gazette_carousel() after each successful pipeline run.
    """

    def __init__(self, api_key: str):
        if not api_key:
            raise UploadPostError(
                "UPLOAD_POST_API_KEY is not set — see upload_post_client.py for setup instructions."
            )
        self._key = api_key
        self._s = requests.Session()
        self._s.headers.update({"Authorization": f"Apikey {api_key}"})

    def queue_gazette_carousel(
        self,
        profile: str,
        slide_paths: list[Path],
        caption: str,
        hashtags: Optional[list[str]] = None,
    ) -> dict:
        """
        Post a carousel of images to TikTok under the given Upload-Post profile.

        Args:
            profile: The Upload-Post "user" profile name connected to a
                     specific TikTok account (set in the Upload-Post dashboard).
            slide_paths: Ordered list of slide PNGs — slide 0 is the cover.
                         TikTok supports up to 35 images per carousel.
            caption: The approved post caption (from ContentApprovalSystem).
            hashtags: Optional list of hashtag strings (with or without leading #).
                      Appended to the caption, space-separated.

        Returns:
            The raw Upload-Post API response dict.

        Raises:
            UploadPostError: If the API call fails or returns an error.
        """
        text = caption.strip()
        if hashtags:
            tag_line = " ".join(f"#{h.lstrip('#')}" for h in hashtags if h.strip())
            if tag_line:
                text = f"{text}\n\n{tag_line}"

        images = [p for p in slide_paths if p.exists()][:35]
        if not images:
            raise UploadPostError("No valid slide paths provided — nothing to upload.")

        log.info("upload_post.post_start", profile=profile, slides=len(images), caption_len=len(text))

        files = [
            ("photos[]", (img.name, open(img, "rb"), "image/png"))
            for img in images
        ]
        data = {
            "user": profile,
            "platform[]": "tiktok",
            "title": text[:150],
            "description": text,
        }

        try:
            r = self._s.post(
                f"{_API_BASE}/upload_photos",
                data=data,
                files=files,
                timeout=_REQUEST_TIMEOUT * 3,  # large payload — give it 3 min
            )
        finally:
            for _, (_, fh, _) in files:
                fh.close()

        _raise_for_status(r, "queue_carousel")
        result = r.json()
        log.info("upload_post.post_complete", profile=profile, response=result)
        return result

    def list_profiles(self) -> list[dict]:
        """Return all Upload-Post profiles configured for this API key."""
        r = self._s.get(f"{_API_BASE}/uploadposts/users", timeout=_REQUEST_TIMEOUT)
        _raise_for_status(r, "list_profiles")
        return r.json()


def _raise_for_status(r: requests.Response, op: str) -> None:
    if r.ok:
        return
    try:
        body = r.json()
        msg = body.get("message") or body.get("error") or r.text[:300]
    except Exception:
        msg = r.text[:300]
    log.error("upload_post.api_error", op=op, status=r.status_code, msg=msg)
    raise UploadPostError(f"Upload-Post API error ({op}): HTTP {r.status_code} — {msg}")


# ── CLI helper (python -m src.integrations.upload_post_client) ────────────

if __name__ == "__main__":
    import os
    import sys

    key = os.getenv("UPLOAD_POST_API_KEY", "").strip()
    if not key:
        print(
            "\n❌  UPLOAD_POST_API_KEY not set.\n"
            "   Follow the setup instructions at the top of this file.\n"
        )
        sys.exit(1)

    client = UploadPostClient(key)
    try:
        profiles = client.list_profiles()
    except UploadPostError as e:
        print(f"\n❌  {e}\n")
        sys.exit(1)

    print(f"\n✅  Connected. {len(profiles)} profile(s) configured in Upload-Post:\n")
    for p in profiles:
        print(f"  {p}")
    print(
        "\nUse the profile's name (not shown above if the API returns a "
        "different shape — check your Upload-Post dashboard) in each "
        "Account's 'Upload-Post profile' field.\n"
    )
