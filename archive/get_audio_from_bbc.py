import requests
from bs4 import BeautifulSoup
import os
import re
import time

BASE_URL = "https://www.bbc.co.uk/programmes/p02pc9s1/episodes/downloads"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_128kbps_links_from_page(page: int):
    url = f"{BASE_URL}?page={page}"
    print(f"📄 正在解析第 {page} 页: {url}")
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        print(f"❌ 请求失败，状态码 {resp.status_code}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.find_all("a", attrs={"aria-label": lambda v: v and "128kbps" in v})

def extract_filename_from_response(resp, fallback_url):
    dispo = resp.headers.get("Content-Disposition", "")
    match = re.search(r'filename=\"?([^\";]+)\"?', dispo)
    if match:
        return match.group(1)
    return fallback_url.split("/")[-1]

# 下载目录
os.makedirs("audios", exist_ok=True)

page = 1
count = 0

while True:
    links = get_128kbps_links_from_page(page)
    if not links:
        print("✅ 没有更多链接，下载结束。")
        break

    for link in links:
        href = link.get("href")
        if not href:
            continue
        # 修复协议
        if href.startswith("//"):
            href = "https:" + href

        try:
            resp = requests.get(href, stream=True, headers=HEADERS)
            filename = extract_filename_from_response(resp, href)
            filepath = os.path.join("audios", filename)

            # 下载并保存文件
            print(f"🎧 下载: {filename}")
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024):
                    f.write(chunk)
            count += 1
        except Exception as e:
            print(f"⚠️ 下载失败: {href} - 错误: {e}")

        time.sleep(0.5)  # 防止过快请求

    page += 1

print(f"\n✅ 共下载 {count} 个 MP3 文件，保存在文件夹中。")