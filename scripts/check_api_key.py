#!/usr/bin/env python3
"""
Onboarding credential check — run by quickstart.sh right after the key is saved.

Validates the Anthropic API key and prints a clear, human result so a new user
learns immediately if their key is missing/invalid/expired/rate-limited, instead
of discovering it only as mysteriously "weak" AI output later.

Exit code is always 0 (a bad key should not abort setup — the app still runs in
fallback mode), but the message makes the state unmistakable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
NC = "\033[0m"


def main() -> int:
    try:
        from src.content.ai_status import check_api_key
    except Exception as exc:  # import problems shouldn't break onboarding
        print(f"{YELLOW}!  Could not run the AI key check ({exc}). "
              f"You can verify it later in the dashboard.{NC}")
        return 0

    status = check_api_key()
    if status.ok:
        print(f"{GREEN}✓  {status.title}{NC}")
    else:
        color = YELLOW if status.state in ("rate_limited", "unreachable") else RED
        print(f"{color}!  {status.title}{NC}")
        print(f"   {status.message}")
        print(f"   (The app will still run, but in FALLBACK mode until this is fixed.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
