import os
import sys
import sys
sys.stdout.reconfigure(encoding='utf-8')

import time
import requests
import feedparser
import textwrap
import re
import json
import threading
from io import BytesIO
import base64
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps
from flask import Flask, render_template, request, jsonify, send_file, Response

# --- CONFIGURAÇÃO DE CAMINHO ---
app = Flask(__name__)
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
sys.path.append(diretorio_atual)

try:
    from library.lcd.lcd_comm_rev_a import LcdCommRevA
except Exception as e:
    print(f"❌ Erro Crítico do LcdCommRevA: {e}")
    # Define como None para não lançar NameError e o painel Web continuar online
    LcdCommRevA = None

# ==========================================
# VARIÁVEIS GLOBAIS E ESTADO
# ==========================================
ARQUIVO_CONFIG = os.path.join(diretorio_atual, 'painel_config.json')

# Estado padrao que será sobrescrito ao ler o JSON
estado_app = {
    "modulo_jogos": True,
    "jogos_plataforma": "todas",
    "modulo_noticias": True,
    "modulo_reddit": True,
    "modulo_promocoes": True,
    "promo_generos": ["todos"],
    "lista_subreddits": ['emulation', 'PiratedGames', 'gadgets', 'SBCGaming'],
    "tempo_slide": 12,
    "porta_com": "AUTO",
    "rotacao": -90
}

# Variável para armazenar o preview
preview_lock = threading.Lock()
preview_bytes = None

HEADERS_NAVEGADOR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# ==========================================
# FUNÇÕES DE CONFIGURAÇÃO
# ==========================================
def carregar_configuracao():
    global estado_app
    if os.path.exists(ARQUIVO_CONFIG):
        try:
            with open(ARQUIVO_CONFIG, 'r', encoding='utf-8') as f:
                config_salva = json.load(f)
                estado_app.update(config_salva)
        except Exception as e:
            print(f"Erro ao ler config: {e}")

def salvar_configuracao():
    with open(ARQUIVO_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(estado_app, f, indent=4)

# ==========================================
# BUSCADORES DE DADOS
# ==========================================
def buscar_jogos_gratis():
    if not estado_app['modulo_jogos']: return []
    
    url = "https://www.gamerpower.com/api/giveaways?type=game"
    plat_filter = estado_app.get('jogos_plataforma', 'todas').lower()
    
    # A API não documenta bem filtros compostos. Busca tudo de PC e filtramos manual:
    url += "&platform=pc"
        
    try:
        res = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=10).json()
        jogos = []
        titulos_vistos = set()
        
        for j in res:
            plat = j.get('platforms', '')
            titulo = j.get('title', '')
            
            loja = None
            if 'Steam' in plat: loja = 'Steam'
            elif 'Epic' in plat: loja = 'Epic Games'
            
            if not loja: continue # Ignora jogos que não são nem Steam nem Epic (ex: GOG, Itchio)
            
            if plat_filter == 'steam' and loja != 'Steam': continue
            if plat_filter == 'epic' and loja != 'Epic Games': continue
            
            if titulo not in titulos_vistos:
                titulos_vistos.add(titulo)
                
                jogos.append({
                    'tipo': 'JOGO', 
                    'titulo': titulo, 
                    'img': j.get('thumbnail', ''),
                    'preco': j.get('worth', 'N/A'),
                    'loja': loja
                })
            if len(jogos) >= 5: break
        return jogos
    except: return []

import random

# Cache de gêneros por AppID da Steam (evita requests repetidos)
_cache_generos = {}

