#!/bin/bash

cd "$(dirname "$0")" || exit 1

VENV_PYTHON="./.venv/bin/python"
MAIN_FILE="main.py"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ 未找到虚拟环境：$VENV_PYTHON"
    echo "请先在当前目录创建并安装依赖。"
    exit 1
fi

export PLAYWRIGHT_BROWSERS_PATH="$HOME/.playwright_browsers"

echo "📂 工作目录: $(pwd)"
echo "🐍 Python: $VENV_PYTHON"
echo "🏠 Playwright 浏览器路径: $PLAYWRIGHT_BROWSERS_PATH"
if [ "$#" -eq 0 ]; then
    echo "🚀 运行模式: all (默认 下载 + 上传)"
else
    echo "🚀 运行参数: $*"
fi
echo "----------------------------------------"

"$VENV_PYTHON" "$MAIN_FILE" "$@"
RET=$?

if [ $RET -eq 0 ]; then
    echo "✅ 任务正常结束。"
else
    echo "❌ 任务失败，退出码: $RET"
fi

exit $RET
