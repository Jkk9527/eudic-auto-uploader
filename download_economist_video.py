#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PlaywrightTimeoutError = TimeoutError


# ================= Fixed settings =================

# First run:
#   ./.venv/bin/python download_economist_video.py login
#
# Normal run after login:
#   ./.venv/bin/python download_economist_video.py download

DEFAULT_COMMAND = "download"

# Drum Tower defaults. The implementation below follows the media-internals
# method directly; it does not call any external skill script.
PODCAST_NAME = "Drum Tower"
ACAST_SHOW_ALIAS = "drumtower"
ACAST_SHOW_ID = "633ebf6dfc7f5a0012acdc97"
ACAST_METADATA_URL = (
    "https://shows.acast.com/drumtower/episodes/"
    "why-has-china-gone-quiet-on-north-koreas-nukes"
)
ECONOMIST_RUNTIME_DIR = "economist_runtime"
EPISODES_JSON = f"{ECONOMIST_RUNTIME_DIR}/drum_tower_episodes.json"
LEGACY_EPISODES_JSON = f"{ECONOMIST_RUNTIME_DIR}/drum_tower_episodes_2026-06-22.json"
MEDIA_LOG_GLOB = "/Users/roy/Downloads/media-internals*.txt"
USE_MEDIA_INTERNALS_LOGS = True
AUTO_CAPTURE_MISSING_URLS = True
SIGNED_MEDIA_URLS_FILE = f"{ECONOMIST_RUNTIME_DIR}/signed_media_urls.json"

# Put exact episode URLs here. If this list is not empty, the script downloads
# these URLs and ignores COLLECTION_URL discovery.
TARGET_URLS: list[str] = [
    # "https://www.economist.com/...",
]

# Podcast list page. When TARGET_URLS is empty, the script opens this page and
# discovers dated episode URLs in page order.
COLLECTION_URL = "https://www.economist.com/audio/podcasts/drum-tower"

# Collection discovery controls. START_DATE accepts "YYYY-MM-DD" or "".
START_DATE = "2026-01-01"
MAX_ITEMS = 20
REQUIRE_DATE_FOR_COLLECTION_ITEMS = True
COLLECTION_LINK_RE = r"^https://www\.economist\.com/audio/podcasts/drum-tower/"

# Login/session file. This is intentionally separate from auth/eudic_auth.json.
AUTH_FILE = "auth/economist_auth.json"
LOGIN_URL = COLLECTION_URL

# Output and runtime behavior.
RSS_DOWNLOAD_ROOT = "rss_download"
OUTPUT_DIR = f"{RSS_DOWNLOAD_ROOT}/{PODCAST_NAME}"
CLEAR_RSS_DOWNLOAD_BEFORE_ECONOMIST = True
BROWSER_CHANNEL = "chrome"
HEADLESS_DISCOVER = False
HEADLESS_DOWNLOAD = False
MUTE_BROWSER_AUDIO = True
SLOW_MO_MS = 150
NAVIGATION_TIMEOUT_MS = 60_000
NETWORK_IDLE_TIMEOUT_MS = 15_000
CAPTURE_SECONDS = 30
SCROLL_STEPS = 4
ECONOMIST_LOAD_MORE_CLICKS = 6
OVERWRITE_EXISTING = False
MAX_DOWNLOAD_SECONDS = 600

# Media preference: "auto", "video", or "audio".
PREFERRED_MEDIA = "audio"

# For HLS/m3u8 streams, ffmpeg is required. Browser cookies are not passed to
# ffmpeg unless INCLUDE_COOKIES_FOR_FFMPEG is enabled.
INCLUDE_COOKIES_FOR_FFMPEG = False

# Keep this true while tuning selectors. The file redacts signed URLs.
SAVE_DEBUG_CANDIDATES = True
DEBUG_CANDIDATES_FILE = "logs/economist_media_candidates.json"

# Playwright browser path follows the existing project convention.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser("~/.playwright_browsers")


MEDIA_EXTENSIONS = (".m3u8", ".mp4", ".m4v", ".mov", ".mp3", ".m4a", ".aac", ".webm")
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac")
VIDEO_EXTENSIONS = (".m3u8", ".mp4", ".m4v", ".mov", ".webm")
MEDIA_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/",
    "video/",
)
ACAST_MEDIA_URL_RE = re.compile(r'https://sphinx\.acast\.com[^"\s]+')
ACAST_GUID_RE = re.compile(r"/e/([^/]+)/media\.mp3")
ACAST_EPISODE_RE = re.compile(
    r'\{"title":"(?P<title>(?:[^"\\]|\\.)*)",'
    r'"alias":"(?P<alias>[^"]+)",'
    rf'"show":"{re.escape(ACAST_SHOW_ID)}".*?'
    r'"publishDate":"(?P<publish_date>[^"]+)".*?'
    r'"_id":"(?P<guid>[^"]+)"\}'
)

_RSS_DOWNLOAD_CLEARED_THIS_RUN = False


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def clear_rss_download_before_economist() -> None:
    global _RSS_DOWNLOAD_CLEARED_THIS_RUN

    if not CLEAR_RSS_DOWNLOAD_BEFORE_ECONOMIST or _RSS_DOWNLOAD_CLEARED_THIS_RUN:
        return

    root = Path(RSS_DOWNLOAD_ROOT)
    if root.exists() and not root.is_dir():
        raise SystemExit(f"{root} exists but is not a directory.")

    root.mkdir(parents=True, exist_ok=True)
    print(f"Clearing {root}/ before Economist download.")
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    _RSS_DOWNLOAD_CLEARED_THIS_RUN = True


