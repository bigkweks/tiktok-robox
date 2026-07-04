"""
Buffer web uploader — posts a Gazette carousel via the Buffer website.

The Buffer developer API is no longer available to new apps. This module
uses Playwright to drive buffer.com directly in a headless browser instead.

SETUP
─────
1. Add to your .env:
      BUFFER_EMAIL=your@email.com
      BUFFER_PASSWORD=yourpassword

2. On each Account in /accounts, set "Buffer TikTok Profile ID" to the
   TikTok handle exactly as it appears in Buffer's channel list, e.g.:
      @robloxgems

   The uploader finds this channel by matching that text in Buffer's
   channel selector. If you only have one TikTok channel connected,
   any non-empty value works — the uploader picks the only channel.

3. If Buffer has 2FA enabled on your account, disable it:
      buffer.com → Settings → Security → Two-Factor Authentication → Disable
   Or complete a manual login first so cookies are cached (see below).

SESSION COOKIES
───────────────
After the first successful login, cookies are saved to .buffer_session.json.
Subsequent uploads skip the login step and reuse the saved session (~7-day TTL).
Delete that file to force a fresh login.

TEST YOUR LOGIN
───────────────
Run:  python -m src.integrations.buffer_client
Opens a visible browser so you can confirm login works and see your channels.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import structlog
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

log = structlog.get_logger(__name__)

_SESSION_FILE = Path(".buffer_session.json")
_BUFFER_PUBLISH = "https://publish.buffer.com/"
_BUFFER_LOGIN = "https://login.buffer.com/login"
_TIMEOUT = 30_000       # ms — most UI interactions
_UPLOAD_TIMEOUT = 120_000  # ms — file uploads


class BufferError(Exception):
    pass


class BufferClient:
    """
    Playwright-based Buffer uploader. Drives buffer.com in a headless Chromium
    browser. Same public interface as the old API-based client.
    """

    def __init__(self, email: str, password: str, *, headless: bool = True):
        if not email or not password:
            raise BufferError(
                "BUFFER_EMAIL and BUFFER_PASSWORD must be set in .env — "
                "see src/integrations/buffer_client.py for setup instructions."
            )
        self._email = email
        self._password = password
        self._headless = headless

    # ── Public API ────────────────────────────────────────────────────────

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
        Post a carousel to Buffer via the web interface.

        Args:
            profile_id: The TikTok handle as shown in Buffer's channel
                        selector (e.g. "@robloxgems"). Matched
                        case-insensitively. If only one channel is
                        connected, any non-empty string works.
            slide_paths: Ordered list of slide image files (PNG/JPEG).
                         Slide 0 is the cover. Max 10 uploaded.
            caption:     Post caption text.
            hashtags:    Optional hashtag strings appended to caption.
            now:         Post immediately instead of adding to queue.

        Returns:
            {"queued": True, "updates": 1, "slides": N}

        Raises:
            BufferError on login failure, channel not found, or upload error.
        """
        text = _build_caption(caption, hashtags)
        images = [p for p in slide_paths if p.exists()][:10]
        if not images:
            raise BufferError("No valid slide image files found.")

        log.info("buffer.upload_start", channel=profile_id, slides=len(images))

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self._headless,
                executable_path="/opt/pw-browsers/chromium",
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            # Restore saved session to skip login when cookies are still valid
            if _SESSION_FILE.exists():
                try:
                    ctx.add_cookies(json.loads(_SESSION_FILE.read_text()))
                    log.debug("buffer.session_restored")
                except Exception:
                    pass

            page = ctx.new_page()
            try:
                result = self._run(page, ctx, profile_id, images, text, now)
                log.info("buffer.upload_complete", **result)
                return result
            except BufferError:
                _save_debug_screenshot(page, "buffer_error")
                raise
            except Exception as exc:
                _save_debug_screenshot(page, "buffer_unexpected")
                raise BufferError(
                    f"Unexpected error during Buffer upload: {exc}"
                ) from exc
            finally:
                browser.close()

    def test_login(self) -> dict:
        """Verify credentials and return visible channel names."""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self._headless,
                executable_path="/opt/pw-browsers/chromium",
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            if _SESSION_FILE.exists():
                try:
                    ctx.add_cookies(json.loads(_SESSION_FILE.read_text()))
                except Exception:
                    pass
            page = ctx.new_page()
            try:
                page.goto(_BUFFER_PUBLISH, wait_until="domcontentloaded", timeout=_TIMEOUT)
                if "login" in page.url.lower() or "auth" in page.url.lower():
                    self._login(page)
                    _save_session(ctx)
                time.sleep(2)
                channels = _list_visible_channels(page)
                return {"ok": True, "channels": channels}
            except BufferError as exc:
                return {"ok": False, "error": str(exc)}
            finally:
                browser.close()

    # ── Internal flow ─────────────────────────────────────────────────────

    def _run(
        self,
        page: Page,
        ctx,
        channel: str,
        images: list[Path],
        text: str,
        now: bool,
    ) -> dict:
        # Navigate to Buffer publish interface
        page.goto(_BUFFER_PUBLISH, wait_until="domcontentloaded", timeout=_TIMEOUT)

        # Log in if redirected to auth
        if "login" in page.url.lower() or "auth" in page.url.lower():
            log.info("buffer.logging_in")
            self._login(page)
            _save_session(ctx)

        # Wait for publish interface
        try:
            page.wait_for_url("**/publish.buffer.com/**", timeout=_TIMEOUT)
        except PlaywrightTimeoutError:
            raise BufferError(
                f"Expected publish.buffer.com but landed on: {page.url}"
            )

        # Open the New Post composer
        self._open_composer(page)

        # Select the target TikTok channel
        self._select_channel(page, channel)

        # Upload carousel images
        self._upload_images(page, images)

        # Fill caption text
        self._fill_caption(page, text)

        # Submit
        if now:
            self._post_now(page)
        else:
            self._add_to_queue(page)

        return {"queued": True, "updates": 1, "slides": len(images)}

    def _login(self, page: Page) -> None:
        page.goto(_BUFFER_LOGIN, wait_until="domcontentloaded", timeout=_TIMEOUT)

        # Fill email
        email_sel = 'input[type="email"], input[name="email"], #email'
        page.wait_for_selector(email_sel, timeout=_TIMEOUT)
        page.fill(email_sel, self._email)
        time.sleep(0.3)

        # Some Buffer flows have a single page with both fields; others step through
        pw_sel = 'input[type="password"], input[name="password"]'
        if page.locator(pw_sel).count() == 0:
            # Click Continue/Next to reach the password step
            page.click(
                'button[type="submit"], button:has-text("Continue"), '
                'button:has-text("Next"), button:has-text("Log in")'
            )
            try:
                page.wait_for_selector(pw_sel, timeout=8_000)
            except PlaywrightTimeoutError:
                raise BufferError(
                    "Could not find password field after email step. "
                    "Check BUFFER_EMAIL in your .env."
                )

        page.fill(pw_sel, self._password)
        time.sleep(0.3)

        # Submit
        page.click(
            'button[type="submit"], button:has-text("Log In"), '
            'button:has-text("Sign in"), button:has-text("Continue")'
        )

        # Wait for redirect away from login — or detect 2FA
        try:
            page.wait_for_url("**/publish.buffer.com/**", timeout=12_000)
        except PlaywrightTimeoutError:
            url = page.url.lower()
            if "two-factor" in url or "2fa" in url or "otp" in url or \
               page.locator('input[name="token"], input[name="code"], input[name="otp"]').count() > 0:
                raise BufferError(
                    "Buffer is asking for 2FA. "
                    "Disable it at buffer.com → Settings → Security, "
                    "or run 'python -m src.integrations.buffer_client' with a "
                    "visible browser to complete login once and cache the session."
                )
            raise BufferError(
                "Login failed or unexpected redirect. "
                f"Current page: {page.url}\n"
                "Check BUFFER_EMAIL and BUFFER_PASSWORD in your .env file."
            )

        log.info("buffer.login_ok")

    def _open_composer(self, page: Page) -> None:
        """Click the New Post / Create button to open the post composer."""
        selectors = [
            'button:has-text("New Post")',
            'button:has-text("Create Post")',
            'button:has-text("Create")',
            'a:has-text("New Post")',
            '[data-testid*="compose"], [data-testid*="new-post"]',
            '[aria-label*="new post" i], [aria-label*="create post" i]',
        ]
        for sel in selectors:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                time.sleep(1.2)
                return

        raise BufferError(
            "Could not find 'New Post' button in Buffer. "
            "Buffer's UI may have changed — check the debug screenshot."
        )

    def _select_channel(self, page: Page, channel: str) -> None:
        """
        Select the channel matching `channel` in the composer.
        Matches case-insensitively against the text of each channel card.
        Falls back to the only channel if exactly one exists.
        """
        handle = channel.lstrip("@").lower()

        # Wait for the channel picker to render
        try:
            page.wait_for_selector(
                '[class*="channel" i], [data-testid*="channel"], label, button',
                timeout=_TIMEOUT,
            )
        except PlaywrightTimeoutError:
            pass

        time.sleep(0.8)

        # Try to find and click by text match — Buffer renders channels as
        # clickable elements (buttons or labels) containing the handle text
        clicked = page.locator(f'*:has-text("@{handle}")').first
        if clicked.count() > 0 and clicked.is_visible():
            clicked.click()
            time.sleep(0.5)
            log.info("buffer.channel_selected", channel=channel)
            return

        # Broader search: any clickable element containing the bare handle
        clicked = page.locator(f'button:has-text("{handle}"), label:has-text("{handle}")').first
        if clicked.count() > 0 and clicked.is_visible():
            clicked.click()
            time.sleep(0.5)
            log.info("buffer.channel_selected_fallback", channel=channel)
            return

        # If there's only one channel available, select it regardless of name
        channel_btns = page.locator(
            '[class*="ChannelSelector"] button, '
            '[class*="channel-selector"] button, '
            '[data-testid*="channel"] button'
        )
        if channel_btns.count() == 1:
            channel_btns.first.click()
            time.sleep(0.5)
            log.warning("buffer.channel_auto_selected_only_one", channel=channel)
            return

        # Give up with actionable error
        visible_text = _list_visible_channels(page)
        raise BufferError(
            f"Channel '{channel}' not found in Buffer's channel selector. "
            f"Channels visible: {visible_text}. "
            f"Update 'Buffer TikTok Profile ID' on the account in /accounts "
            f"to match exactly what Buffer shows (including the @ sign)."
        )

    def _upload_images(self, page: Page, images: list[Path]) -> None:
        """Upload carousel slides to the Buffer composer."""
        file_paths = [str(p.resolve()) for p in images]

        # If there's no file input visible, click a media button to reveal it
        file_input = page.locator('input[type="file"]').first
        if file_input.count() == 0 or not file_input.is_visible():
            media_sels = [
                'button:has-text("Photo")', 'button:has-text("Media")',
                'button:has-text("Image")', '[aria-label*="photo" i]',
                '[aria-label*="media" i]', '[data-testid*="media"]',
                '[data-testid*="photo"]', '[class*="MediaButton"]',
            ]
            for sel in media_sels:
                btn = page.locator(sel).first
                if btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break

        file_input = page.locator('input[type="file"]').first
        file_input.set_input_files(file_paths)
        log.info("buffer.images_uploading", count=len(file_paths))

        # Wait for upload spinners/progress to finish
        try:
            page.wait_for_selector(
                '[class*="uploading" i], [aria-label*="uploading" i]',
                state="detached",
                timeout=_UPLOAD_TIMEOUT,
            )
        except PlaywrightTimeoutError:
            pass  # Spinner may not appear for fast uploads

        time.sleep(2)
        log.info("buffer.images_uploaded")

    def _fill_caption(self, page: Page, text: str) -> None:
        """Type caption into the Buffer text area."""
        selectors = [
            '[contenteditable="true"]',
            'div[role="textbox"]',
            'textarea[placeholder*="caption" i]',
            'textarea[placeholder*="write" i]',
            '[data-testid*="caption"]',
            'textarea',
        ]
        for sel in selectors:
            ta = page.locator(sel).first
            if ta.is_visible():
                ta.click()
                tag = ta.evaluate("el => el.tagName")
                if tag == "TEXTAREA":
                    ta.fill(text)
                else:
                    # contenteditable — type char by char to trigger React handlers
                    ta.type(text, delay=8)
                log.info("buffer.caption_filled", length=len(text))
                return

        log.warning("buffer.caption_field_not_found", preview=text[:60])

    def _add_to_queue(self, page: Page) -> None:
        selectors = [
            'button:has-text("Add to Queue")',
            'button:has-text("Add to queue")',
            'button:has-text("Queue")',
            '[data-testid*="queue"]',
            '[aria-label*="queue" i]',
        ]
        for sel in selectors:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                time.sleep(2)
                log.info("buffer.added_to_queue")
                return
        raise BufferError(
            "Could not find 'Add to Queue' button. "
            "Buffer's UI may have changed — check output/debug_buffer_error_*.png."
        )

    def _post_now(self, page: Page) -> None:
        selectors = [
            'button:has-text("Share Now")',
            'button:has-text("Post Now")',
            'button:has-text("Publish Now")',
            '[data-testid*="share-now"]',
        ]
        for sel in selectors:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                time.sleep(2)
                log.info("buffer.posted_now")
                return
        raise BufferError("Could not find 'Share Now' / 'Post Now' button.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_caption(caption: str, hashtags: Optional[list[str]]) -> str:
    text = caption.strip()
    if hashtags:
        tag_line = " ".join(f"#{h.lstrip('#')}" for h in hashtags if h.strip())
        if tag_line:
            text = f"{text}\n\n{tag_line}"
    return text


def _save_session(ctx) -> None:
    try:
        _SESSION_FILE.write_text(json.dumps(ctx.cookies()))
        log.debug("buffer.session_saved")
    except Exception as exc:
        log.warning("buffer.session_save_failed", error=str(exc))


def _save_debug_screenshot(page: Page, label: str) -> None:
    try:
        out = Path("output") / f"debug_{label}_{int(time.time())}.png"
        out.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(out))
        log.info("buffer.debug_screenshot_saved", path=str(out))
    except Exception:
        pass


