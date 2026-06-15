@echo off
chcp 65001 >nul
title Study AI — Local Server

echo.
echo ╔══════════════════════════════════════════╗
echo ║         Study AI — Local Mode           ║
echo ╚══════════════════════════════════════════╝
echo.

:: .env file আছে কিনা দেখো
if not exist .env (
    echo ❌ .env file পাওয়া যায়নি!
    echo.
    echo ➡  প্রথমে .env.example কপি করো:
    echo    copy .env.example .env
    echo.
    echo ➡  তারপর .env ফাইল খুলে Gemini API Key বসাও
    echo    GEMINI_API_KEY_1=তোমার_key_এখানে
    echo.
    pause
    exit /b 1
)

:: .env থেকে variable load করো
for /f "tokens=1,2 delims==" %%a in (.env) do (
    if not "%%a"=="" if not "%%a:~0,1%"=="#" (
        set "%%a=%%b"
    )
)

:: Python আছে কিনা দেখো
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python পাওয়া যায়নি!
    echo    https://python.org থেকে Python 3.10+ install করো
    pause
    exit /b 1
)

:: requirements install হয়েছে কিনা দেখো
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo ⏳ প্রথমবার — packages install হচ্ছে...
    pip install -r requirements.txt
    echo.
)

echo ✅ সার্ভার চালু হচ্ছে...
echo.
echo 🌐 Main App  :  http://localhost:5000
echo 🔧 Admin Panel:  http://localhost:5000/admin
echo.
echo বন্ধ করতে:  Ctrl+C চাপো
echo ════════════════════════════════════════════
echo.

python app.py
pause
