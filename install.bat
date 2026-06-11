@echo off
cd /d %~dp0

echo ========================================
echo 正在安装智能银行询证函生成助手依赖
echo ========================================

py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m playwright install chromium

echo.
echo ========================================
echo 安装完成
echo ========================================
pause