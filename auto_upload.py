import os
import sys
import time
import zipfile
import re
from contextlib import contextmanager
from playwright.sync_api import sync_playwright

# ==========================================
# 设置 Playwright 浏览器路径（与 login.py 保持一致）
# ==========================================
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser("~/.playwright_browsers")

# ================= 配置区域 =================
AUTH_FILE = "auth.json"
# 导入外部配置
from fetch_rss import HEADLESS, RSS_FEEDS, DOWNLOAD_FOLDER

LOG_DIR = "logs"


class Tee:
    """Write to multiple streams (console + file)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


@contextmanager
def log_to_file():
    """
    Mirror stdout/stderr to a timestamped log file under LOG_DIR.
    文件名格式: yymmddhhmmss.log
    """

    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = time.strftime("%y%m%d%H%M%S")
    log_path = os.path.join(LOG_DIR, f"{timestamp}.log")

    with open(log_path, "w", encoding="utf-8") as f:
        tee = Tee(sys.stdout, f)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = tee
        try:
            yield log_path
        finally:
            sys.stdout, sys.stderr = old_out, old_err


def clean_filename_string(original_name):
    """
    统一的文件名清洗逻辑
    把所有非字母、数字、点、下划线、短横线的字符都变成短横线
    """

    clean_name = re.sub(r"[^a-zA-Z0-9\.\_\-]", "-", original_name)
    return clean_name


def zip_files_flat(file_paths, output_zip_path):
    """辅助函数：把文件列表打包x'x'x'x成 zip"""
    print(f"      🗜️ 正在压缩 {len(file_paths)} 个文件...")
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in file_paths:
            # zf.write(file, arcname=os.path.basename(file))

            # 1. 原始文件名
            original_name = os.path.basename(file)

            # 2. 清洗文件名 (关键修改)
            cleaned_name = clean_filename_string(original_name)

            # 3. 写入 ZIP (关键修改: arcname 使用清洗后的名字)
            zf.write(file, arcname=cleaned_name)
    return output_zip_path


