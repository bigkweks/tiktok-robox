"""
Buffer API client — queues a Gazette carousel for TikTok posting.

HOW TO GET YOUR BUFFER ACCESS TOKEN
─────────────────────────────────────
1. Go to  https://buffer.com/developers/apps/create
2. Fill in any app name (e.g. "Gemvault Bot") + redirect URI (e.g. http://localhost)
3. Note your  Client ID  and  Client Secret
4. Open this URL in your browser, replacing CLIENT_ID:
      https://bufferapp.com/oauth2/authorize?client_id=CLIENT_ID&redirect_uri=http://localhost&response_type=code
5. Approve → you'll be redirected to http://localhost?code=SOME_CODE
6. Copy SOME_CODE, then in your terminal:
      curl -X POST https://api.bufferapp.com/1/oauth2/token.json \
        -d "client_id=CLIENT_ID&client_secret=CLIENT_SECRET&redirect_uri=http://localhost&code=SOME_CODE&grant_type=authorization_code"
7. Copy the access_token from the response
8. Add to your .env:
      BUFFER_ACCESS_TOKEN=your_token_here

TIKTOK PROFILE ID
─────────────────
Run:  python -m src.integrations.buffer_client
This will print all your connected Buffer profiles and their IDs.
Copy the TikTok profile id and add to .env:
      BUFFER_TIKTOK_PROFILE_ID=your_profile_id

POSTING SCHEDULE
─────────────────
Set your daily posting times in Buffer:
  buffer.com → Settings → Posting Schedule → TikTok → Add a posting time → 12:00pm
The morning pipeline job (7:00am UTC by default) generates the carousel and adds
it to the queue. Buffer posts it at your next scheduled slot — no extra config needed.
"""
from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Optional

import requests
import structlog

log = structlog.get_logger(__name__)

_BUFFER_API = "https://api.bufferapp.com/1"
_REQUEST_TIMEOUT = 60


class BufferError(Exception):
    pass


