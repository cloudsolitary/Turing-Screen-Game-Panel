@echo off
chcp 65001 >nul
title Gamer Panel Hub - Atualizador
color 0A

echo.
echo =============================================
echo    GAMER PANEL HUB - ATUALIZADOR AUTOMATICO
echo =============================================
echo.

:: Verifica se Git está instalado
where git >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] Git nao encontrado no sistema.
    echo.
    echo     Para atualizar, voce precisa do Git instalado:
    echo     https://git-scm.com/download/win
    echo.
    echo     Ou baixe o ZIP manualmente em:
    echo     https://github.com/cloudsolitary/Turing-Screen-Game-Panel/archive/refs/heads/main.zip
    echo.
    pause
    exit /b
)

:: Verifica se é um repositório Git
if not exist ".git" (
    echo [!] Esta pasta nao e um repositorio Git.
    echo     Convertendo para repositorio Git...
    echo.
    git init
    git remote add origin https://github.com/cloudsolitary/Turing-Screen-Game-Panel.git
    git fetch origin
    git reset --hard origin/main
    git branch --set-upstream-to=origin/main main
    echo.
    echo [OK] Repositorio configurado com sucesso!
    echo.
) else (
    echo [*] Buscando atualizacoes no GitHub...
    echo.
    git fetch origin

    :: Verifica se há atualizações
    for /f %%i in ('git rev-parse HEAD') do set LOCAL=%%i
    for /f %%i in ('git rev-parse origin/main') do set REMOTE=%%i

    if "%LOCAL%"=="%REMOTE%" (
        echo =============================================
        echo   [OK] Voce ja esta na versao mais recente!
        echo =============================================
        echo.
        pause
        exit /b
    )

    echo [*] Nova versao encontrada! Atualizando...
    echo.
    git pull origin main
)

echo.
echo =============================================
echo   [OK] ATUALIZADO COM SUCESSO!
echo =============================================
echo.
echo   Agora rode o "instalar_dependencias.bat"
echo   caso tenha novas bibliotecas, e depois
echo   inicie o script com: python meu_painel.py
echo.
pause
