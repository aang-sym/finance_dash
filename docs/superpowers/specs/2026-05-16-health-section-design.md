# Health Section Design

**Date:** 2026-05-16
**Status:** Approved

## Overview

Add a Health section to the existing finance dashboard (FINTERM). The section is a separate experience from Finance — same visual aesthetic (JetBrains Mono, green-on-black terminal theme), but focused on actionable routines and sourced reference cards derived from the Qoves Studio YouTube channel.

## Navigation & Routing

The shared header across all existing pages gets two pill buttons on the right side: **FINANCE** and **HEALTH**. Clicking a pill switches the nav row below it:

- While on a Finance page, FINANCE pill is active and the existing nav row shows (DASH, NET.WORTH, PORTFOLIO, CGT, HOUSE, BILLS, SPEND, BUDGET, PERF, TAX)
- While on a Health page, HEALTH pill is active and the nav row shows health tabs

Health routes follow the pattern `/health/<tab>`. Tab names and count are determined after transcript curation — could be 4–8 tabs. Example candidates: SKIN, HAIR, ANTI-AGE, EYES — but this list is not final.

All existing finance files are modified only to add the pill buttons to the header. Finance routing and content is untouched.

## Tab Layout

Each health tab uses a two-column layout:

**Left column — ROUTINES**
Morning / evening / weekly checklists. Each item is specific and actionable (e.g. "Apply SPF 50+ before going outside" not "use sunscreen"). Items are derived directly from Qoves video recommendations.

**Right column — REFERENCE**
Cards ranked by impact (01, 02, 03…). Each card contains:
- The insight (one line, bold)
- A one-sentence explanation of why it matters
- One or more linked citations formatted as `[Author et al., Year]` linking to the DOI URL

## Content Pipeline

### Script: `scripts/fetch_transcripts.py`

Dependencies: `yt-dlp`, `youtube-transcript-api` (no YouTube API key required).

**Pass 1 — Recent actionable videos:**
Fetch all videos uploaded after and including "Why you're shy around attractive people". Filter by title before downloading — skip videos that are:
- Women-specific (e.g. "A Woman's Guide to...")
- Non-improvement content (entertainment, opinion, non-actionable)
- Shorts

**Pass 2 — Top by view count:**
Fetch the channel's most-viewed videos across all time. Apply the same title filter. Skip videos already downloaded in Pass 1.

For each qualifying video, save:
- `data/health/transcripts/<video-id>-<slug>.txt` — full transcript
- `data/health/transcripts/<video-id>-<slug>.sources.txt` — video description (contains Qoves' academic source list)
- `data/health/transcripts/index.md` — summary index with title, date, view count, and URL for every downloaded video

### Curation (Claude)

After the script runs, Claude reads all transcripts and source files, determines the tab structure, and writes the tab HTML files including sourced reference cards. The user does not manually curate content.

## File Structure

```
scripts/
  fetch_transcripts.py

data/
  health/
    transcripts/
      index.md
      <video-id>-<slug>.txt
      <video-id>-<slug>.sources.txt

health/
  <tab>.html          # one file per tab, determined after curation

server.py             # new /health/<tab> routes added
```

Existing `*.html` files (dashboard.html, networth.html, etc.) each get the FINANCE/HEALTH pill buttons added to the shared header block.

## Branch

All work on branch `feature/health-section`.

## Out of Scope

- No live data integration — health tabs are static reference/checklist pages
- No persistence of checklist state (checkboxes are visual only, not saved)
- No AI auto-extraction — Claude reads transcripts directly and writes content
