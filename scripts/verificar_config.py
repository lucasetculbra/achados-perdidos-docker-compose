#!/usr/bin/env python3
"""Verificações estáticas do repositório (não sobe contêineres de teste).

Confere, contra o enunciado, o que dá para provar só lendo os arquivos: código fornecido intacto,
segredos fora do Git, Dockerfile, estrutura do docker-compose.yml, e (com --final) se as
evidências e a documentação entregues correspondem ao código atual.

    python scripts/verificar_config.py            # antes de commitar
    python scripts/verificar_config.py --final    # CI / entrega: exige evidências e documentação
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from comum import (
    ARQUIVOS_INFRA,
    EM_CI,
    RAIZ,
    Checagem,
    configurar_saida,
    ler_env,
    resumo_ci,
    sha256_arquivo,
)

# SHA-256 (fim de linha normalizado para LF) do código fornecido no enunciado: não pode ser alterado.
HASH_CODIGO_FORNECIDO = {
    "app/app.py": "36532ce006c30e044a268ecc01094b3a4be80df06f1685a74cc7408cf3a6bca4",
    "app/requirements.txt": "b77dbdd309050c6a32108b5922a01efbbbe03177b33781178e4f539fe8bc2184",
    "db/init.sql": "d9e8ba872f684483bd8347fd9686a45eeaca2635ccaf7ba51ead8e381a0f4639",
}
DOCS_OBRIGATORIOS = [
    "README.md",
    "docs/index.md",
    "docs/arquitetura.md",
    "docs/RELATORIO.md",
    "docs/REFLEXAO.md",
    "mkdocs.yml",
    "requirements-docs.txt",
]

checagens: list[Checagem] = []


def checar(req: str, descricao: str, ok: bool, detalhe: str = "") -> None:
    checagens.append(Checagem(req, descricao, bool(ok), detalhe))
    print(f"  [{'OK' if ok else 'FALHOU'}] {req}: {descricao}" + (f" -> {detalhe}" if detalhe and not ok else ""))
    if EM_CI and not ok:
        print(f"::error title={req}::{descricao} {detalhe}".replace("\n", " "))


def ler(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- blocos de verificação
def codigo_fornecido() -> None:
    for rel, esperado in HASH_CODIGO_FORNECIDO.items():
        atual = sha256_arquivo(RAIZ / rel, normalizar_eol=True) if (RAIZ / rel).exists() else "(ausente)"
        checar("T1", f"{rel} é o código fornecido, sem alterações", atual == esperado, atual[:16])


def segredos() -> None:
    env = ler_env()
    if git("rev-parse", "--is-inside-work-tree").returncode == 0:
        checar("RNF03", ".env não está versionado (git ls-files)", git("ls-files", "--error-unmatch", ".env").returncode != 0)
        checar("RNF03", ".env é ignorado pelo Git (git check-ignore)", git("check-ignore", "-q", ".env").returncode == 0)
        arquivos = [a for a in git("ls-files", "--cached", "--others", "--exclude-standard").stdout.splitlines() if a]
    else:
        checar("RNF03", "pasta é um repositório Git", False, "sem .git: não foi possível verificar o versionamento")
        arquivos = [str(p.relative_to(RAIZ)) for p in RAIZ.rglob("*") if p.is_file() and ".git" not in p.parts and p.name != ".env"]

    exemplo = {}
    for linha in ler(".env.example").splitlines():
        if linha.strip() and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            exemplo[k.strip()] = v.strip()
    checar("T3", ".env.example define POSTGRES_DB, POSTGRES_USER e POSTGRES_PASSWORD", {"POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"} <= set(exemplo))
    if env:
        checar("T3", ".env.example tem as mesmas chaves do .env", set(exemplo) == set(env), f"exemplo={sorted(exemplo)} env={sorted(env)}")
        senha = env.get("POSTGRES_PASSWORD", "")
        if senha == exemplo.get("POSTGRES_PASSWORD"):
            print("  (o .env é uma cópia do .env.example, como logo depois de clonar: não há senha real para procurar nos arquivos)")
        else:
            checar("RNF03", ".env.example não repete a senha real do .env", True)
            vazou = []
            if len(senha) >= 8:
                for rel in arquivos:
                    caminho = RAIZ / rel
                    if caminho.is_file() and caminho.stat().st_size < 5_000_000:
                        try:
                            if senha in caminho.read_text(encoding="utf-8", errors="ignore"):
                                vazou.append(rel)
                        except OSError:
                            pass
            checar("RNF03", "a senha real do .env não aparece em nenhum arquivo do projeto (fora o .env)", not vazou, ", ".join(vazou))
    else:
        print("  (sem .env local: comparações com a senha real foram puladas)")

    # senhas literais nos arquivos de infraestrutura: o valor precisa vir de variável (${VAR}, $VAR) ou de código ({...})
    padrao = re.compile(r"""(?i)\b\w*(password|passwd|secret|token)\w*\s*[:=]\s*(?!['"]?\{)['"]?([^\s'",#]{3,})""")
    niveis_de_permissao = {"read", "write", "none"}  # "id-token: write" é permissão do GitHub Actions, não um segredo
    suspeitos = []
    for rel in ["app/Dockerfile", "docker-compose.yml", "app/app.py", "nginx/default.conf", *sorted(p.relative_to(RAIZ).as_posix() for p in (RAIZ / ".github/workflows").glob("*.yml"))]:
        if (RAIZ / rel).exists():
            for n, linha in enumerate(ler(rel).splitlines(), 1):
                sem_variaveis = re.sub(r"\$\{[^}]*\}|\$\w+", "", linha)  # ${POSTGRES_PASSWORD:?msg}, $PW...
                achou = padrao.search(sem_variaveis)
                if achou and achou.group(2).lower() not in niveis_de_permissao and not linha.strip().startswith("#"):
                    suspeitos.append(f"{rel}:{n}")
    checar("RNF03", "nenhuma senha escrita no Dockerfile, no docker-compose.yml, no código ou nos workflows", not suspeitos, ", ".join(suspeitos))


def dockerfile() -> None:
    d = ler("app/Dockerfile")
    linhas = [l.strip() for l in d.splitlines() if l.strip() and not l.strip().startswith("#")]
    texto = "\n".join(linhas)
    checar("T2", "partiu de python:3.12-slim (imagem oficial enxuta)", re.search(r"(?m)^FROM python:3\.12-slim\s*$", texto) is not None)
    i_req = next((i for i, l in enumerate(linhas) if l.startswith("COPY requirements.txt")), -1)
    i_pip = next((i for i, l in enumerate(linhas) if l.startswith("RUN pip install")), -1)
    i_app = next((i for i, l in enumerate(linhas) if re.match(r"COPY (app\.py|\. )", l)), -1)
    checar("T2", "COPY requirements.txt -> RUN pip install -> COPY do código (cache de camadas)", 0 <= i_req < i_pip < i_app, f"{i_req},{i_pip},{i_app}")
    checar("T2", "pip instala com --no-cache-dir", "pip install --no-cache-dir -r requirements.txt" in texto)
    usuarios = re.findall(r"(?m)^USER\s+(\S+)", texto)
    checar("RNF04", "o Dockerfile executa a aplicação com USER não-root", bool(usuarios) and usuarios[-1].split(":")[0] not in ("root", "0"), str(usuarios))
    checar("T2", "cria /app/uploads e dá a posse ao usuário sem privilégios", "mkdir -p /app/uploads" in texto and re.search(r"chown \S+ /app/uploads", texto) is not None)
    checar("T2", "EXPOSE 5000", re.search(r"(?m)^EXPOSE 5000\s*$", texto) is not None)
    cmd = re.search(r"(?m)^CMD\s+(\[.*\])\s*$", texto)
    try:
        partes = json.loads(cmd.group(1)) if cmd else []
    except ValueError:
        partes = []
    checar("T2", "CMD em forma exec: gunicorn escutando em 0.0.0.0:5000", bool(partes) and partes[0] == "gunicorn" and "0.0.0.0:5000" in partes, str(partes))
    ig = [l.strip() for l in ler("app/.dockerignore").splitlines()]
    checar("T2", ".dockerignore exclui .env, __pycache__/ e *.pyc", {".env", "__pycache__/", "*.pyc"} <= set(ig))


def porta_publicada(svc: dict) -> list[tuple[str, int]]:
    return [(p.get("host_ip", ""), int(p["published"])) for p in svc.get("ports", []) if p.get("published")]


def compose() -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES")}
    env.update({"POSTGRES_DB": "x", "POSTGRES_USER": "x", "POSTGRES_PASSWORD": "x"})  # valores fictícios: não depende do .env
    try:
        r = subprocess.run(["docker", "compose", "--profile", "*", "config", "--format", "json"], cwd=RAIZ, env=env, capture_output=True, text=True, encoding="utf-8")
        cfg = json.loads(r.stdout)
    except (OSError, ValueError):
        checar("T3", "docker compose config foi interpretado", False, "docker indisponível ou configuração inválida")
        return
    s = cfg["services"]
    checar("T3", "serviços: db, web, nginx (bônus A) e adminer (bônus C)", set(s) == {"db", "web", "nginx", "adminer"}, str(sorted(s)))
    checar("T3", "rede rede_interna do tipo bridge, compartilhada por todos os serviços", cfg["networks"]["rede_interna"].get("driver") == "bridge" and all("rede_interna" in v.get("networks", {}) for v in s.values()))
    checar("T3", "volumes nomeados dados_banco e fotos declarados", {"dados_banco", "fotos"} <= set(cfg.get("volumes", {})))

    db, web, nginx, adm = s["db"], s["web"], s["nginx"], s["adminer"]
    checar("T3", "db usa postgres:16-alpine", db["image"] == "postgres:16-alpine")
    checar("T3", "db recebe POSTGRES_DB, POSTGRES_USER e POSTGRES_PASSWORD", {"POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"} <= set(db.get("environment", {})))
    mont = {v["target"]: v for v in db.get("volumes", [])}
    checar("T3", "db: volume nomeado dados_banco em /var/lib/postgresql/data", mont.get("/var/lib/postgresql/data", {}).get("source") == "dados_banco" and mont["/var/lib/postgresql/data"]["type"] == "volume")
    init = mont.get("/docker-entrypoint-initdb.d/init.sql", {})
    checar("T3", "db: init.sql montado em /docker-entrypoint-initdb.d/ como bind mount somente leitura", init.get("type") == "bind" and init.get("read_only") is True and init.get("source", "").replace("\\", "/").endswith("/db/init.sql"))
    checar("T3", "db: healthcheck com pg_isready", "pg_isready" in " ".join(db.get("healthcheck", {}).get("test", [])))
    checar("RNF/ARQ", "db: nenhuma porta publicada no host", not db.get("ports"))
    checar("T3", "web: construído de ./app com as variáveis DB_* e UPLOAD_DIR", Path(web["build"]["context"]).name == "app" and {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "UPLOAD_DIR"} <= set(web["environment"]), str(sorted(web["environment"])))
    checar("T3", "web: DB_HOST=db, DB_PORT=5432, UPLOAD_DIR=/app/uploads", web["environment"].get("DB_HOST") == "db" and web["environment"].get("DB_PORT") == "5432" and web["environment"].get("UPLOAD_DIR") == "/app/uploads")
    wm = {v["target"]: v for v in web.get("volumes", [])}
    checar("T3", "web: volume nomeado fotos montado em /app/uploads", wm.get("/app/uploads", {}).get("source") == "fotos" and wm["/app/uploads"]["type"] == "volume")
    checar("RNF05", "web: depends_on db com condition: service_healthy", web.get("depends_on", {}).get("db", {}).get("condition") == "service_healthy")
    checar("T3", "restart: unless-stopped em db, web e nginx", all(s[n].get("restart") == "unless-stopped" for n in ("db", "web", "nginx")))
    checar("BONUS-A", "nginx publica 8080 (-> 80) e o web não publica porta", porta_publicada(nginx) == [("", 8080)] and not web.get("ports"), f"nginx={porta_publicada(nginx)} web={web.get('ports')}")
    checar("BONUS-A", "nginx: configuração montada somente leitura e depende do web saudável", any(v["target"].endswith("default.conf") and v.get("read_only") for v in nginx.get("volumes", [])) and nginx.get("depends_on", {}).get("web", {}).get("condition") == "service_healthy")
    checar("BONUS-C", "adminer: apenas no profile debug, publicado só em 127.0.0.1", adm.get("profiles") == ["debug"] and all(h == "127.0.0.1" for h, _ in porta_publicada(adm)) and bool(porta_publicada(adm)))
    todas = [pt for n in s for _, pt in porta_publicada(s[n])]
    checar("RNF/ARQ", "nenhum serviço publica a porta 5432 (PostgreSQL) no host", 5432 not in todas, str(todas))
    checar("RNF04", "web endurecido: sistema de arquivos somente leitura, sem capabilities, sem novos privilégios", web.get("read_only") is True and web.get("cap_drop") == ["ALL"] and "no-new-privileges:true" in web.get("security_opt", []))


def evidencias_e_docs(final: bool) -> None:
    pasta = RAIZ / "docs/evidencias"
    amb = pasta / "00-ambiente.txt"
    if not amb.exists():
        checar("A4", "evidências geradas (docs/evidencias/00-ambiente.txt)", not final, "execute scripts/testar_ambiente.py --evidencias docs/evidencias" if final else "")
    else:
        registrados = dict((m.group(2), m.group(1)) for m in re.finditer(r"(?m)^\s*([0-9a-f]{64})\s+(\S+)\s*$", amb.read_text(encoding="utf-8")))
        divergentes = [rel for rel in ARQUIVOS_INFRA if registrados.get(rel) != sha256_arquivo(RAIZ / rel, normalizar_eol=True)]
        checar("A4", "as evidências correspondem ao código atual (SHA-256 dos arquivos de infraestrutura)", not divergentes, "alterados depois das evidências: " + ", ".join(divergentes) + " -> regenere as evidências")
        txts = [t for t in pasta.rglob("*.txt")]
        sem_legenda = [t.relative_to(pasta).as_posix() for t in txts if not t.read_text(encoding="utf-8").startswith("# Legenda:")]
        checar("A4", "todo arquivo de evidência começa com uma legenda de uma linha", not sem_legenda, ", ".join(sem_legenda))
        indice = (pasta / "README.md").read_text(encoding="utf-8") if (pasta / "README.md").exists() else ""
        fora = [t.relative_to(pasta).as_posix() for t in txts if t.relative_to(pasta).as_posix() not in indice]
        checar("A4", "o índice docs/evidencias/README.md lista todas as evidências", not fora, ", ".join(fora))
        resumo = (pasta / "resumo-testes.md").read_text(encoding="utf-8") if (pasta / "resumo-testes.md").exists() else ""
        checar("A4", "resumo-testes.md sem nenhuma verificação reprovada", bool(resumo) and "FALHOU" not in resumo)
        senha = ler_env().get("POSTGRES_PASSWORD", "")
        if senha and senha != next((l.split("=", 1)[1].strip() for l in ler(".env.example").splitlines() if l.startswith("POSTGRES_PASSWORD=")), None) and len(senha) >= 8:
            checar("RNF03", "evidências não contêm a senha do .env", not any(senha in t.read_text(encoding="utf-8", errors="ignore") for t in pasta.rglob("*") if t.is_file() and t.suffix in {".txt", ".md"}))

    if final:
        faltam = [rel for rel in DOCS_OBRIGATORIOS if not (RAIZ / rel).exists()]
        checar("A1-A5", "README, docs/ (index, arquitetura, RELATORIO, REFLEXAO), mkdocs.yml e requirements-docs.txt existem", not faltam, ", ".join(faltam))
        if (RAIZ / "docs/RELATORIO.md").exists():
            relatorio = ler("docs/RELATORIO.md").replace("\r\n", "\n")
            checar("A3", "o Dockerfile transcrito em docs/RELATORIO.md é idêntico a app/Dockerfile", ler("app/Dockerfile").replace("\r\n", "\n").rstrip() in relatorio)
            partes = ["## A. Dockerfile", "## B. `docker-compose.yml`", "## C. O caminho de um `POST /itens` com foto", "## D. Ciclo de vida dos volumes"]
            checar("A3", "o relatório tem as quatro partes (A) a (D)", all(p in relatorio for p in partes), str([p for p in partes if p not in relatorio]))
        if (RAIZ / "docs/REFLEXAO.md").exists():
            reflexao = ler("docs/REFLEXAO.md")
            blocos = re.split(r"(?m)^##\s+(Q[1-7])\b.*$", reflexao)
            respostas = {blocos[i]: blocos[i + 1] for i in range(1, len(blocos) - 1, 2)}
            checar("A5", "as sete questões (Q1 a Q7) estão respondidas", set(respostas) == {f"Q{n}" for n in range(1, 8)}, str(sorted(respostas)))
            for q, texto in sorted(respostas.items()):
                corpo = re.split(r"(?m)^#{1,2}\s", texto)[0]  # até o próximo título de nível 1-2
                n = sum(1 for l in corpo.splitlines() if l.strip() and not l.lstrip().startswith(("#", "<!--", ">")))
                checar("A5", f"{q} tem entre 3 e 8 linhas de resposta", 3 <= n <= 8, f"{n} linhas")


def main() -> int:
    configurar_saida()
    ap = argparse.ArgumentParser(description="Verificações estáticas do repositório Achados & Perdidos.")
    ap.add_argument("--final", action="store_true", help="exige evidências e documentação completas (CI / entrega)")
    args = ap.parse_args()
    print("== código fornecido"); codigo_fornecido()
    print("== segredos e .env"); segredos()
    print("== Dockerfile"); dockerfile()
    print("== docker-compose.yml"); compose()
    print("== evidências e documentação"); evidencias_e_docs(args.final)
    resumo_ci("Verificações estáticas", checagens)
    falhas = [c for c in checagens if not c.ok]
    print(f"\n{len(checagens) - len(falhas)}/{len(checagens)} verificações aprovadas.")
    for c in falhas:
        print(f"  FALHOU [{c.req}] {c.descricao} {c.detalhe}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
