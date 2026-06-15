@echo off
chcp 65001 >nul
title Study AI — First Time Setup

echo.
echo ╔══════════════════════════════════════════╗
echo ║       Study AI — প্রথমবার Setup         ║
echo ╚══════════════════════════════════════════╝
echo.

:: .env তৈরি করো
if not exist .env (
    copy .env.example .env
    echo ✅ .env file তৈরি হয়েছে
) else (
    echo ℹ  .env আগে থেকেই আছে
)

:: packages install করো
echo.
echo ⏳ Python packages install হচ্ছে...
pip install -r requirements.txt
echo.

:: folders তৈরি করো
if not exist data mkdir data
if not exist uploads mkdir uploads
if not exist split_pdfs mkdir split_pdfs
if not exist cq_data mkdir cq_data
echo ✅ Folders তৈরি হয়েছে

echo.
echo ════════════════════════════════════════════
echo ✅ Setup সম্পন্ন!
echo.
echo এখন:
echo  1. .env ফাইল খুলো (Notepad দিয়ে)
echo  2. GEMINI_API_KEY_1 এ তোমার Gemini key বসাও
echo  3. run.bat চালাও
echo ════════════════════════════════════════════
pause
