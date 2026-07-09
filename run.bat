@echo off
echo Starting FAQ Chatbot Server...
echo.

REM Check if virtual environment exists
if not exist .venv (
    echo ERROR: Virtual environment not found!
    echo Please run setup.bat first to install dependencies.
    pause
    exit /b 1
)

REM Check if .env file exists
if not exist .env (
    echo WARNING: .env file not found!
    echo Creating from template...
    copy .env.example .env
    echo.
    echo IMPORTANT: Please edit .env and add your GROQ_API_KEY
    echo Then run this script again.
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Start the server
echo Server starting at http://localhost:8000
echo Press Ctrl+C to stop the server
echo.
uvicorn main:app --reload --port 8000
