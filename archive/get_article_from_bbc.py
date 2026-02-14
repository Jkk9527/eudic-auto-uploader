"""fetch_article.py – BBC Six-Minute English scraper with extra spacing for Notion
===================================================================================
Fetch a BBC Six-Minute English episode, convert its rich-text content to Markdown,
and prepend a 6-digit numeric timestamp and cleaned title as the first H1 heading.
Saves to a file named `articles/<timestamp>_<PascalCaseTitle>.md`.
Added extra newline between elements for better Notion import spacing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Union

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

__all__ = ["fetch_article"]

BBC_EP_DEFAULT = (
    "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2025/ep-250612"
)

# ---------------------------------------------------------------------------
# HTML-to-Markdown helpers
# ---------------------------------------------------------------------------

_RE_BOLD_CLASS = re.compile(r"\bbold\b", re.I)
_RE_BOLD_STYLE = re.compile(r"font-weight\s*:\s*bold", re.I)

def _is_bold(tag: Tag) -> bool:
    name = tag.name.lower()
    if name in {"b", "strong"}:
        return True
    if any(_RE_BOLD_CLASS.search(c) for c in tag.get("class", [])):
        return True
    if _RE_BOLD_STYLE.search(tag.get("style", "")):
        return True
    return False

def _append_bold(out: List[str], nodes: List[Union[Tag, NavigableString]]) -> None:
    tmp: List[str] = []
    for node in nodes:
        _node_to_md(node, tmp)
    text = "".join(tmp).strip()
    if text:
        out.append(f"**{text}**")

def _node_to_md(node: Union[Tag, NavigableString], out: List[str]) -> None:
    if isinstance(node, NavigableString):
        out.append(str(node))
        return
    name = node.name.lower()
    if name == "hr":
        return
    # Bold styling
    if _is_bold(node):
        _append_bold(out, list(node.children))
        return
    # Line break
    if name == "br":
        out.append("  \n")
        return
    # Headings h1-h4 with extra spacing
    if name in {"h1","h2","h3","h4"}:
        lvl = int(name[1])
        out.append("#" * lvl + " ")
        for c in node.children:
            _node_to_md(c, out)
        out.append("\n\n\n")  # triple newline for Notion spacing
        return
    # Paragraphs & list items with extra spacing
    if name in {"p","li"}:
        for c in node.children:
            _node_to_md(c, out)
        out.append("\n\n\n")  # triple newline between elements
        return
    # Generic container — recurse
    for c in node.children:
        _node_to_md(c, out)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_article(
    url: str = BBC_EP_DEFAULT,
) -> str:
    """Fetch URL, scrape content, and save Markdown with timestamped filename."""
    # Download page
    resp = requests.get(
        url,
        headers={"User-Agent": "fetch_article/6.2"},
        timeout=20,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract raw title
    raw_title = ""
    if soup.head and soup.head.title:
        raw_title = soup.head.title.get_text(strip=True)
    prefix = "BBC Learning English - 6 Minute English /"
    title = raw_title[len(prefix):].strip() if raw_title.startswith(prefix) else raw_title

    # Extract 6-digit timestamp from featuresubheader
    timestamp = ""
    fs_div = soup.find(
        "div",
        class_=lambda cl: cl and "widget-bbcle-featuresubheader" in cl.split(),
    )
    if fs_div:
        m = re.search(r"Episode\s+(.+)$", fs_div.get_text(strip=True))
        if m:
            digits = "".join(ch for ch in m.group(1) if ch.isdigit())
            timestamp = digits[:6].rjust(6, "0")

    # Find rich-text container
    container = soup.find(
        "div",
        class_=lambda cl: cl and set(cl.split()).issuperset({"widget","widget-richtext","6"}),
    )
    if not container:
        raise RuntimeError("Rich-text container not found.")

    # Convert HTML to Markdown
    md_parts: List[str] = []
    for child in container.children:
        _node_to_md(child, md_parts)

    # Build Markdown content
    header = []
    if timestamp:
        header.append(f"# {timestamp} - {title}\n\n")
    else:
        header.append(f"# {title}\n\n")
    content_md = "".join(md_parts).replace("_", "")
    markdown = "".join(header) + content_md

    # Generate filename: articles/<timestamp>_<PascalCaseTitle>.md
    words = re.findall(r"[A-Za-z0-9]+", title)
    pascal = ''.join(word.capitalize() for word in words) or "Episode"
    
    # 创建 articles 目录（如果不存在）
    articles_dir = Path("articles")
    articles_dir.mkdir(exist_ok=True)
    
    # 在 articles 目录下保存文件
    filename = articles_dir / (f"{timestamp}_{pascal}.md" if timestamp else f"{pascal}.md")

    # Write to file
    filename.write_text(markdown, encoding="utf-8")
    print(f"Article saved to: {filename}")
    return markdown

if __name__ == "__main__":
    print(fetch_article())




