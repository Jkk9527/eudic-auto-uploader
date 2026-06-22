#!/usr/bin/env zsh
set -euo pipefail

script_dir="${0:A:h}"

exec python3 "$script_dir/download_from_media_log.py" \
  --feed-url "https://feeds.acast.com/public/shows/633ebf6dfc7f5a0012acdc97" \
  --log-glob "/Users/roy/Downloads/media-internals*.txt" \
  --out-dir "outputs" \
  --count 10 \
  --download \
  "$@"
