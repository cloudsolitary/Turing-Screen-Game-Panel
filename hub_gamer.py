import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

import time
import requests
import feedparser
import textwrap
import re
import threading
import random
from io import BytesIO
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from flask import Flask, request, jsonify, Response, render_template_string
import serial.tools.list_ports

# --- CONFIGURAÇÃO DE CAMINHO E IMPORT DA TELA ---
app = Flask(__name__)
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
sys.path.append(diretorio_atual)

try:
    from library.lcd.lcd_comm_rev_a import LcdCommRevA
except Exception as e:
    print(f"❌ Erro Crítico do LcdCommRevA: {e}")
    LcdCommRevA = None

# ==========================================
# VARIÁVEIS GLOBAIS E ESTADO (NA MEMÓRIA)
# ==========================================
estado_app = {
    "modulo_jogos": True,
    "jogos_plataforma": "todas",
    "modulo_noticias": True,
    "modulo_reddit": True,
    "modulo_steam_random": True, 
    "modulo_promocoes": True,
    
    # TEMPOS INDIVIDUAIS DE CADA MÓDULO (em segundos)
    "tempo_jogos": 12,
    "tempo_promocoes": 15,
    "tempo_random": 10,
    "tempo_noticias": 14,
    "tempo_reddit": 14,
    
    "promo_generos": ["metroidvania", "rpg"],
    "lista_subreddits": ['emulation', 'PiratedGames', 'gadgets', 'SBCGaming'],
    "porta_com": "AUTO",
    "rotacao": 270 # 270 = -90 graus (padrão em pé)
}

preview_lock = threading.Lock()
preview_bytes = None

HEADERS_NAVEGADOR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
}

