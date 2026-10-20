# Desafios bônus

Os três desafios adicionais foram implementados **depois** de os requisitos obrigatórios estarem funcionando e testados (a versão só com os obrigatórios está na tag Git `base-obrigatoria`).
Todos passam pelos testes automáticos (`scripts/testar_ambiente.py`) e não alteram o comportamento do restante.

| Bônus | Pontos | O que é | Prova |
|---|---|---|---|
| **A — Proxy reverso** | +0,4 | `nginx` na frente do `web`; só o `nginx` publica a 8080 | [`bonus/01`](evidencias/bonus/01-nginx-unico-publicador.txt), [`bonus/02`](evidencias/bonus/02-nginx-upload-grande.txt), [`bonus/03`](evidencias/bonus/03-nginx-fotos-cabecalhos-de-seguranca.txt) |
| **B — Backup do volume** | +0,3 | `.tar.gz` do volume `fotos` com `docker run --rm` e restauração em volume novo | [`bonus/05`](evidencias/bonus/05-backup-e-restauracao-fotos.txt) |
| **C — Painel do banco** | +0,3 | `adminer` no profile `debug` | [`bonus/04`](evidencias/bonus/04-adminer-profile-debug.txt) |

## A — Nginx como proxy reverso

**O que mudou.** O serviço `nginx` (imagem `nginx:1.30-alpine`) publica `8080:80`; o serviço `web` perdeu o `ports` e ficou só com `expose: "5000"`. O `nginx` encaminha tudo para `web:5000` pela `rede_interna`.
O [diagrama](arquitetura.md) já reflete a nova rota (navegador → `nginx` → `web` → `db`) e a [ordem de inicialização](arquitetura.md#ordem-de-inicializacao) agora é **db → web → nginx**.

**Como conferir:**

```bash
docker compose ps                          # só o nginx mostra 0.0.0.0:8080->80
docker inspect achados-perdidos-web-1 --format '{{json .NetworkSettings.Ports}}'   # {"5000/tcp":null}
curl -I http://localhost:8080/health       # "Server: nginx" (sem número de versão)
```

**Decisões de configuração** ([`nginx/default.conf`](https://github.com/lucasetculbra/achados-perdidos-docker-compose/blob/main/nginx/default.conf)):

- `resolver 127.0.0.11 valid=10s` e `proxy_pass` por variável: o nome `web` é resolvido **a cada 10 s**. Sem isso o `nginx` guardaria o IP do `web` na inicialização e quebraria quando o `web` fosse recriado; com isso ele também distribui entre
  réplicas (`--scale web=3`, [Q7](REFLEXAO.md#q7-docker-compose-up-d-scale-web3)).
- `client_max_body_size 10m`: o padrão (1 MB) rejeitaria fotos comuns. **Medido:** 2 MB passam (`201`), 11 MB recebem `413` ([`bonus/02`](evidencias/bonus/02-nginx-upload-grande.txt)).
- Em `/fotos/`: `X-Content-Type-Options: nosniff`, `Content-Security-Policy` com `sandbox` e `Content-Disposition: attachment` para tudo que não for imagem. O `app.py` aceita **qualquer** arquivo como "foto" e o serve com o tipo
  deduzido da extensão; sem essa proteção, um `.html` enviado seria executado no site. **Medido:** o `.html` enviado como foto é baixado, o PNG é exibido, e há um único `Content-Disposition` em cada resposta
  ([`bonus/03`](evidencias/bonus/03-nginx-fotos-cabecalhos-de-seguranca.txt)). Descartar o cabeçalho do Flask com `proxy_hide_header` foi necessário: dois `Content-Disposition` diferentes fariam alguns navegadores recusarem a resposta.

## B — Backup e restauração do volume `fotos`

O volume não é montado no computador: um **contêiner temporário** (`docker run --rm`, imagem `alpine:3.24`) monta o volume e uma pasta do host e roda o `tar` lá dentro. O script
[`scripts/backup_fotos.py`](https://github.com/lucasetculbra/achados-perdidos-docker-compose/blob/main/scripts/backup_fotos.py) automatiza os dois sentidos e funciona igual no Windows, Linux e macOS:

```bash
python scripts/backup_fotos.py backup                                   # cria backups/fotos-AAAAMMDD-HHMMSS.tar.gz
python scripts/backup_fotos.py restaurar --arquivo backups/fotos-20261019-220102.tar.gz   # restaura em um volume NOVO
```

Por trás, são estes comandos (use-os diretamente se preferir; no PowerShell troque `$(pwd)` por `$PWD`):

```bash
# BACKUP: volume (somente leitura) -> arquivo .tar.gz na pasta ./backups
docker run --rm \
  --mount type=volume,source=achados-perdidos_fotos,target=/origem,readonly \
  --mount type=bind,source="$(pwd)/backups",target=/backup \
  alpine:3.24 tar czf /backup/fotos-$(date +%Y%m%d-%H%M%S).tar.gz -C /origem .

# RESTAURAÇÃO: cria um volume novo e extrai o arquivo nele
docker volume create achados-perdidos_fotos_restaurado
docker run --rm \
  --mount type=volume,source=achados-perdidos_fotos_restaurado,target=/destino \
  --mount type=bind,source="$(pwd)/backups",target=/backup,readonly \
  alpine:3.24 tar xzf /backup/fotos-AAAAMMDD-HHMMSS.tar.gz -C /destino
```

| Parte do comando | Para que serve |
|---|---|
| `docker run --rm` | Roda um contêiner descartável: ele é **removido** ao terminar, não deixa lixo. |
| `--mount type=volume,source=…,target=/origem,readonly` | Monta o volume de fotos **somente leitura** em `/origem`: o backup não consegue alterá-lo. |
| `--mount type=bind,source=./backups,target=/backup` | Monta a pasta `backups/` do computador em `/backup`: é por onde o arquivo sai do Docker. |
| `tar czf … -C /origem .` | Compacta (`c`), com gzip (`z`), em arquivo (`f`), o **conteúdo** do volume (`-C /origem .`). |
| `alpine:3.24` | Imagem mínima (cerca de 4 MB) que já traz o `tar`. |
| `docker volume create … ` + `tar xzf` | A restauração usa um volume **novo**, para nunca misturar com dados existentes. Roda como root, então preserva o dono dos arquivos. |

**Demonstração real** ([`bonus/05`](evidencias/bonus/05-backup-e-restauracao-fotos.txt)): o arquivo foi criado com as 3 fotos do volume, restaurado em `…_fotos_restaurado` com o dono `10001` preservado e a lista de
`sha256sum` dos dois volumes saiu **idêntica**. Para usar o volume restaurado no Compose, declare-o como `external` (`volumes: fotos: {external: true, name: achados-perdidos_fotos_restaurado}`) — esse último passo não é exercitado pelos testes.

> WARNING: **Backups contêm fotos de pessoas.** Os backups contêm as fotos dos usuários, que podem mostrar documentos pessoais. A pasta `backups/` e os arquivos `*.tar.gz` estão no `.gitignore` e **nunca devem ser versionados**; guarde-os criptografados.
> O backup **não** inclui o banco (`dados_banco`); para ele, use `pg_dump`.

## C — Adminer no profile `debug`

O `adminer` está no `docker-compose.yml` com `profiles: ["debug"]`, então **não sobe** com `docker compose up -d`:

```bash
docker compose --profile debug up -d       # sobe o Adminer junto com o resto
# abra http://127.0.0.1:8081  -> Sistema: PostgreSQL | Servidor: db | Usuário, Senha e Banco: os do .env
docker compose rm -sf adminer              # encerra e remove SÓ o Adminer (db, web e nginx continuam)
docker compose --profile debug down        # alternativa: derruba tudo, inclusive o Adminer (volumes mantidos)
```

- O Adminer só escuta em **`127.0.0.1:8081`** (*loopback*): outras máquinas da rede não o enxergam. A senha não está pré-preenchida.
- Ele alcança o banco **pela rede interna** (`ADMINER_DEFAULT_SERVER: db`); o **PostgreSQL continua sem porta publicada**, como exige o bônus.
- **Medido** ([`bonus/04`](evidencias/bonus/04-adminer-profile-debug.txt)): sem o profile o Adminer não existe entre os serviços; com o profile responde `200` em `127.0.0.1`; um `fsockopen('db', 5432)` de dentro dele conecta;
  o `docker inspect` do `db` segue com `{"5432/tcp":null}`; e `docker compose rm -sf adminer` deixa só `db`, `web` e `nginx`.