def print_download_folder_status() -> None:
    root = Path(RSS_DOWNLOAD_ROOT)
    output_dir = Path(OUTPUT_DIR)

    print("\n=== rss_download before download ===")
    if not root.exists():
        print(f"{root}/ does not exist yet; creating {output_dir}/")
        output_dir.mkdir(parents=True, exist_ok=True)
        print("====================================\n")
        return

    if not root.is_dir():
        raise SystemExit(f"{root} exists but is not a directory.")

    folders = sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))
    total_mp3 = 0
    total_media = 0
    total_size = 0

    print(f"Root: {root.resolve()}")
    if not folders:
        print(f"{root}/ exists but has no channel folders.")
    else:
        print(f"Channel folders: {len(folders)}")
        for folder in folders:
            mp3_count = len(list(folder.glob("*.mp3")))
            media_files = [
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
            ]
            media_count = len(media_files)
            media_size = sum(path.stat().st_size for path in media_files)
            total_mp3 += mp3_count
            total_media += media_count
            total_size += media_size
            print(
                f"- {folder.name}: {mp3_count} mp3, "
                f"{media_count} media files, {format_bytes(media_size)}"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(output_dir.glob("*.mp3"))
    print(
        f"Total media under rss_download: {total_mp3} mp3, "
        f"{total_media} media files, {format_bytes(total_size)}"
    )
    print(f"Target: {output_dir}/ ({len(existing)} existing mp3 files)")
    if existing:
        for path in existing[-5:]:
            print(f"  existing: {path.name}")
    print("====================================\n")


def require_playwright():
    global PlaywrightTimeoutError

    try:
        from playwright.sync_api import TimeoutError as ImportedTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Python package 'playwright' is not installed in this interpreter. "
            "Use the project virtualenv, for example: "
            "./.venv/bin/python download_economist_video.py login"
        ) from exc

    PlaywrightTimeoutError = ImportedTimeoutError
    return sync_playwright


def launch_browser(playwright, *, headless: bool, slow_mo: int = 0):
    browser_args = ["--mute-audio"] if MUTE_BROWSER_AUDIO else []
    kwargs = {"headless": headless, "slow_mo": slow_mo, "args": browser_args}
    if BROWSER_CHANNEL:
        try:
            return playwright.chromium.launch(channel=BROWSER_CHANNEL, **kwargs)
        except Exception as exc:
            print(f"Could not launch browser channel {BROWSER_CHANNEL!r}: {exc}")
            print("Falling back to Playwright Chromium.")
    return playwright.chromium.launch(**kwargs)


@dataclass
class TargetItem:
    url: str
    title: str = ""
    date: str = ""
    guid: str = ""


@dataclass
class MediaCandidate:
    url: str
    source: str
    resource_type: str = ""
    content_type: str = ""
    headers: dict[str, str] | None = None
    score: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Economist media using a saved Playwright login state."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["login", "discover", "download"],
        default=DEFAULT_COMMAND,
        help="login saves auth/economist_auth.json; discover lists targets; download saves media.",
    )
    parser.add_argument(
        "max_items",
        nargs="?",
        type=int,
        help="Optional temporary MAX_ITEMS override for discover/download, e.g. download 30.",
    )
    parser.add_argument(
        "--max-items",
        dest="max_items_flag",
        type=int,
        help="Optional temporary MAX_ITEMS override for discover/download.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Optional one-off URL override. Can be passed multiple times.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser during download/discovery.",
    )
    return parser.parse_args()


def resolve_max_items_override(*values: int | None) -> int | None:
    provided = [value for value in values if value is not None]
    if not provided:
        return None
    if len(set(provided)) > 1:
        raise SystemExit("Conflicting MAX_ITEMS overrides were provided.")

    value = provided[0]
    if value <= 0:
        raise SystemExit("MAX_ITEMS override must be a positive integer.")
    return value


def normalize_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    if match:
        return match.group(0)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def date_from_url(url: str) -> str:
    match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", urllib.parse.urlparse(url).path)
    if not match:
        return ""
    return "-".join(match.groups())


def file_date(value: str) -> str:
    normalized = normalize_date(value)
    return normalized.replace("-", "") if normalized else ""


def clean_episode_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = title.replace("’", "'").replace("‘", "'")
    title = re.sub(r"^listen\s+\d{1,2}:\d{2}(?::\d{2})?\s*[-:]\s*", "", title, flags=re.I)
    title = re.sub(r"\s*\|\s*The Economist\s*$", "", title).strip()
    return title


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:"*?<>|]+', "", name).strip()
    return re.sub(r"\s+", "-", name)


def safe_filename(value: str, fallback: str = "economist-media") -> str:
    value = sanitize_filename(clean_episode_title(value))
    return value[:160] or fallback


def decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def date_from_filename(path: str) -> str:
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", path)
    if not match:
        return ""
    return "-".join(match.groups())


def load_acast_episode_metadata_from_url(url: str) -> dict[str, TargetItem]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Eudic-listen-sync)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="ignore")

    episodes: dict[str, TargetItem] = {}
    for match in ACAST_EPISODE_RE.finditer(html):
        guid = match.group("guid").strip()
        alias = match.group("alias").strip()
        title = clean_episode_title(decode_json_string(match.group("title")))
        date = normalize_date(match.group("publish_date"))
        url = f"https://shows.acast.com/drumtower/episodes/{alias}"
        episodes[guid] = TargetItem(url=url, title=title, date=date, guid=guid)
    return episodes


def target_from_acast_episode(item: dict) -> TargetItem | None:
    guid = str(item.get("_id", "")).strip()
    alias = str(item.get("alias", "")).strip()
    title = clean_episode_title(str(item.get("title", "")).strip())
    date = normalize_date(str(item.get("publishDate", "")).strip())
    if not guid or not title:
        return None
    url = f"https://shows.acast.com/{ACAST_SHOW_ALIAS}/episodes/{alias}" if alias else ""
    return TargetItem(url=url, title=title, date=date, guid=guid)


