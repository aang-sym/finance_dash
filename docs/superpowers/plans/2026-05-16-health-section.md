# Health Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Health section to the FINTERM dashboard — a separate nav experience with sourced routine checklists and reference cards, populated from Qoves Studio YouTube transcripts.

**Architecture:** The existing header on every finance page gets FINANCE/HEALTH pill buttons; clicking HEALTH navigates to `/health/<tab>` routes served by Flask. A standalone script downloads and filters Qoves transcripts + descriptions into `data/health/transcripts/`. Claude then reads those files and writes the health tab HTML files with two-column checklist + sourced reference layouts.

**Tech Stack:** Python 3, Flask (existing), yt-dlp, youtube-transcript-api, HTML/CSS (JetBrains Mono terminal aesthetic)

---

## File Map

**Create:**
- `scripts/fetch_transcripts.py` — downloads Qoves transcripts and descriptions, with two-pass filtering
- `data/health/transcripts/` — directory for transcript + source files + index
- `health/<tab>.html` — one file per tab (filenames determined after curation in Task 5)

**Modify:**
- `server.py` — add `/health/<tab>` routes + `data/health/` directory setup
- `dashboard.html`, `bills.html`, `budget.html`, `cgt.html`, `house.html`, `networth.html`, `performance.html`, `portfolio.html`, `spending.html`, `tax.html` — add FINANCE/HEALTH pill buttons to header + section-switching CSS/JS

---

## Task 1: Create branch and install dependencies

**Files:**
- Modify: `venv/` (pip install)

- [ ] **Step 1: Create the feature branch**

```bash
git checkout -b feature/health-section
```

Expected: `Switched to a new branch 'feature/health-section'`

- [ ] **Step 2: Install yt-dlp and youtube-transcript-api into the venv**

```bash
source venv/bin/activate && pip install yt-dlp youtube-transcript-api
```

Expected: both packages install without error. Verify:

```bash
python3 -c "import yt_dlp; from youtube_transcript_api import YouTubeTranscriptApi; print('ok')"
```

Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: install yt-dlp and youtube-transcript-api"
```

---

## Task 2: Write the transcript fetch script

**Files:**
- Create: `scripts/fetch_transcripts.py`

The script fetches Qoves Studio videos in two passes, filters by title, and saves transcript + description per video.

- [ ] **Step 1: Create the scripts directory and script file**

```bash
mkdir -p scripts data/health/transcripts
```

- [ ] **Step 2: Write `scripts/fetch_transcripts.py`**

```python
#!/usr/bin/env python3
"""
Fetch Qoves Studio transcripts in two passes:
  Pass 1 — all videos from CUTOFF_VIDEO onwards (recent actionable content)
  Pass 2 — top N videos by view count across all time

Saves per-video:
  data/health/transcripts/<video-id>-<slug>.txt       — transcript text
  data/health/transcripts/<video-id>-<slug>.sources.txt — video description
  data/health/transcripts/index.md                    — triage index
"""

import re
import sys
from pathlib import Path

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

CHANNEL_URL = "https://www.youtube.com/@QOVESStudio/videos"
CUTOFF_TITLE = "why you're shy around attractive people"
TOP_N = 30
OUT_DIR = Path("data/health/transcripts")

# Title filter — skip if any denylist phrase matches (case-insensitive)
DENYLIST = [
    "woman's guide", "women's guide", "a woman's", "women's",
    "female guide", "for women", "for girls",
    "instagram vs reality", "bending space",
    "reaction", "q&a", "podcast", "vlog",
]

# Must contain at least one allowlist signal to pass (skip purely entertainment titles)
ALLOWLIST = [
    "how to", "guide", "fix", "improve", "anti-aging", "anti-ageing",
    "aging", "ageing", "skin", "hair", "face", "eye", "brow",
    "jaw", "bone", "posture", "sleep", "diet", "fat", "muscle",
    "attract", "look", "appearance", "mistakes", "tips", "routine",
    "exercise", "mewing", "neck", "body", "health", "science",
    "study", "research", "causes", "effects", "works", "secret",
]


