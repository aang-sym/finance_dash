#!/usr/bin/env python3
"""
Fetch Qoves Studio transcripts in two passes:
  Pass 1 — all videos from CUTOFF_VIDEO onwards (recent actionable content)
  Pass 2 — top N videos by view count across all time

Channel list is returned newest-first by yt-dlp, so Pass 1 slices from
index 0 up to and including the cutoff video.

Uses process=False to bypass yt-dlp format selection (which fails with n-challenge),
then downloads subtitle JSON directly via ydl.urlopen (inherits browser cookies).

Saves per-video:
  data/health/transcripts/<video-id>-<slug>.txt       — transcript text
  data/health/transcripts/<video-id>-<slug>.sources.txt — video description
  data/health/transcripts/index.md                    — triage index
"""

import json
import re
from pathlib import Path

import yt_dlp

CHANNEL_URL = "https://www.youtube.com/@QOVESStudio/videos"
CUTOFF_TITLE = "why you're shy around attractive people"
TOP_N = 30
OUT_DIR = Path("data/health/transcripts")

DENYLIST = [
    "woman's guide", "women's guide", "a woman's", "women's",
    "female guide", "for women", "for girls",
    "instagram vs reality", "bending space",
    "reaction", "q&a", "podcast", "vlog",
]

ALLOWLIST = [
    "how to", "guide", "fix", "improve", "anti-aging", "anti-ageing",
    "aging", "ageing", "skin", "hair", "face", "eye", "brow",
    "jaw", "bone", "posture", "sleep", "diet", "fat", "muscle",
    "attract", "look", "appearance", "mistakes", "tips", "routine",
    "exercise", "mewing", "neck", "body", "health", "science",
    "study", "research", "causes", "effects", "works", "secret",
]

YDL_OPTS = {
    "cookiesfrombrowser": ("chrome",),
    "quiet": True,
}


def slugify(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"[\s_-]+", "-", title).strip("-")
    return title[:60]


def is_relevant(title: str) -> bool:
    t = title.lower()
    if any(phrase in t for phrase in DENYLIST):
        return False
    return any(phrase in t for phrase in ALLOWLIST)


def fetch_all_video_metadata() -> list[dict]:
    opts = {**YDL_OPTS, "extract_flat": "in_playlist", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
    return info.get("entries", [])


def fetch_transcript_and_description(video_id: str) -> tuple[str, str]:
    """Return (transcript_text, description) using process=False to bypass format errors."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
        description = info.get("description", "") or ""
        subs = info.get("automatic_captions", {})
        en_formats = subs.get("en-orig") or subs.get("en") or []
        sub_url = next((f["url"] for f in en_formats if f.get("ext") == "json3"), None)
        if not sub_url:
            return "", description
        try:
            raw = ydl.urlopen(sub_url).read().decode("utf-8")
        except Exception:
            return "", description

    obj = json.loads(raw)
    texts = []
    for event in obj.get("events", []):
        for seg in event.get("segs", []):
            t = seg.get("utf8", "")
            if t and t.strip() and t.strip() != "\n":
                texts.append(t.strip())
    return " ".join(texts), description


def save_video(video_id: str, title: str, transcript: str, description: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    stem = f"{video_id}-{slug}"
    (OUT_DIR / f"{stem}.txt").write_text(
        f"TITLE: {title}\nVIDEO_ID: {video_id}\n\n{transcript}", encoding="utf-8"
    )
    (OUT_DIR / f"{stem}.sources.txt").write_text(
        f"TITLE: {title}\nVIDEO_ID: {video_id}\n\n{description}", encoding="utf-8"
    )


def write_index(saved: list[dict]) -> None:
    lines = [
        "# Qoves Transcript Index\n",
        f"Total videos: {len(saved)}\n\n",
        "| # | Title | Video ID | Views | Date | Transcript |\n",
        "|---|-------|----------|-------|------|------------|\n",
    ]
    for i, entry in enumerate(saved, 1):
        vid = entry["video_id"]
        title = entry["title"]
        views = f"{entry.get('view_count', 0):,}"
        date = entry.get("upload_date", "")
        fname = f"{vid}-{slugify(title)}.txt"
        lines.append(f"| {i} | {title} | {vid} | {views} | {date} | [{fname}]({fname}) |\n")
    (OUT_DIR / "index.md").write_text("".join(lines), encoding="utf-8")


def main() -> None:
    print("Fetching all video metadata from channel...")
    all_entries = fetch_all_video_metadata()
    print(f"Found {len(all_entries)} total videos")

    cutoff_idx = next(
        (i for i, e in enumerate(all_entries) if CUTOFF_TITLE in (e.get("title") or "").lower()),
        len(all_entries),
    )
    if cutoff_idx == len(all_entries):
        print("WARNING: cutoff video not found, using all entries for Pass 1")

    pass1 = all_entries[:cutoff_idx + 1]
    pass2 = sorted(all_entries, key=lambda e: e.get("view_count") or 0, reverse=True)[:TOP_N]

    downloaded: set[str] = set()
    saved: list[dict] = []

    def process(entry: dict) -> None:
        video_id = entry.get("id") or ""
        title = entry.get("title") or ""
        if not video_id or not title or video_id in downloaded:
            return
        if not is_relevant(title):
            print(f"  [SKIP] {title}")
            return
        print(f"  [FETCH] {title}")
        transcript, description = fetch_transcript_and_description(video_id)
        if not transcript:
            print("    -> no transcript, skipping")
            return
        save_video(video_id, title, transcript, description)
        downloaded.add(video_id)
        saved.append({
            "video_id": video_id,
            "title": title,
            "view_count": entry.get("view_count") or 0,
            "upload_date": entry.get("upload_date") or "",
        })

    print(f"\n=== Pass 1: {len(pass1)} recent videos (from cutoff) ===")
    for entry in pass1:
        process(entry)

    print(f"\n=== Pass 2: top {TOP_N} by view count ===")
    for entry in pass2:
        process(entry)

    print(f"\nDone. {len(saved)} videos saved to {OUT_DIR}/")
    write_index(saved)
    print(f"Index written to {OUT_DIR}/index.md")


if __name__ == "__main__":
    main()