def obter_generos_steam(appid):
    """Consulta a Steam Storefront API e o SteamSpy para obter uma lista completa de tags/gêneros."""
    if not appid:
        return []
    if appid in _cache_generos:
        return _cache_generos[appid]
    
    tags_encontradas = set()
    
    # 1. Tenta Steam Storefront API (Gêneros e Categorias)
    try:
        url_steam = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        r = requests.get(url_steam, timeout=5).json()
        dados = r.get(str(appid), {})
        if dados.get('success') and 'data' in dados:
            gen = [g['description'] for g in dados['data'].get('genres', [])]
            cat = [c['description'] for c in dados['data'].get('categories', [])]
            for t in gen + cat: tags_encontradas.add(t)
    except: pass
    
    # 2. Tenta SteamSpy para "User Tags" (onde fica Metroidvania, Roguelike, etc.)
    try:
        url_spy = f"https://steamspy.com/api.php?request=appdetails&appid={appid}"
        r_spy = requests.get(url_spy, timeout=5).json()
        tags_spy = r_spy.get('tags', {})
        if isinstance(tags_spy, dict):
            for t in tags_spy.keys(): tags_encontradas.add(t)
    except: pass

    final_tags = list(tags_encontradas)
    _cache_generos[appid] = final_tags
    return final_tags

# Gêneros e Categorias comuns da Steam para auxílio no UI (opcional)
GENEROS_STEAM_POPULARES = [
    "Action", "Adventure", "RPG", "Strategy", "Simulation", "Sports", "Racing", 
    "Indie", "Casual", "Massively Multiplayer", "Single-player", "Multi-player", "Co-op",
    "Metroidvania", "Platformer", "Action-Adventure", "Horror", "Survival"
]

def buscar_promocoes_steam():
    if not estado_app.get('modulo_promocoes', True): return []
    
    # storeID=1 (Steam), onSale=1, metacritic=80+
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=1&onSale=1&metacritic=80&steamRating=80&pageSize=60"
    
    filtros = [f.lower() for f in estado_app.get('promo_generos', ['todos'])]
    selecionou_todos = 'todos' in filtros or not filtros
    
    try:
        res = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=10).json()
        candidatos = []
        
        # Se tem filtro de gênero, precisa consultar cada AppID
        if not selecionou_todos:
            random.shuffle(res)
            for p in res:
                if len(candidatos) >= 5:
                    break
                appid = p.get('steamAppID', '')
                tags_jogo = [t.lower() for t in obter_generos_steam(appid)]
                
                # Verifica se existe intersecção entre filtros e tags do jogo
                if any(f in tags_jogo for f in filtros):
                    candidatos.append(p)
        else:
            # Sem filtro: embaralha e pega 5
            if len(res) > 5:
                candidatos = random.sample(res, 5)
            else:
                candidatos = res
        
        promos = []
        for p in candidatos:
            try:
                titulo = p.get('title', '')
                preco_normal = p.get('normalPrice', '0')
                preco_venda = p.get('salePrice', '0')
                savings = p.get('savings', '0')
                desconto = float(savings) if savings else 0
                appid = p.get('steamAppID', '')
                
                img_url = p.get('thumb', '')
                if appid:
                    img_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"

                promos.append({
                    'tipo': 'STEAM_PROMO', 
                    'titulo': titulo, 
                    'img': img_url,
                    'preco_normal': preco_normal,
                    'preco': preco_venda,
                    'desconto': f"-{int(desconto)}%",
                    'score': p.get('metacriticScore', '80')
                })
            except Exception as e:
                print(f"Erro ao processar item de promoção: {e}")
            
        return promos
    except Exception as e:
        print(f"Erro ao buscar promoções Steam: {e}")
        return []

