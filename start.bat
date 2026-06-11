@echo off
cd /d %~dp0

echo ========================================
echo 正在启动智能银行询证函生成助手
echo ========================================

py -m streamlit run app.py

pause