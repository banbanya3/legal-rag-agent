@echo off
chcp 65001 >nul
echo ============================================
echo   法眼 · 法律知识库智能问答系统 - 后端（FastAPI）
echo ============================================
cd /d "%~dp0..\backend"
echo 接口文档: http://127.0.0.1:5000/docs
python main.py
pause
