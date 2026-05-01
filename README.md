# Turing Screen - Gamer Panel Hub 🎮

> Transforme o seu pequeno display IPS USB-C em um verdadeiro painel geek de mesa!

O Gamer Panel Hub é um servidor desenvolvido em Python + Flask que empurra atualizações diretamente para a sua telinha secundária (como as Turing Smart Screens). Funciona 100% em **background (segundo plano)** sem janelas pretas irritantes rodando, com uma **Interface Web Dashboard** acessível de qualquer dispositivo na sua rede local para você fazer modificações em tempo real!

![Painel Web (Dashboard)](./templates/index.html) <!-- Apenas para ilustrar -->

## 🌟 Funcionalidades Integradas
Tudo operando num loop contínuo e inteligente:
* **🆓 Jogos Grátis (API GamerPower):** Mostra os jogos da Epic Games e Steam que estão 100% de graça!
* **🌍 Reddit (RSS):** Puxa diretamente os tops do dia de subreddits da sua escolha (Ex: `r/SBCGaming`, `r/PiratedGames`).
* **📰 GameVicio News (Scraping):** Extrai as principais manchetes frescas do maior site de games para exibir com imagenzinhas de capa!
* **🔌 Autoconexão COM:** Esqueça de adivinhar `COM9` ou `COM4`, o software busca a telinha nativamente e conecta nela.
* **⚡ Live Preview Web:** Veja o que está passando na telinha através do seu navegador com 1 segundo de atraso e controle os módulos por switches na tela.

## 🛠 Como Instalar

1. Clone o repositório ou baixe o ZIP.
2. Dê dois cliques em **`instalar_dependencias.bat`**. O arquivo se encarregará de atualizar o `pip` e baixar tudo do `requirements.txt` (Flask, PyInstaller, Pillow, Requests, etc).

## 🚀 Como Usar

### 👨‍💻 Modo Editor/Terminal (Desenvolvimento)
Rode direto via terminal:
```bash
python meu_painel.py
```
Acesse em seu navegador `http://localhost:5000`.

### 🎮 Modo EXE Oculto (Recomendado)
Para deixar rodando nativamente:
1. Dê 2 cliques em **`construir_exe.bat`**. Ele vai pegar todos os pacotes e empilhar numa aplicação única e silenciosa através do *PyInstaller*.
2. Ao finalizar, vá na pasta `/dist/meu_painel/` gerada, dê 2 cliques no `meu_painel.exe`.
3. Pronto! Acesse no navegador `http://localhost:5000` para configurar tudo invisivelmente.

---
**Nota:** Este projeto utiliza a incrível biblioteca base (pasta `library/`) proveniente do projeto original *turing-smart-screen-python (mathoudebine)* para fazer a comunicação direta via driver USB com os displays LCD Rev.A.