class BufferClient:
    """
    Minimal Buffer API v1 client.  Instantiate with an access token and call
    queue_gazette_carousel() after each successful pipeline run.
    """

    def __init__(self, access_token: str):
        if not access_token:
            raise BufferError("BUFFER_ACCESS_TOKEN is not set — see buffer_client.py for setup instructions.")
        self._token = access_token
        self._s = requests.Session()
        self._s.headers.update({"Accept": "application/json"})

    # ── Profile discovery ──────────────────────────────────────────────

    def get_profiles(self) -> list[dict]:
        """Return all social profiles connected to this Buffer account."""
        r = self._s.get(
            f"{_BUFFER_API}/profiles.json",
            params={"access_token": self._token},
            timeout=_REQUEST_TIMEOUT,
        )
        _raise_for_status(r, "get_profiles")
        return r.json()

    def find_tiktok_profile_id(self) -> Optional[str]:
        """Return the Buffer profile id for the first connected TikTok account."""
        for p in self.get_profiles():
            if p.get("service", "").lower() == "tiktok":
                log.info("buffer.tiktok_profile_found",
                         id=p["id"], username=p.get("formatted_username"))
                return p["id"]
        log.warning("buffer.no_tiktok_profile",
                    advice="Connect TikTok to Buffer at buffer.com/manage-channels")
        return None

    # ── Media helpers ──────────────────────────────────────────────────

    @staticmethod
    def _img_data_uri(path: Path) -> str:
        """Encode a PNG/JPEG as a data URI so Buffer can receive it inline."""
        suffix = path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"data:{mime};base64,{b64}"

    # ── Core upload ────────────────────────────────────────────────────

    def queue_gazette_carousel(
        self,
        profile_id: str,
        slide_paths: list[Path],
        caption: str,
        hashtags: Optional[list[str]] = None,
        *,
        now: bool = False,
    ) -> dict:
        """
        Add a Gazette carousel to the Buffer queue for the given profile.

        Args:
            profile_id: Buffer profile id for TikTok (or any supported network).
            slide_paths: Ordered list of slide PNGs — slide 0 is the cover.
                         TikTok supports up to 35 images; Buffer accepts up to 10.
            caption: The approved post caption (from ContentApprovalSystem).
            hashtags: Optional list of hashtag strings (with or without leading #).
                      Appended to the caption, space-separated.
            now: If True, post immediately instead of adding to the queue.

        Returns:
            The raw Buffer API response dict.

        Raises:
            BufferError: If the API call fails or returns an error.
        """
        # Build the full post text
        text = caption.strip()
        if hashtags:
            tag_line = " ".join(
                f"#{h.lstrip('#')}" for h in hashtags if h.strip()
            )
            if tag_line:
                text = f"{text}\n\n{tag_line}"

        # Encode slides — Buffer accepts up to 10 images per update.
        # Carousel slides are the cover (0) + per-game slides (1–N).
        images = [p for p in slide_paths if p.exists()][:10]
        if not images:
            raise BufferError("No valid slide paths provided — nothing to upload.")

        log.info("buffer.upload_start", profile_id=profile_id,
                 slides=len(images), caption_len=len(text))

        data: dict[str, str] = {
            "profile_ids[]": profile_id,
            "text": text,
            "access_token": self._token,
        }

        if now:
            data["now"] = "true"

        if len(images) == 1:
            # Single-image path — safe for all Buffer/TikTok plan levels.
            data["media[photo]"] = self._img_data_uri(images[0])
        else:
            # Multi-image carousel path.
            # Buffer encodes multiple photos as media[photos][0], [1], …
            for i, img_path in enumerate(images):
                data[f"media[photos][{i}]"] = self._img_data_uri(img_path)

        r = self._s.post(
            f"{_BUFFER_API}/updates/create.json",
            data=data,
            timeout=_REQUEST_TIMEOUT * 3,   # large payload — give it 3 min
        )
        _raise_for_status(r, "queue_carousel")
        result = r.json()

        n = len(result.get("updates", []))
        log.info("buffer.upload_complete", updates=n, profile_id=profile_id)
        return result


# ── Error handling ─────────────────────────────────────────────────────────────

def _raise_for_status(r: requests.Response, op: str) -> None:
    if r.ok:
        return
    try:
        body = r.json()
        msg = body.get("message") or body.get("error") or r.text[:300]
    except Exception:
        msg = r.text[:300]
    log.error("buffer.api_error", op=op, status=r.status_code, msg=msg)
    raise BufferError(f"Buffer API error ({op}): HTTP {r.status_code} — {msg}")


# ── CLI helper (python -m src.integrations.buffer_client) ─────────────────────

if __name__ == "__main__":
    import os, sys  # noqa: E401

    token = os.getenv("BUFFER_ACCESS_TOKEN", "").strip()
    if not token:
        print(
            "\n❌  BUFFER_ACCESS_TOKEN not set.\n"
            "   Follow the setup instructions at the top of this file.\n"
        )
        sys.exit(1)

    client = BufferClient(token)
    try:
        profiles = client.get_profiles()
    except BufferError as e:
        print(f"\n❌  {e}\n")
        sys.exit(1)

    print(f"\n✅  Connected. {len(profiles)} profile(s):\n")
    for p in profiles:
        marker = " ← TikTok" if p.get("service", "").lower() == "tiktok" else ""
        print(f"  {p.get('service'):12s}  id={p['id']}  "
              f"@{p.get('formatted_username','?')}{marker}")
    print()
    tiktok_id = next(
        (p["id"] for p in profiles if p.get("service", "").lower() == "tiktok"),
        None,
    )
    if tiktok_id:
        print(f"Add to .env:\n  BUFFER_TIKTOK_PROFILE_ID={tiktok_id}\n")
    else:
        print("No TikTok profile found. Connect TikTok at buffer.com/manage-channels\n")