def run_uploader():
    if not os.path.exists(AUTH_FILE):
        print(f"❌ 未找到 {AUTH_FILE}。请先运行登录脚本生成 json 文件。")
        return
    upload_summary = []
    print("🚀 启动浏览器进行上传...")

    with sync_playwright() as p:
        # headless 由 rss_config.yaml 控制
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=1000)
        context = browser.new_context(storage_state=AUTH_FILE)
        page = context.new_page()

        try:
            print("🌍 打开后台管理页面...")
            page.goto("http://my.eudic.net/Ting/index")
            page.wait_for_load_state("networkidle")

            # 1. 检查下载主目录是否存在
            if not os.path.exists(DOWNLOAD_FOLDER):
                print(
                    f"❌ 下载主目录 [{DOWNLOAD_FOLDER}] 不存在，无法开始。请先运行 fetch_rss.py 下载音频。"
                )
                return

            # 2. 扫描主目录下的所有子文件夹 (直接把文件夹名作为频道名)
            # os.listdir 列出所有文件 -> os.path.isdir 只要文件夹 -> not startswith(".") 过滤隐藏文件

            all_folders = [
                d
                for d in os.listdir(DOWNLOAD_FOLDER)
                if os.path.isdir(os.path.join(DOWNLOAD_FOLDER, d))
                and not d.startswith(".")
            ]

            # [关键修改] 自定义排序：让顺序跟 RSS_FEEDS (rss_config.yaml) 保持一致
            # 1. 拿到配置里的顺序列表
            priority_list = list(RSS_FEEDS.keys())

            # 2. 定义排序规则函数
            def custom_sort(folder_name):
                if folder_name in priority_list:
                    return priority_list.index(
                        folder_name
                    )  # 返回它在配置里的索引(0, 1, 2...)
                return 999  # 没在配置里的文件夹(手动加的)，统统排在最后

            # 3. 执行排序
            local_channels = sorted(all_folders, key=custom_sort)

            if not local_channels:
                print(f"📂 目录 [{DOWNLOAD_FOLDER}] 为空，没有找到任何频道文件夹。")
                return

            print(
                f"📂 扫描到本地有 {len(local_channels)} 个频道待处理: {local_channels}"
            )

            # 初始化计数器
            upload_ops_count = 0

            # 3. 遍历每个本地频道
            for channel_name in local_channels:

                local_dir = os.path.join(DOWNLOAD_FOLDER, channel_name)

                print(f"\n{'='*60}")
                print(f"👀 正在处理栏目: [{channel_name}]")
                page.wait_for_timeout(2000)  # 稍微停顿

                # 4. 在网页左侧点击栏目
                try:
                    page.get_by_text(channel_name, exact=False).first.click()
                    page.wait_for_timeout(5000)  # 等待右侧刷新
                except Exception as e:
                    print(f"  ⚠️  网页上找不到栏目 '{channel_name}'，跳过。")
                    continue

                # 滚动到底，确保懒加载内容出现（直到高度不再增长）
                last_height = page.evaluate(
                    "() => document.documentElement.scrollHeight"
                )
                while True:
                    page.evaluate(
                        "() => window.scrollTo(0, document.documentElement.scrollHeight)"
                    )
                    page.wait_for_timeout(1000)
                    new_height = page.evaluate(
                        "() => document.documentElement.scrollHeight"
                    )
                    if new_height == last_height:
                        break
                    last_height = new_height

                # 5. 扫描文件并比对
                page_content = page.content()
                all_files = sorted(
                    [f for f in os.listdir(local_dir) if f.endswith(".mp3")]
                )
                files_to_upload = []

                if not all_files:
                    print("  📂 本地为空，跳过。")
                    continue

                print(f"  📂 扫描本地文件 ({len(all_files)}个)...")
                for f in all_files:
                    file_stem = os.path.splitext(f)[0]
                    cleaned_stem = clean_filename_string(file_stem)
                    if (file_stem in page_content) or (cleaned_stem in page_content):
                        # 简单的包含检查，如果网页源代码里有这个文件名，就当做已存在
                        print(f"     ⏭️ 已存在:{f}:")
                    else:
                        print(f"     🆕待上传:{f}:")
                        files_to_upload.append(os.path.join(local_dir, f))

                count = len(files_to_upload)
                if count == 0:
                    print(f"  ✅ [{channel_name}] 无需更新。")
                    continue

                # ==================================================
                # 6. 准备上传流程
                # ==================================================
                upload_path = ""
                is_zip_mode = False

                # 单文件上传：
                if count == 1:
                    print("  ⬆️  模式: 单文件上传 (启用AI字幕)")
                    upload_path = files_to_upload[0]

                    fname_record = os.path.basename(upload_path)
                    upload_summary.append(f"单文件：[{channel_name}] {fname_record}")

                    # A. 点击上传按钮
                    print("      1️⃣  点击 [上传听力]...")
                    page.get_by_role("button", name=re.compile("上传听力")).click()

                    # B. 填入文件
                    print(f"      2️⃣  填入文件: {os.path.basename(upload_path)}")
                    page.locator("input[type='file']").set_input_files(upload_path)

                    # C. 等待上传进度条走完
                    print("      ⏳  等待上传成功提示...")

                    try:
                        page.get_by_text("上传成功").wait_for(timeout=36000000)
                    except Exception as e:
                        # 【如果没等到成功，检查是不是失败了
                        if (
                            page.get_by_text("上传失败").is_visible()
                            or page.get_by_text("失败").is_visible()
                        ):
                            print(
                                f"\n❌❌❌ 严重错误: 文件 [{fname_record}] 上传失败！"
                            )
                            print("🛑 停止运行，退出程序。")
                            sys.exit(1)  # 强制退出
                        else:
                            raise e  # 如果不是失败（只是超时），抛出原异常

                    page.wait_for_timeout(1000)  # 稍微停顿

                    print("      ✅  文件传输完成")

                    # D. 点击下一步 (这是去第二页的关键)
                    print("      3️⃣  点击 [下一步]...")
                    page.wait_for_timeout(1000)  # 稍微停顿
                    page.get_by_text("下一步", exact=True).click()
                    page.wait_for_timeout(1000)  # 稍微停顿

                    # E. 第二页
                    print("      点击 生成AI字幕")
                    page.get_by_role("radio", name="生成AI字幕").check()
                    page.wait_for_timeout(1000)  # 稍微停顿

                    print("      点击 我已阅读并同意")
                    page.get_by_role("checkbox", name="我已阅读并同意").check()
                    page.wait_for_timeout(1000)  # 稍微停顿

                    print("      准备点击 [保存] 按钮...")
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="保存").click()
                    page.wait_for_timeout(3000)  # 稍微停顿

                    print("      捕捉点击 [OK] 按钮...")
                    page.wait_for_timeout(3000)  # 稍微停顿

                # 多文件上传，打包成 ZIP：
                else:
                    print(f"  ⬆️  模式: 批量ZIP上传 ({count} 个文件)")
                    is_zip_mode = True

                    files_str = ", ".join(
                        [os.path.basename(f) for f in files_to_upload]
                    )
                    upload_summary.append(
                        f"多文件：[{channel_name}] 共{count}个: {files_str}"
                    )

                    zip_name = os.path.join(local_dir, "1.zip")
                    zip_files_flat(files_to_upload, zip_name)
                    upload_path = zip_name

                    # A. 点击上传按钮
                    print("      1️⃣  点击 [上传听力]...")
                    page.get_by_role("button", name=re.compile("上传听力")).click()

                    # B. 填入文件
                    print(f"      2️⃣  填入文件: {os.path.basename(upload_path)}")
                    page.locator("input[type='file']").set_input_files(upload_path)

                    # C. 等待上传进度条走完
                    print("      ⏳  等待上传成功提示...")

                    try:
                        # 尝试等待“上传成功”，超时设置为60分钟
                        page.get_by_text("上传成功").wait_for(timeout=3600000)
                    except Exception as e:
                        # 如果没等到成功，检查是不是失败了
                        if (
                            page.get_by_text("上传失败").is_visible()
                            or page.get_by_text("失败").is_visible()
                        ):
                            print(
                                f"\n❌❌❌ 严重错误: 文件 [{fname_record}] 上传失败！"
                            )
                            print("🛑 停止运行，退出程序。")
                            sys.exit(1)  # 强制退出
                        else:
                            raise e  # 如果不是失败（只是超时），抛出原异常

                    page.wait_for_timeout(5000)  # 稍微停顿
                    print("      ✅  文件传输完成")

                    # D. 点击下一步 (这是去第二页的关键)
                    print("      3️⃣  点击 [下一步]...")
                    page.wait_for_timeout(5000)  # 稍微停顿
                    page.get_by_text("下一步", exact=True).click()
                    page.wait_for_timeout(5000)  # 稍微停顿

                    # E. 第二页
                    print("      点击 我已阅读并同意")
                    page.get_by_role("checkbox", name="我已阅读并同意").check()
                    page.wait_for_timeout(5000)  # 稍微停顿

                    print("      准备点击 [保存] 按钮...")
                    page.get_by_role("button", name="保存").click()
                    page.wait_for_timeout(5000)  # 稍微停顿

                    print("      准备点击 [确定] 按钮...")
                    # page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_text("确定").click()
                    page.wait_for_timeout(5000)  # 稍微停顿

                    # ==================================================
                    # 7. 收尾：刷新页面
                    # ==================================================
                print("      🔄  刷新页面，准备下一轮...")
                page.reload()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)  # 稍微停顿

                upload_ops_count += 1
                print(f"上传动作计数，目前已上传{upload_ops_count}次:")
                if upload_ops_count % 2 == 0:
                    print(
                        f"☕ 已连续上传 2 次 (累计{upload_ops_count}次)，休息 5 分钟以缓解网页拥堵..."
                    )
                    time.sleep(300)
                    print("⏰ 休息结束，准备处理下一个...")
                    # 休息久了防止页面状态失效，保险起见再刷一次
                    page.reload()
                    page.wait_for_load_state("networkidle")

        except Exception as e:
            print(f"❌ 脚本崩溃: {e}")
        finally:
            context.close()
            browser.close()

            print("\n" + "=" * 50)
            print("📊 本次上传汇总报告:")
            if not upload_summary:
                print("   (本次没有上传任何新文件)")
            else:
                for i, msg in enumerate(upload_summary, 1):
                    print(f"   {i}. {msg}\n")
            print("=" * 50 + "\n")

            print("\n🏁 程序退出。")
    print("✅任务完成。")
