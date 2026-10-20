# Reflexão e equivalência em nuvem

Respostas às questões da seção 5 do enunciado (3 a 8 linhas cada) e a tabela de equivalência da seção 5.1. Cada resposta cita os arquivos do próprio repositório e as
[evidências](evidencias/README.md) geradas pelos scripts; onde um fato foi **medido**, o experimento está em `docs/evidencias/reflexao/`.

## Q1. Por que o nome `db` funciona no lugar de um IP?

O `app.py` usa `DB_HOST` (padrão `db`) e o Compose define `DB_HOST: db`. Quem resolve o nome é o **DNS embutido do Docker** (`127.0.0.11`),
presente em todo contêiner de uma rede definida pelo usuário, como a `rede_interna`: ele devolve o IP atual do serviço, que muda a cada
recriação (aqui `172.21.0.2`), enquanto o nome é estável ([`complementares/03`](evidencias/complementares/03-dns-interno.txt)).
Com `docker run` na rede *bridge* **padrão** não há esse DNS por nome: o contêiner só alcançaria o outro por IP ou pelo `--link` obsoleto.
Medido: o `nslookup` na bridge padrão deu `NXDOMAIN`; em uma rede criada com `docker network create`, resolveu
([`reflexao/q1`](evidencias/reflexao/q1-dns-bridge-padrao-x-rede-definida.txt)).

## Q2. Qual a diferença entre volume nomeado e bind mount?

**Volume nomeado:** o Docker cria e administra o armazenamento, que independe de caminhos do host, é portátil e só some com `down -v`.
**Bind mount:** mapeia um caminho **do host** (arquivo ou pasta), então depende da máquina e das permissões (e é lento no Windows/OneDrive).
O `init.sql` é bind mount `:ro` por ser um arquivo **versionado**, editado pela equipe e apenas lido pelo banco
([`complementares/04`](evidencias/complementares/04-sistema-de-arquivos-somente-leitura.txt): `Read-only file system`).
Os dados do banco são volume nomeado: são estado de execução, não vão para o Git, exigem permissões corretas e têm de sobreviver ao `down`
([`tarefa5/02`](evidencias/tarefa5/02-inspecao-volumes.txt) lista os dois tipos de montagem).

## Q3. Alterar o `init.sql` depois da primeira subida

**Não é aplicada.** A imagem só executa `/docker-entrypoint-initdb.d/` quando o diretório de dados está **vazio**; com o volume `dados_banco`
populado, o log diz `Skipping initialization` e a coluna nova não aparece em `\d itens` ([`reflexao/q3`](evidencias/reflexao/q3-init-sql-alterado.txt)).
Para aplicar **sem perder dados**, faz-se uma migração no banco em execução:
`docker compose exec db psql … -c "ALTER TABLE itens ADD COLUMN IF NOT EXISTS contato VARCHAR(100)"` — no experimento, as 4 linhas continuaram lá.
O `down -v` também aplicaria o novo `init.sql`, mas **apaga os dados** ([`tarefa5/03`](evidencias/tarefa5/03-remocao-volumes.txt));
em produção usam-se migrações versionadas (Flyway, Alembic).

## Q4. Por que `depends_on` sozinho não basta?

O `depends_on` simples só ordena o **início**: o `web` sobe quando o contêiner `db` **começou**, não quando o PostgreSQL aceita conexões.
Na primeira subida o banco ainda cria o cluster e roda o `init.sql`, recusando conexões; o `app.py` não tem *retry*, então `/health` cairia no `except` e
responderia `503`. Com `condition: service_healthy` e `pg_isready -h 127.0.0.1` (TCP, pois o servidor temporário do *initdb* só escuta no socket Unix),
o Compose espera o banco ficar pronto: na saída real `db-1 Healthy` vem **antes** de `web-1 Starting`
([`tarefa4/01`](evidencias/tarefa4/01-docker-compose-up.txt)) — é o RNF05.

## Q5. Cache de camadas do Dockerfile

Cada instrução vira uma **camada** reaproveitada (`CACHED`) se ela e os arquivos que usa não mudaram; mudando uma camada, ela e **todas as seguintes** são refeitas.
O `requirements.txt` muda pouco e o `app.py` sempre, então copiar e instalar as dependências **antes** do código mantém o `pip install` em cache.
Medido ([`reflexao/q5`](evidencias/reflexao/q5-cache-de-camadas.txt)): só o `app.py` alterado → `pip install` **`CACHED`** e só o `COPY app.py` refeito (2,5 s);
`requirements.txt` alterado → `pip install` refeito (11,8 s). Com o `COPY app.py` antes, cada edição de código reinstalaria tudo.

## Q6. Por que não publicar a porta 5432? LGPD e medidas adicionais