def buscar_gamevicio():
    if not estado_app['modulo_noticias']: return []
    
    url = "https://www.gamevicio.com/"
    try:
        res = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        noticias = []
        titulos_vistos = set()
        
        cards = soup.find_all('div', class_=re.compile(r"e-loop-item"))
        
        for card in cards:
            if 'swiper-slide' in card.get('class', []): continue
                
            img = card.find('img')
            if not img: continue
                
            src = ""
            for attr in ['data-lazy-src', 'data-src', 'src']:
                val = img.get(attr, '')
                if val and val.startswith('http'):
                    src = val
                    break

            h2 = card.find('h2', class_=re.compile(r"elementor-heading-title"))
            if not h2: continue
            titulo = h2.get_text(strip=True)

            tag = "#NOTÍCIA"
            tags_encontradas = card.find_all('a', rel='tag')
            if tags_encontradas:
                tag_texto = tags_encontradas[-1].get_text(strip=True)
                tag = f"#{tag_texto.upper()}"

            if src and titulo and (titulo not in titulos_vistos):
                titulos_vistos.add(titulo)
                noticias.append({
                    'tipo': 'GAMEVICIO', 
                    'titulo': titulo, 
                    'img': src,
                    'tag': tag
                })
            if len(noticias) >= 5: break
        return noticias
    except: return []

def buscar_reddit_multiplos():
    if not estado_app['modulo_reddit']: return []
    
    posts_finais = []
    titulos_vistos = set()
    subs = estado_app.get('lista_subreddits', [])
    
    for subreddit in subs:
        url = f"https://www.reddit.com/r/{subreddit}/top.rss?t=day"
        try:
            resposta = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=10)
            feed = feedparser.parse(resposta.content)
            adicionados_neste_sub = 0
            
            for e in feed.entries:
                titulo = e.title
                if titulo not in titulos_vistos:
                    autor = e.author.replace('/u/', 'u/') if hasattr(e, 'author') else f'r/{subreddit}'
                    
                    img_url = None
                    if hasattr(e, 'media_thumbnail') and e.media_thumbnail:
                        img_url = e.media_thumbnail[0]['url']
                    else:
                        html_content = e.content[0].value if hasattr(e, 'content') else (e.summary if hasattr(e, 'summary') else "")
                        if html_content:
                            soup = BeautifulSoup(html_content, 'html.parser')
                            img_tag = soup.find('img')
                            if img_tag and img_tag.get('src'):
                                img_url = img_tag['src']
                    
                    titulos_vistos.add(titulo)
                    posts_finais.append({
                        'tipo': 'REDDIT', 
                        'titulo': titulo, 
                        'info': autor,
                        'img': img_url,
                        'sub': subreddit
                    })
                    adicionados_neste_sub += 1
                if adicionados_neste_sub >= 2: break
        except: continue
    return posts_finais

# ==========================================
# GERADOR DE UI
# ==========================================
def desenhar_texto_centralizado(draw, y, texto, fonte, cor_texto, cor_fundo=None):
    try:
        bbox = draw.textbbox((0, 0), texto, font=fonte)
        largura = bbox[2] - bbox[0]
        altura = bbox[3] - bbox[1]
    except AttributeError:
        largura = len(texto) * (fonte.size * 0.6)
        altura = fonte.size
    x = max(10, (480 - largura) / 2) 
    if cor_fundo:
        draw.rectangle([x - 10, y - 5, x + largura + 10, y + altura + 5], fill=cor_fundo)
    draw.text((x, y), texto, font=fonte, fill=cor_texto)

def desenhar_etiqueta_topo(draw, x, y, texto, fonte, cor_fundo):
    try:
        bbox = draw.textbbox((0, 0), texto, font=fonte)
        largura = bbox[2] - bbox[0]
        altura = bbox[3] - bbox[1]
    except AttributeError:
        largura = len(texto) * (fonte.size * 0.6)
        altura = fonte.size
    draw.rounded_rectangle([x, y, x + largura + 20, y + altura + 16], fill=cor_fundo, radius=4)
    draw.text((x + 10, y + 6), texto, font=fonte, fill=(255, 255, 255, 255))

