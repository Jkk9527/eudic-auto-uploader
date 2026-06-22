# Eudic-listen-sync

这个项目做两类任务：

1. 从普通 RSS 源下载音频到 `rss_download/`，再上传到每日英语听力。
2. 从已登录的 Economist 页面抓取 Drum Tower 播客音频，保存到 `rss_download/Drum Tower/`，再上传到每日英语听力。

推荐入口是 `listen_upload.sh`。它会固定使用本项目的 `.venv`，并设置 Playwright 浏览器路径。

```bash
./listen_upload.sh <mode> [参数]
```

也可以直接调用：

```bash
./.venv/bin/python main.py <mode> [参数]
```

## 程序框架

| 文件 | 作用 |
|------|------|
| `listen_upload.sh` | 推荐命令入口；切到项目目录，使用 `.venv/bin/python` 调 `main.py` |
| `main.py` | 总调度入口；根据模式调用下载、上传、Economist、Web UI |
| `download.py` | 普通 RSS 下载；读取 `rss_config.yaml` |
| `upload.py` | 上传 `rss_download/` 下的频道文件夹到每日英语听力 |
| `download_economist_video.py` | Economist Drum Tower 专用下载器 |
| `login.py` | 生成每日英语听力登录状态 `auth/eudic_auth.json` |
| `streamlit_app.py` | Web 控制台 |
| `rss_config.yaml` | 普通 RSS 下载和上传浏览器配置 |

运行数据目录：

| 路径 | 作用 |
|------|------|
| `rss_download/` | 下载后的音频；上传器扫描这里 |
| `auth/eudic_auth.json` | 每日英语听力登录状态 |
| `auth/economist_auth.json` | Economist 登录状态 |
| `economist_runtime/` | Economist 运行缓存、条目 JSON、签名播放 URL 缓存 |
| `logs/` | 运行日志 |

`auth/`、`economist_runtime/`、`rss_download/`、`logs/` 都不应该提交。

## 常用命令

| 命令 | 作用 |
|------|------|
| `./listen_upload.sh` | 默认 `all`：普通 RSS 下载 + 上传 |
| `./listen_upload.sh download` | 只下载普通 RSS |
| `./listen_upload.sh upload` | 只上传当前 `rss_download/` |
| `./listen_upload.sh economist` | Economist Drum Tower 下载，然后自动上传 |
| `./listen_upload.sh economist 20` | Economist 本次下载 20 条，然后自动上传 |
| `./listen_upload.sh web` | 打开 Streamlit 控制台 |

等价的 Python 调用：

```bash
./.venv/bin/python main.py economist
./.venv/bin/python main.py economist 20
./.venv/bin/python main.py --mode economist --max-items 20
```

别名：

| 主模式 | 别名 |
|--------|------|
| `all` | `full`, `run` |
| `download` | `fetch` |
| `economist` | `drum`, `drum-tower`, `drum_tower` |
| `web` | `ui`, `streamlit` |

## 参数规则

普通 RSS 参数在 `rss_config.yaml`：

| key | 作用 |
|-----|------|
| `rss_feeds` | 频道名到 RSS URL 的映射 |
| `year_from` / `year_end` | 下载年份范围 |
| `latest_num` | 每个频道最多下载几条，`-1` 表示全部 |
| `headless` | 上传浏览器是否无头 |
| `download_folder` | 下载目录，默认 `rss_download` |

普通 RSS 命令行参数：

| 参数 | 作用 |
|------|------|
| `--no-clean` | 普通 RSS 下载前不清空 `rss_download/` |
| `--mode <mode>` | 用参数形式指定模式 |
| `--port <N>` | Web UI 端口 |
| `--address <IP>` | Web UI 监听地址 |

Economist 参数在 `download_economist_video.py` 顶部固定区：

| 变量 | 作用 |
|------|------|
| `MAX_ITEMS` | 默认下载条数 |
| `START_DATE` | 起始日期过滤 |
| `HEADLESS_DOWNLOAD` | Economist 自动播放/下载时是否无头 |
| `MUTE_BROWSER_AUDIO` | 新开的 Playwright 浏览器是否静音 |
| `CLEAR_RSS_DOWNLOAD_BEFORE_ECONOMIST` | 运行 Economist 前是否清空整个 `rss_download/` |
| `AUTH_FILE` | Economist 登录状态文件 |

`main.py economist` 默认使用 `download_economist_video.py` 里的 `MAX_ITEMS`。如果命令后面加数字，只覆盖本次运行：

```bash
./listen_upload.sh economist 30
```

也可以写成：

```bash
./listen_upload.sh --mode economist --max-items 30
```

## Economist 流程

首次或登录失效时，先保存 Economist 登录状态：

```bash
./.venv/bin/python download_economist_video.py login
```

正常运行：

```bash
./listen_upload.sh economist
```

这个模式会：

1. 清空 `rss_download/`。
2. 重新创建 `rss_download/Drum Tower/`。
3. 读取 Acast 元数据并生成 `economist_runtime/drum_tower_episodes.json`。
4. 如果缺播放 URL，自动打开 Economist Drum Tower 页面，点击对应 `Listen` 按钮抓取 URL。
5. 下载 MP3。
6. 自动调用上传流程，把 `rss_download/Drum Tower/` 上传到每日英语听力。

直接运行下载器只下载、不上传：

```bash
./.venv/bin/python download_economist_video.py download
./.venv/bin/python download_economist_video.py download 20
./.venv/bin/python download_economist_video.py download --max-items 20
```

注意：`economist_runtime/signed_media_urls.json` 里是临时签名 URL，脚本不会在正常输出里打印真实 URL。

## 登录状态

每日英语听力登录：

```bash
./.venv/bin/python login.py
```

生成：

```text
auth/eudic_auth.json
```

Economist 登录：

```bash
./.venv/bin/python download_economist_video.py login
```

生成：

```text
auth/economist_auth.json
```

## Web 控制台

启动：

```bash
./listen_upload.sh web
```

默认地址：

```text
http://127.0.0.1:8501
```

自定义端口：

```bash
./listen_upload.sh web --port 9090
```

如果缺少 Streamlit：

```bash
./.venv/bin/python -m pip install streamlit
```
