#!/usr/bin/env bash
# ============================================================
#  💎 RoboxPipeline — One-Command Setup
#  Just run:  bash quickstart.sh
#  It does everything for you.
# ============================================================

set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
say()  { echo -e "${BLUE}▶${NC}  $1"; }
ok()   { echo -e "${GREEN}✓${NC}  $1"; }
warn() { echo -e "${YELLOW}!${NC}  $1"; }
die()  { echo -e "${RED}✗  $1${NC}"; exit 1; }

echo ""
echo "============================================"
echo "   💎  RoboxPipeline — Easy Setup"
echo "============================================"
echo ""
echo "This will set everything up for you."
echo "It may take a few minutes. That's normal."
echo ""

# ── Step 0: Pull latest code ────────────────────────────────
say "Step 0 of 7: Getting the latest updates..."
# The database file is local-only; stop git tracking it so it never blocks pulls
git rm --cached tiktok_robox.db 2>/dev/null || true
git checkout -- tiktok_robox.db 2>/dev/null || true
if git pull origin claude/handoff-continuation-ab99x3 2>&1; then
  ok "Code is up to date."
else
  warn "Could not pull updates (no internet or not a git repo). Continuing anyway."
fi

# ── Step 1: Find Python ─────────────────────────────────────
say "Step 1 of 7: Looking for Python on your computer..."
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo ""
  die "Python is not installed yet.
   1. Go to this website:  https://www.python.org/downloads/
   2. Click the big yellow 'Download' button and install it.
   3. IMPORTANT (Windows): tick the box that says 'Add Python to PATH'.
   4. Then run this setup again."
fi
ok "Found Python."

# Best-effort: install fonts so burned-in text + emoji render crisply.
# (Liberation = clean Latin text, Noto Color Emoji = ⭐💎 instead of boxes.)
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get install -y -q fonts-liberation fonts-noto-color-emoji >/dev/null 2>&1 \
    && ok "Fonts ready (crisp text + emoji)." \
    || warn "Could not auto-install fonts — text still works, emoji may show as boxes."
fi

# ── Step 2: Check for ffmpeg (video maker) ──────────────────
say "Step 2 of 7: Checking the video tool (ffmpeg)..."
if command -v ffmpeg >/dev/null 2>&1; then
  ok "Video tool is ready."
else
  warn "The video tool 'ffmpeg' isn't installed."
  warn "Pictures (thumbnails) will still work, but videos won't render yet."
  warn "  • On a Mac, install it later by running:   brew install ffmpeg"
  warn "  • On Ubuntu/Linux, run:                    sudo apt install ffmpeg"
  echo ""
  read -r -p "   Press the Enter key to keep going... " _ || true
fi

# ── Step 3: Make a clean private workspace ──────────────────
say "Step 3 of 7: Creating a clean workspace..."
$PY -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate
ok "Workspace ready."

# ── Step 4: Install the helper programs ─────────────────────
say "Step 4 of 7: Installing the parts (grab a coffee, a few minutes)..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "All parts installed."

# ── Step 5: Set up your secret key ──────────────────────────
say "Step 5 of 7: Setting up your AI key..."
if [ ! -f .env ]; then
  cp .env.example .env
fi

if grep -qE '^ANTHROPIC_API_KEY=sk-ant-[A-Za-z0-9]' .env; then
  ok "AI key already saved. Skipping."
else
  echo ""
  echo "   ----------------------------------------------------"
  echo "   I need your Anthropic AI key to write game ratings."
  echo "   Get one here (it gives you free starter credit):"
  echo "        https://console.anthropic.com"
  echo "   The key starts with:  sk-ant-"
  echo "   ----------------------------------------------------"
  echo ""
  read -r -p "   Paste your key here, then press Enter: " USER_KEY
  if [ -z "$USER_KEY" ]; then
    warn "No key entered. You can add it later by editing the .env file."
  else
    ANTHROPIC_KEY_INPUT="$USER_KEY" $PY - <<'PYEOF'
import os, re, pathlib
key = os.environ["ANTHROPIC_KEY_INPUT"].strip()
p = pathlib.Path(".env")
t = p.read_text()
if re.search(r'(?m)^ANTHROPIC_API_KEY=', t):
    t = re.sub(r'(?m)^ANTHROPIC_API_KEY=.*$', f'ANTHROPIC_API_KEY={key}', t)
else:
    t += f'\nANTHROPIC_API_KEY={key}\n'
p.write_text(t)
PYEOF
    ok "Key saved."
  fi
fi

# ── Step 6: Build the robot's memory + app icon ─────────────
say "Step 6 of 7: Building the database and app icon..."
$PY scripts/init_db.py
$PY scripts/generate_app_icon.py 2>/dev/null && ok "App icon ready (assets/app_icon_1024.png)." || warn "Icon generation skipped."
ok "Memory ready."

# ── Step 7: Optional first batch ────────────────────────────
echo ""
read -r -p "   Find games and make your first videos now? [Y/n] " DO_FIRST || true
if [[ ! "$DO_FIRST" =~ ^[Nn] ]]; then
  say "Hunting for trending Roblox games..."
  $PY main.py discover || warn "Game hunt hit a snag — you can retry from the website later."
  say "Making content for the top 5 games (a few minutes)..."
  $PY main.py generate 5 || warn "Content step hit a snag — you can retry from the website later."
  ok "First batch done!"
fi

# ── Launch ──────────────────────────────────────────────────
echo ""
echo "============================================"
ok "ALL DONE! Starting your control panel..."
echo "============================================"
echo ""
echo "   👉  Open your web browser (Chrome, Safari, etc.)"
echo "   👉  Go to this address:   http://localhost:8000"
echo ""
echo "   To STOP it later: hold the Control key and press C."
echo "   To START it again next time: run  bash quickstart.sh"
echo ""
echo "   ── TikTok Auto-Posting ─────────────────────────────"
echo "   To enable automatic TikTok posting, add these to .env:"
echo "     TIKTOK_ACCESS_TOKEN=your_token"
echo "     TIKTOK_OPEN_ID=your_open_id"
echo "   Get credentials: https://developers.tiktok.com/doc/content-posting-api-get-started"
echo "   After adding, restart this script. The pipeline will post"
echo "   approved carousels automatically every 30 minutes."
echo "   ────────────────────────────────────────────────────"
echo ""
$PY main.py serve