Publicar a `5432` abriria o banco à rede do computador, expondo-o a força bruta e a falhas do PostgreSQL, sem necessidade: só o `web` o acessa.
Aqui o `db` não tem `ports` (`db: {"5432/tcp":null}`, [`complementares/02`](evidencias/complementares/02-portas-publicadas.txt)) e só o `nginx` publica a 8080.
As fotos podem mostrar RG ou carteira de estudante (dados pessoais): a LGPD pede necessidade, segurança e prevenção (art. 6º) e medidas técnicas de proteção (art. 46).
Duas medidas a mais: **(1) HTTPS e autenticação** para listar e ver as fotos (hoje públicas); **(2) retenção e minimização** — apagar fotos após um prazo
(ex.: 90 dias), restringir o acesso à equipe e criptografar disco e backups.

## Q7. `docker compose up -d --scale web=3`

**Funciona** com o `nginx` à frente e sem porta fixa no `web`: 3 réplicas saudáveis e 3 `container` diferentes em `/health`
([`reflexao/q7`](evidencias/reflexao/q7-scale-com-nginx.txt)). **Com porta fixa** (`8080:5000`, como no enunciado básico) **falha**:
`Bind for 0.0.0.0:18090 failed: port is already allocated` (18090 foi a porta de teste; [`conflito`](evidencias/reflexao/q7-scale-conflito-de-porta.txt)).
São necessários: nenhuma porta fixa no `web`, um balanceador (o `nginx` resolve `web` pelo DNS a cada 10 s) e nada de `container_name`.
O volume `fotos` foi compartilhado sem conflito **na mesma máquina** (3 réplicas, mesmos arquivos), mas **não é seguro nem escalável**: outro servidor
não o enxerga e o banco segue único — na nuvem, usa-se armazenamento de objetos.

## 5.1 Do ambiente local para a nuvem

| Peça do ambiente local | Microsoft Azure | AWS | Google Cloud |
|---|---|---|---|
| Contêiner `web` | Azure Container Apps (ou App Service para contêineres) | Amazon ECS com Fargate (ou App Runner) | Cloud Run |
| Contêiner `db` + volume `dados_banco` | Azure Database for PostgreSQL – Flexible Server | Amazon RDS for PostgreSQL (ou Aurora PostgreSQL) | Cloud SQL for PostgreSQL |
| Volume `fotos` | Azure Blob Storage (ou Azure Files, para montar como disco) | Amazon S3 (ou Amazon EFS, para montar como disco) | Cloud Storage (ou Filestore) |
| `rede_interna` | Azure Virtual Network (sub-redes privadas, NSG e Private Endpoint) | Amazon VPC (sub-redes privadas e *security groups*) | Rede VPC (regras de firewall e acesso privado à Cloud SQL) |
| Arquivo `.env` (segredos) | Azure Key Vault (com *managed identity*) | AWS Secrets Manager (ou SSM Parameter Store) | Secret Manager |
| Imagem construída localmente | Azure Container Registry (ACR) | Amazon ECR | Artifact Registry |
| *Extra:* `nginx` (proxy reverso) | Application Gateway ou Front Door | Application Load Balancer (ALB) | Cloud Load Balancing (HTTPS) |

- **Contêiner `web`:** serviços de contêineres *serverless* executam a **mesma imagem** e escalam sozinhos; o `restart: unless-stopped` e o `healthcheck` viram reinício automático e sondas de saúde da plataforma.
- **`db` + volume:** em vez de um PostgreSQL em contêiner com volume, usa-se o PostgreSQL **gerenciado** (backup, alta disponibilidade, atualizações e criptografia em repouso incluídos).
- **Volume `fotos`:** o armazenamento de **objetos** (Blob, S3, Cloud Storage) substitui o disco local; é compartilhado, durável e barato.
- **`rede_interna`:** a rede privada (VNet/VPC) e suas regras de firewall fazem o isolamento; o banco recebe só endereço privado, como o `db` sem porta publicada.
- **`.env`:** dá lugar a um **cofre de segredos** com controle de acesso e auditoria; a aplicação recebe os valores por identidade gerenciada ou por variáveis injetadas pela plataforma.
- **Imagem:** o *registry* da nuvem guarda a imagem que hoje é construída localmente; a CI a constrói e publica a cada alteração.
- **`nginx`:** o balanceador gerenciado assume o papel do proxy (TLS, balanceamento e limites); o `nginx` deixa de ser necessário.

**Qual peça muda mais na migração?** O **volume `fotos`**. O `app.py` usa o **disco local**: grava com `foto.save(...)` em `/app/uploads` e lê com `send_from_directory`. Contêineres na nuvem têm disco **efêmero** e podem ter várias réplicas
em máquinas diferentes (o que, como mostra a [Q7](#q7-docker-compose-up-d-scale-web3), um volume local não suporta com segurança), então os arquivos precisam ir para armazenamento de objetos. Isso exige **mudar o código** (usar o SDK do
S3/Blob/Cloud Storage ou URLs assinadas) — justamente o único componente que esta etapa não alterou. Montar um compartilhamento de arquivos (Azure Files, EFS, Filestore) seria um paliativo que dispensa a mudança de código, mas é mais caro e mais lento.
As outras peças são trocas de configuração: o banco vira um serviço gerenciado (muda a *string* de conexão e entram SSL e cofre de segredos) e o proxy vira um balanceador.