def criar_layout(item):
    try:
        f_pequena = ImageFont.truetype("arial.ttf", 14)       
        f_plat = ImageFont.truetype("arialbd.ttf", 16)        
        f_tipo = ImageFont.truetype("arialbd.ttf", 18)        
        f_gratis = ImageFont.truetype("arialbd.ttf", 26)      
        f_titulo = ImageFont.truetype("arialbd.ttf", 20) 
    except:
        f_pequena = f_plat = f_tipo = f_gratis = f_titulo = ImageFont.load_default()

    rotacao = estado_app.get('rotacao', -90)

    # LAYOUT 1: JOGOS
    if item['tipo'] == 'JOGO':
        try:
            res = requests.get(item['img'], timeout=10)
            capa = Image.open(BytesIO(res.content)).convert("RGB")
            fundo = ImageOps.fit(capa, (480, 320), Image.Resampling.LANCZOS).convert('RGBA')
        except: fundo = Image.new('RGBA', (480, 320), color='#1e1e2e')

        camada = Image.new('RGBA', (480, 320), (0, 0, 0, 0))
        draw = ImageDraw.Draw(camada)

        draw.rounded_rectangle([340, 20, 460, 50], fill=(24, 24, 37, 220), radius=6)
        draw.text((355, 26), f"🎮 {item['loja']}", font=f_plat, fill=(203, 166, 247, 255))
        
        preco = item['preco']
        if preco != 'N/A' and preco != 'Free':
            draw.rounded_rectangle([310, 230, 460, 300], fill=(17, 17, 27, 230), radius=8)
            draw.text((325, 238), f"De: {preco}", font=f_pequena, fill=(166, 173, 200, 255))
            comp = len(preco) * 8 + 25
            draw.line([(325, 247), (325 + comp, 247)], fill=(243, 139, 168, 255), width=2)
            draw.text((325, 260), "GRÁTIS!", font=f_gratis, fill=(166, 227, 161, 255))
        else:
            draw.rounded_rectangle([320, 250, 460, 300], fill=(17, 17, 27, 230), radius=8)
            draw.text((335, 260), "GRÁTIS!", font=f_gratis, fill=(166, 227, 161, 255))

        img_final = Image.alpha_composite(fundo, camada).convert('RGB')
        return img_final.rotate(rotacao, expand=True)

    # LAYOUT 1.5: PROMOÇÕES STEAM
    elif item['tipo'] == 'STEAM_PROMO':
        try:
            from PIL import ImageFilter
            res = requests.get(item['img'], timeout=10)
            capa = Image.open(BytesIO(res.content)).convert("RGB")
            
            # Melhora Proporcionalidade: Fundo desfocado + arte centralizada proporcional
            # 1. Cria o fundo desfocado (preenche tudo)
            fundo_base = ImageOps.fit(capa, (480, 320), bleed=0.1)
            fundo = fundo_base.filter(ImageFilter.GaussianBlur(radius=15))
            
            # 2. Cria a camada da arte centralizada proporcionalmente (sem cortar)
            arte_proporcional = ImageOps.contain(capa, (440, 240)) # Deixa espaço para textos
            pos_x = (480 - arte_proporcional.width) // 2
            pos_y = 50 # Um pouco abaixo do topo
            
            fundo.paste(arte_proporcional, (pos_x, pos_y))
            fundo = fundo.convert('RGBA')
        except: fundo = Image.new('RGBA', (480, 320), color='#1e1e2e')

        camada = Image.new('RGBA', (480, 320), (0, 0, 0, 0))
        draw = ImageDraw.Draw(camada)

        # Selo Metacritic
        draw.rounded_rectangle([20, 20, 75, 50], fill=(250, 208, 0, 220), radius=6)
        draw.text((28, 26), f"M {item['score']}", font=f_plat, fill=(0, 0, 0, 255))

        # Loja Steam
        draw.rounded_rectangle([310, 20, 460, 50], fill=(24, 24, 37, 220), radius=6)
        draw.text((325, 26), "🎮 Promoção Steam", font=f_plat, fill=(137, 207, 240, 255))
        
        # Caixa de Preços
        draw.rounded_rectangle([250, 230, 460, 300], fill=(17, 17, 27, 230), radius=8)
        
        # Etiqueta de % Desconto
        draw.rounded_rectangle([260, 245, 335, 285], fill=(76, 175, 80, 255), radius=4)
        draw.text((265, 252), item['desconto'], font=f_titulo, fill=(255, 255, 255, 255))
        
        # Preço Cortado
        texto_de = f"De: ${item['preco_normal']}"
        draw.text((345, 238), texto_de, font=f_pequena, fill=(166, 173, 200, 255))
        comp = len(texto_de) * 8
        draw.line([(345, 247), (345 + comp, 247)], fill=(243, 139, 168, 255), width=2)
        
        # Preço Novo Promocional
        draw.text((345, 260), f"${item['preco']}", font=f_gratis, fill=(166, 227, 161, 255))

        img_final = Image.alpha_composite(fundo, camada).convert('RGB')
        return img_final.rotate(rotacao, expand=True)

    # LAYOUT 2: GAMEVICIO
    elif item['tipo'] == 'GAMEVICIO':
        try:
            res = requests.get(item['img'], timeout=10)
            capa = Image.open(BytesIO(res.content)).convert("RGB")
            fundo = ImageOps.fit(capa, (480, 320), Image.Resampling.LANCZOS).convert('RGBA')
        except: fundo = Image.new('RGBA', (480, 320), color='#000000')

        camada = Image.new('RGBA', (480, 320), (0, 0, 0, 0))
        draw = ImageDraw.Draw(camada)

        desenhar_etiqueta_topo(draw, 20, 20, item['tag'], f_plat, (211, 47, 47, 230))
        draw.rectangle([0, 220, 480, 320], fill=(0, 0, 0, 160))
        
        linhas_titulo = textwrap.wrap(item['titulo'], width=45)[:2]
        
        altura_linha = 26
        y_atual = 220 + (100 - (len(linhas_titulo) * altura_linha)) // 2

        for linha in linhas_titulo:
            desenhar_texto_centralizado(draw, y_atual, linha, f_titulo, cor_texto=(255, 255, 255, 255))
            y_atual += altura_linha

        img_final = Image.alpha_composite(fundo, camada).convert('RGB')
        return img_final.rotate(rotacao, expand=True)

    # LAYOUT 3: REDDIT
    elif item['tipo'] == 'REDDIT':
        tag_texto = f"r/{item['sub']}"
        if item.get('img'):
            try:
                res = requests.get(item['img'], timeout=10)
                capa = Image.open(BytesIO(res.content)).convert("RGB")
                fundo = ImageOps.fit(capa, (480, 320), Image.Resampling.LANCZOS).convert('RGBA')
            except: fundo = Image.new('RGBA', (480, 320), color='#1A1A1B')

            camada = Image.new('RGBA', (480, 320), (0, 0, 0, 0))
            draw = ImageDraw.Draw(camada)

            desenhar_etiqueta_topo(draw, 20, 20, tag_texto, f_plat, (255, 69, 0, 230))
            draw.rectangle([0, 220, 480, 320], fill=(0, 0, 0, 160))
            
            linhas_titulo = textwrap.wrap(item['titulo'], width=45)[:2]
            altura_linha = 26
            altura_total = (len(linhas_titulo) * altura_linha) + 18
            y_atual = 220 + (100 - altura_total) // 2

            for linha in linhas_titulo: 
                desenhar_texto_centralizado(draw, y_atual, linha, f_titulo, cor_texto=(255, 255, 255, 255))
                y_atual += altura_linha
                
            desenhar_texto_centralizado(draw, y_atual, f"por {item['info']}", f_pequena, cor_texto=(200, 200, 200, 255))

            img_final = Image.alpha_composite(fundo, camada).convert('RGB')
            return img_final.rotate(rotacao, expand=True)
        else:
            img_final = Image.new('RGB', (480, 320), color='#1A1A1B')
            draw = ImageDraw.Draw(img_final)

            draw.rectangle([0, 0, 480, 15], fill='#FF4500')
            desenhar_etiqueta_topo(draw, 20, 35, tag_texto, f_plat, (255, 69, 0, 255))
            draw.text((20, 85), f"Postado por {item['info']}", font=f_pequena, fill='#818384')

            linhas = textwrap.wrap(item['titulo'], width=40)
            y = 130
            for linha in linhas[:3]:
                draw.text((20, y), linha, font=f_titulo, fill='#D7DADC')
                y += 32
            return img_final.rotate(rotacao, expand=True)

