# Achados & Perdidos — Docker Compose

Documentação do ambiente em contêineres do **Achados & Perdidos**, a pequena API web (Flask + PostgreSQL) do Setor de Atendimento ao Estudante para cadastrar objetos perdidos e suas fotos.
Trabalho da **Avaliação de Grau 1 — Computação em Nuvem** (Prof. Fábio Castro), de [@lucasetculbra](https://github.com/lucasetculbra).

> WARNING: **Este site é a documentação do projeto — não é o servidor da aplicação.** O GitHub Pages só hospeda estas páginas estáticas. A API roda no seu computador, com Docker:
> `docker compose up -d --build` (veja [Como executar](guia.md)).

## O que foi entregue

Um repositório em que **um único comando** sobe a aplicação web e o banco de dados, com os dados persistidos em volumes — itens e fotos sobrevivem à recriação dos contêineres — e uma documentação que explica
como e por que cada peça funciona.

<div class="grid cards" markdown>

- :material-rocket-launch: **Como executar**

    ---

    Pré-requisitos, `.env`, subir, testar, parar e destruir; tabela das rotas da API e diagnóstico.

    [:octicons-arrow-right-24: Abrir o guia](guia.md)

- :material-sitemap: **Arquitetura**

    ---

    Diagrama com rede, portas, volumes, *bind mounts* e o que fica dentro e fora da rede interna.

    [:octicons-arrow-right-24: Ver o diagrama](arquitetura.md)

- :material-file-document-outline: **Relatório técnico**

    ---

    Dockerfile instrução por instrução, cada bloco do Compose, o caminho de um `POST /itens` e o ciclo de vida dos volumes.

    [:octicons-arrow-right-24: Ler o relatório](RELATORIO.md)

- :material-cloud-outline: **Reflexão e nuvem**

    ---

    As sete questões respondidas e a tabela de equivalência com Azure, AWS e Google Cloud.

    [:octicons-arrow-right-24: Ver as respostas](REFLEXAO.md)

- :material-star-circle-outline: **Bônus**

    ---

    Proxy reverso Nginx, backup e restauração do volume de fotos, e painel Adminer em um *profile*.

    [:octicons-arrow-right-24: Ver os bônus](bonus.md)

- :material-source-branch-check: **CI/CD e GitHub Pages**

    ---

    Testes automáticos com Docker de verdade e publicação desta documentação só depois de os testes passarem.

    [:octicons-arrow-right-24: Ver o workflow](cicd.md)

</div>

## Tecnologias

| Peça | Tecnologia |
|---|---|
| API | Python 3.12, Flask, psycopg 3, Gunicorn — imagem própria sobre `python:3.12-slim` |
| Banco | PostgreSQL 16 (`postgres:16-alpine`) |
| Proxy reverso | Nginx 1.30 |
| Painel do banco (depuração) | Adminer 6 |
| Orquestração | Docker Compose v2: rede `bridge` definida pelo usuário, volumes nomeados, *healthchecks* |
| Automação | Scripts Python (biblioteca padrão) e GitHub Actions |
| Documentação | Markdown, Mermaid, MkDocs Material, GitHub Pages |

## Requisitos e onde estão comprovados

Cada requisito do enunciado tem um arquivo que o implementa e uma **evidência** (saída real de um comando). Os arquivos de código estão no
[repositório](https://github.com/lucasetculbra/achados-perdidos-docker-compose).

| Requisito | Implementação | Evidência |
|---|---|---|
| **RF01** — `GET /health` → `ok` e `conectado` | `app/app.py` (fornecido) | [`tarefa4/03`](evidencias/tarefa4/03-health.txt) |
| **RF02** — listar e filtrar por local | `app/app.py` | [`tarefa4/04`](evidencias/tarefa4/04-itens.txt), [`05`](evidencias/tarefa4/05-itens-filtro-local.txt) |
| **RF03** — cadastrar com/sem foto | `app/app.py` | [`tarefa4/06`](evidencias/tarefa4/06-cadastro-com-foto.txt), [`07`](evidencias/tarefa4/07-cadastro-sem-foto-e-validacao.txt) |
| **RF04** — servir foto e `/estatisticas` | `app/app.py` | [`tarefa4/08`](evidencias/tarefa4/08-estatisticas.txt), [`09`](evidencias/tarefa4/09-foto-download.txt) |
| **RNF01** — tudo sobe com `docker compose up -d --build` | `docker-compose.yml`, `app/Dockerfile` | [`tarefa4/01`](evidencias/tarefa4/01-docker-compose-up.txt), [`clone-limpo`](evidencias/clone-limpo.txt) |
| **RNF02** — itens e fotos sobrevivem a `down` + `up` | volumes `dados_banco` e `fotos` | [`tarefa5/01`](evidencias/tarefa5/01-recriacao-conteineres.txt), [`02`](evidencias/tarefa5/02-inspecao-volumes.txt), [`03`](evidencias/tarefa5/03-remocao-volumes.txt) |
| **RNF03** — nenhuma senha em Dockerfile, compose ou código | `.env` (não versionado), `.env.example`, interpolação `${…}` | [`complementares/05`](evidencias/complementares/05-sem-segredos-na-imagem.txt) |
| **RNF04** — `web` sem privilégios de root | `USER 10001:10001` no `Dockerfile` | [`complementares/01`](evidencias/complementares/01-usuario-nao-root.txt) |
| **RNF05** — `web` só inicia com o banco pronto | `healthcheck` + `depends_on … service_healthy` | [`tarefa4/01`](evidencias/tarefa4/01-docker-compose-up.txt) |
| Banco **sem porta publicada** | sem `ports` no serviço `db` | [`complementares/02`](evidencias/complementares/02-portas-publicadas.txt) |
| Rede `bridge` definida pelo usuário | `rede_interna` | [`complementares/06`](evidencias/complementares/06-docker-network-inspect.txt) |
| Tamanho da imagem | `python:3.12-slim`, `--no-cache-dir` | [`complementares/07`](evidencias/complementares/07-docker-image-ls.txt) |
| **Bônus A, B e C** | `nginx/default.conf`, `scripts/backup_fotos.py`, serviço `adminer` | [`bonus/`](evidencias/README.md#bonus) |

O resultado de **cada** verificação automática está em [`resumo-testes.md`](evidencias/resumo-testes.md) e [`reflexao/resumo-experimentos.md`](evidencias/reflexao/resumo-experimentos.md);
o contexto das execuções (versões, portas e o SHA-256 dos arquivos testados) em [`00-ambiente.txt`](evidencias/00-ambiente.txt); o índice completo, com uma legenda por arquivo, em [Evidências](evidencias/README.md).

> NOTE: **Porta usada nos testes.** Nos testes feitos no computador do autor a porta 8080 estava ocupada por outro programa, então o ambiente de teste usou a porta **18080** (um *override* de porta só no ambiente de teste; o `docker-compose.yml` entregue publica a **8080**).
> Isso está registrado no cabeçalho de cada evidência. A CI do GitHub roda na 8080.

## Como navegar

Use o menu lateral. Para só subir o ambiente, vá direto a [Como executar](guia.md); para entender o desenho, comece pela [Arquitetura](arquitetura.md) e siga para o [Relatório técnico](RELATORIO.md).
