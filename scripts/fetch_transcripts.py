#!/usr/bin/env python3
"""
Fetch Qoves Studio transcripts in two passes:
  Pass 1 — all videos from CUTOFF_VIDEO onwards (recent actionable content)
  Pass 2 — top N videos by view count across all time

Channel list is returned newest-first by yt-dlp, so Pass 1 slices from
index 0 up to and including the cutoff video.

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

    # Find cutoff index (list is newest-first)
    cutoff_idx = None
    for i, entry in enumerate(all_entries):
        if CUTOFF_TITLE in (entry.get("title") or "").lower():
            cutoff_idx = i
            break

    if cutoff_idx is None:
        print("WARNING: cutoff video not found, using all entries for Pass 1")
        cutoff_idx = len(all_entries)

    pass1_entries = all_entries[:cutoff_idx + 1]
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
