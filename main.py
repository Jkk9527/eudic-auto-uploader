#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)


MODE_ALIASES = {
    "all": "all",
    "full": "all",
    "run": "all",
    "download": "download",
    "fetch": "download",
    "upload": "upload",
    "economist": "economist",
    "drum": "economist",
    "drum-tower": "economist",
    "drum_tower": "economist",
    "web": "web",
    "ui": "web",
    "streamlit": "web",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RSS 下载 / 上传入口。默认无参数执行：下载 + 上传。",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        help=(
            "运行模式，默认 all。\n"
            "可用: all, download/fetch, upload, economist/drum-tower, web/ui/streamlit。\n"
            "Economist 可追加数量，例如: economist 20"
        ),
    )
    parser.add_argument(
        "economist_count",
        nargs="?",
        help="Economist 临时下载数量，只在 command 为 economist/drum-tower 时生效。",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODE_ALIASES),
        help="用参数形式指定运行模式，例如 --mode web。",
    )
    parser.add_argument("--all", action="store_true", help="执行下载 + 上传。")
    parser.add_argument("--download-only", action="store_true", help="只执行下载。")
    parser.add_argument("--upload-only", action="store_true", help="只执行上传。")
    parser.add_argument("--economist", action="store_true", help="下载 Economist Drum Tower 后上传。")
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Economist 临时下载数量，例如 --mode economist --max-items 20。",
    )
    parser.add_argument("--web", action="store_true", help="打开 Streamlit 网页控制台。")
    parser.add_argument(
        "--no-clean",
        action="store_false",
        dest="clean_folder",
        default=True,
        help="普通 RSS 下载前不清空下载目录；不影响 Economist 清空逻辑。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="网页控制台端口；默认使用 STREAMLIT_PORT 或 8501。",
    )
    parser.add_argument(
        "--address",
        default="127.0.0.1",
        help="网页控制台监听地址，默认 127.0.0.1。",
    )
    return parser


def normalize_mode(parser: argparse.ArgumentParser, args: argparse.Namespace) -> str:
    requested: list[str] = []
    command = args.command
    economist_count = args.economist_count

    wants_economist = bool(
        args.economist
        or (args.mode and MODE_ALIASES.get(args.mode) == "economist")
    )
    if wants_economist and command and command.isdigit() and economist_count is None:
        economist_count = command
        command = None

    args.command = command
    args.economist_count = economist_count

    if command:
        requested.append(command)
    if args.mode:
        requested.append(args.mode)
    if args.all:
        requested.append("all")
    if args.download_only:
        requested.append("download")
    if args.upload_only:
        requested.append("upload")
    if args.economist:
        requested.append("economist")
    if args.web:
        requested.append("web")

    if not requested:
        return "all"

    normalized = []
    for item in requested:
        mode = MODE_ALIASES.get(str(item).strip().lower())
        if mode is None:
            parser.error(
                f"未知模式: {item}。可用: all, download/fetch, upload, economist/drum-tower, web/ui/streamlit"
            )
        normalized.append(mode)

    unique_modes = set(normalized)
    if len(unique_modes) > 1:
        parser.error(f"模式参数冲突: {', '.join(requested)}")

    return normalized[0]


def resolve_economist_max_items(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    mode: str,
) -> int | None:
    if args.economist_count and mode != "economist":
        parser.error("数量参数只支持 economist 模式，例如: economist 20")
    if args.max_items is not None and mode != "economist":
        parser.error("--max-items 只支持 economist 模式。")

    values: list[int] = []
    for raw in [args.economist_count, args.max_items]:
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            parser.error(f"Economist 数量必须是正整数: {raw}")
        if value <= 0:
            parser.error(f"Economist 数量必须是正整数: {raw}")
        values.append(value)

    if len(set(values)) > 1:
        parser.error("Economist 数量参数冲突，请只传一个数量。")
    return values[0] if values else None


def run_web_console(args: argparse.Namespace) -> int:
    if importlib.util.find_spec("streamlit") is None:
        print("❌ 未安装 streamlit，请先安装依赖：")
        print(f"   {sys.executable} -m pip install streamlit")
        return 1

    port = args.port or int(os.environ.get("STREAMLIT_PORT", "8501"))
    print(f"🌐 浏览器控制台: http://{args.address}:{port}")
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(BASE_DIR / "streamlit_app.py"),
            "--server.address",
            args.address,
            "--server.port",
            str(port),
        ]
    )


def run_cli_pipeline(
    mode: str,
    clean_folder: bool,
    economist_max_items: int | None = None,
) -> None:
    from upload import log_to_file, run_uploader
    from download import fetch_rss_main

    with log_to_file() as log_file_path:
        print(f"日志文件: {log_file_path}")
        print(f"Python: {sys.executable}")
        print(f"工作目录: {BASE_DIR}")
        print(f"运行模式: {mode}")

        if mode in {"all", "download"}:
            print("▶️ 开始下载任务...")
            fetch_rss_main(clean_folder=clean_folder)

        if mode in {"all", "upload"}:
            print("▶️ 开始上传任务...")
            run_uploader()

        if mode == "economist":
            print("▶️ 开始 Economist Drum Tower 下载任务...")
            from download_economist_video import run_download

            run_download(
                show_browser=False,
                override_urls=None,
                max_items=economist_max_items,
            )
            print("▶️ Economist 下载完成，开始上传任务...")
            run_uploader()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    mode = normalize_mode(parser, args)
    economist_max_items = resolve_economist_max_items(parser, args, mode)

    if mode == "web":
        return run_web_console(args)

    run_cli_pipeline(
        mode=mode,
        clean_folder=args.clean_folder,
        economist_max_items=economist_max_items,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