def _list_visible_channels(page: Page) -> list[str]:
    """Return text of channel elements visible on the current page."""
    try:
        els = page.locator(
            '[class*="channel" i] span, [data-testid*="channel"] span'
        ).all_inner_texts()
        return [t.strip() for t in els if t.strip()][:10]
    except Exception:
        return []


# ── CLI — test login & list channels ─────────────────────────────────────────

if __name__ == "__main__":
    import os, sys  # noqa: E401

    email = os.getenv("BUFFER_EMAIL", "").strip()
    password = os.getenv("BUFFER_PASSWORD", "").strip()
    if not email or not password:
        print(
            "\n❌  BUFFER_EMAIL and BUFFER_PASSWORD not set.\n"
            "   Add to your .env:\n"
            "     BUFFER_EMAIL=your@email.com\n"
            "     BUFFER_PASSWORD=yourpassword\n"
        )
        sys.exit(1)

    print(f"\nOpening Buffer in a visible browser for {email}…")
    print("(headless=False so you can see what's happening)\n")

    uploader = BufferClient(email, password, headless=False)
    result = uploader.test_login()

    if result["ok"]:
        print("✅  Login OK — session cached in .buffer_session.json")
        channels = result.get("channels", [])
        if channels:
            print("\nChannels visible in Buffer:")
            for ch in channels:
                print(f"  • {ch}")
            print(
                "\nSet 'Buffer TikTok Profile ID' on each account in /accounts\n"
                "to the TikTok handle exactly as shown above (e.g. @robloxgems)."
            )
        else:
            print("\nNo channel names detected — check the browser window.")
    else:
        print(f"❌  {result['error']}")
        sys.exit(1)
