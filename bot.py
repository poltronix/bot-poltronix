"""
Bot de postagens automáticas de filmes (rascunho).

Fluxo:
 1. Busca o filme no TMDB (capa, título, ano e sinopse em pt-BR).
 2. Posta a capa com "Título (Ano)" + sinopse no canal @poltronix.
 3. Cada post leva um botão "🎬 ASSISTA AQUI" para https://t.me/canalpoltronix
    (os trailers lá continuam manuais).

Uso:
  python bot.py "Duna Parte Dois"      # posta um filme pelo nome
  python bot.py "Duna (2021)"          # nome + ano, para acertar o filme certo
  python bot.py --id 693134            # posta pelo ID do TMDB
  python bot.py --populares 3          # posta 3 filmes em cartaz no Brasil ainda não postados
  python bot.py --comandos             # lê os pedidos que você mandou no privado do bot e posta
  python bot.py "Duna" --teste         # só mostra o que seria postado, não envia nada

Comandos no privado do bot (só o ADMIN_USERNAME é atendido):
  /postar Nome do Filme      (ou só o nome do filme)
  /postar Nome do Filme (2021)
  /forcar Nome do Filme      (posta mesmo se já foi postado antes)

Variáveis de ambiente (arquivo .env ou Secrets do GitHub):
  TELEGRAM_TOKEN   token do @BotFather
  TMDB_TOKEN       "API Read Access Token" do themoviedb.org (grátis)
  ADMIN_USERNAME   seu @ do Telegram (sem o @), o único que pode pedir posts
  CANAL_ID         padrão: @poltronix
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
HIST = pathlib.Path("postados.json")
OFFSET = pathlib.Path("offset.txt")

def historico():
    return json.loads(HIST.read_text()) if HIST.exists() else []

def tmdb(path, **params):
    params.setdefault("language", "pt-BR")
    r = requests.get(f"{TMDB}{path}", headers=HDR, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

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
        "capa": f"https://image.tmdb.org/t/p/w780{f['poster_path']}" if f.get("poster_path") else None,
    }

def legenda(f):
    # Formato igual aos posts do canal: título (ano) em negrito + sinopse
    sinopse = f["sinopse"] if len(f["sinopse"]) < 900 else f["sinopse"][:897] + "..."
    return f"<b>{f['titulo']} ({f['ano']})</b>\n\n{sinopse}"

def tg(method, **data):
    r = requests.post(f"{TG}/{method}", json=data, timeout=30).json()
    if not r.get("ok"):
        raise RuntimeError(f"Telegram {method}: {r}")
    return r["result"]

def postar(f, teste=False):
    txt = legenda(f)
    if teste:
        print("---- CANAL ----\n" + txt + f"\n[capa] {f['capa']}\n[botão] {BOTAO_TEXTO} -> {BOTAO_LINK}")
        return
    kb = {"inline_keyboard": [[{"text": BOTAO_TEXTO, "url": BOTAO_LINK}]]}
    if f["capa"]:
        tg("sendPhoto", chat_id=CANAL, photo=f["capa"], caption=txt, parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=CANAL, text=txt, parse_mode="HTML", reply_markup=kb)
    hist = historico()
    if f["id"] not in hist:
        hist.append(f["id"]); HIST.write_text(json.dumps(hist))
    print(f"Postado: {f['titulo']}")

def comandos(teste=False):
    """Processa mensagens que o admin mandou no privado do bot."""
    if not ADMIN:
        sys.exit("Defina ADMIN_USERNAME para usar --comandos")
    offset = int(OFFSET.read_text()) if OFFSET.exists() else 0
    ups = tg("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
    for u in ups:
        OFFSET.write_text(str(u["update_id"] + 1))
        msg = u.get("message") or {}
        chat = msg.get("chat", {})
        texto = (msg.get("text") or "").strip()
        user = (msg.get("from", {}).get("username") or "").lower()
        if chat.get("type") != "private" or not texto:
            continue
        if user != ADMIN:
            tg("sendMessage", chat_id=chat["id"], text="Desculpe, só o administrador pode usar este bot.")
            continue
        forcar = texto.lower().startswith("/forcar")
        nome = re.sub(r"^/(postar|forcar)(@\w+)?\s*", "", texto, flags=re.I).strip()
        if not nome or nome.startswith("/"):
            tg("sendMessage", chat_id=chat["id"],
               text="Mande /postar Nome do Filme (ou Nome do Filme (2021) para escolher o ano).")
            continue
        try:
            mid = buscar(nome)
            if not mid:
                resp = f"❌ Não achei '{nome}' no TMDB. Tente com o ano: {nome} (2024)"
            elif mid in historico() and not forcar:
                resp = f"⚠️ '{nome}' já foi postado antes. Use /forcar {nome} para postar de novo."
            else:
                f = detalhes(mid)
                postar(f, teste)
                resp = f"✅ Postado no {CANAL}: {f['titulo']} ({f['ano']})"
        except Exception as e:
            resp = f"❌ Erro ao postar '{nome}': {e}"
        print(resp)
        if not teste:
            tg("sendMessage", chat_id=chat["id"], text=resp)

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
            postar(detalhes(mid), a.teste)
    else:
        if not (a.id or a.nome):
            ap.error("informe um nome, --id, --populares ou --comandos")
        mid = a.id or buscar(a.nome)
        if not mid:
            sys.exit(f"Nenhum filme encontrado para '{a.nome}'")
        postar(detalhes(mid), a.teste)

if __name__ == "__main__":
    main()
