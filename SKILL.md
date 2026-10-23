---
name: dalton-michael
description: Use when the user asks a startup question and wants Dalton Caldwell and Michael Seibel's answer, types /dalton-michael, or says "ask Dalton and Michael", "what would Dalton and Michael say", "D+M", or "office hours". Searches every episode of YC's Dalton & Michael series and their own Dalton + Michael channel by transcript, cuts the moments where they answer it into one continuous reel, plays it in the browser pane, then gives a short summary in chat.
---

# Dalton + Michael

Question in, reel out. **Be fast:** about four tool calls, no narration, no verification, then a short summary. The player is already tested; don't screenshot or debug it.

**The rule: Claude never speaks as them.** Everything attributed to them is a real clip at a real timestamp. Never invent or paraphrase a quote.

**Recording mode.** First, check whether `~/.claude/skills/dalton-michael/data/RECORDING` exists. If it does, this chat is being screen-recorded for a public demo. The chat answer is then generic startup advice only. Never mention the user's company, product, customers, pipeline, pricing, dates, deals, people, or anything from CLAUDE.md or memory, not even as "my read". Skip the personal line entirely.

Corpus: 106 videos, ~32 hours (YC's Dalton & Michael series 2019-2024, their own channel 2025+, 18 solo YC talks).

The skill lives at `~/.claude/skills/dalton-michael` (if it was installed elsewhere, use the base directory shown above in every path below).

**First run, or anything fails.** Run `python3 ~/.claude/skills/dalton-michael/scripts/dm.py doctor`. It checks Python, yt-dlp, the index and the player port, and prints the exact fix for each problem; apply the fixes. If the index is missing, start it in the background with `python3 ~/.claude/skills/dalton-michael/scripts/dm.py ingest > ~/.claude/skills/dalton-michael/data/ingest.log 2>&1 &` (it won't start twice). It becomes searchable after about 5 minutes and finishes in about 30. Meanwhile, if one of the sample reels (`dm.py samples`) matches the question, play it, and say in one line that it's a sample and the full index is still building. If the index is only partly built, answer from what's there and say so in one line.

## Silly questions: skip everything

If the question is a joke, not a real startup question ("does eating pizza get me customers?", "should my cat be CTO?", "is Mercury in retrograde bad for fundraising?"), don't search. One call:

```bash
python3 ~/.claude/skills/dalton-michael/scripts/dm.py silly "Does eating pizza get me more customers?"
```

It builds a five-second reel: one "No." from the bank (rotating), then a smash cut to "So is it fair? No. [laughter] End of video." Play it as in step 4 below. The whole chat reply is **No.** and nothing else.

If it's a real question asked in a funny way ("how do I get customers, pizza?"), treat it as a real question.

## The four steps

**1. One search call.** Pass the question plus 2-3 phrasings they'd use on the show:

```bash
python3 ~/.claude/skills/dalton-michael/scripts/dm.py find "how do I sell to customers" "founder sales" "close enterprise deals" -n 8
```

Each hit prints as timestamped sentences (`»` = speaker change), followed by the intros of the matched episodes. That is all you need to cut; don't run anything else to read transcripts.

**2. Pick 3-5 clips from that output.** The reel is a conversation between the two of them, so both Dalton and Michael have to be heard. Build it from the Dalton & Michael episodes (source `Dalton + Michael` or `Y Combinator`), where they talk to each other. A solo YC talk (`YC talk by Dalton` or `by Michael`, often just slides) gets at most one clip of 20s or less, and never two in a row. If one episode is exactly about the question, take most clips from it, picking moments where each of them makes a point. Then prefer a direct rule of thumb, a concrete story, a funny beat that makes the point, and a moment from a second episode. Start each clip on the first sentence of the thought and end it on a complete sentence. Keep clips to 15-60s and the reel to 2-4 minutes. Give each clip a `beat`: 2-6 words in your own voice that name the point. It shows as a banner over the top of the video.

**3. Build the reel** with a heredoc, one call:

```bash
python3 ~/.claude/skills/dalton-michael/scripts/dm.py reel - <<'EOF'
{"question": "How do I sell to customers?",
 "verdict": "One sentence: the answer.",
 "clips": [
   {"kind": "intro", "video": "yfx_0y7-qDA", "start": "0:18.4", "end": "0:27.4", "card": "none"},
   {"video": "yfx_0y7-qDA", "start": "7:57.1", "end": "8:41.8", "beat": "Be your customer's CEO"},
   {"video": "puOtyUD5qUo", "start": "3:12.8", "end": "3:48.9", "beat": "Don't price in seashells"}
 ]}
EOF
```

- A "great question" sting is added automatically as the cold open; it rotates by question.
- If one episode is *about* the question, add its intro line (from the intros list) as the first clip with `"kind": "intro", "card": "none"`, so the sting smash-cuts into "This is Dalton plus Michael and today we're going to talk about...". If the episode opens on a better joke, use that instead (like the burrito line in the sales episode).
- Cut points snap to the nearest sentence boundary. Times can be given as `m:ss.s` or as seconds.

**4. Play it, in front of the user.** The last line of the output is the URL. Two calls in the same message, in this order:
   1. `preview_start` with `url` set to that URL. It opens the Browser pane, or reuses it, with the reel in front. Don't use `navigate`: it loads the page into a hidden pane, where the user can't see it.
   2. `mcp__ccd_view__show_pane` with `pane: "preview"`, so the pane is on screen. Load it first with ToolSearch (`select:mcp__ccd_view__show_pane`) if it's deferred.

   The reel autoplays once it's visible.

## The chat answer

Once it's playing, reply in this shape and nothing more:

- **The verdict**, one bold line.
- **3-4 bullets**, one per clip's point, in plain words.
- If the user's own situation is known and relevant, one final line applying it, marked as your read, not theirs.

No cut list, no links, no timestamps, no description of what you did. The player has the episode links.

If they never covered the question, say so in one line and play the closest moments anyway.

## Other commands

`dm show VIDEO 4:10 5:20` reads a window that `find` didn't cover. `dm reactions` lists the cold-open bank: stings, plus topic openers like "How to win. Just win." for huge questions or "we disagree strongly" for debates. Put one in as clip 1 (`"kind": "intro", "exact": true`) to replace the automatic sting. `dm ingest` pulls new episodes (slow because YouTube rate-limits; run it in the background). `dm stats` shows corpus size.

Speaker names: the captions mark speaker changes, not who is talking. Only solo YC talks carry a `speaker`. Don't write "Dalton says" unless the transcript makes it obvious.
