"""
Bot de postagens de filmes no canal @poltronix, com aprovação num canal de rascunhos.

Fluxo:
 1. Busca o filme no TMDB (capa, título, ano e sinopse em pt-BR).
 2. Manda uma PRÉVIA para o canal de rascunhos, com os botões ✅ Aprovar / ❌ Descartar.
 3. Quando você aprova, posta no @poltronix: capa + "Título (Ano)" + sinopse,
    com o botão "🎬 ASSISTA AQUI" levando para https://t.me/canalpoltronix.

De onde vêm os filmes:
 - Automático: lançamentos em cartaz no Brasil (--populares N), sem repetir.
 - Você: manda o nome do filme no canal de rascunhos (ou no privado do bot).

Comandos (no canal de rascunhos ou no privado do bot):
  Nome do Filme              -> manda prévia para aprovar
  Nome do Filme (2021)       -> idem, escolhendo o ano
  /forcar Nome do Filme      -> manda prévia mesmo se já foi postado antes
  /rascunho                  -> (enviar dentro do canal novo) define este canal como o de rascunhos

Uso local:
  python bot.py "Duna"             # manda prévia (ou posta direto se não houver canal de rascunhos)
  python bot.py --populares 1      # sugere 1 lançamento
  python bot.py --comandos         # processa pedidos e aprovações pendentes
  python bot.py "Duna" --teste     # só mostra o que seria enviado

Variáveis de ambiente (arquivo .env ou Secrets do GitHub):
  TELEGRAM_TOKEN   token do @BotFather
  TMDB_TOKEN       "API Read Access Token" do themoviedb.org
  ADMIN_USERNAME   seu @ do Telegram (sem o @)
  CANAL_ID         padrão: @poltronix
  RASCUNHO_ID      opcional; se vazio, usa o canal registrado com /rascunho (rascunho.txt)
"""
import argparse, json, os, re, sys, pathlib
import requests

def load_env(path=".env"):
    p = pathlib.Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()
TG = f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_TOKEN','')}"
TMDB = "https://api.themoviedb.org/3"
HDR = {"Authorization": f"Bearer {os.environ.get('TMDB_TOKEN','')}"}
CANAL = os.environ.get("CANAL_ID", "@poltronix")
# Botão em cada post, levando ao canal de trailers
BOTAO_TEXTO = os.environ.get("BOTAO_TEXTO", "🎬 ASSISTA AQUI")
BOTAO_LINK = os.environ.get("BOTAO_LINK", "https://t.me/canalpoltronix")
ADMIN = os.environ.get("ADMIN_USERNAME", "").lstrip("@").lower()
HIST = pathlib.Path("postados.json")       # filmes já publicados ou descartados
OFFSET = pathlib.Path("offset.txt")        # última atualização lida do Telegram
RASC_FILE = pathlib.Path("rascunho.txt")   # id do canal de rascunhos (definido com /rascunho)

# ---------------- utilidades ----------------

def historico():
    return json.loads(HIST.read_text()) if HIST.exists() else []

def marcar(mid):
    hist = historico()
    if mid not in hist:
        hist.append(mid); HIST.write_text(json.dumps(hist))

def rascunho_id():
    rid = os.environ.get("RASCUNHO_ID", "").strip()
    if not rid and RASC_FILE.exists():
        rid = RASC_FILE.read_text().strip()
    return int(rid) if re.fullmatch(r"-?\d+", rid or "") else (rid or None)