# ==========================================
# PAINEL WEB EMBUTIDO (HTML + CSS + JS)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Turing Smart Screen</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
        .container { max-width: 600px; margin: auto; }
        .preview-box { text-align: center; margin-bottom: 20px; }
        .preview-box img { max-width: 100%; border: 3px solid #333; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .card { background: #1e1e1e; padding: 20px; border-radius: 10px; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
        h2 { margin-top: 0; color: #fff; font-size: 1.2rem; border-bottom: 1px solid #333; padding-bottom: 10px;}
        label { display: block; margin: 10px 0 5px; font-weight: bold; font-size: 0.9rem;}
        input[type="text"], input[type="number"], select { width: 100%; padding: 10px; background: #2c2c2c; color: white; border: 1px solid #444; border-radius: 5px; box-sizing: border-box;}
        .checkbox-group { display: flex; align-items: center; margin-bottom: 10px; }
        .checkbox-group input { margin-right: 10px; width: auto; transform: scale(1.2); }
        .checkbox-group label { margin: 0; font-weight: normal; cursor: pointer; }
        .time-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; }
        button { width: 100%; padding: 12px; background: #4CAF50; color: white; border: none; border-radius: 5px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: 0.3s; margin-top: 10px;}
        button:hover { background: #45a049; }
        .btn-danger { background: #d32f2f; }
        .btn-danger:hover { background: #b71c1c; }
        .note { font-size: 0.8rem; color: #aaa; margin-top: 5px;}
    </style>
</head>
<body>
    <div class="container">
        <div class="preview-box">
            <img id="preview-img" src="/api/preview" alt="Preview da Tela">
            <p style="color: #888; font-size: 0.8rem;">Atualiza automaticamente</p>
        </div>

        <div class="card">
            <h2>Módulos Ativos</h2>
            <div class="checkbox-group"><input type="checkbox" id="mod_jogos"><label for="mod_jogos">Jogos Grátis</label></div>
            <div class="checkbox-group"><input type="checkbox" id="mod_promocoes"><label for="mod_promocoes">Promoções Steam</label></div>
            <div class="checkbox-group"><input type="checkbox" id="mod_random"><label for="mod_random">Explorador Steam Aleatório</label></div>
            <div class="checkbox-group"><input type="checkbox" id="mod_noticias"><label for="mod_noticias">Notícias (GameVicio)</label></div>
            <div class="checkbox-group"><input type="checkbox" id="mod_reddit"><label for="mod_reddit">Reddit</label></div>
        </div>

        <div class="card">
            <h2>Tempo de Exibição (Segundos)</h2>
            <div class="time-grid">
                <div><label>Jogos Grátis:</label><input type="number" id="t_jogos" min="5" max="60"></div>
                <div><label>Steam Promo:</label><input type="number" id="t_promos" min="5" max="60"></div>
                <div><label>Steam Aleatório:</label><input type="number" id="t_random" min="5" max="60"></div>
                <div><label>Notícias:</label><input type="number" id="t_noticias" min="5" max="60"></div>
                <div><label>Reddit:</label><input type="number" id="t_reddit" min="5" max="60"></div>
            </div>
        </div>

        <div class="card">
            <h2>Configurações da Tela</h2>
            
            <label>Rotação (Orientação da Telinha):</label>
            <select id="rotacao">
                <option value="0">0° (Paisagem Padrão)</option>
                <option value="90">90° (Retrato Direita)</option>
                <option value="180">180° (Paisagem Invertida)</option>
                <option value="270">270° (Retrato Esquerda)</option>
            </select>
            
            <label style="margin-top: 15px;">Tags da Steam (Gêneros, separados por vírgula):</label>
            <input type="text" id="promo_generos" placeholder="Ex: metroidvania, rpg, anime">
            
            <label style="margin-top: 15px;">Subreddits (separados por vírgula):</label>
            <input type="text" id="lista_subreddits" placeholder="Ex: gadgets, emulation">

            <button onclick="salvarConfig()">Salvar Configurações</button>
        </div>
        
        <div class="card">
            <button class="btn-danger" onclick="reiniciarScript()">Reiniciar Painel</button>
        </div>
    </div>

    <script>
        setInterval(() => {
            document.getElementById('preview-img').src = '/api/preview?' + new Date().getTime();
        }, 1000);

        fetch('/api/config').then(r => r.json()).then(data => {
            document.getElementById('mod_jogos').checked = data.modulo_jogos;
            document.getElementById('mod_promocoes').checked = data.modulo_promocoes;
            document.getElementById('mod_random').checked = data.modulo_steam_random;
            document.getElementById('mod_noticias').checked = data.modulo_noticias;
            document.getElementById('mod_reddit').checked = data.modulo_reddit;
            
            document.getElementById('t_jogos').value = data.tempo_jogos;
            document.getElementById('t_promos').value = data.tempo_promocoes;
            document.getElementById('t_random').value = data.tempo_random;
            document.getElementById('t_noticias').value = data.tempo_noticias;
            document.getElementById('t_reddit').value = data.tempo_reddit;
            
            document.getElementById('rotacao').value = data.rotacao;
            document.getElementById('promo_generos').value = data.promo_generos.join(', ');
            document.getElementById('lista_subreddits').value = data.lista_subreddits.join(', ');
        });

        function salvarConfig() {
            const data = {
                modulo_jogos: document.getElementById('mod_jogos').checked,
                modulo_promocoes: document.getElementById('mod_promocoes').checked,
                modulo_steam_random: document.getElementById('mod_random').checked,
                modulo_noticias: document.getElementById('mod_noticias').checked,
                modulo_reddit: document.getElementById('mod_reddit').checked,
                
                tempo_jogos: parseInt(document.getElementById('t_jogos').value),
                tempo_promocoes: parseInt(document.getElementById('t_promos').value),
                tempo_random: parseInt(document.getElementById('t_random').value),
                tempo_noticias: parseInt(document.getElementById('t_noticias').value),
                tempo_reddit: parseInt(document.getElementById('t_reddit').value),
                
                rotacao: parseInt(document.getElementById('rotacao').value),
                promo_generos: document.getElementById('promo_generos').value.split(',').map(s => s.trim()).filter(s => s),
                lista_subreddits: document.getElementById('lista_subreddits').value.split(',').map(s => s.trim()).filter(s => s)
            };
            
            if(data.promo_generos.length === 0) data.promo_generos = ["todos"];
            
            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            }).then(() => alert('Salvo com sucesso!'));
        }

        function reiniciarScript() {
            fetch('/api/restart', { method: 'POST' }).then(() => alert('Reiniciando painel...'));
        }
    </script>
</body>
</html>
"""

# ==========================================
# CACHES E MEMÓRIA
# ==========================================
CACHE_STEAM_APPIDS = []
_cache_generos = {}
HISTORICO_PROMOCOES = []

# ==========================================
# FUNÇÕES DE BUSCA
# ==========================================
def carregar_lista_steam():
    global CACHE_STEAM_APPIDS
    if CACHE_STEAM_APPIDS: return CACHE_STEAM_APPIDS
    urls = ["https://api.steampowered.com/ISteamApps/GetAppList/v0002/",
            "https://api.steampowered.com/ISteamApps/GetAppList/v2/"]
    for url in urls:
        try:
            res = requests.get(url, timeout=15).json()
            apps = res.get("applist", {}).get("apps", [])
            ids = [a["appid"] for a in apps if a.get("name")]
            if ids:
                CACHE_STEAM_APPIDS = ids
                return CACHE_STEAM_APPIDS
        except: pass
    if not CACHE_STEAM_APPIDS:
        CACHE_STEAM_APPIDS = [730, 570, 4000, 105600, 292030, 252950, 413150]
    return CACHE_STEAM_APPIDS

def buscar_steam_random():
    if not estado_app.get('modulo_steam_random', True): return []
    app_ids = carregar_lista_steam()
    if not app_ids: return []

    for _ in range(10):
        app_id = random.choice(app_ids)
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=BR&l=brazilian"
            res = requests.get(url, timeout=5).json()
            if not res or not isinstance(res, dict): continue
            
            data = res.get(str(app_id))
            if not data or not isinstance(data, dict) or not data.get("success"): continue
            
            info = data.get("data")
            if not info or not isinstance(info, dict) or info.get("type") != "game": continue
            
            img_url = info.get("header_image", "")
            if not img_url: continue
            
            price = "Grátis" if info.get("is_free") else info.get("price_overview", {}).get("final_formatted", "N/A")
            genres = ", ".join([g["description"] for g in info.get("genres", [])[:3]])
            meta = info.get("metacritic", {}).get("score", "N/A") if isinstance(info.get("metacritic"), dict) else "N/A"

            return [{
                'tipo': 'STEAM_RANDOM',
                'titulo': info.get("name", "Desconhecido"),
                'img': img_url,
                'preco': price,
                'generos': genres,
                'score': meta
            }]
        except: pass
    return []

def buscar_promocoes_steam():
    global HISTORICO_PROMOCOES
    if not estado_app.get('modulo_promocoes', True): return []
    
    config_genero = estado_app.get('promo_generos', ['todos'])
    if isinstance(config_genero, str): config_genero = [config_genero]
        
    filtros_lower = [g.lower().strip() for g in config_genero if g.strip()]
    if not filtros_lower: filtros_lower = ['todos']
    
    tag_escolhida = random.choice(filtros_lower)
    todas_promos = []
    
    for pagina in range(1, 4):
        if tag_escolhida == 'todos':
            url = f"https://store.steampowered.com/search/?specials=1&page={pagina}&cc=BR&l=brazilian"
        else:
            tag_formatada = tag_escolhida.replace(' ', '+')
            url = f"https://store.steampowered.com/search/?specials=1&term={tag_formatada}&page={pagina}&cc=BR&l=brazilian"
            
        try:
            res = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.find_all('a', class_='search_result_row')
            
            if not rows: break 
            
            for row in rows:
                appid = row.get('data-ds-appid')
                if not appid or ',' in appid: continue 
                
                title_tag = row.find('span', class_='title')
                title = title_tag.text.strip() if title_tag else "Promoção Steam"
                
                pct_tag = row.find('div', class_=re.compile(r'discount_pct'))
                pct = pct_tag.text.strip() if pct_tag else ""
                
                price_tag = row.find('div', class_=re.compile(r'discount_final_price'))
                price = price_tag.text.strip() if price_tag else ""
                
                if not price or not pct: continue
                
                img = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
                
                score = 'N/A'
                review_tag = row.find('span', class_=re.compile(r'search_review_summary'))
                if review_tag and review_tag.has_attr('data-tooltip-html'):
                    match = re.search(r'(\d+)%', review_tag['data-tooltip-html'])
                    if match: score = match.group(1)
                    
                if tag_escolhida == 'todos': tag_exibicao = "Promoção"
                elif len(tag_escolhida) <= 3: tag_exibicao = tag_escolhida.upper()
                else: tag_exibicao = tag_escolhida.title()
                
                todas_promos.append({
                    'appid': appid,
                    'tipo': 'STEAM_PROMO',
                    'titulo': title,
                    'img': img,
                    'preco': f"{price} ({pct})",
                    'generos': tag_exibicao,
                    'score': score
                })
        except Exception as e:
            print(f"Erro ao buscar na Steam: {e}")
            break
            
    if not todas_promos: return []
    
    promos_novas = [p for p in todas_promos if p['appid'] not in HISTORICO_PROMOCOES]
    
    if len(promos_novas) < 5:
        print(f"[Painel] Esgotaram as novidades da tag '{tag_escolhida}'. Resetando histórico...")
        HISTORICO_PROMOCOES.clear()
        promos_novas = todas_promos
        
    random.shuffle(promos_novas)
    promos_finais = promos_novas[:5]
    
    for p in promos_finais:
        HISTORICO_PROMOCOES.append(p['appid'])
        
    return promos_finais

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
                    'tipo': 'JOGO', 'titulo': titulo, 
                    'img': j.get('thumbnail', ''),
                    'preco': j.get('worth', 'N/A'),
                    'loja': loja
                })
            if len(jogos) >= 5: break
        return jogos
    except: return []

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
                    'tipo': 'GAMEVICIO', 'titulo': titulo, 
                    'img': src, 'tag': tag
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
                        'tipo': 'REDDIT', 'titulo': titulo, 
                        'info': autor, 'img': img_url, 'sub': subreddit
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
        f_pequena_bold = ImageFont.truetype("arialbd.ttf", 12)
    except:
        f_pequena = f_plat = f_tipo = f_gratis = f_titulo = f_pequena_bold = ImageFont.load_default()

    rotacao = estado_app.get('rotacao', 270)

    # LAYOUT 1: STEAM (Imagem 100% Inteira com Fundo Borrado Premium)
    if item['tipo'] in ['STEAM_RANDOM', 'STEAM_PROMO']:
        try:
            res = requests.get(item['img'], timeout=10)
            capa = Image.open(BytesIO(res.content)).convert("RGB")
            
            fundo_blur = ImageOps.fit(capa, (480, 320), Image.Resampling.LANCZOS)
            fundo_blur = fundo_blur.filter(ImageFilter.GaussianBlur(radius=20))
            fundo = fundo_blur.convert('RGBA')
            
            scale = min(480 / capa.width, 320 / capa.height)
            new_w = int(capa.width * scale)
            new_h = int(capa.height * scale)
            capa_inteira = capa.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            px = (480 - new_w) // 2
            py = max(0, (260 - new_h) // 2) 
            fundo.paste(capa_inteira, (px, py))
            
        except: 
            fundo = Image.new('RGBA', (480, 320), color='#151515')

        camada = Image.new('RGBA', (480, 320), (0, 0, 0, 0))
        draw = ImageDraw.Draw(camada)

        start_y = 120
        end_y = 320
        for y in range(start_y, end_y):
            progress = (y - start_y) / (end_y - start_y)
            alpha = int((progress ** 1.8) * 255) 
            draw.line([(0, y), (480, y)], fill=(15, 15, 20, alpha))

        lt_y = 220
        
        linhas_titulo = textwrap.wrap(item['titulo'], width=35)[:1]
        desenhar_texto_centralizado(draw, lt_y + 10, linhas_titulo[0], f_gratis, cor_texto=(166, 227, 161, 255))

        info_parts = []
        if item.get('generos'): info_parts.append(item['generos'])
        if item.get('preco'): info_parts.append(item['preco'])
        info_str = "  ·  ".join(info_parts)
        desenhar_texto_centralizado(draw, lt_y + 45, info_str, f_plat, cor_texto=(250, 208, 0, 255))

        if item.get('score', 'N/A') != 'N/A':
            try:
                score_val = int(item['score'])
                sc_col = (166, 227, 161, 255) if score_val >= 75 else ((250, 208, 0, 255) if score_val >= 50 else (243, 139, 168, 255))
            except:
                sc_col = (166, 227, 161, 255)
            
            prefix = "⭐" if item['tipo'] == 'STEAM_PROMO' else "MC"
            sufix = "%" if item['tipo'] == 'STEAM_PROMO' else ""
            mc_texto = f"{prefix} {item['score']}{sufix}"
            
            bbox = draw.textbbox((0, 0), mc_texto, font=f_plat)
            largura_mc = bbox[2] - bbox[0]
            draw.text((480 - largura_mc - 15, lt_y + 75), mc_texto, font=f_plat, fill=sc_col)

        assinatura = "STEAM PROMO" if item['tipo'] == 'STEAM_PROMO' else "STEAM"
        bbox = draw.textbbox((0, 0), assinatura, font=f_pequena_bold)
        largura_steam = bbox[2] - bbox[0]
        draw.text(((480 - largura_steam) / 2, lt_y + 78), assinatura, font=f_pequena_bold, fill=(203, 166, 247, 255))

        img_final = Image.alpha_composite(fundo, camada).convert('RGB')
        return img_final.rotate(rotacao, expand=True)

    # LAYOUT 2: JOGOS GRÁTIS
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

    # LAYOUT 3: GAMEVICIO
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

    # LAYOUT 4: REDDIT
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
    return img_final.rotate(estado_app.get('rotacao', 270), expand=True)

# ==========================================
# WORKER BACKGROUND (LCD & PREVIEW)
# ==========================================
is_running = True
force_restart = False

def update_preview(img_pil):
    global preview_bytes
    img_byte_arr = BytesIO()
    
    # A preview na web sempre desfaz a rotação física para você ver reto no PC
    rotacao_atual = estado_app.get('rotacao', 270)
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
            if p.serial_number == "USB35INCHIPSV2": return p.device
            if p.vid == 0x1a86 and p.pid == 0x5722: return p.device
        for p in portas:
            desc = (p.description or '').upper()
            if 'CH340' in desc or 'CH341' in desc: return p.device
        for p in portas:
            if p.vid == 0x1a86: return p.device
        return None
    except Exception: return None

display_global = None

def validar_porta_com(porta):
    if not porta: return False
    try:
        teste = serial.Serial(porta, 115200, timeout=1)
        teste.close()
        return True
    except Exception: return False

def run_worker_cycle():
    global force_restart, display_global
    print("[Worker] Iniciando ciclo (buscando hardware e dados)...")
    
    porta = estado_app.get('porta_com', 'AUTO')
    if not porta or porta.strip().upper() == 'AUTO':
        porta_descoberta = auto_descobrir_com()
        if porta_descoberta:
            estado_app['porta_com'] = porta_descoberta
            porta = porta_descoberta
        else: porta = None

    if porta and not validar_porta_com(porta): porta = None

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
        except Exception:
            display_global = None
            
    if display_global is not None:
        try: display_global.Clear()
        except: pass

    update_preview(gerar_tela_padrao("Buscando dados..."))
    
    while is_running and not force_restart:
        try:
            steam_aleatorio = buscar_steam_random()
            promocoes = buscar_promocoes_steam()
            jogos = buscar_jogos_gratis()
            noticias = buscar_gamevicio()
            reddit = buscar_reddit_multiplos() 
            
            conteudo = steam_aleatorio + promocoes + jogos + noticias + reddit
            
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
                
                # --- SISTEMA INTELIGENTE DE TEMPO ---
                tipo = item.get('tipo')
                if tipo == 'JOGO':
                    t_slide = estado_app.get('tempo_jogos', 12)
                elif tipo == 'STEAM_PROMO':
                    t_slide = estado_app.get('tempo_promocoes', 12)
                elif tipo == 'STEAM_RANDOM':
                    t_slide = estado_app.get('tempo_random', 12)
                elif tipo == 'GAMEVICIO':
                    t_slide = estado_app.get('tempo_noticias', 12)
                elif tipo == 'REDDIT':
                    t_slide = estado_app.get('tempo_reddit', 12)
                else:
                    t_slide = 12
                
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
    
    if force_restart and display_global is not None:
        print("[LCD] Desconectando hardware para forçar reset limpo...")
        try: display_global.closeSerial()
        except: pass
        display_global = None

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
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(estado_app)

@app.route('/api/config', methods=['POST'])
def save_config():
    dados = request.json
    if dados:
        estado_app.update(dados)
        return jsonify({"status": "sucesso"}), 200
    return jsonify({"status": "erro"}), 400

@app.route('/api/preview')
def get_preview():
    with preview_lock: b = preview_bytes
    if b: return Response(b, mimetype='image/jpeg')
    return Response(b"", status=404)

@app.route('/api/restart', methods=['POST'])
def restart():
    global force_restart
    force_restart = True
    return jsonify({"status": "reiniciando"}), 200

def pedir_porta_com():
    porta_auto = auto_descobrir_com()
    if porta_auto:
        print(f"[LCD] ✅ Tela detectada automaticamente: {porta_auto}")
        estado_app['porta_com'] = porta_auto
        return
    
    try:
        portas = list(serial.tools.list_ports.comports())
        if portas:
            print("\n  Portas disponíveis no sistema:")
            for i, p in enumerate(portas): print(f"    [{i+1}] {p.device} — {p.description}")
    except: pass
    
    try: resposta = input("\n  Porta COM > ").strip()
    except: resposta = ""
    
    if resposta and resposta.upper() != 'SKIP':
        estado_app['porta_com'] = resposta.upper()
        print(f"  ✅ Porta configurada: {resposta.upper()}")
    print("")

def main():
    pedir_porta_com()
    
    t = threading.Thread(target=worker_thread, daemon=True)
    t.start()
    
    print("=======================================")
    print("  🌐 Acesso WEB: http://localhost:5000 ")
    print("=======================================")
    
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()