def slugify(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"[\s_-]+", "-", title).strip("-")
    return title[:60]


def is_relevant(title: str) -> bool:
    t = title.lower()
    if any(phrase in t for phrase in DENYLIST):
        return False
    if any(phrase in t for phrase in ALLOWLIST):
        return True
    return False


def fetch_all_video_metadata() -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
    return info.get("entries", [])


def fetch_video_description(video_id: str) -> str:
    ydl_opts = {"quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    return info.get("description", "") or ""


def fetch_transcript(video_id: str) -> str:
    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        return " ".join(seg["text"] for seg in segments)
    except (NoTranscriptFound, TranscriptsDisabled):
        return ""


def save_video(video_id: str, title: str, transcript: str, description: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    stem = f"{video_id}-{slug}"
    transcript_path = OUT_DIR / f"{stem}.txt"
    sources_path = OUT_DIR / f"{stem}.sources.txt"
    transcript_path.write_text(f"TITLE: {title}\nVIDEO_ID: {video_id}\n\n{transcript}", encoding="utf-8")
    sources_path.write_text(f"TITLE: {title}\nVIDEO_ID: {video_id}\n\n{description}", encoding="utf-8")
    return transcript_path


def write_index(saved: list[dict]) -> None:
    lines = ["# Qoves Transcript Index\n"]
    lines.append(f"Total videos: {len(saved)}\n\n")
    lines.append("| # | Title | Video ID | Views | Date | Transcript |\n")
    lines.append("|---|-------|----------|-------|------|------------|\n")
    for i, entry in enumerate(saved, 1):
        vid = entry["video_id"]
        title = entry["title"]
        views = f"{entry.get('view_count', 0):,}"
        date = entry.get("upload_date", "")
        slug = slugify(title)
        fname = f"{vid}-{slug}.txt"
        lines.append(f"| {i} | {title} | {vid} | {views} | {date} | [{fname}]({fname}) |\n")
    (OUT_DIR / "index.md").write_text("".join(lines), encoding="utf-8")


def main() -> None:
    print("Fetching all video metadata from channel...")
    all_entries = fetch_all_video_metadata()
    print(f"Found {len(all_entries)} total videos")

    # Find cutoff index
    cutoff_idx = None
    for i, entry in enumerate(all_entries):
        if CUTOFF_TITLE in (entry.get("title") or "").lower():
            cutoff_idx = i
            break

    if cutoff_idx is None:
        print(f"WARNING: cutoff video not found, using all entries for Pass 1")
        cutoff_idx = len(all_entries)

    pass1_entries = all_entries[:cutoff_idx + 1]  # newest-first list, so slice from start
    pass2_entries = sorted(all_entries, key=lambda e: e.get("view_count") or 0, reverse=True)[:TOP_N]

    downloaded_ids: set[str] = set()
    saved: list[dict] = []

    def process(entry: dict, pass_name: str) -> None:
        video_id = entry.get("id") or entry.get("url", "").split("v=")[-1]
        title = entry.get("title") or ""
        if not video_id or not title:
            return
        if video_id in downloaded_ids:
            return
        if not is_relevant(title):
            print(f"  [SKIP] {title}")
            return
        print(f"  [FETCH] {title}")
        transcript = fetch_transcript(video_id)
        if not transcript:
            print(f"    -> no transcript, skipping")
            return
        description = fetch_video_description(video_id)
        save_video(video_id, title, transcript, description)
        downloaded_ids.add(video_id)
        saved.append({
            "video_id": video_id,
            "title": title,
            "view_count": entry.get("view_count") or 0,
            "upload_date": entry.get("upload_date") or "",
        })

    print(f"\n=== Pass 1: {len(pass1_entries)} recent videos (from cutoff) ===")
    for entry in pass1_entries:
        process(entry, "Pass 1")

    print(f"\n=== Pass 2: top {TOP_N} by view count ===")
    for entry in pass2_entries:
        process(entry, "Pass 2")

    print(f"\nDone. {len(saved)} videos saved to {OUT_DIR}/")
    write_index(saved)
    print(f"Index written to {OUT_DIR}/index.md")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Make it executable and do a dry-run to check imports**

```bash
chmod +x scripts/fetch_transcripts.py
source venv/bin/activate && python3 -c "
import scripts.fetch_transcripts as f
print('is_relevant tests:')
print(f.is_relevant(\"How to Fix Facial Asymmetry\"))        # True
print(f.is_relevant(\"A Woman's Guide to Hair Color\"))      # False
print(f.is_relevant(\"Instagram vs Reality\"))               # False
print(f.is_relevant(\"The Anti-Aging Pyramid\"))             # True
print(f.slugify(\"Why the Eyes Make or Break a Face!\"))
"
```

Expected output:
```
is_relevant tests:
True
False
False
True
why-the-eyes-make-or-break-a-face
```

- [ ] **Step 4: Commit**

```bash
git add scripts/fetch_transcripts.py data/health/
git commit -m "feat: add transcript fetch script with two-pass Qoves filtering"
```

---

## Task 3: Run the transcript fetch and review the index

**Files:**
- Populate: `data/health/transcripts/`

- [ ] **Step 1: Run the fetch script**

```bash
source venv/bin/activate && python3 scripts/fetch_transcripts.py 2>&1 | tee /tmp/fetch_log.txt
```

This will take several minutes. Watch for `[FETCH]` vs `[SKIP]` lines. If a video has no transcript it will print `-> no transcript, skipping`.

- [ ] **Step 2: Check how many videos were downloaded**

```bash
ls data/health/transcripts/*.txt 2>/dev/null | wc -l
cat data/health/transcripts/index.md
```

Expected: at least 15–20 `.txt` files and a populated index table.

- [ ] **Step 3: Spot-check a transcript and its sources file**

```bash
# Show first transcript (first 40 lines)
head -40 $(ls data/health/transcripts/*.txt | head -1)
echo "---"
# Show its sources file
head -40 $(ls data/health/transcripts/*.sources.txt | head -1)
```

Verify the transcript contains meaningful content and the sources file contains description text (look for "SOURCES" and academic citations).

- [ ] **Step 4: Commit the transcripts**

```bash
git add data/health/transcripts/
git commit -m "data: add Qoves transcript corpus for health section curation"
```

---

## Task 4: Add FINANCE/HEALTH pill buttons to all finance page headers

This task modifies the 10 existing HTML files. The change is identical in each: replace the `<div class="hdr-right" id="hdr-date"></div>` with a version that includes the section pills, and add CSS for the pills.

The pills sit in the right side of the header. Finance pages show FINANCE as active. Health pages (built later) show HEALTH as active.

**Files:**
- Modify: `dashboard.html`, `bills.html`, `budget.html`, `cgt.html`, `house.html`, `networth.html`, `performance.html`, `portfolio.html`, `spending.html`, `tax.html`

- [ ] **Step 1: In each of the 10 finance HTML files, add pill CSS to the `<style>` block**

Find the closing `</style>` tag in each file and insert before it:

```css
.section-pills{display:flex;gap:6px;align-items:center}
.section-pill{padding:3px 10px;border:1px solid rgba(120,180,120,0.2);color:rgba(207,234,207,0.4);font-size:11px;font-weight:600;letter-spacing:0.08em;cursor:pointer;text-decoration:none;transition:color 0.15s,border-color 0.15s}
.section-pill.active{border-color:var(--green);color:var(--green)}
.section-pill:hover:not(.active){color:var(--txt);border-color:rgba(120,180,120,0.5)}
```

- [ ] **Step 2: In each of the 10 finance HTML files, replace the header right div**

Find:
```html
  <div class="hdr-right" id="hdr-date"></div>
```

Replace with:
```html
  <div class="hdr-right" style="display:flex;align-items:center;gap:14px">
    <span id="hdr-date"></span>
    <div class="section-pills">
      <a class="section-pill active" href="/dashboard">FINANCE</a>
      <a class="section-pill" href="/health/skin">HEALTH</a>
    </div>
  </div>
```

Note: `/health/skin` is a placeholder — update to the first real health tab slug once Tab 5 determines the tab list.

- [ ] **Step 3: Start the server and visually verify the pills appear on dashboard**

```bash
source venv/bin/activate && python3 server.py &
```

Open http://localhost:5001/dashboard — confirm FINANCE pill is active (green border), HEALTH pill is dim. Confirm clicking HEALTH gives a 404 (expected — routes not added yet).

Kill the server after checking: `kill %1`

- [ ] **Step 4: Commit**

```bash
git add dashboard.html bills.html budget.html cgt.html house.html networth.html performance.html portfolio.html spending.html tax.html
git commit -m "feat: add FINANCE/HEALTH section pill buttons to all finance page headers"
```

---

## Task 5: Curate transcripts and write health tab HTML files

**Files:**
- Create: `health/` directory + one `.html` per tab
- Determine: final tab list and slugs

This task is performed by Claude reading the downloaded transcripts and writing the tab HTML files. The tab list is not fixed — it emerges from what the transcripts cover.

- [ ] **Step 1: Read the transcript index to plan tab structure**

```bash
cat data/health/transcripts/index.md
```

Then read the actual transcript files, grouping insights by topic. Determine tab names and slugs (e.g. `skin`, `hair`, `anti-age`, `eyes`, `face`, `lifestyle` — whatever the content warrants).

- [ ] **Step 2: Create the `health/` directory**

```bash
mkdir -p health
```

- [ ] **Step 3: For each tab, write `health/<slug>.html`**

Each file follows this exact template (replace `SKIN` / skin / SKINCARE etc. with the appropriate tab):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FINTERM · SKIN</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080a08;--panel:#0d100d;--panel2:#111411;
  --rule:rgba(120,180,120,0.13);--rule2:rgba(120,180,120,0.06);
  --txt:#cfeacf;--dim:rgba(207,234,207,0.55);--dim2:rgba(207,234,207,0.28);
  --green:#7ee787;--amber:#f0b86e;--red:#ff7b72;--blue:#79c0ff;
  --font:'JetBrains Mono',monospace;
}
html,body{height:100%;background:var(--bg);color:var(--txt);font-family:var(--font);font-size:13px;line-height:1.5;overflow-x:hidden}
a{color:inherit;text-decoration:none}
body::after{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.04) 2px,rgba(0,0,0,0.04) 4px);pointer-events:none;z-index:9999}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--rule);background:var(--panel)}
.hdr-left{display:flex;align-items:center;gap:12px}
.hdr-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
.hdr-title{color:var(--green);font-weight:700;font-size:14px;letter-spacing:0.05em}
.hdr-sub{color:var(--dim);font-size:11px}
.section-pills{display:flex;gap:6px;align-items:center}
.section-pill{padding:3px 10px;border:1px solid rgba(120,180,120,0.2);color:rgba(207,234,207,0.4);font-size:11px;font-weight:600;letter-spacing:0.08em;cursor:pointer;text-decoration:none;transition:color 0.15s,border-color 0.15s}
.section-pill.active{border-color:var(--green);color:var(--green)}
.section-pill:hover:not(.active){color:var(--txt);border-color:rgba(120,180,120,0.5)}
.nav{display:flex;align-items:center;border-bottom:1px solid var(--rule);background:var(--panel);overflow-x:auto}
.nav-item{padding:8px 14px;color:var(--dim);font-size:12px;white-space:nowrap;border-bottom:2px solid transparent;cursor:pointer;transition:color 0.15s;text-decoration:none}
.nav-item:hover{color:var(--txt)}
.nav-item.active{color:var(--green);border-bottom-color:var(--green)}
.nav-key{color:rgba(207,234,207,0.28)}
.page{padding:12px 16px;display:flex;flex-direction:column;gap:12px;max-width:1400px;margin:0 auto}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.box{background:var(--panel);border:1px solid var(--rule);padding:14px}
.sec-label{font-size:11px;font-weight:600;color:var(--dim);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:10px}
.checklist{display:flex;flex-direction:column;gap:6px}
.checklist-item{display:flex;align-items:flex-start;gap:8px;font-size:12px;color:var(--txt)}
.checklist-item input[type=checkbox]{margin-top:2px;accent-color:var(--green);flex-shrink:0;width:13px;height:13px;cursor:pointer}
.period-label{font-size:10px;color:var(--dim2);letter-spacing:0.1em;text-transform:uppercase;margin:12px 0 6px}
.period-label:first-child{margin-top:0}
.ref-list{display:flex;flex-direction:column;gap:10px}
.ref-item{display:flex;gap:10px;align-items:flex-start}
.ref-num{font-size:11px;color:var(--green);min-width:20px;font-weight:600;padding-top:1px}
.ref-body{}
.ref-insight{font-size:12px;color:var(--txt);font-weight:600;line-height:1.4}
.ref-why{font-size:11px;color:var(--dim);margin-top:2px;line-height:1.4}
.ref-sources{font-size:10px;color:rgba(207,234,207,0.35);margin-top:4px}
.ref-sources a{color:var(--blue);text-decoration:none}
.ref-sources a:hover{text-decoration:underline}
.ref-num.amber{color:var(--amber)}
.ref-num.red{color:var(--red)}
@media(max-width:768px){.two-col{grid-template-columns:1fr}}
</style>
</head>
<body>