def load_acast_episode_metadata_from_api() -> dict[str, TargetItem]:
    episodes: dict[str, TargetItem] = {}
    page = 1
    total = None

    while len(episodes) < MAX_ITEMS:
        url = (
            f"https://shows.acast.com/api/shows/{ACAST_SHOW_ALIAS}/episodes"
            f"?paginate=true&page={page}"
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Eudic-listen-sync)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))

        info = payload.get("info", {})
        total = int(info.get("total") or total or 0)
        results = payload.get("results") or []
        if not results:
            break

        for raw in results:
            item = target_from_acast_episode(raw)
            if item and item.guid not in episodes:
                episodes[item.guid] = item
            if len(episodes) >= MAX_ITEMS:
                break

        if total and len(episodes) >= total:
            break
        page += 1

    return episodes


def load_acast_episode_metadata() -> dict[str, TargetItem]:
    try:
        return load_acast_episode_metadata_from_api()
    except Exception:
        return load_acast_episode_metadata_from_url(ACAST_METADATA_URL)


def load_episode_order_from_json(path: str) -> list[TargetItem]:
    json_path = Path(path)
    if not json_path.exists():
        return []

    fallback_date = date_from_filename(str(json_path))
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [{"guid": guid, "title": title} for guid, title in data.items()]

    episodes: list[TargetItem] = []
    for item in data:
        guid = str(item.get("guid", "")).strip()
        title = clean_episode_title(str(item.get("title", "")).strip())
        date = normalize_date(str(item.get("date", "")).strip()) or fallback_date
        url = str(item.get("url", "")).strip()
        if guid and title:
            episodes.append(TargetItem(url=url, title=title, date=date, guid=guid))
    return episodes


def load_episode_seed_items() -> list[TargetItem]:
    seeds: list[TargetItem] = []
    seen: set[str] = set()
    for path in [EPISODES_JSON, LEGACY_EPISODES_JSON]:
        for item in load_episode_order_from_json(path):
            if item.guid and item.guid not in seen:
                seeds.append(item)
                seen.add(item.guid)
    return seeds


def save_episode_json(episodes: list[TargetItem]) -> None:
    path = Path(EPISODES_JSON)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "date": item.date,
            "guid": item.guid,
            "title": item.title,
            "url": item.url,
        }
        for item in episodes
    ]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Regenerated episode metadata: {path}")


def load_drum_tower_episodes(*, regenerate_json: bool = True) -> list[TargetItem]:
    try:
        metadata = load_acast_episode_metadata()
        print(f"Loaded Acast metadata for {len(metadata)} Drum Tower episodes.")
    except Exception as exc:
        metadata = {}
        print(f"Could not load Acast metadata, using local episode JSON only: {type(exc).__name__}")

    seed_items = load_episode_seed_items()
    try:
        urls_by_guid, _ = extract_media_urls_from_logs()
        seed_items.extend(
            TargetItem(url="", title="", date="", guid=guid)
            for guid in urls_by_guid
            if guid and guid not in metadata
        )
    except Exception:
        pass

    missing_metadata = [item.guid for item in seed_items if item.guid and item.guid not in metadata]
    for guid in missing_metadata:
        try:
            metadata.update(
                load_acast_episode_metadata_from_url(
                    f"https://shows.acast.com/drumtower/episodes/{guid}"
                )
            )
        except Exception:
            pass

    start_date = normalize_date(START_DATE)
    candidates_by_guid: dict[str, TargetItem] = {}
    for episode in [*metadata.values(), *seed_items]:
        if not episode.guid:
            continue
        meta = metadata.get(episode.guid)
        candidates_by_guid[episode.guid] = TargetItem(
            url=episode.url or (meta.url if meta else ""),
            title=episode.title or (meta.title if meta else ""),
            date=(meta.date if meta and meta.date else episode.date),
            guid=episode.guid,
        )

    merged = []
    for episode in candidates_by_guid.values():
        if start_date and episode.date and episode.date < start_date:
            continue
        if episode.title:
            merged.append(episode)

    merged.sort(key=lambda item: (item.date, item.title), reverse=True)
    merged = merged[:MAX_ITEMS]

    if regenerate_json:
        save_episode_json(merged)

    return merged


def load_drum_tower_episodes_from_json() -> list[TargetItem]:
    episodes = load_episode_order_from_json(EPISODES_JSON)
    if episodes:
        return episodes[:MAX_ITEMS]

    # Bootstrap path for older checkouts before the runtime folder exists.
    return load_drum_tower_episodes(regenerate_json=True)


def normalize_media_url(raw: str) -> str:
    return raw.replace("&amp;", "&").rstrip(".,;)")


def extract_media_urls_from_logs() -> tuple[dict[str, str], list[Path]]:
    paths = [Path(path) for path in glob.glob(MEDIA_LOG_GLOB)]
    paths.sort(key=lambda path: path.stat().st_mtime)
    urls_by_guid: dict[str, str] = {}

    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in ACAST_MEDIA_URL_RE.finditer(text):
            url = normalize_media_url(match.group(0))
            guid_match = ACAST_GUID_RE.search(url)
            if guid_match:
                urls_by_guid[guid_match.group(1)] = url
    return urls_by_guid, paths


def load_cached_signed_media_urls() -> dict[str, str]:
    path = Path(SIGNED_MEDIA_URLS_FILE)
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    urls_by_guid: dict[str, str] = {}
    for guid, url in data.items():
        guid = str(guid).strip()
        url = normalize_media_url(str(url).strip())
        if guid and ACAST_GUID_RE.search(url):
            urls_by_guid[guid] = url
    return urls_by_guid


