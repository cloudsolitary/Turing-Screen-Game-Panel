import os
import sys
import time
import requests
import feedparser
import textwrap
import re
import json
import threading
import random
from io import BytesIO
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps
from flask import Flask, render_template, request, jsonify, send_file, Response

# Força o encoding correto no terminal
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURAÇÃO DE CAMINHO ---
app = Flask(__name__)
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
sys.path.append(diretorio_atual)

try:
    from library.lcd.lcd_comm_rev_a import LcdCommRevA
except Exception as e:
    print(f"❌ Erro Crítico do LcdCommRevA: {e}")
    LcdCommRevA = None

# ==========================================
# VARIÁVEIS GLOBAIS E ESTADO
# ==========================================
ARQUIVO_CONFIG = os.path.join(diretorio_atual, 'painel_config.json')

estado_app = {
    "modulo_jogos": True,
    "jogos_plataforma": "todas",
    "modulo_noticias": True,
    "modulo_reddit": True,
    "modulo_promocoes": True,
    "modulo_steam_random": True,  # ⚡ NOVO MÓDULO: Jogo Aleatório Steam
    "promo_generos": ["todos"],
    "lista_subreddits": ['emulation', 'PiratedGames', 'gadgets', 'SBCGaming'],
    "tempo_slide": 12,
    "porta_com": "AUTO",
    "rotacao": -90
}

preview_lock = threading.Lock()
preview_bytes = None

HEADERS_NAVEGADOR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Cache global para não baixar 150 mil IDs toda hora
CACHE_STEAM_APPIDS = []

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
def carregar_lista_steam():
    """Baixa e faz cache de todos os AppIDs da Steam usando múltiplos métodos de fallback."""
    global CACHE_STEAM_APPIDS
    if CACHE_STEAM_APPIDS: 
        return CACHE_STEAM_APPIDS
    
    # Métodos 1 e 2: API Principal de AppList
    for url in ["https://api.steampowered.com/ISteamApps/GetAppList/v2/",
                 "https://api.steampowered.com/ISteamApps/GetAppList/v0002/"]:
        try:
            res = requests.get(url, timeout=15).json()
            apps = res.get('applist', {}).get('apps', [])
            ids = [a['appid'] for a in apps if a.get('name')]
            if ids:
                CACHE_STEAM_APPIDS = ids
                return ids
        except: continue
        
    # Método 3: Featured (puxa IDs de jogos populares/novos)
    try:
        res = requests.get("https://store.steampowered.com/api/featuredcategories/", timeout=15).json()
        ids_extra = set()
        for cat in ("specials", "top_sellers", "new_releases"):
            for g in res.get(cat, {}).get("items", []): ids_extra.add(g.get("id", 0))
        if ids_extra:
            CACHE_STEAM_APPIDS = list(ids_extra)
            return CACHE_STEAM_APPIDS
    except: pass
    
    # Fallback manual se tudo falhar
    if not CACHE_STEAM_APPIDS:
        CACHE_STEAM_APPIDS = [730, 570, 4000, 105600, 292030, 252950, 413150, 367520, 201810, 1145360]
    return CACHE_STEAM_APPIDS