<header class="hdr">
  <div class="hdr-left">
    <div class="hdr-dot"></div>
    <span class="hdr-title">FINTERM/ANGUS</span>
    <span class="hdr-sub">health</span>
  </div>
  <div style="display:flex;align-items:center;gap:14px">
    <div class="section-pills">
      <a class="section-pill" href="/dashboard">FINANCE</a>
      <a class="section-pill active" href="/health/skin">HEALTH</a>
    </div>
  </div>
</header>

<nav class="nav">
  <!-- populate with all health tab links; mark current tab as active -->
  <a class="nav-item active" href="/health/skin"><span class="nav-key">[S]</span>KIN</a>
  <a class="nav-item" href="/health/hair"><span class="nav-key">[H]</span>AIR</a>
  <!-- add more tabs as determined by curation -->
</nav>

<main class="page">
  <div class="two-col">

    <!-- LEFT: ROUTINES -->
    <div class="box">
      <div class="sec-label">Routines</div>

      <div class="period-label">Morning</div>
      <div class="checklist">
        <!-- Each item: exact actionable step derived from Qoves transcripts -->
        <label class="checklist-item">
          <input type="checkbox">
          <span>Gentle pH-balanced cleanser (avoid harsh sulfates)</span>
        </label>
        <!-- ... more items ... -->
      </div>

      <div class="period-label">Evening</div>
      <div class="checklist">
        <label class="checklist-item">
          <input type="checkbox">
          <span>Double cleanse — oil cleanser first, then water-based</span>
        </label>
        <!-- ... more items ... -->
      </div>

      <div class="period-label">Weekly</div>
      <div class="checklist">
        <label class="checklist-item">
          <input type="checkbox">
          <span>Chemical exfoliant — AHA (glycolic/lactic) or BHA (salicylic)</span>
        </label>
        <!-- ... more items ... -->
      </div>
    </div>

    <!-- RIGHT: REFERENCE -->
    <div class="box">
      <div class="sec-label">Reference · by impact</div>
      <div class="ref-list">
        <!-- Items numbered 01+ in descending impact order -->
        <div class="ref-item">
          <div class="ref-num">01</div>
          <div class="ref-body">
            <div class="ref-insight">SPF 50+ every day without exception</div>
            <div class="ref-why">UV radiation is the single largest driver of visible facial aging — responsible for ~80% of skin aging signs.</div>
            <div class="ref-sources">
              <a href="https://doi.org/10.1111/jocd.12476" target="_blank">[Hughes et al., 2013]</a>
            </div>
          </div>
        </div>
        <!-- ... more items ... -->
      </div>
    </div>

  </div>
