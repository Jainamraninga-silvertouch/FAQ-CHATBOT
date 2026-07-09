@echo off
echo ================================
echo FAQ Chatbot Setup Script
echo ================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10 or higher from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Step 1: Creating virtual environment...
if exist .venv (
    echo Virtual environment already exists, skipping...
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo Virtual environment created successfully!
)

echo.
echo Step 2: Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

echo.
echo Step 3: Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo Step 4: Checking environment configuration...
if exist .env (
    echo .env file found!
) else (
    echo WARNING: .env file not found
    echo Creating .env from template...
    copy .env.example .env
    echo.
    echo IMPORTANT: Please edit .env and add your GROQ_API_KEY
    echo Get your API key from: https://console.groq.com/keys
)

echo.
echo ================================
echo Setup completed successfully!
echo ================================
echo.
echo Next steps:
echo 1. Edit .env and add your GROQ_API_KEY
echo 2. Activate the virtual environment: .venv\Scripts\activate
echo 3. Run the server: uvicorn main:app --reload --port 8000
echo 4. Open http://localhost:8000 in your browser
echo.
pause
