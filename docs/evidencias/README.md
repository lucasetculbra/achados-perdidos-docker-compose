# Evidências

Saídas **reais** dos comandos executados pelos scripts [`testar_ambiente.py`](https://github.com/lucasetculbra/achados-perdidos-docker-compose/blob/main/scripts/testar_ambiente.py) e
[`experimentos_reflexao.py`](https://github.com/lucasetculbra/achados-perdidos-docker-compose/blob/main/scripts/experimentos_reflexao.py). Cada arquivo começa com uma legenda de uma linha;
este índice é gerado automaticamente a partir delas. Contexto da execução (versões, portas, hashes dos arquivos): [`00-ambiente.txt`](00-ambiente.txt). Resultado de cada verificação: [`resumo-testes.md`](resumo-testes.md).

> Para regenerar: `python scripts/testar_ambiente.py --evidencias docs/evidencias` e `python scripts/experimentos_reflexao.py --evidencias docs/evidencias` (veja o README).

## Geral

| Arquivo | O que demonstra |
|---|---|
| [`00-ambiente.txt`](00-ambiente.txt) | Contexto da execução dos testes: versões, projeto Compose isolado, portas e SHA-256 dos arquivos testados. |
| [`clone-limpo.txt`](clone-limpo.txt) | Os testes completos repetidos em um clone recém-feito do repositório, depois de cp .env.example .env: o ambiente sobe e passa só com o que está no Git. |

## bonus

| Arquivo | O que demonstra |
|---|---|
| [`bonus/01-nginx-unico-publicador.txt`](bonus/01-nginx-unico-publicador.txt) | Só o nginx expõe a porta do host; as respostas chegam com 'Server: nginx' (sem versão), passando pelo proxy até o web. |
| [`bonus/02-nginx-upload-grande.txt`](bonus/02-nginx-upload-grande.txt) | Foto de ~2 MB passa pelo proxy (client_max_body_size 10m); arquivo de ~11 MB é recusado com 413. |
| [`bonus/03-nginx-fotos-cabecalhos-de-seguranca.txt`](bonus/03-nginx-fotos-cabecalhos-de-seguranca.txt) | Em /fotos/ o nginx força download de arquivos que não são imagem (ex.: .html enviado como foto) e adiciona nosniff e CSP. |
| [`bonus/04-adminer-profile-debug.txt`](bonus/04-adminer-profile-debug.txt) | O Adminer só sobe com --profile debug, escuta apenas em 127.0.0.1, alcança o db pela rede interna (sem publicar 5432) e é encerrado sozinho. |
| [`bonus/05-backup-e-restauracao-fotos.txt`](bonus/05-backup-e-restauracao-fotos.txt) | Backup do volume fotos em .tar.gz com um contêiner temporário (docker run --rm) e restauração em um volume novo, com SHA-256 idênticos. |

## complementares

| Arquivo | O que demonstra |
|---|---|
| [`complementares/01-usuario-nao-root.txt`](complementares/01-usuario-nao-root.txt) | O contêiner web roda como 'appuser' (UID 10001), nunca como root (RNF04). |
| [`complementares/02-portas-publicadas.txt`](complementares/02-portas-publicadas.txt) | Só o nginx publica porta no host; o PostgreSQL (5432) e o web (5000) existem apenas na rede interna. |
| [`complementares/03-dns-interno.txt`](complementares/03-dns-interno.txt) | O web encontra o banco pelo nome 'db' usando o DNS embutido do Docker (127.0.0.11), sem IP fixo. |
| [`complementares/04-sistema-de-arquivos-somente-leitura.txt`](complementares/04-sistema-de-arquivos-somente-leitura.txt) | O sistema de arquivos do web é somente leitura (só /app/uploads e /tmp aceitam escrita) e o init.sql é montado :ro no db. |
| [`complementares/05-sem-segredos-na-imagem.txt`](complementares/05-sem-segredos-na-imagem.txt) | A imagem do web não contém senhas: nenhuma variável embutida é de banco e o .env não está em /app; as credenciais só chegam em tempo de execução (RNF03). |
| [`complementares/06-docker-network-inspect.txt`](complementares/06-docker-network-inspect.txt) | docker network inspect da rede_interna: rede bridge definida pelo usuário com os contêineres db, web e nginx. |
| [`complementares/07-docker-image-ls.txt`](complementares/07-docker-image-ls.txt) | docker image ls: tamanho da imagem do web (base python:3.12-slim + dependências) comparado às imagens oficiais usadas. |

## reflexao

| Arquivo | O que demonstra |
|---|---|
| [`reflexao/00-contexto.txt`](reflexao/00-contexto.txt) | Contexto da execução dos experimentos da reflexão (versões, projeto isolado e hashes dos arquivos). |
| [`reflexao/q1-dns-bridge-padrao-x-rede-definida.txt`](reflexao/q1-dns-bridge-padrao-x-rede-definida.txt) | Na bridge padrão um contêiner não resolve outro pelo nome; em uma rede definida pelo usuário o DNS embutido (127.0.0.11) resolve. |
| [`reflexao/q3-init-sql-alterado.txt`](reflexao/q3-init-sql-alterado.txt) | Com o volume dados_banco já populado, um init.sql alterado NÃO é reaplicado (initdb é ignorado); a coluna nova só entra com ALTER TABLE, sem perder dados. |
| [`reflexao/q5-cache-de-camadas.txt`](reflexao/q5-cache-de-camadas.txt) | Build com cache: sem mudanças tudo é reaproveitado; mudando só o app.py o pip install continua em cache; mudando o requirements.txt ele é refeito. |
| [`reflexao/q7-scale-com-nginx.txt`](reflexao/q7-scale-com-nginx.txt) | Com o nginx na frente e sem porta fixa no web, --scale web=3 funciona: 3 réplicas respondem e compartilham o volume fotos (no mesmo host). |
| [`reflexao/q7-scale-conflito-de-porta.txt`](reflexao/q7-scale-conflito-de-porta.txt) | Se o web publicasse uma porta fixa no host (como no enunciado básico, 8080:5000), --scale web=3 falha: só um contêiner pode ocupar a porta. |

## tarefa4

| Arquivo | O que demonstra |
|---|---|
| [`tarefa4/01-docker-compose-up.txt`](tarefa4/01-docker-compose-up.txt) | docker compose up -d --build constrói a imagem do web e sobe db, web e nginx com um único comando (RNF01), na ordem db -> web -> nginx (RNF05). |
| [`tarefa4/02-docker-compose-ps.txt`](tarefa4/02-docker-compose-ps.txt) | docker compose ps: db healthy e web/nginx em execução; só o nginx tem porta publicada no host. |
| [`tarefa4/03-health.txt`](tarefa4/03-health.txt) | GET /health responde "status": "ok" e "banco": "conectado" (RF01). |
| [`tarefa4/04-itens.txt`](tarefa4/04-itens.txt) | GET /itens lista os três objetos de exemplo criados pelo init.sql na primeira execução (RF02). |
| [`tarefa4/05-itens-filtro-local.txt`](tarefa4/05-itens-filtro-local.txt) | GET /itens?local=biblio filtra por local sem diferenciar maiúsculas de minúsculas (RF02). |
| [`tarefa4/06-cadastro-com-foto.txt`](tarefa4/06-cadastro-com-foto.txt) | POST /itens com foto (multipart) devolve 201 e o nome da foto; o item passa a aparecer em GET /itens com a URL /fotos/<nome> (RF03). |
| [`tarefa4/07-cadastro-sem-foto-e-validacao.txt`](tarefa4/07-cadastro-sem-foto-e-validacao.txt) | POST /itens sem foto devolve 201 com foto=null; sem o campo obrigatório 'local' devolve 400 (RF03). |
| [`tarefa4/08-estatisticas.txt`](tarefa4/08-estatisticas.txt) | GET /estatisticas informa o total de itens no banco e de fotos no volume (RF04). |
| [`tarefa4/09-foto-download.txt`](tarefa4/09-foto-download.txt) | GET /fotos/<nome> devolve exatamente o arquivo enviado (mesmo SHA-256) e o nginx acrescenta cabeçalhos de segurança (RF04). |
| [`tarefa4/10-foto-no-navegador.txt`](tarefa4/10-foto-no-navegador.txt) | A URL da foto retornada em GET /itens aberta no navegador (roteiro da Tarefa 4). ([captura](tarefa4/10-foto-no-navegador.png)) |
| [`tarefa4/11-logs-web.txt`](tarefa4/11-logs-web.txt) | docker compose logs web --tail 20: o Gunicorn registra as requisições recebidas pelo web. |

## tarefa5

| Arquivo | O que demonstra |
|---|---|
| [`tarefa5/01-recriacao-conteineres.txt`](tarefa5/01-recriacao-conteineres.txt) | docker compose down + up -d recria os contêineres e, mesmo assim, itens e fotos continuam lá (RNF02). |
| [`tarefa5/02-inspecao-volumes.txt`](tarefa5/02-inspecao-volumes.txt) | docker volume ls/inspect: os dois volumes nomeados, onde ficam fisicamente (Mountpoint) e o conteúdo do volume de fotos. |
| [`tarefa5/03-remocao-volumes.txt`](tarefa5/03-remocao-volumes.txt) | docker compose down -v apaga os volumes: itens e fotos cadastrados somem e o init.sql recria os 3 itens de exemplo (contraprova do RNF02). |
| [`tarefa5/04-foto-apos-recriacao.txt`](tarefa5/04-foto-apos-recriacao.txt) | A mesma foto aberta no navegador DEPOIS do down + up: o arquivo sobreviveu no volume fotos. ([captura](tarefa5/04-foto-apos-recriacao.png)) |