def gerar_tela_padrao(mensagem="Turing Smart Screen"):
    img_final = Image.new('RGB', (480, 320), color='#121212')
    draw = ImageDraw.Draw(img_final)
    try:
        f_titulo = ImageFont.truetype("arialbd.ttf", 26) 
    except:
        f_titulo = ImageFont.load_default()
    
    desenhar_texto_centralizado(draw, 140, mensagem, f_titulo, cor_texto=(255, 255, 255, 255))
    return img_final.rotate(estado_app.get('rotacao', -90), expand=True)

# ==========================================
# WORKER BACKGROUND (LCD & PREVIEW)
# ==========================================
import serial.tools.list_ports

is_running = True
force_restart = False

def update_preview(img_pil):
    global preview_bytes
    img_byte_arr = BytesIO()
    
    # Desfaz a rotação da imagem apenas para o web preview ficar natural (paisagem 480x320)
    rotacao_atual = estado_app.get('rotacao', -90)
    if rotacao_atual != 0:
        img_pil = img_pil.rotate(-rotacao_atual, expand=True)
        
    img_pil.save(img_byte_arr, format='JPEG', quality=85)
    with preview_lock:
        preview_bytes = img_byte_arr.getvalue()

def auto_descobrir_com():
    """Detecção robusta da porta COM da tela Turing Smart Screen.
    Prioridade:
      1. Identifica pelo serial_number ou VID/PID exato da tela Turing
      2. Fallback: procura chips CH340/CH341 (conversor USB-Serial comum nessas telas)
      3. Último recurso: ignora e retorna None (painel continua apenas na web)
    """
    try:
        portas = list(serial.tools.list_ports.comports())
        if not portas:
            print("[LCD] Nenhuma porta serial encontrada no sistema.")
            return None
        
        print(f"[LCD] Portas seriais encontradas: {[(p.device, p.description, p.vid, p.pid) for p in portas]}")
        
        # PRIORIDADE 1: Método exato da biblioteca Turing (serial number ou VID:PID)
        for p in portas:
            if p.serial_number == "USB35INCHIPSV2":
                print(f"[LCD] ✅ Tela Turing detectada por número de série: {p.device}")
                return p.device
            if p.vid == 0x1a86 and p.pid == 0x5722:
                print(f"[LCD] ✅ Tela Turing detectada por VID/PID (1a86:5722): {p.device}")
                return p.device
        
        # PRIORIDADE 2: Chip CH340/CH341 (convertidor USB-Serial usado por essas telas)
        for p in portas:
            desc = (p.description or '').upper()
            if 'CH340' in desc or 'CH341' in desc:
                print(f"[LCD] ⚠️ Chip CH340/CH341 encontrado (provável tela): {p.device} ({p.description})")
                return p.device
        
        # PRIORIDADE 3: VID 0x1a86 (fabricante do CH340) com qualquer PID
        for p in portas:
            if p.vid == 0x1a86:
                print(f"[LCD] ⚠️ Dispositivo do fabricante CH340 encontrado: {p.device} ({p.description})")
                return p.device
        
        # NÃO retorna porta aleatória — evita conectar em mouse/teclado/bluetooth
        print("[LCD] ⚠️ Nenhuma tela Turing/CH340 reconhecida entre as portas disponíveis.")
        return None
    except Exception as e:
        print(f"[LCD] Erro durante detecção de portas: {e}")
        return None

