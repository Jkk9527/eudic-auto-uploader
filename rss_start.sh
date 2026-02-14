#!/bin/bash

# 1. 切到脚本所在目录
cd "$(dirname "$0")"
echo "📂 工作目录已切换至：$(pwd)"

# 2. 只用本项目 .venv 里的 Python
VENV_PYTHON="./.venv/bin/python"

# 3. 如果 .venv 不存在，直接报错退出
if [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ 未找到虚拟环境：$VENV_PYTHON"
    echo "请先在当前目录创建并安装依赖"
    read -p "按 [回车键] 关闭窗口..."
    exit 1
fi

# ==========================================
# ✨ [新增] 设置 Playwright 浏览器的新家
# 把它指向用户目录下的 .playwright_browsers 文件夹
# 这样 CleanMyMac 就不会把它当成垃圾缓存删掉了
# ==========================================
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.playwright_browsers"

echo "🐍 使用虚拟环境 Python: $VENV_PYTHON"
echo "🏠 Playwright 浏览器路径: $PLAYWRIGHT_BROWSERS_PATH"
echo "----------------------------------------"
echo "🚀 正在启动自动上传助手..."

# 4. 用虚拟环境里的 Python 运行主脚本
"$VENV_PYTHON" main.py
RET=$?

# 5. 根据返回码给出提示
if [ $RET -eq 0 ]; then
    echo "✅ 程序执行成功！"
else
    echo "❌ 程序执行出错，请检查上方报错信息。"
    # ✨ [新增提示] 如果是因为找不到浏览器报错，提示用户安装
    echo "💡 提示：如果是提示 'Executable doesn't exist'，请手动运行一次安装命令。"
fi

echo "🏁 脚本运行结束，已为你保留终端窗口。"
echo "----------------------------------------"

# ✨ 关键修改：启动一个新的交互式 Bash
# -i 表示 interactive（交互式）
exec bash -i
