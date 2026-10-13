@echo off
title �g���[�h������ �b �͂��߂�
cd /d "%~dp0"
cls

echo.
echo  ============================================================
echo    �g���[�h������  �ڑ��c�[��
echo  ============================================================
echo.
echo    �͂��߂Ă̏��������܂��B���̃t�@�C�����J���͍̂ŏ���1�񂾂��ł��B
echo    �o�߂�������悤�ɁA���̉�ʂɂ͓r���̗l�q���o���Ă��܂��B
echo    ������̓T�C�g�̃{�^�������łȂ���܂��i��ʂ͏o�܂���j�B
echo.
echo  ------------------------------------------------------------
echo.

set "LOCALMODE="
set "HASCURL="
where curl >nul 2>&1
if not errorlevel 1 set "HASCURL=1"

REM ============================================================
REM  1/5  MT5 ���N�����ă��O�C�����Ă��邩
REM ============================================================
echo   [1/5]  MT5 �̊m�F
tasklist /fi "imagename eq terminal64.exe" 2>nul | find /i "terminal64.exe" >nul
if errorlevel 1 (
  echo.
  echo          MT5 ���܂��N�����Ă��܂���B
  echo          MT5 ���J���āA�����ʂ�����Ƀ��O�C�����Ă��������B
  echo          �i�����ԍ��� MT5 �̍���ɏo�Ă���Α��v�ł��j
  echo.
  echo          ���O�C���ł����� Enter �������Ă�������...
  pause >nul
) else (
  echo          OK  MT5 �͋N�����Ă��܂�
)
echo.

REM ============================================================
REM  2/5  Python �����邩
REM ============================================================
echo   [2/5]  Python �̊m�F
where py >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [!]  Python �������Ă��܂���B
  echo.
  echo        https://www.python.org ���� 64bit �ł����Ă��������B
  echo        �C���X�g�[����ʂ́uAdd python.exe to PATH�v��
  echo        �K���`�F�b�N�����Ă��������B
  echo.
  echo        ����I�������A���̃t�@�C����������x�J���Ă��������B
  echo.
  pause
  exit /b 1
)
echo          OK  Python �͂���܂�
echo.

REM ============================================================
REM  3/5  �͂��߂Ă̏����i2��ڂ���͔�΂��܂��j
REM ============================================================
echo   [3/5]  �K�v�Ȃ��̂̏���
if exist bridge\venv\Scripts\python.exe (
  echo          OK  ��������
) else (
  echo          �͂��߂Ă̏��������Ă��܂��B3���قǂ�����܂�...
  py -3 -m venv bridge\venv
  if errorlevel 1 (
    echo.
    echo   [!]  �����Ɏ��s���܂����BPython �� 64bit �ł��m�F���Ă��������B
    echo.
    pause
    exit /b 1
  )
  bridge\venv\Scripts\python.exe -m pip install --upgrade pip -q
  bridge\venv\Scripts\python.exe -m pip install -q -r bridge\requirements.txt
  if errorlevel 1 (
    echo.
    echo   [!]  �K�v�Ȃ��̂������܂���ł����B
    echo        �C���^�[�l�b�g�ɂȂ����Ă��邩�m�F���Ă��������B
    echo.
    pause
    exit /b 1
  )
  echo          OK  �����ł��܂���
)
echo.

REM ============================================================
REM  4/5  �ǂ���œ�������
REM ============================================================
echo   [4/5]  �Ȃ���
echo.
echo            ���̂܂� Enter ... �g���[�h�������̃T�C�g�ɂȂ��i�ӂ��͂�����j
echo            1 ������ Enter ... �e�X�g�i���̃p�\�R���̒������BNode.js ���v��܂��j
echo.
set "MODE=2"
set /p MODE=         Enter �������Ă�������:
echo.

if not "%MODE%"=="1" goto HONBAN

REM ------------------------------------------------------------
REM  �e�X�g �c ���p����ʂ��A���̃p�\�R���̒��œ�����
REM ------------------------------------------------------------
set "LOCALMODE=1"
where node >nul 2>&1
if errorlevel 1 (
  echo   [!]  Node.js �������Ă��܂���B
  echo.
  echo        �e�X�g�́A���̃p�\�R���̒��ɒ��p�T�[�o�[�𗧂Ă�̂�
  echo        Node.js ���v��܂��Bhttps://nodejs.org �� LTS �ł����āA
  echo        ���̃t�@�C����������x�J���Ă��������B
  echo.
  echo        ���ꂸ�ɐi�߂�Ȃ�A�������� 2�i�{�Ԃ̃T�C�g�j��I��ł��������B
  echo.
  pause
  exit /b 1
)

REM ��ʂ����ɂ������p�i.env ��� .env.local ���D�悳��܂��j
> .env.local echo VITE_RELAY_URL=ws://localhost:8080/app
REM �u���b�W���Ȃ����p�Bbridge\.env ���ۂ��Ə��������ƁA�T�C�g����
REM �󂯎���������i���ID�j�������Ă��܂��̂ŁA�ڑ����1���ڂ�������
set "RELAY=ws://127.0.0.1:8080/bridge"

if not exist server\node_modules (
  echo          ���p�T�[�o�[�̏��������Ă��܂��B����������܂�...
  call npm install --prefix server --silent
)
if not exist node_modules (
  echo          ��ʂ̏��������Ă��܂��B����������܂�...
  call npm install --silent
)

echo          ���p�T�[�o�[�Ɖ�ʂ��A�����ŋN�����܂�...
wscript "%~dp0tools\run-hidden.vbs" "cmd /c npm start" "%~dp0server"
wscript "%~dp0tools\run-hidden.vbs" "cmd /c npm run dev" "%~dp0"
set "SITE=http://localhost:5181"

REM ���p��������܂ő҂i�ő�30�b�j
if not defined HASCURL (
  timeout /t 10 /nobreak >nul
  goto CONNECT
)
set /a TRY=0
:WAITRELAY
curl -s -o nul -m 2 http://127.0.0.1:8080/health
if not errorlevel 1 goto RELAYOK
set /a TRY+=1
if %TRY% geq 15 goto RELAYNG
timeout /t 2 /nobreak >nul
goto WAITRELAY
:RELAYOK
echo          OK  ���p�T�[�o�[�������܂���
goto CONNECT
:RELAYNG
echo   [!]  ���p�T�[�o�[�������オ��܂���ł����B
echo        Node.js �������������Ă��邩�m�F���Ă��������B
echo        ���̂܂ܑ�����Ȃ� Enter �������Ă�������...
pause >nul
goto CONNECT

REM ------------------------------------------------------------
REM  �{�� �c �N���E�h�̒��p�ɂȂ�
REM ------------------------------------------------------------
:HONBAN
REM �e�X�g�̂Ƃ��ɏ������u��ʂ̐ڑ���v�͖{�Ԃł͎ז��ɂȂ�̂ŏ���
if exist .env.local del .env.local
set "RELAY=wss://kinyu-relay.onrender.com/bridge"
set "SITE=https://kinyu-kenkyujo-dec-opt.vercel.app"
echo          �ڑ���: �N���E�h�̒��p�T�[�o�[
if not defined HASCURL goto CONNECT
echo          �͂����m�F���Ă��܂��B���΂炭���҂���������...
curl -s -m 45 -o nul https://kinyu-relay.onrender.com/health
if errorlevel 1 (
  echo.
  echo   [!]  �N���E�h�̒��p�T�[�o�[�ɓ͂��܂���ł����B
  echo        Render �̒��p���܂������Ă��Ȃ��\��������܂��B
  echo        ���̏ꍇ�� 1�i�e�X�g�j�Ŏ����Ă��������B
  echo.
  echo        ���̂܂ܑ�����Ȃ� Enter �������Ă�������...
  pause >nul
) else (
  echo          OK  ���p�T�[�o�[�͓����Ă��܂�
)
goto CONNECT

REM ============================================================
REM  5/5  �Ȃ��iMT5�̊m�F�E�V�X�e���z�u�E�u���b�W�N���E�o�^�j
REM ============================================================
:CONNECT
echo.
echo   [5/5]  �Ȃ��܂�
echo  ------------------------------------------------------------
bridge\venv\Scripts\python.exe connect.py --console --relay %RELAY%
echo  ------------------------------------------------------------
echo.

REM �e�X�g�̂Ƃ��́A��ʂ������オ��̂�҂��Ă���J���i�ő�60�b�j
if not defined LOCALMODE goto OPENSITE
if not defined HASCURL (
  timeout /t 10 /nobreak >nul
  goto OPENSITE
)
echo   ��ʂ̏�����҂��Ă��܂�...
set /a TRY=0
:WAITSITE
curl -s -o nul -m 2 http://localhost:5181
if not errorlevel 1 goto OPENSITE
set /a TRY+=1
if %TRY% geq 30 goto SITENG
timeout /t 2 /nobreak >nul
goto WAITSITE
:SITENG
echo   [!]  ��ʂ������オ��܂���ł����B
echo        �ʂ̂��̂� 5181 �Ԃ��g���Ă���\��������܂��B
echo        Enter �������ƁA���̂܂܃u���E�U���J���Ă݂܂�...
pause >nul

:OPENSITE
echo   �T�C�g���J���܂�: %SITE%
start "" "%SITE%"

echo.
echo  ============================================================
echo    ��������T�C�g�Ŏ����܂�
echo.
echo      1. ��t�̃��C���N���b�N ���u�����ݒ���͂��߂�v
echo         �� ���b�ŘA�g�܂Ői�݂܂�
echo         �i�T�C�g�̏����ݒ�̓r���Ȃ�A���̂܂܎����Ő�ɐi�݂܂��j
echo      2. �A���S�i���������j���u�����������͂��߂�v�ŉғ�
echo      3. �u�����̐��сv�u�ߋ��̐��сv�u���܂̃|�W�V�����v
echo      4. �����i�`���[�g���́j���u�g���[�h��Y�킵�āv
echo.
echo    ������́A���̃t�@�C�����J���K�v�͂���܂���B
echo    �T�C�g�̃{�^�������łȂ���܂��B
echo    �i�p�\�R���𗧂��グ�������Ƃ��������łȂ���܂��j
echo.
echo    �~�߂����Ƃ�:  tools\��~����.bat
echo    �A�g����߂�Ƃ�: tools\�A�g����������.bat
echo.
echo    ���܂������Ȃ��Ƃ��̋L�^:
echo      %%LOCALAPPDATA%%\AITrader\connect.log
echo  ============================================================
echo.
echo    ���̉�ʂ͕��Ă����v�ł��i�����œ��������܂��j�B
echo.
pause
