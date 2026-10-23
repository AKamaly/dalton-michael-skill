#!/usr/bin/env python3
"""Dalton + Michael advisor: transcript index, search, and reel builder.

Commands:
  doctor              check the setup and print the fix for anything missing
  samples             list the sample reels that work before the index exists
  ingest [--limit N]  fetch episode lists + word-timed captions (skips what exists)
  index               (re)build the sqlite search index from captions
  find Q1 [Q2 ...] [-n N]  several queries at once, hits as timestamped sentences
  search QUERY [-n N] ranked transcript passages for a question
  show VIDEO START END  timestamped sentences in a window, for picking cut points
  reactions           cold-open / laugh / "great question" bank
  reel SPEC.json      build a playable reel, print its URL (use - for stdin)
  silly QUESTION      five-second "No." reel for a joke question
  serve               make sure the local player server is up, print its URL
  stats               corpus summary
"""
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CAPS = DATA / "captions"
META = DATA / "videos.json"
DB = DATA / "index.sqlite"
PLAYER = ROOT / "player"
REELS = PLAYER / "reels"
SAMPLES = PLAYER / "samples"
LOCK = DATA / "ingest.lock"
PORT = int(os.environ.get("DM_PORT", "8765"))
# set to chrome/firefox/safari/... when YouTube asks yt-dlp to "confirm you're not a bot"
COOKIES = os.environ.get("DM_COOKIES_FROM_BROWSER", "")
YTDLP = []   # resolved by ytdlp() when ingest starts

SOURCES = [
    # Their own channel (2025+, after YC; Standard Capital era)
    ("Dalton + Michael", "https://www.youtube.com/channel/UCllx7jOjBL794FK67jtb5Og/videos"),
    # The original YC series
    ("Y Combinator", "https://www.youtube.com/playlist?list=PLQ-uHSnFig5Nd98Sc9I-kkc0ZWe8peRMC"),
]

# Solo YC talks: one speaker, so clips can be attributed by name
TALKS = [
    ("8pNxKX1SUGE", "Dalton"), ("8yiOcCPvyNE", "Dalton"), ("Cmzwq7hg17M", "Dalton"),
    ("N8deM6B4eE4", "Dalton"), ("NmEyx9TEkRw", "Dalton"), ("PJge-MV3Z5w", "Dalton"),
    ("RxjZbmr1d1w", "Dalton"), ("uCRBLKGaHtY", "Dalton"), ("msWFarwD-fU", "Dalton + Eric Migicovsky"),
    ("1hHMwLxN6EM", "Michael"), ("5fmDKGV0TnQ", "Michael"), ("9NhEBVPlJs4", "Michael"),
    ("C27RVio2rOs", "Michael"), ("D56QeyyQMLI", "Michael"), ("d7tDaFr5EYA", "Michael"),
    ("kJIBAp48Pv8", "Michael"), ("qh8sHetf-Nk", "Michael"), ("vDXkpJw16os", "Michael"),
    ("Z_ZzQmmSN5Y", "Michael + Eric Migicovsky"),
]

STOP = set("""a an the and or but if of to in on at for with from by as is are was were be been being
do does did doing have has had i you he she it we they me my your our their this that these those
what which who whom how why when where should would could can will just so not no yes about into
than then there here very really get got im i'm ive i've dont don't its it's startup startups""".split())


# ---------- helpers ----------

def ts(sec):
    sec = max(0.0, float(sec))
    m, s = divmod(sec, 60)
    return "%d:%04.1f" % (m, s)


def parse_time(v):
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    if ":" in v:
        parts = [float(p) for p in v.split(":")]
        sec = 0.0
        for p in parts:
            sec = sec * 60 + p
        return sec
    return float(v)


def load_meta():
    if META.exists():
        return json.loads(META.read_text())
    return {}


def save_meta(meta):
    META.write_text(json.dumps(meta, indent=1, ensure_ascii=False))


def open_db():
    if not DB.exists():
        sys.exit("No transcript index yet. Build it once (takes ~30 min, YouTube rate-limits captions):\n"
                 "  python3 %s ingest" % Path(__file__).resolve())
    return sqlite3.connect(DB)


