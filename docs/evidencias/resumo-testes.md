# Resumo das verificações automáticas

Gerado em 2026-10-19T23:21:36-03:00 — **66/66 verificações aprovadas**.

| Requisito | Verificação | Resultado |
|---|---|---|
| RNF01 | docker compose up -d --build conclui com código 0 só com o Docker e o arquivo .env | ✅ passou |
| RNF05 | o web só iniciou depois de o db ficar healthy (ordem na saída do compose) | ✅ passou |
| RNF05 | o nginx só iniciou depois de o web ficar healthy | ✅ passou |
| T4 | serviço db em execução e healthy | ✅ passou |
| T4 | serviço web em execução e healthy | ✅ passou |
| T4 | serviço nginx em execução e healthy | ✅ passou |
| RF01 | GET /health -> 200, status=ok, banco=conectado | ✅ passou |
| RF02 | GET /itens devolve exatamente os 3 itens de exemplo do init.sql | ✅ passou |
| RF02 | filtro local=biblio devolve só 'Biblioteca' | ✅ passou |
| RF02 | filtro é insensível a maiúsculas (BIBLIO = biblio) | ✅ passou |
| RF02 | filtro sem correspondência devolve lista vazia | ✅ passou |
| RF03 | POST /itens com foto -> 201 e nome <uuid>.png | ✅ passou |
| RF03 | o item cadastrado aparece em GET /itens com foto=/fotos/<nome> | ✅ passou |
| RF03 | POST /itens sem foto -> 201 e foto=null | ✅ passou |
| RF03 | POST /itens sem 'local' -> 400 | ✅ passou |
| RF04 | GET /estatisticas após os cadastros da Tarefa 4: 5 itens no banco e 1 fotos no volume | ✅ passou |
| RF04 | GET /fotos/<nome> -> 200 com o mesmo SHA-256 do arquivo enviado | ✅ passou |
| RF04 | Content-Type da foto é image/png | ✅ passou |
| T4 | captura do navegador gerada para /fotos/a6ed12ba21e947c1a670489ef3658ea8.... | ✅ passou |
| T4 | logs do web registram as requisições (POST /itens e GET /health) | ✅ passou |
| RNF04 | docker compose exec web whoami não retorna root | ✅ passou |
| RNF04 | o processo do web não tem UID 0 | ✅ passou |
| RNF/ARQ | o db não publica nenhuma porta no host | ✅ passou |
| RNF/ARQ | o web não publica nenhuma porta no host (bônus A) | ✅ passou |
| RNF/ARQ | o nginx publica apenas a porta 18080 | ✅ passou |
| Q1 | o nome 'db' resolve para o IP do contêiner db na rede_interna | ✅ passou |
| SEG | o web não consegue gravar fora dos volumes (read_only) | ✅ passou |
| SEG | o web consegue gravar em /app/uploads (volume fotos) | ✅ passou |
| T3 | o bind mount do init.sql é somente leitura | ✅ passou |
| RNF03 | variáveis embutidas na imagem do web não incluem senha (nomes e valores verificados) | ✅ passou |
| RNF03 | o arquivo .env não está dentro da imagem (/app) | ✅ passou |
| T3 | rede_interna é do tipo bridge e contém db, web e nginx | ✅ passou |
| T2 | imagem do web enxuta (< 300 MB) — docker image inspect: 50 MB | ✅ passou |
| T5.1 | GET /estatisticas antes dos cadastros: 5 itens no banco e 1 fotos no volume | ✅ passou |
| T5.1 | GET /estatisticas antes do down: 7 itens no banco e 3 fotos no volume | ✅ passou |
| RNF02 | GET /estatisticas depois de down + up -d: 7 itens no banco e 3 fotos no volume | ✅ passou |
| RNF02 | a lista de itens (ids, textos, fotos, datas) é idêntica depois de down + up | ✅ passou |
| RNF02 | os arquivos de foto têm os mesmos SHA-256 depois de down + up | ✅ passou |
| T5.1 | o down manteve os dois volumes nomeados | ✅ passou |
| T4 | captura do navegador gerada para /fotos/a6ed12ba21e947c1a670489ef3658ea8.... | ✅ passou |
| T5.2 | GET /estatisticas antes da inspeção: 7 itens no banco e 3 fotos no volume | ✅ passou |
| T5.2 | docker volume inspect mostra os volumes dados_banco e fotos (driver local) com Mountpoint próprio | ✅ passou |
| T3 | db monta dados_banco em /var/lib/postgresql/data e o init.sql como bind somente leitura | ✅ passou |
| BONUS-B | o backup gerou um arquivo .tar.gz não vazio | ✅ passou |
| BONUS-B | a restauração em volume novo preserva o dono dos arquivos (UID 10001) | ✅ passou |
| BONUS-B | volume restaurado tem os mesmos arquivos e SHA-256 do volume original | ✅ passou |
| T5.3 | GET /estatisticas antes do down -v: 7 itens no banco e 3 fotos no volume | ✅ passou |
| T5.3 | GET /estatisticas depois do down -v + up -d: 3 itens no banco e 0 fotos no volume | ✅ passou |
| T5.3 | o down -v removeu os dois volumes | ✅ passou |
| T5.3 | depois do down -v só existem os 3 itens de exemplo do init.sql | ✅ passou |
| T5.3 | a foto cadastrada antes do down -v não existe mais (404) | ✅ passou |
| T5.3 | o log do db mostra o init.sql executado de novo (CREATE TABLE + INSERT 0 3) | ✅ passou |
| BONUS-A | a resposta passa pelo nginx (Server: nginx, sem número de versão) | ✅ passou |
| BONUS-A | GET /estatisticas depois dos uploads: 4 itens no banco e 1 fotos no volume | ✅ passou |
| BONUS-A | upload de ~2 MB pelo proxy -> 201 | ✅ passou |
| BONUS-A | upload de ~11 MB é recusado pelo proxy -> 413 (limite de 10 MB) | ✅ passou |
| BONUS-A | o .html enviado como foto é servido com Content-Disposition: attachment (único cabeçalho) | ✅ passou |
| BONUS-A | a imagem PNG é servida inline (único Content-Disposition) | ✅ passou |
| BONUS-A | as fotos levam X-Content-Type-Options: nosniff e Content-Security-Policy com sandbox | ✅ passou |
| BONUS-C | sem o profile debug o adminer não está no ambiente | ✅ passou |
| BONUS-C | o adminer não aparece entre os serviços sem o profile | ✅ passou |
| BONUS-C | com --profile debug o Adminer responde HTTP 200 em 127.0.0.1 | ✅ passou |
| BONUS-C | o Adminer alcança db:5432 pela rede interna | ✅ passou |
| BONUS-C | o db continua sem porta publicada no host | ✅ passou |
| BONUS-C | docker compose rm -sf adminer remove só o adminer | ✅ passou |
| RNF03 | evidências geradas não contêm a senha do .env nem caminhos do computador do autor | ✅ passou |

Gerado por `scripts/testar_ambiente.py`; cada linha corresponde a uma asserção executada contra o ambiente real.
