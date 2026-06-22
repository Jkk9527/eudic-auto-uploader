#!/usr/bin/env python3
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


URL_RE = re.compile(r'https://sphinx\.acast\.com[^"\s]+')
GUID_RE = re.compile(r"/e/([^/]+)/media\.mp3")
BAD_FILENAME_CHARS_RE = re.compile(r'[\\/*"<>|]+')


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download podcast MP3s by matching Acast RSS GUIDs to Chrome media-internals logs."
    )
    parser.add_argument("--feed-url", help="RSS feed URL used for title and GUID metadata.")
    parser.add_argument("--feed-file", help="Local RSS XML file. Overrides --feed-url.")
    parser.add_argument("--episodes-json", help="JSON file with a list of {guid,title} episodes.")
    parser.add_argument("--log-glob", default="/Users/roy/Downloads/media-internals*.txt")
    parser.add_argument("--out-dir", default="outputs")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-time", type=int, default=600)
    return parser.parse_args()


def text_or_empty(node):
    return "" if node is None or node.text is None else node.text.strip()


def load_feed_xml(args):
    if args.feed_file:
        return Path(args.feed_file).read_bytes()
    if not args.feed_url:
        raise SystemExit("Provide --feed-url, --feed-file, or --episodes-json.")
    request = urllib.request.Request(
        args.feed_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Codex podcast downloader)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def load_episodes(args):
    if args.episodes_json:
        data = json.loads(Path(args.episodes_json).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [{"guid": guid, "title": title} for guid, title in data.items()]
        return [
            {"guid": str(item["guid"]).strip(), "title": str(item["title"]).strip()}
            for item in data[: args.count]
        ]

    root = ET.fromstring(load_feed_xml(args))
    channel = root.find("channel")
    if channel is None:
        raise SystemExit("RSS feed has no channel element.")

    episodes = []
    for item in channel.findall("item"):
        title = text_or_empty(item.find("title"))
        guid = text_or_empty(item.find("guid"))
        if title and guid:
            episodes.append({"guid": guid, "title": title})
        if len(episodes) >= args.count:
            break
    return episodes


def normalize_url(raw):
    return raw.replace("&amp;", "&").rstrip(".,;)")


def extract_media_urls(log_glob):
    paths = [Path(p) for p in glob.glob(log_glob)]
    paths.sort(key=lambda p: p.stat().st_mtime)
    urls_by_guid = {}

    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in URL_RE.finditer(text):
            url = normalize_url(match.group(0))
            guid_match = GUID_RE.search(url)
            if guid_match:
                urls_by_guid[guid_match.group(1)] = url
    return urls_by_guid, paths


def safe_filename(title):
    name = title.replace(":", " - ").replace("?", "")
    name = BAD_FILENAME_CHARS_RE.sub("-", name)
    name = re.sub(r"\s*-\s*", " - ", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .-")
    if not name:
        name = "podcast"
    if not name.lower().endswith(".mp3"):
        name += ".mp3"
    return name


def download_with_curl(url, destination, max_time):
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "2",
            "--connect-timeout",
            "20",
            "--max-time",
            str(max_time),
            "-o",
            str(destination),
            url,
        ],
        check=True,
    )


def main():
    args = parse_args()
    if args.dry_run and args.download:
        raise SystemExit("Choose only one of --dry-run or --download.")
    if not args.dry_run and not args.download:
        args.dry_run = True

    episodes = load_episodes(args)
    urls_by_guid, log_paths = extract_media_urls(args.log_glob)
    if not log_paths:
        raise SystemExit(f"No media-internals logs matched: {args.log_glob}")

    out_dir = Path(args.out_dir)
    missing = []
    for episode in episodes:
        guid = episode["guid"]
        title = episode["title"]
        filename = safe_filename(title)
        url = urls_by_guid.get(guid)
        if not url:
            missing.append((guid, title))
            print(f"[missing] {title} ({guid})")
            continue

        destination = out_dir / filename
        if args.download:
            print(f"[download] {filename}")
            download_with_curl(url, destination, args.max_time)
        else:
            print(f"[ok] {filename} ({guid})")

    if missing:
        print(
            "\nMissing signed URLs. Trigger playback for those episodes, save a fresh "
            "chrome://media-internals log, then rerun.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
