@echo off
cd /d "%~dp0"
echo ============================================
echo   Policy Reaction Simulator - Setup
echo ============================================
echo.
echo [1/3] Installing libraries (can take a few minutes)...
pip install -r requirements.txt
echo.
if not exist ".env" (
    echo [2/3] Creating .env from template...
    copy ".env.example" ".env" >nul
    echo.
    echo   *** ACTION NEEDED ***
    echo   Open the .env file, paste your OpenAI API key, save it.
    echo   Then double-click setup.bat again.
    echo.
    pause
    exit /b
)
echo [2/3] .env found.
echo.
echo [3/3] Checking environment...
python check.py
echo.
echo Done. Press any key to close.
pause >nul