def buscar_steam_random():
    """Sorteia um jogo aleatório da base da Steam com alta robustez."""
    if not estado_app.get('modulo_steam_random', True): return []
    
    appids = carregar_lista_steam()
    
    # Tenta sortear até achar um que funcione (máximo 20 tentativas)
    for _ in range(20):
        appid = random.choice(appids)
        try:
            res = requests.get(f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=BR&l=brazilian", timeout=5).json()
            data = res.get(str(appid), {})
            
            if not data.get('success'): continue
            
            info = data.get('data', {})
            if info.get('type') != 'game': continue

            preco = "Grátis" if info.get('is_free') else info.get('price_overview', {}).get('final_formatted', 'N/A')
            generos = ", ".join([g['description'] for g in info.get('genres', [])[:3]])
            meta = info.get('metacritic', {}).get('score', 'N/A')
            img_url = info.get('header_image', '')

            if not img_url: continue

            return [{
                'tipo': 'STEAM_RANDOM',
                'titulo': info.get('name', 'Desconhecido'),
                'img': img_url,
                'preco': preco,
                'generos': generos,
                'score': meta
            }]
        except: pass
    return []

def buscar_jogos_gratis():
    if not estado_app['modulo_jogos']: return []
    
    url = "https://www.gamerpower.com/api/giveaways?type=game&platform=pc"
    plat_filter = estado_app.get('jogos_plataforma', 'todas').lower()
        
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
            
            if not loja: continue 
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

def buscar_promocoes_steam():
    if not estado_app.get('modulo_promocoes', True): return []
    
    filtros = [f.lower() for f in estado_app.get('promo_generos', ['todos'])]
    selecionou_todos = 'todos' in filtros or not filtros
    termo = "" if selecionou_todos else random.choice(filtros)
    
    search_url = f"https://store.steampowered.com/search/?term={termo}&specials=1"
    
    try:
        res_html = requests.get(search_url, headers=HEADERS_NAVEGADOR, timeout=10)
        soup = BeautifulSoup(res_html.text, 'html.parser')
        cards = soup.find_all('a', class_=re.compile(r"search_result_row"))
        
        appids_encontrados = []
        for card in cards:
            appid = card.get('data-ds-appid')
            if appid and ',' not in appid:
                appids_encontrados.append(appid)
        
        if not appids_encontrados: return []

        random.shuffle(appids_encontrados)
        appids_selecionados = appids_encontrados[:10]
        ids_str = ",".join(appids_selecionados)

        url_batch = f"https://store.steampowered.com/api/appdetails?appids={ids_str}&filters=price_overview,metacritic,basic&cc=BR&l=brazilian"
        detalhes_batch = requests.get(url_batch, headers=HEADERS_NAVEGADOR, timeout=10).json()

        promos = []
        for appid in appids_selecionados:
            game_data = detalhes_batch.get(str(appid), {})
            if not game_data.get('success'): continue
                
            info = game_data.get('data', {})
            if info.get('type') != 'game': continue

            price_data = info.get('price_overview', {})
            if not price_data: continue
                
            initial = price_data.get('initial', 0) / 100
            final = price_data.get('final', 0) / 100
            desconto = price_data.get('discount_percent', 0)
            
            score = info.get('metacritic', {}).get('score', "N/A")
            titulo = info.get('name', 'Steam Promo')
            img_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
            genero_display = termo.capitalize() if termo else "Promoção"

            promos.append({
                'tipo': 'STEAM_PROMO', 
                'titulo': titulo, 
                'img': img_url,
                'preco_normal': f"{initial:.2f}".replace('.', ','),
                'preco': f"{final:.2f}".replace('.', ','),
                'desconto': f"-{desconto}%",
                'score': score,
                'genero': genero_display
            })
            if len(promos) >= 6: break
        return promos
    except Exception as e:
        print(f"Erro ao buscar promoções Steam (Híbrido): {e}")
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

    # ⚡ NOVO LAYOUT: STEAM RANDOM FULLSCREEN
    if item['tipo'] == 'STEAM_RANDOM':
        try:
            res = requests.get(item['img'], timeout=10)
            capa = Image.open(BytesIO(res.content)).convert("RGB")
            # Deixa a imagem tela cheia (como o script externo sugeriu)
            fundo = ImageOps.fit(capa, (480, 320), Image.Resampling.LANCZOS).convert('RGBA')
        except: fundo = Image.new('RGBA', (480, 320), color='#1e1e2e')

        camada = Image.new('RGBA', (480, 320), (0, 0, 0, 0))
        draw = ImageDraw.Draw(camada)

        # Gradiente suave escuro na parte de baixo (Efeito "Lower Third")
        y_gradiente = 200
        for i in range(50):
            # Vai de transparente até quase preto (220)
            alpha = int((i / 50) * 220)
            draw.line([(0, y_gradiente + i), (480, y_gradiente + i)], fill=(15, 15, 20, alpha))
        
        # Preenche o resto até o final com o fundo escuro
        draw.rectangle([0, y_gradiente + 50, 480, 320], fill=(15, 15, 20, 220))

        # Tag no topo pra identificar
        desenhar_etiqueta_topo(draw, 20, 20, "🎲 Explorar Steam", f_plat, (63, 81, 181, 230))
        
        if item['score'] != 'N/A':
            draw.rounded_rectangle([390, 20, 460, 50], fill=(250, 208, 0, 220), radius=6)
            draw.text((400, 26), f"MC {item['score']}", font=f_plat, fill=(0, 0, 0, 255))

        # Título grande e branco no gradiente
        linhas_titulo = textwrap.wrap(item['titulo'], width=38)[:1]
        desenhar_texto_centralizado(draw, y_gradiente + 20, linhas_titulo[0], f_gratis, cor_texto=(255, 255, 255, 255))

        # Gênero e Preço formatados como "Ação, RPG  •  R$ 19,90"
        info_texto = f"{item['generos']}   •   {item['preco']}"
        desenhar_texto_centralizado(draw, y_gradiente + 65, info_texto, f_plat, cor_texto=(166, 227, 161, 255))

        img_final = Image.alpha_composite(fundo, camada).convert('RGB')
        return img_final.rotate(rotacao, expand=True)

    # LAYOUT 1: JOGOS
    elif item['tipo'] == 'JOGO':
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
            
            fundo_base = ImageOps.fit(capa, (480, 320), bleed=0.1)
            fundo = fundo_base.filter(ImageFilter.GaussianBlur(radius=15))
            
            arte_proporcional = ImageOps.contain(capa, (440, 240))
            pos_x = (480 - arte_proporcional.width) // 2
            pos_y = 50 
            
            fundo.paste(arte_proporcional, (pos_x, pos_y))
            fundo = fundo.convert('RGBA')
        except: fundo = Image.new('RGBA', (480, 320), color='#1e1e2e')

        camada = Image.new('RGBA', (480, 320), (0, 0, 0, 0))
        draw = ImageDraw.Draw(camada)

        tag_genero = f"🏷️ {item.get('genero', 'Steam')}"
        desenhar_etiqueta_topo(draw, 20, 20, tag_genero, f_plat, (103, 58, 183, 230))

        if item['score'] != "N/A":
            draw.rounded_rectangle([20, 60, 75, 90], fill=(250, 208, 0, 220), radius=6)
            draw.text((28, 66), f"M {item['score']}", font=f_plat, fill=(0, 0, 0, 255))

        draw.rounded_rectangle([310, 20, 460, 50], fill=(24, 24, 37, 220), radius=6)
        draw.text((325, 26), "🎮 Steam", font=f_plat, fill=(137, 207, 240, 255))
        
        draw.rounded_rectangle([250, 230, 460, 300], fill=(17, 17, 27, 230), radius=8)
        draw.rounded_rectangle([260, 245, 335, 285], fill=(76, 175, 80, 255), radius=4)
        draw.text((265, 252), item['desconto'], font=f_titulo, fill=(255, 255, 255, 255))
        
        texto_de = f"De: R$ {item['preco_normal']}"
        draw.text((345, 238), texto_de, font=f_pequena, fill=(166, 173, 200, 255))
        comp = len(texto_de) * 8
        draw.line([(345, 247), (345 + comp, 247)], fill=(243, 139, 168, 255), width=2)
        draw.text((345, 260), f"R$ {item['preco']}", font=f_gratis, fill=(166, 227, 161, 255))

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
    rotacao_atual = estado_app.get('rotacao', -90)
    if rotacao_atual != 0:
        img_pil = img_pil.rotate(-rotacao_atual, expand=True)
        
    img_pil.save(img_byte_arr, format='JPEG', quality=85)
    with preview_lock:
        preview_bytes = img_byte_arr.getvalue()

def auto_descobrir_com():
    try:
        portas = list(serial.tools.list_ports.comports())
        if not portas: return None
        for p in portas:
            if p.serial_number == "USB35INCHIPSV2" or (p.vid == 0x1a86 and p.pid == 0x5722):
                return p.device
        for p in portas:
            desc = (p.description or '').upper()
            if 'CH340' in desc or 'CH341' in desc or p.vid == 0x1a86:
                return p.device
        return None
    except Exception as e:
        print(f"[LCD] Erro: {e}")
        return None

display_global = None

def validar_porta_com(porta):
    if not porta: return False
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
    
    if not porta or porta.strip().upper() == 'AUTO':
        porta_descoberta = auto_descobrir_com()
        if porta_descoberta:
            porta = porta_descoberta
            estado_app['porta_com'] = porta
            salvar_configuracao()
        else:
            porta_manual = estado_app.get('_porta_manual', None)
            if porta_manual: porta = porta_manual
            else: porta = None

    if porta and not validar_porta_com(porta):
        print(f"⚠️ Porta {porta} não está disponível.")
        porta = None

    if display_global is not None and getattr(display_global, 'com_port', None) != porta:
        try: display_global.closeSerial()
        except: pass
        display_global = None

    if display_global is None and porta and LcdCommRevA is not None:
        try:
            display_global = LcdCommRevA(porta)
            display_global.Reset()
            display_global.InitializeComm()
            print(f"✅ Conectado na porta {porta}!")
        except Exception as e:
            display_global = None
    
    if display_global is not None:
        try: display_global.Clear()
        except: pass

    update_preview(gerar_tela_padrao("Buscando dados..."))
    
    while is_running and not force_restart:
        try:
            jogos = buscar_jogos_gratis()
            promos = buscar_promocoes_steam()
            noticias = buscar_gamevicio()
            reddit = buscar_reddit_multiplos() 
            steam_aleatorio = buscar_steam_random()  # ⚡ Adicionando o Aleatório da Steam
            
            # Embaralha os conteudos para a tela ficar dinâmica
            conteudo = promos + jogos + noticias + reddit + steam_aleatorio
            
            if not conteudo:
                update_preview(gerar_tela_padrao("Sem conteúdo ativo."))
                for _ in range(5):
                    if force_restart or not is_running: break
                    time.sleep(1)
                continue
            
            for item in conteudo:
                if not is_running or force_restart: break
                
                img_pronta = criar_layout(item)
                update_preview(img_pronta)
                
                if display_global:
                    try: display_global.DisplayPILImage(img_pronta, 0, 0)
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

def worker_thread():
    global force_restart
    while is_running:
        force_restart = False
        run_worker_cycle()
        if is_running and force_restart:
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
    porta_config = estado_app.get('porta_com', 'AUTO')
    
    if porta_config and porta_config.strip().upper() != 'AUTO':
        if validar_porta_com(porta_config):
            print(f"[LCD] ✅ Porta salva {porta_config} validada com sucesso.")
            return
        else:
            estado_app['porta_com'] = 'AUTO'
    
    porta_auto = auto_descobrir_com()
    if porta_auto:
        print(f"[LCD] ✅ Tela detectada automaticamente: {porta_auto}")
        estado_app['porta_com'] = porta_auto
        salvar_configuracao()
        return
    
    try:
        portas = list(serial.tools.list_ports.comports())
        if portas:
            print("\n  Portas disponíveis:")
            for i, p in enumerate(portas): print(f"    [{i+1}] {p.device}")
    except: pass
    
    try:
        resposta = input("\n  Porta COM > ").strip()
    except: resposta = ""
    
    if resposta and resposta.upper() != 'SKIP':
        estado_app['porta_com'] = resposta.upper()
        estado_app['_porta_manual'] = resposta.upper()
        salvar_configuracao()
    else:
        estado_app['_porta_manual'] = None

def main():
    carregar_configuracao()
    pedir_porta_com()
    
    t = threading.Thread(target=worker_thread, daemon=True)
    t.start()
    
    print("\n=======================================")
    print("  🌐 Acesso WEB: http://localhost:5000 ")
    print("=======================================\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()