def caption_file(vid):
    for lang in ("en-orig", "en", "en-US"):
        p = CAPS / ("%s.%s.json3" % (vid, lang))
        if p.exists():
            return p
    return None


def load_words(vid):
    """[(t_seconds, word)] from a json3 caption file; [laughter]-style tags kept as markers."""
    p = caption_file(vid)
    if not p:
        return []
    d = json.loads(p.read_text())
    words = []
    for e in d.get("events", []):
        base = e.get("tStartMs", 0)
        segs = [s for s in (e.get("segs") or []) if (s.get("utf8") or "").strip()]
        # manual captions put a whole line in one seg: spread it over the event.
        # ASR captions are word-timed; a seg like ">> This" is a speaker turn plus one word.
        spread = len(segs) == 1 and "tOffsetMs" not in segs[0] and len(segs[0]["utf8"].split()) > 2
        for s in segs:
            t = (base + s.get("tOffsetMs", 0)) / 1000.0
            parts = s["utf8"].split()
            dur = e.get("dDurationMs", 2000) / 1000.0
            for i, part in enumerate(parts):
                words.append((t + (dur * i / len(parts) if spread else 0.001 * i), part))
    words.sort(key=lambda x: x[0])
    return words


def sentences(words):
    """Group words into sentences on terminal punctuation, falling back to long pauses."""
    out, cur = [], []
    for i, (t, w) in enumerate(words):
        cur.append((t, w))
        nw = words[i + 1] if i + 1 < len(words) else (t + 0.6, "")
        terminal = re.search(r"[.?!]\"?$", w) is not None
        pause = nw[0] - t > 1.2
        turn = nw[1] == ">>"
        if terminal or pause or turn or len(cur) > 60:
            out.append((cur[0][0], nw[0], " ".join(x[1] for x in cur)))
            cur = []
    if cur:
        out.append((cur[0][0], cur[-1][0] + 0.6, " ".join(x[1] for x in cur)))
    return out


def clean(text):
    """Speaker turns (>>) become », [music]/[applause] go."""
    text = re.sub(r"\s*\[(music|applause)\]\s*", " ", text, flags=re.I)
    text = re.sub(r"(^|\s)>>\s*", r"\1» ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------- ingest ----------

def find_ytdlp():
    """(command, version) for the first working yt-dlp: the installer's standalone copy, PATH, pip module."""
    local = ROOT / "bin" / "yt-dlp"
    candidates = ([[str(local)]] if local.exists() else []) + \
                 ([["yt-dlp"]] if shutil.which("yt-dlp") else []) + [[sys.executable, "-m", "yt_dlp"]]
    for cmd in candidates:
        r = subprocess.run(cmd + ["--version"], capture_output=True, text=True)
        if r.returncode == 0:
            return cmd, r.stdout.strip()
    return None, None


def ytdlp_age(version):
    """Days since this yt-dlp release (versions are dates); YouTube breaks old ones within months."""
    try:
        y, m, d = (int(x) for x in version.split(".")[:3])
        return (time.time() - time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))) // 86400
    except (ValueError, AttributeError):
        return 0


UPDATE_YTDLP = ("Update it: brew upgrade yt-dlp, or run the installer again:\n"
                "curl -fsSL https://raw.githubusercontent.com/AKamaly/dalton-michael-skill/main/install.sh | bash")


def ytdlp():
    cmd, version = find_ytdlp()
    if not cmd:
        sys.exit("yt-dlp isn't installed. Run the installer, which sets it up:\n"
                 "  curl -fsSL https://raw.githubusercontent.com/AKamaly/dalton-michael-skill/main/install.sh | bash")
    if ytdlp_age(version) > 120:
        print("Warning: yt-dlp %s is %d days old and YouTube may refuse it. %s"
              % (version, ytdlp_age(version), UPDATE_YTDLP), flush=True)
    return cmd + (["--cookies-from-browser", COOKIES] if COOKIES else [])


