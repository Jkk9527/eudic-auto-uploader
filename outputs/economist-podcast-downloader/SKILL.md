---
name: economist-podcast-downloader
description: Download Economist podcast MP3 files, especially Drum Tower, from a legitimate logged-in Chrome session. Use when the user asks to save recent Economist podcast audio locally, extract audio URLs from Chrome media playback, reuse the chrome://media-internals workflow, or automate downloading subscriber podcast episodes they can already play in their browser.
---

# Economist Podcast Downloader

## Overview

Use the user's existing logged-in Chrome session to trigger Economist podcast playback, capture signed Acast MP3 URLs from `chrome://media-internals`, and download the requested episodes into an output folder with podcast-title filenames.

This skill does not bypass subscriptions or paywalls. If the logged-in page cannot play an episode, stop and ask the user to log in or confirm access in the browser.

## Workflow

1. Open the Economist podcast page in the user's system Chrome, not the in-app browser, when the task depends on saved login state.
2. Confirm the page is logged in and the requested episodes expose playable `Listen` controls.
3. Trigger playback for each requested episode. For Drum Tower, the page button names are usually `Listen MM:SS - <episode title>`.
4. Open `chrome://media-internals` in Chrome. Use Computer Use for this internal page because normal browser automation cannot claim Chrome internal tabs.
5. Select any recent `https://sphinx.acast.com/.../media.mp3` player and click `Save Log`.
6. Run `scripts/download_drum_tower_from_log.sh` from the workspace where the user wants files saved. If sandbox DNS blocks downloads, rerun the same wrapper with external-network approval.
7. Verify the result with `ls -lh outputs` and `file outputs/*.mp3`.
8. Pause any still-playing Economist audio in Chrome and release browser control.

## Scripts

Use `scripts/download_drum_tower_from_log.sh` for the common Drum Tower case:

```bash
zsh outputs/economist-podcast-downloader/scripts/download_drum_tower_from_log.sh
```

The wrapper downloads the latest 10 Drum Tower items from the Acast RSS metadata, matches their GUIDs against local `media-internals*.txt` logs, and saves MP3s under `./outputs` by default.

Use the Python script directly for custom feeds or dry runs:

```bash
python3 outputs/economist-podcast-downloader/scripts/download_from_media_log.py \
  --feed-url "https://feeds.acast.com/public/shows/633ebf6dfc7f5a0012acdc97" \
  --log-glob "/Users/roy/Downloads/media-internals*.txt" \
  --out-dir outputs \
  --count 10 \
  --dry-run
```

Add `--download` instead of `--dry-run` to save files.

## Playwright Feasibility

Pure standalone Playwright is only feasible if it owns a logged-in browser profile or attaches to Chrome launched with remote debugging. It cannot automatically use an arbitrary already-open Chrome session. In Codex, prefer the Chrome skill to claim the user's existing Chrome tab, then use the in-skill Playwright API to click visible `Listen` buttons. Use Computer Use for `chrome://media-internals`.

Read `references/economist-media-internals.md` when implementing or adapting the workflow.

## Safety Notes

- Never ask for the user's password, OTP, cookies, local storage, or session files.
- Do not print or include signed Acast URLs in final answers.
- Treat media-internals logs as sensitive because they may contain temporary signed URLs.
- Download only episodes the logged-in browser can play.
