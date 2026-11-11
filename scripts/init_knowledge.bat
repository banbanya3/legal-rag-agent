@echo off
chcp 65001 >nul
echo 构建法律知识库索引（首次约 8-12 分钟）
cd /d "%~dp0..\backend"
python init_knowledge.py --build
pause
