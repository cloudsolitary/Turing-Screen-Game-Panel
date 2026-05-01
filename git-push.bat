@echo off
title Atualizador do GitHub - Turing Screen
color 0A

echo ==========================================
echo   Atualizador do GitHub - Turing Screen
echo ==========================================
echo.

:: Pede a mensagem do commit para o usuario
set /p msg="Digite a mensagem do commit (ou aperte Enter para padrao): "

:: Se o usuario nao digitar nada, usa a mensagem padrao
if "%msg%"=="" set msg=Atualizacao automatica

echo.
echo [1/3] Adicionando arquivos modificados...
git add .

echo.
echo [2/3] Criando o pacote da versao (Commit)...
git commit -m "%msg%"

echo.
echo [3/3] Enviando para o repositorio (Push)...
git push

echo.
echo ==========================================
echo   PROCESSO CONCLUIDO COM SUCESSO!
echo ==========================================
pause