display_global = None

def validar_porta_com(porta):
    """Testa se a porta COM existe e pode ser aberta. Retorna True/False."""
    if not porta:
        return False
    try:
        teste = serial.Serial(porta, 115200, timeout=1)
        teste.close()
        return True
    except Exception:
        return False

def run_worker_cycle():
    global force_restart, display_global
    print("[Worker] Iniciando ciclo (buscando hardware e dados)...")
    
    porta = estado_app.get('porta_com', 'AUTO')
    
    # Se a porta estiver como AUTO ou vazia, faz detecção inteligente
    if not porta or porta.strip().upper() == 'AUTO':
        print("[LCD] Modo automático — buscando tela Turing...")
        porta_descoberta = auto_descobrir_com()
        if porta_descoberta:
            porta = porta_descoberta
            estado_app['porta_com'] = porta
            salvar_configuracao()
        else:
            porta_manual = estado_app.get('_porta_manual', None)
            if porta_manual:
                porta = porta_manual
            else:
                porta = None

    # Pré-validação: testa se a porta realmente existe antes de passar ao driver
    # (o driver chama os._exit() se falhar, matando o processo inteiro)
    if porta and not validar_porta_com(porta):
        print(f"⚠️ Porta {porta} não está disponível. Rodando apenas no modo Web.")
        porta = None

    # Se a porta mudou ou se não temos conexão, reconecta
    if display_global is not None and getattr(display_global, 'com_port', None) != porta:
        print(f"[LCD] Porta alterada ou reconexão solicitada. Fechando a anterior...")
        try:
            display_global.closeSerial()
        except: pass
        display_global = None

    if display_global is None and porta and LcdCommRevA is not None:
        try:
            display_global = LcdCommRevA(porta)
            display_global.Reset()
            display_global.InitializeComm()
            print(f"✅ Conectado na porta {porta}!")
        except SystemExit:
            print(f"⚠️ Driver tentou encerrar o programa ao conectar na {porta}. Ignorando.")
            display_global = None
        except Exception as e:
            print(f"⚠️ Aviso LCD: Não foi possível conectar na {porta} ({e}). Mostrarei apenas a Web.")
            display_global = None
    elif display_global is None:
        if LcdCommRevA is None:
            print("⚠️ Driver LcdCommRevA não disponível — rodando apenas no modo Web.")
        elif not porta:
            print("⚠️ Nenhuma tela disponível — rodando apenas no modo Web Preview.")
    else:
        try: display_global.Clear()
        except: pass

    update_preview(gerar_tela_padrao("Buscando dados..."))
    
    while is_running and not force_restart:
        try:
            jogos = buscar_jogos_gratis()
            promos = buscar_promocoes_steam()
            noticias = buscar_gamevicio()
            reddit = buscar_reddit_multiplos() 
            conteudo = promos + jogos + noticias + reddit
            
            if not conteudo:
                update_preview(gerar_tela_padrao("Sem conteúdo ativo."))
                # Aguarda até o próximo ciclo ou até dar restart
                for _ in range(5):
                    if force_restart or not is_running: break
                    time.sleep(1)
                continue
            
            for item in conteudo:
                if not is_running or force_restart: break
                
                img_pronta = criar_layout(item)
                update_preview(img_pronta)
                
                if display_global:
                    try:
                        display_global.DisplayPILImage(img_pronta, 0, 0)
                    except: pass 
                
                t_slide = estado_app.get('tempo_slide', 12)
                t_elapsed = 0
                while t_elapsed < t_slide and is_running and not force_restart:
                    time.sleep(1)
                    t_elapsed += 1

        except Exception as e:
            print(f"Erro no loop principal: {e}")
            for _ in range(5):
                if force_restart or not is_running: break
                time.sleep(1)
            
    print("[Worker] Ciclo encerrado ou reiniciando.")