def save_cached_signed_media_urls(urls_by_guid: dict[str, str]) -> None:
    path = Path(SIGNED_MEDIA_URLS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        guid: url
        for guid, url in sorted(urls_by_guid.items())
        if guid and ACAST_GUID_RE.search(url)
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_signed_media_urls() -> tuple[dict[str, str], list[Path], int]:
    cached_urls = load_cached_signed_media_urls()
    log_urls, log_paths = extract_media_urls_from_logs()

    # Prefer media-internals logs when present because they are usually fresher.
    urls_by_guid = dict(cached_urls)
    urls_by_guid.update(log_urls)
    return urls_by_guid, log_paths, len(cached_urls)


def extension_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in MEDIA_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ""


def output_extension(candidate: MediaCandidate) -> str:
    ext = extension_from_url(candidate.url)
    content_type = candidate.content_type.lower()
    if PREFERRED_MEDIA == "audio" and (ext in AUDIO_EXTENSIONS or content_type.startswith("audio/")):
        return ".mp3" if ext in {"", ".mpga"} else ext
    if ext == ".m3u8" or "mpegurl" in content_type:
        return ".mp4"
    if ext:
        return ext
    if content_type.startswith("audio/"):
        return ".mp3"
    return ".mp4"


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    ext = extension_from_url(url) or "media"
    return f"{parsed.scheme}://{parsed.netloc}/.../*{ext}#sha256={digest}"


def is_probable_media_url(url: str, content_type: str = "", resource_type: str = "") -> bool:
    if not url or url.startswith("blob:") or url.startswith("data:"):
        return False
    lower_url = url.lower()
    lower_type = content_type.lower()
    if any(ext in urllib.parse.urlparse(lower_url).path for ext in MEDIA_EXTENSIONS):
        return True
    if any(kind in lower_type for kind in MEDIA_CONTENT_TYPES):
        return True
    return resource_type == "media"


def score_candidate(url: str, content_type: str = "", resource_type: str = "") -> int:
    path = urllib.parse.urlparse(url).path.lower()
    lower_type = content_type.lower()
    score = 0

    if ".m3u8" in path or "mpegurl" in lower_type:
        score += 95
    elif path.endswith((".mp4", ".m4v", ".mov", ".webm")) or lower_type.startswith("video/"):
        score += 100
    elif path.endswith(AUDIO_EXTENSIONS) or lower_type.startswith("audio/"):
        score += 80
    elif resource_type == "media":
        score += 50

    if PREFERRED_MEDIA == "video":
        if path.endswith(VIDEO_EXTENSIONS) or lower_type.startswith("video/") or "mpegurl" in lower_type:
            score += 20
        if path.endswith(AUDIO_EXTENSIONS) or lower_type.startswith("audio/"):
            score -= 25
    elif PREFERRED_MEDIA == "audio":
        if path.endswith(AUDIO_EXTENSIONS) or lower_type.startswith("audio/"):
            score += 20
        if path.endswith(VIDEO_EXTENSIONS) or lower_type.startswith("video/"):
            score -= 10

    if any(token in url.lower() for token in ("segment", "/seg-", ".ts?")):
        score -= 35

    return score


def remember_candidate(
    candidates: dict[str, MediaCandidate],
    url: str,
    source: str,
    resource_type: str = "",
    content_type: str = "",
    headers: dict[str, str] | None = None,
) -> None:
    if not is_probable_media_url(url, content_type=content_type, resource_type=resource_type):
        return
    score = score_candidate(url, content_type=content_type, resource_type=resource_type)
    previous = candidates.get(url)
    if previous is None or score > previous.score:
        candidates[url] = MediaCandidate(
            url=url,
            source=source,
            resource_type=resource_type,
            content_type=content_type,
            headers=headers or {},
            score=score,
        )
        print(
            f"  captured media candidate: source={source}, "
            f"type={content_type or resource_type or '-'}, score={score}"
        )


def attach_media_capture_to_event_source(event_source, candidates: dict[str, MediaCandidate]) -> None:
    def on_request(request) -> None:
        try:
            remember_candidate(
                candidates,
                request.url,
                source="request",
                resource_type=request.resource_type,
                headers=dict(request.headers),
            )
        except Exception:
            pass

    def on_response(response) -> None:
        try:
            content_type = response.headers.get("content-type", "")
            remember_candidate(
                candidates,
                response.url,
                source="response",
                resource_type=response.request.resource_type,
                content_type=content_type,
                headers=dict(response.request.headers),
            )
        except Exception:
            pass

    event_source.on("request", on_request)
    event_source.on("response", on_response)


def attach_media_capture(page, candidates: dict[str, MediaCandidate]) -> None:
    attach_media_capture_to_event_source(page, candidates)


def attach_context_media_capture(context, candidates: dict[str, MediaCandidate]) -> None:
    attach_media_capture_to_event_source(context, candidates)


def maybe_wait_network_idle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass


def click_cookie_prompts(page) -> None:
    patterns = [
        r"accept all",
        r"accept",
        r"agree",
        r"allow all",
        r"continue",
        r"got it",
    ]
    for pattern in patterns:
        try:
            button = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            button.click(timeout=1_500)
            page.wait_for_timeout(500)
            return
        except Exception:
            continue


def scroll_page(page, steps: int = SCROLL_STEPS) -> None:
    for _ in range(max(0, steps)):
        page.evaluate("window.scrollBy(0, Math.max(window.innerHeight, 900))")
        page.wait_for_timeout(700)


def click_play_controls(page) -> None:
    patterns = [
        r"^play$",
        r"play video",
        r"watch",
        r"listen",
        r"start",
        r"resume",
    ]
    clicked = False

    for pattern in patterns:
        try:
            control = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            control.click(timeout=2_000)
            print(f"  clicked playback control matching: {pattern}")
            page.wait_for_timeout(1_500)
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        selectors = [
            "button[aria-label*='Play']",
            "[role='button'][aria-label*='Play']",
            "button:has-text('Play')",
            "button:has-text('Listen')",
            "button:has-text('Watch')",
            "video",
            "audio",
        ]
        for selector in selectors:
            try:
                page.locator(selector).first.click(timeout=2_000)
                print(f"  clicked playback selector: {selector}")
                page.wait_for_timeout(1_500)
                clicked = True
                break
            except Exception:
                continue

    try:
        count = page.evaluate(
            """() => {
                const nodes = Array.from(document.querySelectorAll('video,audio'));
                for (const node of nodes) {
                    try {
                        node.muted = true;
                        const result = node.play && node.play();
                        if (result && result.catch) result.catch(() => {});
                    } catch (_) {}
                }
                return nodes.length;
            }"""
        )
        if count:
            print(f"  asked {count} html media element(s) to play")
    except Exception:
        pass


def guid_from_media_url(url: str) -> str:
    match = ACAST_GUID_RE.search(url)
    return match.group(1) if match else ""


def find_candidate_for_guid(
    candidates: dict[str, MediaCandidate], guid: str
) -> MediaCandidate | None:
    matches = [
        candidate
        for candidate in candidates.values()
        if guid_from_media_url(candidate.url) == guid
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda candidate: candidate.score, reverse=True)[0]


def wait_for_candidate_guid(page, candidates: dict[str, MediaCandidate], guid: str) -> MediaCandidate | None:
    deadline = time.monotonic() + CAPTURE_SECONDS
    while time.monotonic() < deadline:
        candidate = find_candidate_for_guid(candidates, guid)
        if candidate:
            return candidate
        page.wait_for_timeout(1_000)
    return find_candidate_for_guid(candidates, guid)


def build_episode_mp3_path(episode: TargetItem) -> Path:
    filename = f"{file_date(episode.date)}-{safe_filename(episode.title)}.mp3"
    return Path(OUTPUT_DIR) / filename.lstrip("-")


def episode_needs_download(episode: TargetItem) -> bool:
    return OVERWRITE_EXISTING or not build_episode_mp3_path(episode).exists()


def extract_page_metadata(page, fallback: TargetItem) -> TargetItem:
    title = fallback.title
    date = fallback.date or date_from_url(fallback.url)

    if not title:
        for selector in ["h1", "[data-testid='headline']", "article h1"]:
            try:
                text = page.locator(selector).first.text_content(timeout=2_000)
                if text and text.strip():
                    title = text.strip()
                    break
            except Exception:
                continue
    if not title:
        try:
            title = page.title()
        except Exception:
            title = fallback.url
    title = clean_episode_title(title)

    if not date:
        try:
            raw_date = page.locator("time[datetime]").first.get_attribute(
                "datetime", timeout=2_000
            )
            date = normalize_date(raw_date or "")
        except Exception:
            date = ""

    return TargetItem(url=fallback.url, title=title, date=date)


def build_output_path(item: TargetItem, candidate: MediaCandidate) -> Path:
    ext = output_extension(candidate)
    datepart = file_date(item.date)
    prefix = f"{datepart}-" if datepart else ""
    filename = f"{prefix}{safe_filename(item.title)}{ext}"
    return Path(OUTPUT_DIR) / filename


def filtered_download_headers(candidate: MediaCandidate, context, page_url: str) -> dict[str, str]:
    raw_headers = {k.lower(): v for k, v in (candidate.headers or {}).items()}
    headers: dict[str, str] = {}
    for name in ["user-agent", "accept", "referer", "origin"]:
        if raw_headers.get(name):
            headers[name.title()] = raw_headers[name]

    headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "Chrome/120.0.0.0 Safari/537.36",
    )
    headers.setdefault("Referer", page_url)

    try:
        cookies = context.cookies([candidate.url])
    except Exception:
        cookies = []
    if cookies:
        headers["Cookie"] = "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies)
    return headers