def tmdb(path, **params):
    params.setdefault("language", "pt-BR")
    params = {k: v for k, v in params.items() if v is not None}
    r = requests.get(f"{TMDB}{path}", headers=HDR, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def tg(method, **data):
    r = requests.post(f"{TG}/{method}", json=data, timeout=30).json()
    if not r.get("ok"):
        raise RuntimeError(f"Telegram {method}: {r.get('description', r)}")
    return r["result"]

def tg_quieto(method, **data):
    try:
        return tg(method, **data)
    except Exception as e:
        print(f"(aviso) {e}")

# ---------------- filmes ----------------

def buscar(nome):
    """Aceita 'Nome' ou 'Nome (2021)'. Retorna o ID do TMDB ou None."""
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", nome.strip())
    params = {"query": m.group(1), "year": m.group(2)} if m else {"query": nome.strip()}
    res = tmdb("/search/movie", **params)["results"]
    return res[0]["id"] if res else None

def detalhes(mid):
    f = tmdb(f"/movie/{mid}")
    return {
        "id": f["id"],
        "titulo": f["title"],
        "ano": (f.get("release_date") or "")[:4],
        "sinopse": f.get("overview") or "Sinopse indisponível.",
        "capa": melhor_capa(mid) or f.get("poster_path"),
    }

def melhor_capa(mid):
    """Escolhe, entre TODAS as capas do filme no TMDB, a mais nítida.
    Prioridade: capa em português em alta resolução > em inglês > sem texto,
    sempre preferindo a maior resolução (mínimo 1400px de largura)."""
    try:
        imgs = tmdb(f"/movie/{mid}/images", language=None,
                    include_image_language="pt,en,null").get("posters", [])
    except Exception as e:
        print(f"(aviso) imagens: {e}")
        return None
    if not imgs:
        return None
    def nota(i):
        return (i.get("vote_average", 0) or 0) * min(i.get("vote_count", 0) or 0, 10)
    for lang in ("pt", "en", None):
        hd = [i for i in imgs if i.get("iso_639_1") == lang and i.get("width", 0) >= 1400]
        if hd:
            esc = max(hd, key=lambda i: (nota(i), i["width"]))
            break
    else:
        esc = max(imgs, key=lambda i: i.get("width", 0))
    print(f"Capa escolhida entre {len(imgs)}: {esc['width']}x{esc['height']} "
          f"({esc.get('iso_639_1')}) https://image.tmdb.org/t/p/original{esc['file_path']}")
    return esc["file_path"]

def legenda(f):
    # Formato igual aos posts do canal: título (ano) em negrito + sinopse
    sinopse = f["sinopse"] if len(f["sinopse"]) < 900 else f["sinopse"][:897] + "..."
    return f"<b>{f['titulo']} ({f['ano']})</b>\n\n{sinopse}"

def baixar_capa(poster_path):
    """Baixa a capa na resolução ORIGINAL do TMDB (alta qualidade).
    Se passar do limite de 10 MB do Telegram, usa a maior versão reduzida (w780)."""
    for tam in ("original", "w780"):
        r = requests.get(f"https://image.tmdb.org/t/p/{tam}{poster_path}", timeout=60)
        r.raise_for_status()
        if len(r.content) < 9_500_000:
            print(f"Capa baixada ({tam}): {len(r.content)//1024} KB")
            return r.content
    return r.content

def enviar(chat, f, botoes):
    kb = {"inline_keyboard": botoes}
    if f["capa"]:
        foto = baixar_capa(f["capa"])
        r = requests.post(f"{TG}/sendPhoto", timeout=120,
                          data={"chat_id": chat, "caption": legenda(f), "parse_mode": "HTML",
                                "reply_markup": json.dumps(kb)},
                          files={"photo": ("capa.jpg", foto, "image/jpeg")}).json()
        if not r.get("ok"):
            raise RuntimeError(f"Telegram sendPhoto: {r.get('description', r)}")
        return r["result"]
    return tg("sendMessage", chat_id=chat, text=legenda(f), parse_mode="HTML", reply_markup=kb)

BOTAO_CANAL = [[{"text": BOTAO_TEXTO, "url": BOTAO_LINK}]]

def publicar(f):
    enviar(CANAL, f, BOTAO_CANAL)
    marcar(f["id"])
    print(f"Publicado: {f['titulo']}")

def previa(f, teste=False):
    """Manda para o canal de rascunhos; sem canal de rascunhos, publica direto."""
    rid = rascunho_id()
    if teste:
        print(f"---- {'RASCUNHO' if rid else 'CANAL'} ----\n{legenda(f)}\n[capa] https://image.tmdb.org/t/p/original{f['capa']}")
        return
    if not rid:
        return publicar(f)
    botoes = BOTAO_CANAL + [[
        {"text": "✅ Aprovar", "callback_data": f"ok:{f['id']}"},
        {"text": "❌ Descartar", "callback_data": f"no:{f['id']}"},
    ]]
    enviar(rid, f, botoes)
    print(f"Prévia enviada: {f['titulo']}")

def pedido(nome, forcar=False, teste=False):
    """Trata um nome de filme pedido por você. Retorna a resposta em texto."""
    mid = buscar(nome)
    if not mid:
        return f"❌ Não achei '{nome}' no TMDB. Tente com o ano: {nome} (2024)"
    if mid in historico() and not forcar:
        return f"⚠️ '{nome}' já foi postado (ou descartado) antes. Mande /forcar {nome} para ver de novo."
    f = detalhes(mid)
    previa(f, teste)
    return None

# ---------------- leitura do Telegram ----------------

def responder(chat, texto, teste=False):
    print(texto)
    if not teste:
        tg_quieto("sendMessage", chat_id=chat, text=texto)

def comandos(teste=False):
    """Processa pedidos de filmes e cliques em Aprovar/Descartar."""
    offset = int(OFFSET.read_text()) if OFFSET.exists() else 0
    ups = tg("getUpdates", offset=offset, timeout=0,
             allowed_updates=["message", "channel_post", "callback_query"])
    print(f"Bot @{tg('getMe')['username']}: {len(ups)} mensagem(ns) nova(s) | rascunho = {rascunho_id()}")
    for u in ups:
        OFFSET.write_text(str(u["update_id"] + 1))
        try:
            if "callback_query" in u:
                clique(u["callback_query"], teste)
            else:
                mensagem(u.get("message") or u.get("channel_post") or {}, teste)
        except Exception as e:
            print(f"Erro ao processar atualização {u['update_id']}: {e}")

def mensagem(msg, teste):
    chat = msg.get("chat", {})
    texto = (msg.get("text") or "").strip()
    if not texto:
        return
    user = (msg.get("from", {}).get("username") or "").lower()
    rid = rascunho_id()

    # Registrar o canal/grupo de rascunhos: mande /rascunho dentro dele
    if re.match(r"^/rascunho(@\w+)?$", texto, re.I):
        # em canal não há remetente; em grupo, só o admin pode registrar
        if chat.get("type") == "channel" or user == ADMIN:
            RASC_FILE.write_text(str(chat["id"]))
            responder(chat["id"], "✅ Este chat agora é o canal de rascunhos. "
                      "Mande nomes de filmes aqui e aprove as prévias.", teste)
        return

    no_rascunho = rid is not None and str(chat.get("id")) == str(rid)
    privado_admin = chat.get("type") == "private" and user == ADMIN
    if not (no_rascunho or privado_admin):
        if chat.get("type") == "private":
            responder(chat["id"], "Desculpe, só o administrador pode usar este bot.", teste)
        return  # ignora o @poltronix e outros chats
    if no_rascunho and chat.get("type") != "channel" and user != ADMIN:
        return  # num grupo de rascunhos, só o admin pede filmes

    forcar = texto.lower().startswith("/forcar")
    nome = re.sub(r"^/(postar|forcar)(@\w+)?\s*", "", texto, flags=re.I).strip()
    if not nome or nome.startswith("/"):
        responder(chat["id"], "Mande o nome do filme, por exemplo: Duna (2021)", teste)
        return
    try:
        resp = pedido(nome, forcar, teste)
    except Exception as e:
        resp = f"❌ Erro com '{nome}': {e}"
    if resp:
        responder(chat["id"], resp, teste)

_ja_tratados = set()

def clique(cq, teste):
    data = cq.get("data", "")
    msg = cq.get("message") or {}
    chat = msg.get("chat", {})
    user = (cq.get("from", {}).get("username") or "").lower()
    rid = rascunho_id()
    if rid is None or str(chat.get("id")) != str(rid) or user != ADMIN:
        tg_quieto("answerCallbackQuery", callback_query_id=cq["id"], text="Sem permissão.")
        return
    acao, _, mid = data.partition(":")
    chave = (chat.get("id"), msg.get("message_id"))
    if not mid.isdigit() or chave in _ja_tratados:
        return
    _ja_tratados.add(chave)
    f = detalhes(int(mid))
    if acao == "ok":
        if teste:
            print(f"[teste] publicaria {f['titulo']}"); return
        publicar(f)
        status = f"✅ PUBLICADO no {CANAL}"
    else:
        marcar(f["id"])
        status = "❌ DESCARTADO"
    tg_quieto("answerCallbackQuery", callback_query_id=cq["id"], text=status)
    # Atualiza a prévia: troca os botões pelo status
    novo = f"{status}\n\n{legenda(f)}"
    kb = {"inline_keyboard": []}
    if msg.get("photo"):
        tg_quieto("editMessageCaption", chat_id=chat["id"], message_id=msg["message_id"],
                  caption=novo, parse_mode="HTML", reply_markup=kb)
    else:
        tg_quieto("editMessageText", chat_id=chat["id"], message_id=msg["message_id"],
                  text=novo, parse_mode="HTML", reply_markup=kb)

# ---------------- principal ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nome", nargs="?")
    ap.add_argument("--id", type=int)
    ap.add_argument("--populares", type=int, metavar="N")
    ap.add_argument("--comandos", action="store_true")
    ap.add_argument("--teste", action="store_true")
    a = ap.parse_args()
    if a.comandos:
        comandos(a.teste)
    elif a.populares:
        hist = set(historico())
        ids = [m["id"] for m in tmdb("/movie/now_playing", region="BR")["results"] if m["id"] not in hist]
        for mid in ids[:a.populares]:
            previa(detalhes(mid), a.teste)
            if rascunho_id():
                marcar(mid)  # não sugerir o mesmo lançamento de novo
    elif a.id:
        previa(detalhes(a.id), a.teste)
    elif a.nome:
        resp = pedido(a.nome, forcar=True, teste=a.teste)
        if resp:
            sys.exit(resp)
    else:
        ap.error("informe um nome, --id, --populares ou --comandos")

if __name__ == "__main__":
    main()