</main>

</body>
</html>
```

Write the actual content (routines and reference cards) from the transcripts — do not leave placeholder items. Every checklist item and every reference card must contain real content derived from the Qoves videos.

- [ ] **Step 4: Commit**

```bash
git add health/
git commit -m "feat: add health tab HTML files with sourced routines and reference cards"
```

---

## Task 6: Add health routes to server.py

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add health page routes to server.py**

After the existing `@app.get("/tax")` route (around line 1405), add:

```python
HEALTH_DIR = BASE_DIR / "health"


@app.get("/health")
def health_root():
    return redirect("/health/skin")


@app.get("/health/<tab>")
def health_page(tab: str):
    page = HEALTH_DIR / f"{tab}.html"
    if not page.exists():
        return "Not found", 404
    return send_file(page)
```

Replace `"skin"` in the redirect with whatever the first health tab slug actually is (determined in Task 5).

- [ ] **Step 2: Verify routes work**

```bash
source venv/bin/activate && python3 server.py &
```

Test each health route:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/health        # expect 302
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/health/skin   # expect 200
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/health/bogus  # expect 404
```

Open http://localhost:5001/health/skin in a browser — verify the page loads with correct layout, both pill buttons are visible (HEALTH active), and health nav tabs show.

Kill the server: `kill %1`

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat: add /health/<tab> routes to Flask server"
```

---

## Task 7: Update finance page headers with correct health tab link

Now that the real first health tab slug is known (from Task 5), update all 10 finance pages to link HEALTH pill to the correct URL (done in Task 4 with placeholder `/health/skin` — confirm or update).

**Files:**
- Modify: `dashboard.html`, `bills.html`, `budget.html`, `cgt.html`, `house.html`, `networth.html`, `performance.html`, `portfolio.html`, `spending.html`, `tax.html` (only if first tab slug differs from `skin`)

- [ ] **Step 1: Check current placeholder**

```bash
grep -l "health/skin" *.html | wc -l
```

If all 10 files reference `/health/skin` and `skin` is the correct first tab, skip to Step 3. If the first tab slug is different, proceed.

- [ ] **Step 2: Update the HEALTH pill href in all finance pages**

Replace `href="/health/skin"` with `href="/health/<actual-first-tab-slug>"` in all 10 files.

```bash
# Example if first tab is "anti-age":
sed -i '' 's|href="/health/skin"|href="/health/anti-age"|g' dashboard.html bills.html budget.html cgt.html house.html networth.html performance.html portfolio.html spending.html tax.html
```

- [ ] **Step 3: End-to-end navigation test**

```bash
source venv/bin/activate && python3 server.py &
```

1. Open http://localhost:5001/dashboard — FINANCE pill active, HEALTH pill dim
2. Click HEALTH pill — should land on first health tab, HEALTH pill now active, FINANCE pill dim
3. Click through all health tabs — verify nav works, all tabs load, no 404s
4. Click FINANCE pill from a health page — should return to /dashboard

Kill server: `kill %1`

- [ ] **Step 4: Commit**

```bash
git add dashboard.html bills.html budget.html cgt.html house.html networth.html performance.html portfolio.html spending.html tax.html
git commit -m "fix: update HEALTH pill href to correct first health tab across all finance pages"
```

---

## Task 8: Final review and branch cleanup

- [ ] **Step 1: Full visual walkthrough**

```bash
source venv/bin/activate && python3 server.py &
```

Visit every page and check:
- All finance pages: FINANCE pill active (green), HEALTH pill dim
- All health pages: HEALTH pill active (green), FINANCE pill dim
- Health nav: correct tab highlighted on each page
- Reference cards: all citations link to real DOIs (click a few to verify)
- Checklist items: all specific and actionable (no vague items)
- No broken layouts on any tab

- [ ] **Step 2: Verify `.gitignore` covers transcripts if desired**

The transcripts are data files (not code) — they're committed in Task 3, which is correct. No change needed.

- [ ] **Step 3: Kill server and push branch**

```bash
kill %1
git log --oneline feature/health-section ^main
```

Review the commit list — should show 7–8 commits from Tasks 1–7.

When satisfied, push:
```bash
git push -u origin feature/health-section
```
