# Bot Poltronix

Posta capa, título (ano) e sinopse de filmes no canal [@poltronix](https://t.me/poltronix), com o botão "🎬 ASSISTA AQUI" levando para [@canalpoltronix](https://t.me/canalpoltronix). Dados e imagens: [TMDB](https://www.themoviedb.org/).

Todo post passa antes por um **canal de rascunhos**: o bot manda a prévia com os botões ✅ Aprovar / ❌ Descartar, e só publica no @poltronix depois que você aprova.

- **Sugestões automáticas:** 1 lançamento em cartaz às 12h, 18h e 22h (Brasília), direto no rascunho.
- **Pedidos seus:** mande o nome do filme no canal de rascunhos, por exemplo `Duna (2021)`.
- O bot confere pedidos e aprovações a cada 5 minutos (o GitHub pode atrasar um pouco).

## Configuração
1. Secrets (Settings → Secrets and variables → Actions): `TELEGRAM_TOKEN`, `TMDB_TOKEN`, `ADMIN_USERNAME`.
2. Crie um canal privado de rascunhos, adicione o bot como administrador e mande `/rascunho` nele.