def download_direct(candidate: MediaCandidate, destination: Path, headers: dict[str, str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(candidate.url, headers=headers)
    print(f"  downloading direct file -> {destination.name}")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with open(temp_path, "wb") as out:
                while True:
                    chunk = response.read(1024 * 512)
                    if not chunk:
                        break
                    out.write(chunk)
        temp_path.replace(destination)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def ffmpeg_headers_arg(headers: dict[str, str]) -> str:
    allowed = ["User-Agent", "Referer", "Origin", "Accept"]
    if INCLUDE_COOKIES_FOR_FFMPEG:
        allowed.append("Cookie")
    return "".join(f"{name}: {headers[name]}\r\n" for name in allowed if headers.get(name))


def download_hls(candidate: MediaCandidate, destination: Path, headers: dict[str, str]) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for m3u8/HLS downloads but was not found.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part.mp4")
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-headers",
        ffmpeg_headers_arg(headers),
        "-i",
        candidate.url,
        "-c",
        "copy",
        str(temp_path),
    ]
    print(f"  downloading HLS stream with ffmpeg -> {destination.name}")
    try:
        subprocess.run(command, check=True)
        temp_path.replace(destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def download_candidate(candidate: MediaCandidate, destination: Path, headers: dict[str, str]) -> None:
    if destination.exists() and not OVERWRITE_EXISTING:
        print(f"  exists, skipping: {destination}")
        return

    content_type = candidate.content_type.lower()
    url_path = urllib.parse.urlparse(candidate.url).path.lower()
    if ".m3u8" in url_path or "mpegurl" in content_type:
        download_hls(candidate, destination, headers)
    else:
        download_direct(candidate, destination, headers)


def choose_candidate(candidates: dict[str, MediaCandidate]) -> MediaCandidate | None:
    if not candidates:
        return None
    ordered = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
    return ordered[0]


def save_debug_candidates(
    item: TargetItem, candidates: dict[str, MediaCandidate], selected: MediaCandidate | None
) -> None:
    if not SAVE_DEBUG_CANDIDATES:
        return
    path = Path(DEBUG_CANDIDATES_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []

    existing.append(
        {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "page": item.url,
            "title": item.title,
            "selected": redact_url(selected.url) if selected else None,
            "candidates": [
                {
                    "url": redact_url(candidate.url),
                    "source": candidate.source,
                    "resource_type": candidate.resource_type,
                    "content_type": candidate.content_type,
                    "score": candidate.score,
                }
                for candidate in sorted(
                    candidates.values(), key=lambda value: value.score, reverse=True
                )
            ],
        }
    )
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_targets(context, override_urls: list[str] | None = None) -> list[TargetItem]:
    if override_urls:
        return [TargetItem(url=url) for url in override_urls]

    if TARGET_URLS:
        return [TargetItem(url=url) for url in TARGET_URLS]

    if not COLLECTION_URL:
        raise SystemExit(
            "No targets configured. Set TARGET_URLS or COLLECTION_URL at the top of "
            "download_economist_video.py."
        )

    start_date = normalize_date(START_DATE)
    page = context.new_page()
    try:
        print(f"Opening collection page: {COLLECTION_URL}")
        page.goto(COLLECTION_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        maybe_wait_network_idle(page)
        click_cookie_prompts(page)
        scroll_page(page)

        raw_items = page.evaluate(
            """() => {
                const out = [];
                for (const a of document.querySelectorAll('a[href]')) {
                    let url;
                    try {
                        url = new URL(a.getAttribute('href'), location.href).href;
                    } catch (_) {
                        continue;
                    }
                    const container = a.closest('article, li, section, div');
                    const timeNode = container && container.querySelector('time[datetime], time');
                    const titleNode = container && container.querySelector('h1, h2, h3, [data-testid*="headline"]');
                    const title = (
                        (titleNode && (titleNode.innerText || titleNode.textContent)) ||
                        (a.innerText || a.textContent) ||
                        ''
                    ).trim();
                    out.push({
                        url,
                        title,
                        date: timeNode ? (timeNode.getAttribute('datetime') || timeNode.textContent || '') : ''
                    });
                }
                return out;
            }"""
        )
    finally:
        page.close()

    link_re = re.compile(COLLECTION_LINK_RE) if COLLECTION_LINK_RE else None
    seen: set[str] = set()
    items: list[TargetItem] = []
    for raw in raw_items:
        url = raw.get("url", "").split("#", 1)[0]
        if not url or url in seen or url.rstrip("/") == COLLECTION_URL.rstrip("/"):
            continue
        if link_re and not link_re.search(url):
            continue

        date = normalize_date(raw.get("date", "")) or date_from_url(url)
        if REQUIRE_DATE_FOR_COLLECTION_ITEMS and not date:
            continue
        if start_date and date and date < start_date:
            continue

        title = clean_episode_title(raw.get("title", ""))
        seen.add(url)
        items.append(TargetItem(url=url, title=title, date=date))

        if len(items) >= MAX_ITEMS:
            break

    return items


def print_episode_list(items: list[TargetItem]) -> None:
    if not items:
        print("No target items found.")
        return
    for index, item in enumerate(items, start=1):
        label = " | ".join(
            part for part in [item.date, item.guid, item.title, item.url] if part
        )
        print(f"{index}. {label}")


def pause_page_media(page) -> None:
    try:
        page.evaluate(
            """() => {
                for (const node of document.querySelectorAll('audio,video')) {
                    try { node.pause(); } catch (_) {}
                }
            }"""
        )
    except Exception:
        pass


def click_economist_load_more(page) -> bool:
    try:
        page.get_by_role(
            "button",
            name=re.compile(r"load more podcast episodes", re.I),
        ).click(timeout=3_000)
        print("  clicked Load more podcast episodes")
        page.wait_for_timeout(1_500)
        maybe_wait_network_idle(page)
        return True
    except Exception:
        return False


def click_economist_episode_listen(page, episode: TargetItem) -> bool:
    try:
        label = page.evaluate(
            """(title) => {
                const normalize = (value) => (value || '')
                    .toLowerCase()
                    .replace(/[’‘]/g, "'")
                    .replace(/[“”]/g, '"')
                    .replace(/\\s+/g, ' ')
                    .trim();
                const wanted = normalize(title);
                const buttons = Array.from(document.querySelectorAll('button'));
                for (const button of buttons) {
                    const label = (
                        button.getAttribute('aria-label') ||
                        button.innerText ||
                        button.textContent ||
                        ''
                    );
                    const normalized = normalize(label);
                    if (!normalized.includes('listen') && !normalized.includes('play')) {
                        continue;
                    }
                    if (!normalized.includes(wanted)) {
                        continue;
                    }
                    button.scrollIntoView({block: 'center', inline: 'center'});
                    button.click();
                    return label.replace(/\\s+/g, ' ').trim();
                }
                return '';
            }""",
            episode.title,
        )
    except Exception:
        return False

    if not label:
        return False

    print(f"  clicked Economist playback button: {label[:140]}")
    page.wait_for_timeout(1_500)
    return True


def capture_from_economist_collection(
    context, episodes: list[TargetItem], candidates: dict[str, MediaCandidate]
) -> dict[str, str]:
    captured: dict[str, str] = {}
    if not episodes:
        return captured

    print(f"Opening Economist collection page: {COLLECTION_URL}")
    page = context.new_page()
    try:
        page.goto(COLLECTION_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        maybe_wait_network_idle(page)
        click_cookie_prompts(page)

        for index, episode in enumerate(episodes, start=1):
            print(f"[economist capture {index}/{len(episodes)}] {episode.title}")
            candidate = find_candidate_for_guid(candidates, episode.guid)
            if candidate is not None:
                captured[episode.guid] = candidate.url
                print("  already captured matching playback URL.")
                continue

            clicked = click_economist_episode_listen(page, episode)
            load_more_clicks = 0
            while not clicked and load_more_clicks < ECONOMIST_LOAD_MORE_CLICKS:
                if not click_economist_load_more(page):
                    break
                load_more_clicks += 1
                clicked = click_economist_episode_listen(page, episode)

            if not clicked:
                print("  Economist playback button not found on loaded page.")
                continue

            candidate = wait_for_candidate_guid(page, candidates, episode.guid)
            if candidate is None:
                print("  no matching playback URL captured from Economist page.")
                continue

            captured[episode.guid] = candidate.url
            print("  captured matching playback URL from Economist page.")
            pause_page_media(page)
    finally:
        pause_page_media(page)
        page.close()

    return captured


def capture_from_acast_episode_pages(
    context, episodes: list[TargetItem], candidates: dict[str, MediaCandidate]
) -> dict[str, str]:
    captured: dict[str, str] = {}
    for index, episode in enumerate(episodes, start=1):
        target_url = (
            episode.url
            or f"https://shows.acast.com/{ACAST_SHOW_ALIAS}/episodes/{episode.guid}"
        )
        print(f"[acast capture {index}/{len(episodes)}] {episode.title}")
        print(f"  opening playback page: {target_url}")
        page = context.new_page()
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            maybe_wait_network_idle(page)
            click_cookie_prompts(page)
            click_play_controls(page)

            candidate = wait_for_candidate_guid(page, candidates, episode.guid)
            if candidate is None:
                scroll_page(page, steps=2)
                click_play_controls(page)
                candidate = wait_for_candidate_guid(page, candidates, episode.guid)

            if candidate is None:
                print("  no matching playback URL captured from Acast page.")
                continue

            captured[episode.guid] = candidate.url
            print("  captured matching playback URL from Acast page.")
        finally:
            pause_page_media(page)
            page.close()
    return captured


def capture_missing_media_urls(
    episodes: list[TargetItem], *, show_browser: bool = False
) -> dict[str, str]:
    episodes = [episode for episode in episodes if episode.guid]
    if not episodes:
        return {}

    print(f"\nAuto-capturing playback URLs for {len(episodes)} episode(s).")
    if not Path(AUTH_FILE).exists():
        print(f"  {AUTH_FILE} not found; trying public playback pages without saved login.")

    sync_playwright = require_playwright()
    captured: dict[str, str] = {}
    all_candidates: dict[str, MediaCandidate] = {}

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            headless=not show_browser and HEADLESS_DOWNLOAD,
            slow_mo=SLOW_MO_MS if show_browser else 0,
        )
        context = browser.new_context(storage_state=AUTH_FILE if Path(AUTH_FILE).exists() else None)
        attach_context_media_capture(context, all_candidates)

        try:
            captured.update(capture_from_economist_collection(context, episodes, all_candidates))
            remaining = [episode for episode in episodes if episode.guid not in captured]
            if remaining:
                print(
                    f"\nEconomist page did not yield {len(remaining)} URL(s); "
                    "trying Acast episode pages as fallback."
                )
                captured.update(capture_from_acast_episode_pages(context, remaining, all_candidates))
        finally:
            browser.close()

    if captured:
        cached = load_cached_signed_media_urls()
        cached.update(captured)
        save_cached_signed_media_urls(cached)
        print(
            f"Saved {len(captured)} captured playback URL(s) to "
            f"{SIGNED_MEDIA_URLS_FILE}."
        )

    return captured


def download_episode_from_signed_url(
    episode: TargetItem, url: str, *, source: str
) -> bool:
    destination = build_episode_mp3_path(episode)
    if destination.exists() and not OVERWRITE_EXISTING:
        print(f"exists, skipping: {destination.name}")
        return True

    candidate = MediaCandidate(
        url=url,
        source=source,
        content_type="audio/mpeg",
        score=100,
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
    print(f"downloading: {destination.name}")
    try:
        download_direct(candidate, destination, headers)
    except Exception as exc:
        print(f"  failed: {destination.name} ({type(exc).__name__})")
        return False
    return True


def run_download_from_media_logs(*, show_browser: bool = False) -> None:
    print_download_folder_status()

    episodes = load_drum_tower_episodes()
    if not episodes:
        raise SystemExit(f"No episodes found. Check {EPISODES_JSON} and Acast metadata.")

    urls_by_guid, log_paths, cached_count = collect_signed_media_urls()

    if log_paths:
        print(f"Using {len(log_paths)} media-internals log file(s):")
        for path in log_paths:
            print(f"  {path}")
    else:
        print(f"No media-internals logs matched {MEDIA_LOG_GLOB}.")
    if cached_count:
        print(f"Loaded {cached_count} cached playback URL(s) from {SIGNED_MEDIA_URLS_FILE}.")
    print(f"Found playback URLs for {len(urls_by_guid)} Acast GUID(s).")

    missing_before_download = [
        episode
        for episode in episodes
        if episode_needs_download(episode) and not urls_by_guid.get(episode.guid)
    ]
    if missing_before_download and AUTO_CAPTURE_MISSING_URLS:
        captured_urls = capture_missing_media_urls(
            missing_before_download,
            show_browser=show_browser,
        )
        urls_by_guid.update(captured_urls)

    missing: list[TargetItem] = []
    failed: list[TargetItem] = []
    for index, episode in enumerate(episodes, start=1):
        destination = build_episode_mp3_path(episode)
        if destination.exists() and not OVERWRITE_EXISTING:
            print(f"[{index}/{len(episodes)}] exists, skipping: {destination.name}")
            continue

        url = urls_by_guid.get(episode.guid)
        if not url:
            print(f"[{index}/{len(episodes)}] missing signed URL: {episode.title} ({episode.guid})")
            missing.append(episode)
            continue

        print(f"[{index}/{len(episodes)}] ", end="")
        if not download_episode_from_signed_url(episode, url, source="playback-url"):
            failed.append(episode)

    if failed and AUTO_CAPTURE_MISSING_URLS:
        print("\nRefreshing playback URLs for failed download(s), then retrying once.")
        refreshed_urls = capture_missing_media_urls(failed, show_browser=show_browser)
        urls_by_guid.update(refreshed_urls)
        still_failed: list[TargetItem] = []
        for episode in failed:
            refreshed_url = refreshed_urls.get(episode.guid)
            if not refreshed_url:
                still_failed.append(episode)
                continue
            print("[retry] ", end="")
            if not download_episode_from_signed_url(
                episode, refreshed_url, source="refreshed-playback-url"
            ):
                still_failed.append(episode)
        failed = still_failed

    if missing:
        print("\nMissing signed URLs:")
        for episode in missing:
            print(f"  - {episode.title} ({episode.guid})")
        print(
            "The script could not capture playback URLs for those episodes. "
            "Run with --headed to watch the browser and confirm playback starts."
        )

    if failed:
        print("\nFailed downloads:")
        for episode in failed:
            print(f"  - {episode.title} ({episode.guid})")
        raise SystemExit(1)

    if missing:
        raise SystemExit(2)


def run_login() -> None:
    sync_playwright = require_playwright()
    print("Opening browser for Economist login.")
    print(f"After signing in, press Enter here to save {AUTH_FILE}.")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright, headless=False, slow_mo=SLOW_MO_MS)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            maybe_wait_network_idle(page)
            input("Press Enter after the Economist page is signed in and playable...")
            Path(AUTH_FILE).parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=AUTH_FILE)
            print(f"Saved login state: {AUTH_FILE}")
        finally:
            context.close()
            browser.close()


def run_discover(
    show_browser: bool,
    override_urls: list[str] | None = None,
    max_items: int | None = None,
) -> list[TargetItem]:
    global MAX_ITEMS

    previous_max_items = MAX_ITEMS
    if max_items is not None:
        MAX_ITEMS = max_items
        print(f"Using Economist MAX_ITEMS override for this run: {MAX_ITEMS}")

    if not override_urls:
        try:
            items = load_drum_tower_episodes()
            print_episode_list(items)
            return items
        finally:
            MAX_ITEMS = previous_max_items

    sync_playwright = require_playwright()
    try:
        with sync_playwright() as playwright:
            browser = launch_browser(
                playwright,
                headless=HEADLESS_DISCOVER and not show_browser,
                slow_mo=SLOW_MO_MS if show_browser else 0,
            )
            context = browser.new_context(storage_state=AUTH_FILE if Path(AUTH_FILE).exists() else None)
            try:
                items = discover_targets(context, override_urls=override_urls)
            finally:
                context.close()
                browser.close()

        print_episode_list(items)
        return items
    finally:
        MAX_ITEMS = previous_max_items


def run_download(
    show_browser: bool,
    override_urls: list[str] | None = None,
    max_items: int | None = None,
) -> None:
    global MAX_ITEMS

    previous_max_items = MAX_ITEMS
    if max_items is not None:
        MAX_ITEMS = max_items
        print(f"Using Economist MAX_ITEMS override for this run: {MAX_ITEMS}")

    try:
        clear_rss_download_before_economist()

        if USE_MEDIA_INTERNALS_LOGS and not override_urls:
            run_download_from_media_logs(show_browser=show_browser)
            return

        if not Path(AUTH_FILE).exists():
            raise SystemExit(
                f"Missing {AUTH_FILE}. Run: ./.venv/bin/python download_economist_video.py login"
            )

        print_download_folder_status()

        sync_playwright = require_playwright()
        with sync_playwright() as playwright:
            browser = launch_browser(
                playwright,
                headless=not show_browser and HEADLESS_DOWNLOAD,
                slow_mo=SLOW_MO_MS if show_browser else 0,
            )
            context = browser.new_context(storage_state=AUTH_FILE)
            try:
                targets = discover_targets(context, override_urls=override_urls)
                if not targets:
                    raise SystemExit("No target items found.")

                for index, target in enumerate(targets, start=1):
                    print(f"\n[{index}/{len(targets)}] Opening: {target.url}")
                    page = context.new_page()
                    candidates: dict[str, MediaCandidate] = {}
                    attach_media_capture(page, candidates)
                    try:
                        page.goto(
                            target.url,
                            wait_until="domcontentloaded",
                            timeout=NAVIGATION_TIMEOUT_MS,
                        )
                        maybe_wait_network_idle(page)
                        click_cookie_prompts(page)
                        item = extract_page_metadata(page, target)
                        print(f"  title: {item.title}")

                        click_play_controls(page)
                        print(f"  capturing media requests for {CAPTURE_SECONDS}s...")
                        page.wait_for_timeout(CAPTURE_SECONDS * 1000)

                        selected = choose_candidate(candidates)
                        save_debug_candidates(item, candidates, selected)
                        if selected is None:
                            print("  no media candidate found; try --headed and confirm playback starts.")
                            continue

                        destination = build_output_path(item, selected)
                        headers = filtered_download_headers(selected, context, target.url)
                        download_candidate(selected, destination, headers)
                        print(f"  saved: {destination}")
                    finally:
                        page.close()
            finally:
                context.close()
                browser.close()
    finally:
        MAX_ITEMS = previous_max_items


def main() -> int:
    args = parse_args()
    show_browser = args.headed or args.command == "login"
    override_urls = args.url or None
    max_items = resolve_max_items_override(args.max_items, args.max_items_flag)

    if args.command == "login":
        run_login()
    elif args.command == "discover":
        run_discover(show_browser=show_browser, override_urls=override_urls, max_items=max_items)
    elif args.command == "download":
        run_download(show_browser=show_browser, override_urls=override_urls, max_items=max_items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