def worker_thread():
    global force_restart
    while is_running:
        force_restart = False
        run_worker_cycle()
        if is_running and force_restart:
            print("[Worker] Reinicialização solicitada, religando...")
            time.sleep(0.5)

# ==========================================
# ROTAS DO FLASK (WEB API)
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(estado_app)

@app.route('/api/config', methods=['POST'])
def save_config():
    dados = request.json
    if dados:
        estado_app.update(dados)
        salvar_configuracao()
        return jsonify({"status": "sucesso"}), 200
    return jsonify({"status": "erro"}), 400

@app.route('/api/preview')
def get_preview():
    with preview_lock:
        b = preview_bytes
    if b:
        return Response(b, mimetype='image/jpeg')
    else:
        return Response(b"", status=404)

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    global is_running
    is_running = False
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        os._exit(0)
    func()
    return jsonify({"status": "desligando"}), 200

@app.route('/api/restart', methods=['POST'])
def restart():
    global force_restart
    force_restart = True
    return jsonify({"status": "reiniciando"}), 200

def pedir_porta_com():
    """Pergunta a porta COM ao usuário no terminal se a detecção automática falhar."""
    porta_config = estado_app.get('porta_com', 'AUTO')
    
    # Se já tem uma porta fixa configurada (não AUTO), verifica se ela ainda existe
    if porta_config and porta_config.strip().upper() != 'AUTO':
        if validar_porta_com(porta_config):
            print(f"[LCD] ✅ Porta salva {porta_config} validada com sucesso.")
            return
        else:
            print(f"[LCD] ⚠️ Porta salva {porta_config} não existe mais. Refazendo detecção...")
            estado_app['porta_com'] = 'AUTO'
    
    # Tenta auto-detectar primeiro
    porta_auto = auto_descobrir_com()
    if porta_auto:
        print(f"[LCD] ✅ Tela detectada automaticamente: {porta_auto}")
        estado_app['porta_com'] = porta_auto
        salvar_configuracao()
        return
    
    # Auto-detecção falhou — pede ao usuário
    print("")
    print("=======================================")
    print("  ⚠️  TELA NÃO DETECTADA AUTOMATICAMENTE")
    print("=======================================")
    
    try:
        portas = list(serial.tools.list_ports.comports())
        if portas:
            print("")
            print("  Portas disponíveis no sistema:")
            for i, p in enumerate(portas):
                print(f"    [{i+1}] {p.device} — {p.description}")
            print("")
        else:
            print("")
            print("  Nenhuma porta serial encontrada.")
            print("  Verifique se a tela está conectada via USB.")
            print("")
    except:
        pass
    
    print("  Digite a porta COM da sua tela (ex: COM3, COM5)")
    print("  Ou tecle ENTER para rodar apenas o painel Web sem tela.")
    print("")
    
    try:
        resposta = input("  Porta COM > ").strip()
    except (EOFError, KeyboardInterrupt):
        resposta = ""
    
    if resposta and resposta.upper() != 'SKIP':
        porta_final = resposta.upper()
        estado_app['porta_com'] = porta_final
        estado_app['_porta_manual'] = porta_final
        salvar_configuracao()
        print(f"  ✅ Porta configurada: {porta_final}")
    else:
        print("  ⏭️ Rodando sem tela — apenas Web Preview.")
        estado_app['_porta_manual'] = None
    print("")

def main():
    carregar_configuracao()
    
    # Pergunta a porta COM se necessário (antes de iniciar threads)
    pedir_porta_com()
    
    # Inicia a thread de LCD
    t = threading.Thread(target=worker_thread, daemon=True)
    t.start()
    
    print("=======================================")
    print("  🌐 Acesso WEB: http://localhost:5000 ")
    print("=======================================")
    
    # Inicia o servidor Web
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()