def ingest_running():
    """Another ingest holds the lock if its pid is still alive."""
    try:
        os.kill(int(LOCK.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def list_source(url):
    r = subprocess.run(
        YTDLP + ["--flat-playlist", "--print", "%(id)s|%(title)s|%(duration)s", url],
        capture_output=True, text=True)
    rows = []
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 3 and parts[1] != "NA":
            rows.append((parts[0], "|".join(parts[1:-1]), parts[-1]))
    return rows


def cmd_ingest(args):
    """ingest [--limit N]: fetch what's missing; the index refreshes as it goes, so search works early."""
    global YTDLP
    YTDLP = ytdlp()
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    CAPS.mkdir(parents=True, exist_ok=True)
    if ingest_running():
        sys.exit("An ingest is already running (pid %s). Progress: %s" % (LOCK.read_text().strip(), DATA / "ingest.log"))
    LOCK.write_text(str(os.getpid()))
    try:
        _ingest(limit)
    finally:
        LOCK.unlink(missing_ok=True)


def _ingest(limit):
    meta = load_meta()
    for source, url in SOURCES:
        rows = list_source(url)
        print("%s: %d videos" % (source, len(rows)))
        for vid, title, dur in rows:
            m = meta.setdefault(vid, {})
            m.update({"id": vid, "title": title, "source": source})
            if dur not in ("NA", ""):
                m["duration"] = float(dur)
    for vid, speaker in TALKS:
        meta.setdefault(vid, {}).update({"id": vid, "source": "YC talk", "speaker": speaker})
    save_meta(meta)

    todo = [v for v in meta if not caption_file(v)][:limit]
    print("captions to fetch: %d (about %d min; YouTube rate-limits caption downloads)"
          % (len(todo), round(len(todo) * 9 / 60)), flush=True)
    misses = 0
    for i, vid in enumerate(todo):
        for attempt in range(4):
            r = subprocess.run(
                YTDLP + ["--skip-download", "--write-auto-subs", "--sub-langs", "en-orig",
                 "--sub-format", "json3", "-o", str(CAPS / "%(id)s.%(ext)s"),
                 "--print", "%(upload_date)s|%(channel)s|%(duration)s|%(title)s", "--no-simulate",
                 "https://www.youtube.com/watch?v=" + vid],
                capture_output=True, text=True)
            line = (r.stdout.strip().splitlines() or [""])[-1]
            if line.count("|") >= 3:
                up, chan, dur, title = line.split("|", 3)
                meta[vid].update({"upload_date": up, "channel": chan})
                meta[vid].setdefault("title", title)
                if dur not in ("NA", ""):
                    meta[vid]["duration"] = float(dur)
            if caption_file(vid):
                break
            if "429" in r.stderr:
                wait = 30 * (attempt + 1)
                print("  429, backing off %ds" % wait)
                time.sleep(wait)
                continue
            # no en-orig auto track (older uploads): try the uploaded English subs
            subprocess.run(
                YTDLP + ["--skip-download", "--write-subs", "--sub-langs", "en.*",
                 "--sub-format", "json3", "-o", str(CAPS / "%(id)s.%(ext)s"),
                 "https://www.youtube.com/watch?v=" + vid],
                capture_output=True, text=True)
            break
        ok = "ok" if caption_file(vid) else "MISSING"
        print("[%d/%d] %s %s  %s" % (i + 1, len(todo), vid, ok, meta[vid].get("title", "")), flush=True)
        save_meta(meta)
        # three misses in a row means yt-dlp itself is failing: stop and say why, don't grind on
        misses = 0 if caption_file(vid) else misses + 1
        if misses >= 3:
            err = ([l for l in r.stderr.splitlines() if "ERROR" in l] or ["(no error message)"])[-1]
            sys.exit("Stopped: yt-dlp is failing on every video.\n  %s\nFixes:\n"
                     "  - %s\n  - If YouTube asks you to sign in: export DM_COOKIES_FROM_BROWSER=chrome\n"
                     "Then run ingest again; it resumes where it stopped." % (err, UPDATE_YTDLP.replace("\n", "\n    ")))
        if (i + 1) % 12 == 0:
            cmd_index([])        # searchable early; the full set lands at the end
        time.sleep(4)
    # upload dates for anything captioned outside this loop
    for vid in [v for v in meta if caption_file(v) and not meta[v].get("upload_date")]:
        r = subprocess.run(YTDLP + ["--skip-download", "--print", "%(upload_date)s|%(channel)s",
                                    "https://www.youtube.com/watch?v=" + vid], capture_output=True, text=True)
        line = (r.stdout.strip().splitlines() or [""])[-1]
        if "|" in line:
            meta[vid]["upload_date"], meta[vid]["channel"] = line.split("|")
        save_meta(meta)
    cmd_index([])
    missing = [m.get("title", v) for v, m in meta.items() if not caption_file(v)]
    if missing:
        print("%d videos still have no captions; run ingest again later to retry them." % len(missing))


# ---------- index ----------

def cmd_index(args):
    meta = load_meta()
    # build beside the live index and swap it in, so searches during an ingest never see it half-built
    tmp = DB.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
      create table sent(video text, i int, start real, end real, text text);
      create virtual table seg using fts5(title, text, video unindexed, start unindexed,
                                          end unindexed, tokenize='porter unicode61');
    """)
    nvid = nseg = 0
    for vid, m in meta.items():
        words = load_words(vid)
        if not words:
            continue
        nvid += 1
        sents = sentences(words)
        con.executemany("insert into sent values(?,?,?,?,?)",
                        [(vid, i, s, e, clean(t)) for i, (s, e, t) in enumerate(sents)])
        # overlapping ~60s windows so a hit carries its context
        i = 0
        while i < len(sents):
            j, start = i, sents[i][0]
            while j < len(sents) and sents[j][1] - start < 60:
                j += 1
            j = max(j, i + 1)
            # a short tail window would outrank real passages on BM25 length; the previous window covers it
            if i > 0 and j == len(sents) and sents[j - 1][1] - start < 30:
                break
            text = clean(" ".join(s[2] for s in sents[i:j]))
            con.execute("insert into seg values(?,?,?,?,?)",
                        (m.get("title", ""), text, vid, start, sents[j - 1][1]))
            nseg += 1
            step = max(1, (j - i) // 2)
            i += step
    con.commit()
    con.close()
    os.replace(tmp, DB)
    print("indexed %d videos, %d passages" % (nvid, nseg), flush=True)


# ---------- search / show ----------

def fts_query(q):
    terms = [t for t in re.findall(r"[a-z0-9']+", q.lower()) if t not in STOP and len(t) > 1]
    terms = [t.replace("'", "") for t in terms]
    return " OR ".join('"%s"*' % t for t in terms) if terms else '""'


def year(m):
    d = m.get("upload_date") or ""
    return d[:4] if d else "?"


def cmd_search(args):
    n = 12
    if "-n" in args:
        k = args.index("-n")
        n = int(args[k + 1])
        args = args[:k] + args[k + 2:]
    q = " ".join(args)
    meta = load_meta()
    con = open_db()
    rows = con.execute(
        "select video, start, end, text, bm25(seg, 3.0, 1.0) as r from seg where seg match ? "
        "order by r limit ?", (fts_query(q), n * 4)).fetchall()
    shown, seen = 0, []
    for vid, s, e, text, r in rows:
        # drop windows that overlap one already shown
        if any(v == vid and s < e2 and e > s2 for v, s2, e2 in seen):
            continue
        seen.append((vid, s, e))
        m = meta.get(vid, {})
        src = m.get("source", "") + (" by " + m["speaker"] if m.get("speaker") else "")
        print("#%d  %s  [%s - %s]  %s (%s, %s)" % (
            shown + 1, vid, ts(s), ts(e), m.get("title", ""), year(m), src))
        print("    " + text[:420] + ("..." if len(text) > 420 else ""))
        shown += 1
        if shown >= n:
            break
    if not shown:
        print("no hits; try other words")


INTRO_RE = re.compile(r"(dalton|d[oa]lton|alon|doon)\W+(plus|p|puss|post|and)?\W*michael|today,? we'?re (going to|gonna) talk", re.I)


def cmd_find(args):
    """Several queries in one call; each hit comes back as timestamped sentences, ready to cut."""
    n = 8
    if "-n" in args:
        k = args.index("-n")
        n = int(args[k + 1])
        args = args[:k] + args[k + 2:]
    meta = load_meta()
    con = open_db()
    best = {}
    for q in args:
        rows = con.execute("select video, start, end, bm25(seg, 3.0, 1.0) from seg where seg match ? "
                           "order by bm25(seg, 3.0, 1.0) limit 40", (fts_query(q),)).fetchall()
        for rank, (vid, s, e, r) in enumerate(rows):
            key = (vid, round(s))
            score = best.get(key, (0, 0, 0))[0] + 1.0 / (rank + 3)   # reciprocal rank fusion
            best[key] = (score, s, e)
    hits, seen = [], []
    for (vid, _), (score, s, e) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        if any(v == vid and s < e2 and e > s2 for v, s2, e2 in seen):
            continue
        if sum(1 for v, _, _ in hits if v == vid) >= 3:   # leave room for other episodes
            continue
        seen.append((vid, s, e))
        hits.append((vid, s, e))
        if len(hits) >= n:
            break
    for i, (vid, s, e) in enumerate(hits):
        m = meta.get(vid, {})
        src = m.get("source", "") + (" by " + m["speaker"] if m.get("speaker") else "")
        print("== #%d %s  %s (%s, %s)" % (i + 1, vid, m.get("title", ""), year(m), src))
        for a, b, t in con.execute("select start, end, text from sent where video=? and end>? and start<? "
                                   "order by start", (vid, s - 5, e + 8)):
            print("  %s-%s %s" % (ts(a), ts(b), t[:170]))
    print("\n== episode intros (smash-cut after the sting when the episode is about the question)")
    for vid in dict.fromkeys(v for v, _, _ in hits):
        for a, b, t in con.execute("select start, end, text from sent where video=? and start<75 "
                                   "order by start", (vid,)):
            if INTRO_RE.search(t):
                print("  %s %s-%s %s" % (vid, ts(a), ts(b), t[:140]))
                break


def cmd_show(args):
    vid, a, b = args[0], parse_time(args[1]), parse_time(args[2])
    con = open_db()
    m = load_meta().get(vid, {})
    print("%s  %s (%s)" % (vid, m.get("title", ""), year(m)))
    for s, e, t in con.execute(
            "select start, end, text from sent where video=? and end>? and start<? order by start",
            (vid, a - 10, b + 10)):
        mark = " " if a <= s < b else "~"
        print("%s [%s-%s] %s" % (mark, ts(s), ts(e), t))


REACTION_PATTERNS = [
    ("cold open", r"\b(this is dalton|hey,? this is|welcome to|today we'?re (going to|gonna) talk|i'?m michael seibel|i'?m dalton)"),
    ("great question", r"\b(great|good|fun|interesting) (question|topic|one)\b|love this (question|topic)"),
    ("laugh", r"\[laugh|\bha\b|\bhaha|\blol\b|that'?s (so )?funny|hilarious"),
    ("hot take", r"\b(hot take|controversial|unpopular opinion|i disagree|strongly disagree)"),
    ("sign off", r"\b(see you (next|guys)|thanks for watching|that'?s (it|all) for)"),
]


def cmd_reactions(args):
    bank = DATA / "reactions.json"
    if bank.exists() and "--scan" not in args:
        for r in json.loads(bank.read_text()):
            print("%-7s %s  start %.1f  end %.1f   \"%s\"\n        use for: %s" % (
                r["kind"], r["video"], r["start"], r["end"], r["text"], r["use"]))
        print("\nCurated bank. Times are exact seconds: pass them with \"exact\": true."
              "\nFor an episode's own intro, `show VIDEO 0:00 1:00`. --scan searches transcripts for more.")
        return
    con = open_db()
    meta = load_meta()
    kinds = [a for a in args if not a.startswith("--")]
    for kind, pat in REACTION_PATTERNS:
        if kinds and kind.split()[0] not in kinds:
            continue
        print("== %s" % kind)
        for vid, s, e, t in con.execute("select video, start, end, text from sent order by video, start"):
            if re.search(pat, t, re.I):
                print("  %s [%s-%s] %s | %s" % (vid, ts(s), ts(e), t[:150], meta.get(vid, {}).get("title", "")[:40]))


# ---------- reel ----------

def cmd_silly(args):
    """A joke question gets a joke answer: one "no" from the bank, then "End of video." """
    q = " ".join(args).strip() or "?"
    bank = json.loads((DATA / "reactions.json").read_text())
    nopes = [r for r in bank if r["kind"] == "nope"]
    closer = next(r for r in bank if r["kind"] == "closer")
    nope = nopes[sum(map(ord, q)) % len(nopes)]
    spec = {"question": q, "verdict": "No.", "cold_open": False,
            "slug": "silly-" + slugify(q)[:40],
            "clips": [{"kind": "intro", "video": r["video"], "start": r["start"], "end": r["end"],
                       "exact": True, "card": "none"} for r in (nope, closer)]}
    sys.stdin = __import__("io").StringIO(json.dumps(spec))
    cmd_reel(["-"])


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "reel"


def snap(sents, t, edge):
    """Snap a requested cut to the nearest sentence boundary within 2.5s."""
    best, bd = t, 2.5
    for s, e, _ in sents:
        cand = s if edge == "start" else e
        d = abs(cand - t)
        if d < bd:
            best, bd = cand, d
    return best


def cmd_reel(args):
    spec = json.loads(sys.stdin.read() if args[0] == "-" else Path(args[0]).read_text())
    meta = load_meta()
    specs = list(spec["clips"])
    # no cold open given: open on a "great question" sting, rotating by question
    # (an episode intro smash-cut doesn't count as a cold open; a bank opener with its own card does)
    if spec.get("cold_open", True) and not any(c.get("kind") == "intro" and c.get("card") != "none" for c in specs):
        stings = [r for r in json.loads((DATA / "reactions.json").read_text()) if r["kind"] == "sting"]
        s = stings[sum(map(ord, spec["question"])) % len(stings)]
        specs.insert(0, {"kind": "intro", "video": s["video"], "start": s["start"], "end": s["end"],
                         "exact": True, "beat": "Cold open"})
    clips = []
    for c in specs:
        vid = c["video"]
        m = meta.get(vid, {})
        words = load_words(vid)
        sents = sentences(words)
        a, b = parse_time(c["start"]), parse_time(c["end"])
        if not c.get("exact"):
            a, b = snap(sents, a, "start") - 0.15, snap(sents, b, "end") + 0.1
        a = max(0.0, a)
        cw, turn = [], False
        for t, w in words:
            if not (a - 0.05 <= t < b) or re.match(r"\[(music|applause)\]", w, re.I):
                continue
            if w == ">>":
                turn = True
                continue
            cw.append({"t": round(t - a, 2), "w": w, "turn": 1} if turn else {"t": round(t - a, 2), "w": w})
            turn = False
        clips.append({
            "video": vid, "start": round(a, 2), "end": round(b, 2),
            "beat": c.get("beat", ""), "kind": c.get("kind", "clip"), "note": c.get("note", ""),
            "card": c.get("card", "beat"),
            "title": m.get("title", ""), "year": year(m), "source": m.get("source", ""),
            "speaker": c.get("speaker") or m.get("speaker", ""),
            "url": "https://www.youtube.com/watch?v=%s&t=%ds" % (vid, int(a)),
            "words": cw,
        })
    slug = spec.get("slug") or slugify(spec["question"])
    reel = {
        "question": spec["question"], "slug": slug,
        "verdict": spec.get("verdict", ""), "notes": spec.get("notes", []),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "clips": clips,
        "duration": round(sum(c["end"] - c["start"] for c in clips), 1),
    }
    REELS.mkdir(parents=True, exist_ok=True)
    (REELS / (slug + ".json")).write_text(json.dumps(reel, ensure_ascii=False))
    idx_path = REELS / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else []
    idx = [r for r in idx if r["slug"] != slug]
    idx.insert(0, {"slug": slug, "question": reel["question"], "created": reel["created"],
                   "clips": len(clips), "duration": reel["duration"]})
    idx_path.write_text(json.dumps(idx[:100], ensure_ascii=False, indent=1))
    for c in clips:
        print("  %-10s %s [%s-%s] %4.0fs  %s" % (c["kind"], c["video"], ts(c["start"]), ts(c["end"]),
                                               c["end"] - c["start"], c["beat"]))
    print("total %ds" % reel["duration"])
    print(ensure_server() + "/?reel=" + slug + "&autoplay=1")


# ---------- serve ----------

def port_open():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_server():
    if not port_open():
        log = open(DATA / "server.log", "a")
        subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1",
                          "--directory", str(PLAYER)], stdout=log, stderr=log,
                         start_new_session=True)
        for _ in range(30):
            if port_open():
                break
            time.sleep(0.1)
    return "http://localhost:%d" % PORT


def cmd_serve(args):
    print(ensure_server() + "/")


def cmd_stats(args):
    meta = load_meta()
    con = open_db()
    nv = con.execute("select count(distinct video) from sent").fetchone()[0]
    ns = con.execute("select count(*) from sent").fetchone()[0]
    hours = sum(m.get("duration", 0) for v, m in meta.items() if caption_file(v)) / 3600
    by = {}
    for v, m in meta.items():
        if caption_file(v):
            by[m.get("source", "?")] = by.get(m.get("source", "?"), 0) + 1
    print("%d episodes indexed (%s), %.1f hours, %d sentences" % (
        nv, ", ".join("%s: %d" % kv for kv in by.items()), hours, ns))
    missing = [m.get("title", v) for v, m in meta.items() if not caption_file(v)]
    if missing:
        print("no captions: " + "; ".join(missing))


def cmd_samples(args):
    """Reels that ship with the repo, playable before the index exists."""
    for r in json.loads((SAMPLES / "index.json").read_text()):
        print("%-48s %s" % (r["slug"], r["question"]))
    print("\nPlay one: %s/?reel=<slug>&autoplay=1" % ensure_server())


def cmd_doctor(args):
    """Check everything the skill needs; print the fix for anything missing."""
    import urllib.request
    me = Path(__file__).resolve()
    problems = []

    def check(good, what, fix=""):
        print(("  ok   " if good else "  FIX  ") + what)
        if not good:
            problems.append(fix)
            print("       " + fix.replace("\n", "\n       "))

    print("Dalton + Michael: checking your setup\n")
    check(sys.version_info >= (3, 9), "Python %d.%d" % sys.version_info[:2], "Install Python 3.9 or newer.")
    try:
        sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")
        check(True, "SQLite full-text search (FTS5)")
    except sqlite3.Error:
        check(False, "SQLite full-text search (FTS5)", "Use a Python with FTS5, e.g. Homebrew's python3.")
    cmd, version = find_ytdlp()
    if not cmd:
        check(False, "yt-dlp", "Run the installer, which sets it up:\n"
              "curl -fsSL https://raw.githubusercontent.com/AKamaly/dalton-michael-skill/main/install.sh | bash")
    else:
        check(ytdlp_age(version) <= 120, "yt-dlp %s" % version,
              "It's %d days old and YouTube refuses old versions. %s" % (ytdlp_age(version), UPDATE_YTDLP))

    meta = load_meta()
    have = sum(1 for v in meta if caption_file(v))
    if ingest_running():
        check(True, "transcript index: building now, %d of %d videos so far (log: %s)" % (have, len(meta), DATA / "ingest.log"))
    elif DB.exists():
        nv = sqlite3.connect(DB).execute("select count(distinct video) from sent").fetchone()[0]
        check(nv > 0, "transcript index: %d videos searchable" % nv, "python3 %s ingest" % me)
        if 0 < have < len(meta):
            print("       %d videos have no captions yet; running ingest again retries them." % (len(meta) - have))
    else:
        check(False, "transcript index", "Build it once (about 30 minutes, in the background):\n"
              "python3 %s ingest > %s 2>&1 &" % (me, DATA / "ingest.log"))

    if port_open():
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/samples/index.json" % PORT, timeout=2)
            check(True, "player server on port %d" % PORT)
        except Exception:
            check(False, "player port %d is taken by another app" % PORT, "Pick another port: export DM_PORT=8766")
    else:
        check(True, "player port %d free (starts on first reel)" % PORT)
    print("\nAll good." if not problems else "\n%d thing(s) to fix above." % len(problems))


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    fn = globals().get("cmd_" + cmd)
    if not fn:
        print("unknown command: " + cmd)
        sys.exit(1)
    fn(args)


if __name__ == "__main__":
    main()
