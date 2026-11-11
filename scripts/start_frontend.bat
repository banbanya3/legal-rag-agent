@echo off
chcp 65001 >nul
echo ============================================
echo   法眼 · 法律知识库智能问答系统 - 前端
echo ============================================
cd /d "%~dp0..\frontend"
if not exist node_modules (
  echo 首次运行，正在安装依赖...
  call npm install
)
call npm run dev
pause
