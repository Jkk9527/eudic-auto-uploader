#!/usr/bin/env python3
"""
Streamlit control panel for RSS download and upload workflow.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml
from st_aggrid import AgGrid, GridOptionsBuilder
from st_aggrid.shared import DataReturnMode, GridUpdateMode

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "rss_config.yaml"
LOG_DIR = BASE_DIR / "logs"

os.chdir(BASE_DIR)

DEFAULT_CONFIG: dict[str, Any] = {
    "rss_feeds": {},
    "headless": False,
    "year_from": 2025,
    "latest_num": 2,
    "year_end": 9999,
    "download_folder": "rss_download",
}
FEED_COLUMNS = ["启用", "栏目名", "RSS URL", "_id"]
TABLE_COLUMNS = ["序号", "启用", "栏目名", "RSS URL", "_id"]
DEFAULT_FEED_ROW = {"启用": True, "栏目名": "", "RSS URL": "", "_id": ""}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_config(raw: Any) -> dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return normalized

    feeds = raw.get("rss_feeds", {})
    cleaned_feeds: dict[str, str] = {}
    if isinstance(feeds, dict):
        for name, url in feeds.items():
            item_name = str(name).strip()
            item_url = str(url).strip()
            if item_name and item_url:
                cleaned_feeds[item_name] = item_url

    normalized["rss_feeds"] = cleaned_feeds
    normalized["headless"] = _as_bool(raw.get("headless"), DEFAULT_CONFIG["headless"])
    normalized["year_from"] = _as_int(raw.get("year_from"), DEFAULT_CONFIG["year_from"])
    normalized["latest_num"] = _as_int(raw.get("latest_num"), DEFAULT_CONFIG["latest_num"])
    normalized["year_end"] = _as_int(raw.get("year_end"), DEFAULT_CONFIG["year_end"])
    normalized["download_folder"] = str(
        raw.get("download_folder", DEFAULT_CONFIG["download_folder"])
    ).strip() or DEFAULT_CONFIG["download_folder"]

    return normalized


def _extract_rss_feed_lines(config_text: str) -> list[str]:
    lines = config_text.splitlines()
    start_index = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("rss_feeds:"):
            start_index = idx
            break

    if start_index is None:
        return []

    rss_lines: list[str] = []
    for line in lines[start_index + 1 :]:
        if not line.strip():
            rss_lines.append("")
            continue
        if line.startswith((" ", "\t")):
            rss_lines.append(line.rstrip())
            continue
        break
    return rss_lines


def _parse_rss_line(line: str) -> tuple[bool, str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None

    enabled = True
    payload = stripped
    if payload.startswith("#"):
        enabled = False
        payload = payload[1:].strip()

    try:
        parsed = yaml.safe_load(payload)
    except Exception:
        return None

    if not isinstance(parsed, dict) or len(parsed) != 1:
        return None

    name, url = next(iter(parsed.items()))
    item_name = str(name).strip()
    item_url = "" if url is None else str(url).strip()
    if not item_name or not item_url:
        return None

    return enabled, item_name, item_url


def _new_row_id() -> str:
    return uuid.uuid4().hex[:12]


def _ensure_row_id(row: dict[str, Any]) -> str:
    row_id = str(row.get("_id", "")).strip()
    if not row_id:
        row_id = _new_row_id()
        row["_id"] = row_id
    return row_id


def _rows_from_config_text(config_text: str, fallback_feeds: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in _extract_rss_feed_lines(config_text):
        parsed = _parse_rss_line(line)
        if not parsed:
            continue
        enabled, name, url = parsed
        rows.append(
            {
                "启用": enabled,
                "栏目名": name,
                "RSS URL": url,
                "_id": _new_row_id(),
            }
        )

    if rows:
        return rows

    for name, url in fallback_feeds.items():
        item_name = str(name).strip()
        item_url = str(url).strip()
        if not item_name or not item_url:
            continue
        rows.append(
            {
                "启用": True,
                "栏目名": item_name,
                "RSS URL": item_url,
                "_id": _new_row_id(),
            }
        )

    return rows or [dict(DEFAULT_FEED_ROW)]


def _rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        rows = [dict(DEFAULT_FEED_ROW)]

    def centered_seq(idx: int, width: int = 4) -> str:
        # Use fixed-width text so the sequence appears centered in the small column.
        return f"{idx:^{width}}"

    display_rows: list[dict[str, Any]] = []
    for idx, src in enumerate(rows, start=1):
        row = dict(src)
        row_id = _ensure_row_id(row)
        display_rows.append(
            {
                "序号": centered_seq(idx),
                "启用": bool(row.get("启用", True)),
                "栏目名": _to_cell_text(row.get("栏目名", "")),
                "RSS URL": _to_cell_text(row.get("RSS URL", "")),
                "_id": row_id,
            }
        )
    return pd.DataFrame(display_rows, columns=TABLE_COLUMNS)


def _normalize_table_df(df_like: Any) -> pd.DataFrame:
    if isinstance(df_like, pd.DataFrame):
        df = df_like.copy()
    elif df_like is None:
        df = pd.DataFrame(columns=TABLE_COLUMNS)
    else:
        df = pd.DataFrame(df_like)

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rows.append(
            {
                "启用": bool(row.get("启用", True)),
                "栏目名": _to_cell_text(row.get("栏目名", "")),
                "RSS URL": _to_cell_text(row.get("RSS URL", "")),
                "_id": _to_cell_text(row.get("_id", "")) or _new_row_id(),
            }
        )
    return _rows_to_dataframe(rows)


def _selected_row_ids(selected_rows: Any) -> set[str]:
    if isinstance(selected_rows, pd.DataFrame):
        records = selected_rows.to_dict("records")
    elif isinstance(selected_rows, list):
        records = selected_rows
    else:
        records = []

    ids: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        row_id = _to_cell_text(item.get("_id", ""))
        if row_id:
            ids.add(row_id)
    return ids


def _to_cell_text(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _table_to_rows(table: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    active_names: set[str] = set()

    for idx, row in table.iterrows():
        enabled = bool(row.get("启用", True))
        name = _to_cell_text(row.get("栏目名", ""))
        url = _to_cell_text(row.get("RSS URL", ""))
        row_id = _to_cell_text(row.get("_id", "")) or _new_row_id()

        if not name and not url:
            continue
        if not name or not url:
            errors.append(f"第 {idx + 1} 行请同时填写栏目名和 URL。")
            continue
        if enabled and name in active_names:
            errors.append(f"启用栏目名重复: {name}")
            continue
        if enabled and not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"[{name}] 的 URL 需要以 http:// 或 https:// 开头。")
            continue

        if enabled:
            active_names.add(name)
        rows.append(
            {
                "启用": enabled,
                "栏目名": name,
                "RSS URL": url,
                "_id": row_id,
            }
        )

    return rows, errors


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(rows)


def _build_enabled_feeds(rows: list[dict[str, Any]]) -> dict[str, str]:
    feeds: dict[str, str] = {}
    for row in _sorted_rows(rows):
        if not row.get("启用"):
            continue
        feeds[str(row["栏目名"]).strip()] = str(row["RSS URL"]).strip()
    return feeds


def _rows_to_rss_snippet(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in _sorted_rows(rows):
        name = str(row.get("栏目名", "")).strip()
        url = str(row.get("RSS URL", "")).strip()
        if not name or not url:
            continue

        payload = yaml.safe_dump(
            {name: url}, allow_unicode=True, sort_keys=False
        ).strip()
        lines.append(f"  {payload}" if row.get("启用") else f"  # {payload}")

    if not lines:
        lines.append('  # Six Minute English: "https://podcasts.files.bbci.co.uk/p02pc9tn.rss"')
    return "\n".join(lines)


def _build_save_snapshot(config: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    rows_for_save = [{k: row.get(k) for k in FEED_COLUMNS} for row in _sorted_rows(rows)]
    return yaml.safe_dump(
        {"config": config, "rss_rows": rows_for_save},
        allow_unicode=True,
        sort_keys=False,
    )


def _to_yaml_bool(value: bool) -> str:
    return "true" if bool(value) else "false"


def _to_yaml_quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def read_config_file() -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG), [dict(DEFAULT_FEED_ROW)], f"未找到配置文件，已加载默认值: {CONFIG_PATH}"

    try:
        config_text = CONFIG_PATH.read_text(encoding="utf-8")
        raw = yaml.safe_load(config_text) or {}
        normalized = normalize_config(raw)
        rss_rows = _rows_from_config_text(config_text, normalized["rss_feeds"])
        return normalized, rss_rows, ""
    except Exception as exc:
        return dict(DEFAULT_CONFIG), [dict(DEFAULT_FEED_ROW)], f"读取配置失败，已回退默认值: {exc}"


def save_config_file(config: dict[str, Any], rss_rows: list[dict[str, Any]]) -> None:
    rss_snippet = _rows_to_rss_snippet(rss_rows)

    text = (
        "# ================= RSS 下载配置 =================\n\n"
        "# 注意：rss_feeds 下面的 Key 必须与每日英语听力网页左侧栏目名一致\n"
        "rss_feeds:\n"
        f"{rss_snippet}\n\n"
        "# Playwright 浏览器是否无头运行 (true = 不显示 Chromium 窗口)\n"
        f"headless: {_to_yaml_bool(config['headless'])}\n\n"
        "# 起始年份 (含)\n"
        f"year_from: {int(config['year_from'])}\n\n"
        "# 下载最新数量 (-1 表示全部)\n"
        f"latest_num: {int(config['latest_num'])}\n\n"
        "# 结束年份 (含)\n"
        f"year_end: {int(config['year_end'])}\n\n"
        "# 下载文件保存目录\n"
        f"download_folder: {_to_yaml_quoted(str(config['download_folder']).strip() or 'rss_download')}\n"
    )
    CONFIG_PATH.write_text(text, encoding="utf-8")


def load_config_into_state(config: dict[str, Any], rss_rows: list[dict[str, Any]]) -> None:
    st.session_state["headless"] = bool(config["headless"])
    st.session_state["year_from"] = int(config["year_from"])
    st.session_state["latest_num"] = int(config["latest_num"])
    st.session_state["year_end"] = int(config["year_end"])
    st.session_state["download_folder"] = str(config["download_folder"])
    st.session_state["feeds_table_seed"] = _rows_to_dataframe(rss_rows)
    st.session_state["last_saved_snapshot"] = _build_save_snapshot(config, rss_rows)


def build_current_config(
    edited_table: pd.DataFrame,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    rss_rows, errors = _table_to_rows(edited_table)
    feeds = _build_enabled_feeds(rss_rows)
    config = {
        "rss_feeds": feeds,
        "headless": bool(st.session_state["headless"]),
        "year_from": int(st.session_state["year_from"]),
        "latest_num": int(st.session_state["latest_num"]),
        "year_end": int(st.session_state["year_end"]),
        "download_folder": str(st.session_state["download_folder"]).strip()
        or "rss_download",
    }

    if config["year_from"] > config["year_end"]:
        errors.append("起始年份不能大于结束年份。")

    return config, rss_rows, errors


def apply_runtime_config(config: dict[str, Any]):
    import download
    import upload

    download = importlib.reload(download)
    upload = importlib.reload(upload)

    download.RSS_FEEDS = dict(config["rss_feeds"])
    download.YEAR_FROM = int(config["year_from"])
    download.YEAR_END = int(config["year_end"])
    download.LATEST_NUM = int(config["latest_num"])
    download.DOWNLOAD_FOLDER = str(config["download_folder"])
    download.HEADLESS = bool(config["headless"])
    download.ENABLE_FETCH = True
    download.ENABLE_UPLOAD = True

    upload.RSS_FEEDS = download.RSS_FEEDS
    upload.DOWNLOAD_FOLDER = download.DOWNLOAD_FOLDER
    upload.HEADLESS = download.HEADLESS

    return download, upload


def run_pipeline(
    config: dict[str, Any],
    mode: str,
    clean_folder: bool,
    live_log_placeholder: Any | None = None,
) -> tuple[bool, str, str]:
    class LiveLogWriter:
        def __init__(self, placeholder: Any | None, max_chars: int = 25000):
            self.placeholder = placeholder
            self.max_chars = max_chars
            self.parts: list[str] = []
            self.last_flush = 0.0

        def write(self, data: str) -> None:
            if not data:
                return
            self.parts.append(data)
            self._flush_if_needed(force=data.endswith("\n"))

        def flush(self) -> None:
            self._flush_if_needed(force=True)

        def get_value(self) -> str:
            return "".join(self.parts)

        def get_tail(self) -> str:
            text = self.get_value()
            return text if len(text) <= self.max_chars else text[-self.max_chars :]

        def _flush_if_needed(self, force: bool = False) -> None:
            if self.placeholder is None:
                return
            now = time.time()
            if force or (now - self.last_flush) >= 0.25:
                self.placeholder.code(self.get_tail(), language="text")
                self.last_flush = now

    class FanoutWriter:
        def __init__(self, *streams: Any):
            self.streams = streams

        def write(self, data: str) -> None:
            for stream in self.streams:
                stream.write(data)

        def flush(self) -> None:
            for stream in self.streams:
                stream.flush()

    download, upload = apply_runtime_config(config)
    LOG_DIR.mkdir(exist_ok=True)

    live_writer = LiveLogWriter(live_log_placeholder)
    success = True
    log_path = ""

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = FanoutWriter(old_out, live_writer)
    sys.stderr = FanoutWriter(old_err, live_writer)
    try:
        with upload.log_to_file() as generated_log:
            log_path = str(Path(generated_log).resolve())
            try:
                print(f"任务开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"任务模式: {mode}")
                print(f"配置文件: {CONFIG_PATH}")
                print("")

                if mode == "fetch":
                    download.fetch_rss_main(
                        target_feeds=config["rss_feeds"],
                        year_from=config["year_from"],
                        year_end=config["year_end"],
                        latest_num=config["latest_num"],
                        clean_folder=clean_folder,
                    )
                elif mode == "upload":
                    upload.run_uploader()
                else:
                    download.fetch_rss_main(
                        target_feeds=config["rss_feeds"],
                        year_from=config["year_from"],
                        year_end=config["year_end"],
                        latest_num=config["latest_num"],
                        clean_folder=clean_folder,
                    )
                    upload.run_uploader()

                print("")
                print("✅ 任务执行结束")
            except Exception:
                success = False
                traceback.print_exc()
    except Exception:
        success = False
        traceback.print_exc()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        live_writer.flush()

    output = live_writer.get_value()
    if not log_path:
        fallback_log = LOG_DIR / f"{datetime.now().strftime('%y%m%d%H%M%S')}.log"
        fallback_log.write_text(output, encoding="utf-8")
        log_path = str(fallback_log.resolve())

    if live_log_placeholder is not None:
        live_log_placeholder.code(output[-25000:], language="text")

    return success, output, log_path


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url("https://fonts.googleapis.com/css2?family=Barlow:wght@500;700&family=Noto+Sans+SC:wght@400;500;700&display=swap");

        html, body, [class*="css"] {
            font-family: "Noto Sans SC", "Barlow", sans-serif;
        }

        .stApp {
            background:
                radial-gradient(circle at 10% -20%, #ffe3bf 0%, transparent 35%),
                radial-gradient(circle at 90% 0%, #c9e5ff 0%, transparent 40%),
                linear-gradient(170deg, #f4f7fa 0%, #f7efe4 100%);
        }

        .block-container {
            max-width: 1200px;
            padding-top: 1.2rem;
            padding-bottom: 2rem;
        }

        .hero {
            background: linear-gradient(120deg, #0f3d5f 0%, #1f6d8c 55%, #2f8f6b 100%);
            color: #f8fbff;
            border-radius: 18px;
            padding: 20px 24px;
            margin-bottom: 16px;
            box-shadow: 0 10px 24px rgba(15, 61, 95, 0.25);
        }

        .hero h1 {
            margin: 0;
            font-size: 1.72rem;
            letter-spacing: 0.3px;
        }

        .hero p {
            margin: 8px 0 0 0;
            opacity: 0.92;
            font-size: 0.98rem;
        }

        .panel {
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(18, 73, 109, 0.14);
            border-radius: 16px;
            padding: 16px 16px 12px 16px;
            margin-bottom: 12px;
            box-shadow: 0 6px 20px rgba(20, 34, 50, 0.08);
        }

        div.stButton > button {
            border-radius: 10px;
            border: 1px solid #174d79;
            background: linear-gradient(120deg, #1a5f93 0%, #257789 100%);
            color: #ffffff;
            font-weight: 600;
        }

        div.stButton > button:hover {
            border-color: #1e6b9d;
            color: #ffffff;
        }

        code, pre {
            border-radius: 10px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="RSS 上传控制台",
        page_icon="🎧",
        layout="wide",
    )
    inject_styles()

    st.markdown(
        """
        <div class="hero">
          <h1>RSS 上传控制台</h1>
          <p>在页面里编辑配置、执行下载/上传任务、查看日志，不再频繁手改 YAML。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "initialized" not in st.session_state:
        loaded_config, rss_rows, notice = read_config_file()
        load_config_into_state(loaded_config, rss_rows)
        st.session_state["initialized"] = True
        if notice:
            st.session_state["notice"] = notice

    if st.session_state.get("notice"):
        st.info(st.session_state["notice"])
        st.session_state["notice"] = ""

    header_col1, header_col2 = st.columns([1, 5])
    reload_clicked = header_col1.button("重新读取 YAML", use_container_width=True)
    header_col2.caption(f"配置文件路径: {CONFIG_PATH}")

    if reload_clicked:
        loaded_config, rss_rows, notice = read_config_file()
        load_config_into_state(loaded_config, rss_rows)
        st.session_state["notice"] = notice or "已从 YAML 重新加载配置。"
        st.rerun()

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("基础参数")
    basic_left, basic_mid, basic_right = st.columns(3)
    with basic_left:
        st.toggle("浏览器无头模式", key="headless")
    with basic_mid:
        st.number_input("起始年份", min_value=2000, max_value=2100, key="year_from")
        st.number_input(
            "最新数量 ( -1 表示全部 )",
            min_value=-1,
            max_value=500,
            key="latest_num",
        )
    with basic_right:
        st.number_input("结束年份", min_value=2000, max_value=2100, key="year_end")
        st.text_input("下载目录", key="download_folder")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("RSS 栏目配置")
    source_df = _normalize_table_df(st.session_state.get("feeds_table_seed"))

    gb = GridOptionsBuilder.from_dataframe(source_df)
    gb.configure_default_column(
        editable=True,
        resizable=True,
        sortable=False,
        filter=False,
    )
    gb.configure_selection(selection_mode="multiple", use_checkbox=False)
    gb.configure_column(
        "序号",
        editable=False,
        width=88,
        headerClass="seq-center-header",
        cellClass="seq-center-cell",
    )
    gb.configure_column("启用", editable=True, width=90)
    gb.configure_column("栏目名", editable=True, width=280)
    gb.configure_column("RSS URL", editable=True, width=560)
    gb.configure_column("_id", hide=True)
    grid_options = gb.build()

    grid_response = AgGrid(
        source_df,
        gridOptions=grid_options,
        fit_columns_on_grid_load=False,
        update_mode=GridUpdateMode.VALUE_CHANGED | GridUpdateMode.SELECTION_CHANGED,
        data_return_mode=DataReturnMode.AS_INPUT,
        theme="streamlit",
        custom_css={
            ".seq-center-header .ag-header-cell-label": {
                "justify-content": "center",
            },
            ".seq-center-cell": {
                "text-align": "center",
            },
        },
        height=430,
        key="feeds_grid_widget",
    )

    edited_feeds = _normalize_table_df(grid_response.data)
    st.session_state["feeds_table_seed"] = edited_feeds
    selected_ids = _selected_row_ids(grid_response.selected_rows)

    action_col1, action_col2 = st.columns([1, 1])
    add_row_clicked = action_col1.button("新增 RSS", use_container_width=True)
    delete_row_clicked = action_col2.button(
        "删除选中行",
        use_container_width=True,
        disabled=(len(selected_ids) == 0),
    )

    if add_row_clicked:
        appended = edited_feeds.copy()
        new_row = pd.DataFrame(
            [{"序号": "", "启用": True, "栏目名": "", "RSS URL": "", "_id": _new_row_id()}]
        )
        appended = pd.concat([appended, new_row], ignore_index=True)
        st.session_state["feeds_table_seed"] = _normalize_table_df(appended)
        st.rerun()

    if delete_row_clicked and selected_ids:
        remained = edited_feeds[~edited_feeds["_id"].isin(selected_ids)].copy()
        st.session_state["feeds_table_seed"] = _normalize_table_df(remained)
        st.rerun()

    edited_feeds = _normalize_table_df(st.session_state["feeds_table_seed"])
    st.caption("序号居中显示。勾选“启用”表示有效；支持删除选中行。")

    st.markdown("</div>", unsafe_allow_html=True)

    current_config, current_rows, validation_errors = build_current_config(edited_feeds)

    if validation_errors:
        st.warning("\n".join([f"- {message}" for message in validation_errors]))

    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
    stat_col1.metric("启用栏目", len(current_config["rss_feeds"]))
    stat_col2.metric("年份范围", f"{current_config['year_from']} - {current_config['year_end']}")
    stat_col3.metric("latest_num", current_config["latest_num"])
    stat_col4.metric("下载目录", current_config["download_folder"])

    rows_for_save = [{k: row.get(k) for k in FEED_COLUMNS} for row in _sorted_rows(current_rows)]
    auto_save_snapshot = _build_save_snapshot(current_config, current_rows)
    if validation_errors:
        st.caption("自动保存已暂停：请先修复配置错误。")
    else:
        if st.session_state.get("last_saved_snapshot") != auto_save_snapshot:
            try:
                save_config_file(current_config, rows_for_save)
                st.session_state["last_saved_snapshot"] = auto_save_snapshot
                st.caption(f"已自动保存到 {CONFIG_PATH}")
            except Exception as exc:
                st.error(f"自动保存失败: {exc}")
        else:
            st.caption(f"配置已同步到 {CONFIG_PATH}")

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("任务执行")
    run_left, run_mid, run_right, run_ext = st.columns([1, 1, 1, 2])
    fetch_clicked = run_left.button("只执行下载", use_container_width=True)
    upload_clicked = run_mid.button("只执行上传", use_container_width=True)
    full_clicked = run_right.button("下载 + 上传", type="primary", use_container_width=True)
    clean_folder = run_ext.checkbox("下载前清空目录", value=True)
    st.markdown("</div>", unsafe_allow_html=True)

    mode = ""
    if fetch_clicked:
        mode = "fetch"
    elif upload_clicked:
        mode = "upload"
    elif full_clicked:
        mode = "all"

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("运行日志")
    live_log_placeholder = st.empty()
    live_log_placeholder.code("等待任务开始...", language="text")
    st.markdown("</div>", unsafe_allow_html=True)

    if mode:
        if validation_errors:
            st.error("无法执行任务：当前配置存在错误。")
        elif mode in {"fetch", "all"} and not current_config["rss_feeds"]:
            st.error("无法执行下载：请先至少配置一个 RSS 栏目。")
        else:
            with st.spinner("任务执行中，请等待..."):
                success, output, log_path = run_pipeline(
                    config=current_config,
                    mode=mode,
                    clean_folder=clean_folder,
                    live_log_placeholder=live_log_placeholder,
                )
            st.session_state["last_result"] = {
                "success": success,
                "mode": mode,
                "output": output,
                "log_path": log_path,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    last_result = st.session_state.get("last_result")
    if last_result:
        if last_result["success"]:
            st.success(
                f"任务完成 ({last_result['mode']})，时间: {last_result['time']}"
            )
        else:
            st.error(
                f"任务失败 ({last_result['mode']})，时间: {last_result['time']}"
            )
        st.caption(f"日志文件: {last_result['log_path']}")
        live_log_placeholder.code(last_result["output"][-25000:], language="text")


if __name__ == "__main__":
    main()
