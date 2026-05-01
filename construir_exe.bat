@echo off
echo =======================================
echo     Construindo o Hub Gamer (.exe)
echo =======================================
echo.
echo Certifique-se de que instalou o pyinstaller e o flask:
echo pip install pyinstaller flask
echo.
echo Compilando em modo invisivel (background)...
pyinstaller --noconfirm --onedir --windowed --add-data "templates;templates/" --add-data "painel_config.json;." meu_painel.py
echo.
echo =======================================
echo Construcao finalizada! O executavel esta na pasta /dist/meu_painel/
echo.
pause
