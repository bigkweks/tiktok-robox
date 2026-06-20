"""
Screenshot engine.

Strategy: We use Roblox's high-quality official thumbnails rather than
capturing live gameplay. This is actually BETTER for content:
  - Consistent dimensions and quality
  - Professional art direction (Roblox pays designers for these)
  - Available instantly — no game launch needed
  - Batch processable

For each game we fetch:
  1. Cover thumbnail (768×432 landscape, used for video slides)
  2. Game icon (512×512 square, used for thumbnail overlays)
  3. Gallery thumbnails (multiple angles, used for variety)

We also generate a "game page screenshot" via Playwright showing the
Roblox.com game page for extra visual variety.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import httpx
import structlog

from src.config import get_settings

log = structlog.get_logger(__name__)


class ScreenshotEngine:
    def __init__(self):
        self._settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> ScreenshotEngine:
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    async def download_image(self, url: str, dest_path: Path) -> Optional[Path]:
        """Download an image URL to disk, return path on success."""
        if not url:
            return None
        try:
            assert self._client is not None
            resp = await self._client.get(url)
            resp.raise_for_status()

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(resp.content)
            log.debug("screenshot.downloaded", path=str(dest_path))
            return dest_path
        except Exception as exc:
            log.warning("screenshot.download_failed", url=url, error=str(exc))
            return None

    async def capture_game_assets(
        self,
        universe_id: str,
        thumbnail_url: Optional[str],
        icon_url: Optional[str],
    ) -> dict[str, Optional[Path]]:
        """
        Download all visual assets for a game.
        Returns a dict of {asset_type: local_path}.
        """
        base_dir = Path(self._settings.OUTPUT_DIR, "screenshots", universe_id)
        base_dir.mkdir(parents=True, exist_ok=True)

        tasks = {}
        if thumbnail_url:
            tasks["thumbnail"] = self.download_image(
                thumbnail_url,
                base_dir / "thumbnail.png",
            )
        if icon_url:
            tasks["icon"] = self.download_image(
                icon_url,
                base_dir / "icon.png",
            )

        results: dict[str, Optional[Path]] = {}
        if tasks:
            done = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), done):
                if isinstance(result, Exception):
                    log.warning("screenshot.asset_failed", key=key, error=str(result))
                    results[key] = None
                else:
                    results[key] = result

        return results

    async def capture_roblox_page(
        self,
        universe_id: str,
        place_id: str,
    ) -> Optional[Path]:
        """
        Capture the Roblox.com game page via Playwright.
        Falls back gracefully if Playwright isn't available.
        Returns the path to the screenshot PNG, or None.
        """
        dest = Path(self._settings.OUTPUT_DIR, "screenshots", universe_id, "page.png")
        if dest.exists():
            return dest

        try:
            from playwright.async_api import async_playwright  # noqa: PLC0415

            url = f"https://www.roblox.com/games/{place_id}"
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                )
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await asyncio.sleep(2)

                # Hide cookie banners and age-gate popups
                await page.evaluate("""
                    document.querySelectorAll(
                        '.modal-backdrop, .cookie-banner, [class*="cookie"], [class*="Banner"]'
                    ).forEach(el => el.remove());
                """)

                dest.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(dest), full_page=False, clip={"x": 0, "y": 0, "width": 1280, "height": 720})
                await browser.close()

            log.info("screenshot.page_captured", universe_id=universe_id)
            return dest

        except ImportError:
            log.info("screenshot.playwright_not_available")
            return None
        except Exception as exc:
            log.warning("screenshot.page_failed", universe_id=universe_id, error=str(exc))
            return None
