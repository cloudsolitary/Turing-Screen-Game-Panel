@echo off
echo =======================================
echo     Instalador de Dependências
echo =======================================
echo.
echo Verificando e atualizando o Pip...
python -m pip install --upgrade pip
echo.
echo Instalando todos os modulos necessários (incluindo Flask, PyInstaller, Pillow, etc)...
pip install -r requirements.txt
echo.
echo =======================================
echo Instalação concluida!
echo Agora voce pode abrir o "construir_exe.bat" ou rodar o script no terminal.
echo =======================================
pause
