# Economist Media Internals Workflow

## Purpose

Use this reference when the user wants Economist podcast audio downloaded from a logged-in browser session. The repeatable pattern is:

1. Trigger the Economist web player.
2. Save Chrome's media log.
3. Match Acast episode GUIDs from RSS metadata to signed MP3 URLs in the log.
4. Download MP3 files with podcast-title filenames.

## Chrome Procedure

Use system Chrome when the user relies on an existing login. The in-app browser may not share cookies.

For a Codex-controlled Chrome tab:

1. Read the Chrome skill before operating Chrome.
2. Claim the tab whose URL matches `https://www.economist.com/audio/podcasts/...`.
3. Use a DOM snapshot to identify exact visible `Listen` button names.
4. Click each requested `Listen` button once, waiting briefly after each click for media to load.
5. Open `chrome://media-internals` with `open -a "Google Chrome" "chrome://media-internals"`.
6. Use Computer Use to select a recent `https://sphinx.acast.com/.../media.mp3` player and click `Save Log`.

Chrome internal pages cannot usually be claimed by the Chrome browser automation API. Use screen/accessibility automation for `chrome://media-internals`.

## Drum Tower Defaults

Drum Tower page:

```text
https://www.economist.com/audio/podcasts/drum-tower
```

Acast RSS metadata:

```text
https://feeds.acast.com/public/shows/633ebf6dfc7f5a0012acdc97
```

RSS items expose current titles and GUIDs. Subscriber items may omit public enclosure URLs, so use RSS only for metadata and GUID matching.

## Running The Downloader

After saving `media-internals*.txt` in Downloads, run from the workspace where output should be created:

```bash
zsh outputs/economist-podcast-downloader/scripts/download_drum_tower_from_log.sh
```

For a dry run:

```bash
python3 outputs/economist-podcast-downloader/scripts/download_from_media_log.py \
  --feed-url "https://feeds.acast.com/public/shows/633ebf6dfc7f5a0012acdc97" \
  --log-glob "/Users/roy/Downloads/media-internals*.txt" \
  --out-dir outputs \
  --count 10 \
  --dry-run
```

If network fails inside the sandbox with DNS errors, rerun the wrapper with external-network approval. Do not broaden approval to arbitrary Python execution.

## Validation

After download:

```bash
ls -lh outputs
file outputs/*.mp3
```

Expect MP3 files, often 128 kbps at 44.1 kHz for Acast-hosted Economist audio.

## Common Failure Modes

- `media-internals` log contains only a trailer: not all `Listen` buttons were triggered.
- RSS item exists but no matching signed URL is in logs: click that episode's `Listen` button and save a fresh log.
- JavaScript via Apple Events fails: Chrome's "Allow JavaScript from Apple Events" is disabled. Do not require enabling it; use Chrome skill or Computer Use instead.
- `pageAssets` has no audio: assets inventory may not include media until playback is triggered; use media-internals.
- Final answer leaks signed URLs: avoid this. Mention only output files and verification.
