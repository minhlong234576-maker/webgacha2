@echo off
REM ==========================================================================
REM  JellyVale Gacha - Deploy qua Cloudflare Tunnel (Quick Tunnel)
REM
REM  Khoi dong:
REM    1) Uvicorn (web + bot + roulette nen) tren 127.0.0.1:8080
REM    2) cloudflared Quick Tunnel -> public URL trong khoang 10-20 giay
REM
REM  Xuat hienh:
REM    - Web local : http://127.0.0.1:8080
REM    - Web public: https://<random>.trycloudflare.com   (in ra o log)
REM
REM  Luu y:
REM    - Quick Tunnel lay URL ngau nhien moi lan chay. Muon dung domain that,
REM      xem HUONG_DAN_DU_AN.md phan "Cloudflare Tunnel".
REM    - Nho BAT GACHA_TRUST_PROXY=true va SESSION_HTTPS_ONLY=true trong .env
REM      khi public ra Internet (da them san trong .env mau).
REM ==========================================================================
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo [1/4] Tao moi virtualenv .venv ...
  python -m venv .venv
  if errorlevel 1 goto :fail
)
call .venv\Scripts\activate.bat

REM --- Cloudflare CLI ---
set "CF=C:\Program Files (x86)\cloudflared\cloudflared.exe"
if not exist "%CF%" set "CF=cloudflared"
"%CF%" --version >nul 2>&1
if errorlevel 1 (
  echo [CANH BAO] Khong tim thay cloudflared. Cai dat tai:
  echo   winget install --id Cloudflare.cloudflared
  goto :fail
)

REM --- Giu server + tunnel chay khi dong cua so nay ---
echo [2/4] Khoi dong Uvicorn tren 127.0.0.1:8080 ...
start "JellyVale Web" /min cmd /c "call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 > uvicorn8080.log 2> uvicorn8080.err.log"

REM Cho web kip khoi dong truoc khi tunnel tro toi
timeout /t 8 /nobreak >nul

echo [3/4] Khoi dong Cloudflare Quick Tunnel ...
start "JellyVale Tunnel" /min cmd /c "call ""%CF%"" tunnel --url http://127.0.0.1:8080 --no-autoupdate > cloudflared.log 2> cloudflared.err.log"

REM --- Tim URL public ---
echo [4/4] Dang cho Cloudflare cap URL ...
set "URL="
for /l %%i in (1,1,30) do (
  if not defined URL (
    for /f "tokens=2 delims= " %%a in ('findstr /r /c:"https://.*trycloudflare.com" cloudflared.err.log 2^>nul') do (
      if not defined URL set "URL=%%a"
    )
    if not defined URL timeout /t 2 /nobreak >nul
  )
)

if not defined URL (
  echo [LOI] Khong lay duoc URL. Xem cloudflared.err.log va cloudflared.log.
  goto :fail
)

echo.
echo ==============================================================
echo   DA DEPLOY THANH CONG ^(Cloudflare Tunnel^)
echo.
echo   Web local : http://127.0.0.1:8080
echo   Web public: %URL%
echo.
echo   Nhan Ctrl+C de dung. Server + tunnel chay o cua so rieng.
echo ==============================================================
echo.
echo Nhan phim bat ky de mo trinh duyet den %URL%
pause >nul
start "" "%URL%"
goto :eof

:fail
echo.
echo [LOI] Deploy that bai. Xem log trong thu muc hien tai.
pause
exit /b 1
