#!/usr/bin/env python3
"""
登录脚本 - 用于生成或更新 auth/eudic_auth.json 文件

当 cookie 过期时，运行此脚本重新登录。
脚本会打开浏览器，让你手动登录，然后自动保存登录状态到 auth/eudic_auth.json。
"""

import os
from playwright.sync_api import sync_playwright

# ==========================================
# 设置 Playwright 浏览器路径（与 listen_upload.sh 保持一致）
# ==========================================
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser("~/.playwright_browsers")

AUTH_FILE = "auth/eudic_auth.json"
TARGET_URL = "http://my.eudic.net/Ting/index"


def manual_login():
    """
    打开浏览器让用户手动登录，登录成功后保存认证状态
    """
    print("🚀 启动浏览器进行手动登录...")
    print(f"📝 登录后，认证信息将保存到: {AUTH_FILE}")
    print("\n" + "=" * 60)
    print("⚠️  操作步骤:")
    print("1. 浏览器将打开后台页面")
    print("2. 如果未登录会自动跳转到登录页面，请手动登录")
    print("3. 登录成功后按回车键保存认证信息")
    print("=" * 60 + "\n")

    with sync_playwright() as p:
        # 🔔 强制启用可见浏览器窗口（必须有界面才能手动登录）
        print("🖥️  正在启动浏览器窗口...")
        browser = p.chromium.launch(
            headless=False,  # 强制显示浏览器界面
            slow_mo=500,  # 减慢操作速度，便于观察
            channel=None,  # 使用 Playwright 自带的 Chromium
        )
        context = browser.new_context()
        page = context.new_page()

        try:
            # 直接打开后台管理页面
            print(f"🌍 打开页面: {TARGET_URL}")
            page.goto(TARGET_URL)

            # 等待用户手动登录
            print("\n⏳ 请在浏览器中完成登录（如需要）...")

            # 等待用户确认
            input("\n✋ 登录完成后，请按 [回车键] 继续保存认证信息...")

            # 保存认证状态
            os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
            print(f"\n💾 正在保存认证信息到 {AUTH_FILE}...")
            context.storage_state(path=AUTH_FILE)
            print(f"✅ 认证信息已保存!")

            # 备份旧文件（可选）
            if os.path.exists(f"{AUTH_FILE}.bak"):
                os.remove(f"{AUTH_FILE}.bak")

            print(f"\n{'='*60}")
            print("🎉 登录成功！现在可以运行上传脚本了。")
            print(f"{'='*60}")

            return True

        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断操作")
            return False
        except Exception as e:
            print(f"\n\n❌ 发生错误: {e}")
            return False
        finally:
            # 询问是否关闭浏览器
            try:
                input("\n按 [回车键] 关闭浏览器...")
            except:
                pass
            browser.close()


def check_auth_status():
    """检查当前认证文件的状态"""
    if not os.path.exists(AUTH_FILE):
        print(f"❌ 未找到认证文件: {AUTH_FILE}")
        return False

    print(f"✅ 找到认证文件: {AUTH_FILE}")
    file_size = os.path.getsize(AUTH_FILE)
    print(f"   文件大小: {file_size} 字节")

    import time

    mod_time = os.path.getmtime(AUTH_FILE)
    mod_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mod_time))
    print(f"   最后修改: {mod_time_str}")

    return True


def main():
    print("=" * 60)
    print("🔐 Eudic 登录工具")
    print("=" * 60 + "\n")

    # 显示浏览器路径
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "默认位置")
    print(f"🏠 Playwright 浏览器路径: {browsers_path}")
    print()

    # 检查现有认证状态
    has_auth = check_auth_status()

    if has_auth:
        print("\n当前已有认证文件。")
        action = input("是否要重新登录以更新认证? (y/n): ")
        if action.lower() != "y":
            print("取消操作")
            return

        # 备份现有文件
        import shutil

        backup_path = f"{AUTH_FILE}.bak"
        shutil.copy(AUTH_FILE, backup_path)
        print(f"📦 已备份旧文件到: {backup_path}\n")

    # 执行登录
    success = manual_login()

    if success:
        print("\n✅ 所有操作完成！")
    else:
        print("\n❌ 操作未完成")


if __name__ == "__main__":
    main()
