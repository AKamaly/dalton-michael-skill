#!/usr/bin/env bash
# Install the Dalton + Michael skill for Claude Code.
#
#   curl -fsSL https://raw.githubusercontent.com/AKamaly/dalton-michael-skill/main/install.sh | bash
#
# Safe to run again: it updates an existing install and resumes the index.
set -euo pipefail

REPO="${DM_REPO:-https://github.com/AKamaly/dalton-michael-skill}"
DEST="${DM_DIR:-$HOME/.claude/skills/dalton-michael}"
PORT="${DM_PORT:-8765}"

say()  { printf '\033[38;5;208m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Python 3.9+ with SQLite full-text search (stdlib only, nothing else to install)
command -v python3 >/dev/null || fail "Python 3.9+ is required: https://www.python.org/downloads/"
python3 - <<'PY' || fail "Your python3 needs to be 3.9+ with SQLite FTS5 (Homebrew's python3 has both)."
import sys, sqlite3
assert sys.version_info >= (3, 9)
sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")
PY
command -v git >/dev/null || fail "git is required."

# 2. The skill itself, where Claude Code looks for personal skills
if [ -d "$DEST/.git" ]; then
  say "Updating $DEST"
  git -C "$DEST" pull --ff-only --quiet
elif [ -e "$DEST" ]; then
  fail "$DEST exists but isn't a git checkout. Move it aside and run this again."
else
  say "Installing to $DEST"
  mkdir -p "$(dirname "$DEST")"
  git clone --quiet --depth 1 "$REPO" "$DEST"
fi

# 3. yt-dlp, which fetches the captions (text only, never video). YouTube breaks old versions
#    within months, and pip on an old Python can only install an old one, so: a recent copy
#    already on PATH, else Homebrew, else yt-dlp's official standalone binary inside the skill.
fresh() {  # yt-dlp versions are dates; "fresh" means under 120 days old
  "$@" --version 2>/dev/null | python3 -c 'import sys, datetime
v = sys.stdin.read().strip().split(".")
try: age = (datetime.date.today() - datetime.date(int(v[0]), int(v[1]), int(v[2]))).days
except Exception: sys.exit(1)
sys.exit(0 if age < 120 else 1)'
}
if command -v yt-dlp >/dev/null && fresh yt-dlp; then
  say "yt-dlp $(yt-dlp --version) found"
elif command -v brew >/dev/null; then
  say "Installing the latest yt-dlp with Homebrew"
  brew install --quiet yt-dlp 2>/dev/null || true
  brew upgrade --quiet yt-dlp 2>/dev/null || true
else
  case "$(uname -s)/$(uname -m)" in
    Darwin/*)        ASSET=yt-dlp_macos ;;
    Linux/x86_64)    ASSET=yt-dlp_linux ;;
    Linux/aarch64)   ASSET=yt-dlp_linux_aarch64 ;;
    *) fail "Install yt-dlp yourself (https://github.com/yt-dlp/yt-dlp#installation), then run this again." ;;
  esac
  say "Downloading yt-dlp's standalone binary into the skill"
  mkdir -p "$DEST/bin"
  curl -fsSL -o "$DEST/bin/yt-dlp" "https://github.com/yt-dlp/yt-dlp/releases/latest/download/$ASSET" \
    || fail "Couldn't download yt-dlp. Install it yourself (https://github.com/yt-dlp/yt-dlp#installation), then run this again."
  chmod +x "$DEST/bin/yt-dlp"
fi

# 4. The transcript index, built in the background
LOG="$DEST/data/ingest.log"
if python3 - "$DEST/data/ingest.lock" <<'PY'
import os, sys
try:
    os.kill(int(open(sys.argv[1]).read().strip()), 0)
except Exception:
    sys.exit(1)
PY
then
  say "The index is already building (log: $LOG)"
else
  say "Building the transcript index in the background: searchable in about 5 minutes, complete in about 30"
  DM_PORT="$PORT" nohup python3 "$DEST/scripts/dm.py" ingest ${DM_INGEST_LIMIT:+--limit "$DM_INGEST_LIMIT"} > "$LOG" 2>&1 &
fi

# 5. Something to watch right now: the sample answers that ship with the repo
URL="$(DM_PORT="$PORT" python3 "$DEST/scripts/dm.py" serve)?reel=should-i-pivot-my-startup"
if [ -z "${DM_NO_OPEN:-}" ]; then
  if command -v open >/dev/null; then open "$URL"; elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1 || true; fi
fi

cat <<EOF

  Done. A sample answer is opening in your browser: $URL

  In Claude Code (restart it if it was already open), ask:

      /dalton-michael Should I pivot my startup?

  Index progress:  tail -f $LOG
  Check setup:     python3 $DEST/scripts/dm.py doctor

EOF
