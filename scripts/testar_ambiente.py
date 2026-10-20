#!/usr/bin/env python3
"""Testes funcionais (Tarefa 4), de persistência (Tarefa 5) e dos bônus, em projeto Compose ISOLADO.

Usado no computador do autor e no GitHub Actions. Sobe o ambiente de verdade, executa os
comandos do roteiro do PDF (com curl), confere cada resultado e grava a saída real de cada
comando em docs/evidencias/. Termina com código 1 se qualquer verificação falhar.

Exemplos:
    python scripts/testar_ambiente.py                                   # só testa
    python scripts/testar_ambiente.py --evidencias docs/evidencias      # testa e grava evidências
    python scripts/testar_ambiente.py --porta 18080 --capturas ...      # 8080 ocupada; prints da foto

Segurança: usa um projeto Compose próprio (padrão: achados-perdidos-evidencias), com volumes e rede
próprios. O projeto real do usuário ("achados-perdidos") nunca é tocado: o `down -v` só atinge o projeto de teste.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from comum import (
    EM_CI,
    RAIZ,
    Ambiente,
    Falha,
    Resposta,
    configurar_saida,
    escrever_resumo,
    etapa,
    gerar_indice,
    info_ambiente,
    png_ruidoso,
    png_sintetico,
    porta_em_uso,
    resumo_ci,
    sha256_bytes,
    varrer_vazamentos,
)

ITENS_DE_EXEMPLO = {"Garrafa termica azul", "Carregador de notebook USB-C", "Casaco preto com capuz"}
SUBPASTAS_GERADAS = ("tarefa4", "tarefa5", "complementares", "bonus")
TAMANHO_MAXIMO_IMAGEM_MB = 300


class Contagem:
    """Quantidade de itens/fotos que o ambiente DEVE ter (confrontada com GET /estatisticas)."""

    def __init__(self) -> None:
        self.itens = 3  # os três itens de exemplo do init.sql
        self.fotos = 0


# ---------------------------------------------------------------- utilitários
def json_ou_vazio(r: Resposta):
    try:
        return r.json
    except ValueError:
        return {}


def estatisticas(amb: Ambiente, ev) -> dict:
    r = amb.http(ev, "/estatisticas")
    return json_ou_vazio(r) if r.status == 200 else {}


def conferir(amb: Ambiente, ev, req: str, rotulo: str, c: Contagem) -> dict:
    s = estatisticas(amb, ev)
    amb.checar(
        req,
        f"GET /estatisticas {rotulo}: {c.itens} itens no banco e {c.fotos} fotos no volume",
        s == {"fotos_no_volume": c.fotos, "itens_no_banco": c.itens},
        f"obtido {s}",
    )
    return s


def cadastrar(amb: Ambiente, ev, c: Contagem, descricao: str, local: str, arquivo: str | None = None) -> Resposta:
    r = amb.http(ev, "/itens", campos={"descricao": descricao, "local": local}, arquivo=arquivo)
    if r.status == 201:
        c.itens += 1
        c.fotos += 1 if arquivo else 0
    return r


def preparar_arquivos(amb: Ambiente) -> None:
    """Imagens sintéticas (degradês e ruído): nenhuma foto de pessoa ou documento."""
    (amb.tmp / "oculos.png").write_bytes(png_sintetico((220, 70, 70)))
    (amb.tmp / "carregador.png").write_bytes(png_sintetico((60, 140, 220)))
    (amb.tmp / "mochila.png").write_bytes(png_sintetico((70, 190, 110)))
    (amb.tmp / "pequena.png").write_bytes(png_sintetico((200, 200, 60), 64, 64))
    (amb.tmp / "foto-2mb.png").write_bytes(png_ruidoso(2 * 1024 * 1024))
    (amb.tmp / "foto-11mb.png").write_bytes(png_ruidoso(11 * 1024 * 1024))
    (amb.tmp / "nao-e-foto.html").write_text("<script>alert('xss')</script>", encoding="utf-8")


def localizar_navegador() -> str | None:
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
                if (Path(base) / rel).exists():
                    return str(Path(base) / rel)
    for nome in ("google-chrome", "chromium", "chromium-browser", "msedge"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


def capturar(amb: Ambiente, args, caminho_txt: str, legenda: str, url_path: str) -> None:
    """Print da URL em navegador headless (o roteiro do PDF pede para abrir a foto no navegador)."""
    if not args.capturas or amb.pasta_evid is None:
        return
    exe = localizar_navegador()
    if not exe:
        print("  (nenhum navegador encontrado: captura ignorada)")
        return
    destino = amb.pasta_evid / Path(caminho_txt).with_suffix(".png")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.unlink(missing_ok=True)
    perfil = amb.tmp / f"perfil-navegador-{len(list(amb.tmp.glob('perfil-navegador-*')))}"  # um perfil por captura
    try:
        with amb.evidencia(caminho_txt, legenda) as ev:
            ev.cmd(
                [
                    exe, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                    f"--user-data-dir={perfil}", "--window-size=640,480",
                    f"--screenshot={destino}", amb.url(url_path),
                ],
                check=False,
                timeout=60,
            )
            ok = destino.exists() and destino.stat().st_size > 1000
            ev.nota(f"Captura salva em {destino.name} ({destino.stat().st_size if destino.exists() else 0} bytes).")
        amb.checar("T4", f"captura do navegador gerada para {url_path[:40]}...", ok)
    except Falha as e:  # a captura é opcional: não derruba os testes
        print(f"  (captura ignorada: {str(e)[:100]})")
        (amb.pasta_evid / caminho_txt).unlink(missing_ok=True)


def publicadores(amb: Ambiente) -> dict[str, list[int]]:
    """Portas publicadas no host por serviço, segundo `docker compose ps`."""
    return {
        svc: [p["PublishedPort"] for p in (o.get("Publishers") or []) if p.get("PublishedPort")]
        for svc, o in amb.estado().items()
    }


# ---------------------------------------------------------------- pré-voo
def pre_voo(amb: Ambiente, args) -> None:
    r = amb.rodar(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, quieto=True)
    if not r.ok:
        raise Falha("o daemon do Docker não está respondendo (abra o Docker Desktop / inicie o serviço docker).")
    if not (RAIZ / ".env").exists():
        raise Falha("arquivo .env ausente: copie .env.example para .env (veja o README).")
    amb.limpar_anterior()
    for porta, quem in ((args.porta, "do site (nginx)"), (args.porta_adminer, "do Adminer")):
        if porta_em_uso(porta):
            raise Falha(
                f"a porta {porta} {quem} já está em uso por outro programa. Escolha outra com "
                f"{'--porta' if porta == args.porta else '--porta-adminer'} (ex.: 1{porta})."
            )


def gravar_ambiente(amb: Ambiente) -> None:
    if amb.pasta_evid is None:
        return
    linhas = [
        "# Legenda: Contexto da execução dos testes: versões, projeto Compose isolado, portas e SHA-256 dos arquivos testados.",
        "",
        f"Projeto Compose isolado: {amb.projeto}",
        f"Porta do host (nginx): {amb.porta}   |   Porta do Adminer (127.0.0.1): {amb.porta_adminer}",
        f"Executado no GitHub Actions: {'sim' if EM_CI else 'não (computador do autor)'}",
        *[f"Nota: {n}" for n in amb.notas_cabecalho],
        "",
        *info_ambiente(),
    ]
    destino = amb.pasta_evid / "00-ambiente.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(amb.limpar("\n".join(linhas)) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- Tarefa 4
def tarefa4(amb: Ambiente, c: Contagem, args) -> None:
    p = amb.projeto
    with etapa("Tarefa 4 - subida do ambiente e testes funcionais"):
        with amb.evidencia(
            "tarefa4/01-docker-compose-up.txt",
            "docker compose up -d --build constrói a imagem do web e sobe db, web e nginx com um único comando (RNF01), na ordem db -> web -> nginx (RNF05).",
        ) as ev:
            ev.cmd(amb.dc("config", "--quiet"))
            r = ev.cmd(amb.dc("up", "-d", "--build"), timeout=1500)
            segundos = amb.aguardar_pronto()
            ev.nota(f"Serviços healthy e GET /health = 200 após {segundos:.0f}s.")
        amb.checar("RNF01", "docker compose up -d --build conclui com código 0 só com o Docker e o arquivo .env", r.ok)
        pos = lambda padrao: (m.start() if (m := re.search(padrao, r.saida)) else -1)  # noqa: E731
        db_ok, web_ini = pos(rf"Container {p}-db-1\s+Healthy"), pos(rf"Container {p}-web-1\s+Starting")
        amb.checar("RNF05", "o web só iniciou depois de o db ficar healthy (ordem na saída do compose)", 0 <= db_ok < web_ini, f"db healthy@{db_ok}, web starting@{web_ini}")
        web_ok, ng_ini = pos(rf"Container {p}-web-1\s+Healthy"), pos(rf"Container {p}-nginx-1\s+Starting")
        amb.checar("RNF05", "o nginx só iniciou depois de o web ficar healthy", 0 <= web_ok < ng_ini, f"web healthy@{web_ok}, nginx starting@{ng_ini}")

        with amb.evidencia("tarefa4/02-docker-compose-ps.txt", "docker compose ps: db healthy e web/nginx em execução; só o nginx tem porta publicada no host.") as ev:
            ev.cmd(amb.dc("ps"))
        est = amb.estado()
        for svc in ("db", "web", "nginx"):
            o = est.get(svc, {})
            amb.checar("T4", f"serviço {svc} em execução e healthy", o.get("State") == "running" and o.get("Health") == "healthy", f"{o.get('State')}/{o.get('Health')}")

        with amb.evidencia("tarefa4/03-health.txt", 'GET /health responde "status": "ok" e "banco": "conectado" (RF01).') as ev:
            r = amb.http(ev, "/health")
        j = json_ou_vazio(r)
        amb.checar("RF01", "GET /health -> 200, status=ok, banco=conectado", r.status == 200 and j.get("status") == "ok" and j.get("banco") == "conectado", r.corpo[:120])

        with amb.evidencia("tarefa4/04-itens.txt", "GET /itens lista os três objetos de exemplo criados pelo init.sql na primeira execução (RF02).") as ev:
            r = amb.http(ev, "/itens")
        itens = json_ou_vazio(r)
        amb.checar("RF02", "GET /itens devolve exatamente os 3 itens de exemplo do init.sql", r.status == 200 and {i["descricao"] for i in itens} == ITENS_DE_EXEMPLO, r.corpo[:120])

        with amb.evidencia("tarefa4/05-itens-filtro-local.txt", "GET /itens?local=biblio filtra por local sem diferenciar maiúsculas de minúsculas (RF02).") as ev:
            r1 = amb.http(ev, "/itens?local=biblio")
            r2 = amb.http(ev, "/itens?local=BIBLIO")
            r3 = amb.http(ev, "/itens?local=nao-existe")
        locais1 = [i["local"] for i in json_ou_vazio(r1)] if r1.status == 200 else None
        amb.checar("RF02", "filtro local=biblio devolve só 'Biblioteca'", locais1 == ["Biblioteca"], str(locais1))
        amb.checar("RF02", "filtro é insensível a maiúsculas (BIBLIO = biblio)", json_ou_vazio(r2) == json_ou_vazio(r1) and r2.status == 200)
        amb.checar("RF02", "filtro sem correspondência devolve lista vazia", r3.status == 200 and json_ou_vazio(r3) == [])

        with amb.evidencia(
            "tarefa4/06-cadastro-com-foto.txt",
            "POST /itens com foto (multipart) devolve 201 e o nome da foto; o item passa a aparecer em GET /itens com a URL /fotos/<nome> (RF03).",
        ) as ev:
            r = cadastrar(amb, ev, c, "Oculos de grau", "Bloco B", "oculos.png")
            lista = amb.http(ev, "/itens")
        j = json_ou_vazio(r)
        foto = j.get("foto", "")
        amb.checar("RF03", "POST /itens com foto -> 201 e nome <uuid>.png", r.status == 201 and bool(re.fullmatch(r"[0-9a-f]{32}\.png", foto or "")), r.corpo[:120])
        amb.checar("RF03", "o item cadastrado aparece em GET /itens com foto=/fotos/<nome>", any(i.get("foto") == f"/fotos/{foto}" for i in json_ou_vazio(lista)))

        with amb.evidencia(
            "tarefa4/07-cadastro-sem-foto-e-validacao.txt",
            "POST /itens sem foto devolve 201 com foto=null; sem o campo obrigatório 'local' devolve 400 (RF03).",
        ) as ev:
            r1 = cadastrar(amb, ev, c, "Chave de armario", "Cantina")
            r2 = amb.http(ev, "/itens", campos={"descricao": "so descricao"})
        amb.checar("RF03", "POST /itens sem foto -> 201 e foto=null", r1.status == 201 and json_ou_vazio(r1).get("foto") is None, r1.corpo[:100])
        amb.checar("RF03", "POST /itens sem 'local' -> 400", r2.status == 400, r2.corpo[:100])

        with amb.evidencia("tarefa4/08-estatisticas.txt", "GET /estatisticas informa o total de itens no banco e de fotos no volume (RF04).") as ev:
            conferir(amb, ev, "RF04", "após os cadastros da Tarefa 4", c)

        with amb.evidencia(
            "tarefa4/09-foto-download.txt",
            "GET /fotos/<nome> devolve exatamente o arquivo enviado (mesmo SHA-256) e o nginx acrescenta cabeçalhos de segurança (RF04).",
        ) as ev:
            r = amb.http(ev, f"/fotos/{foto}", salvar_em="oculos-baixada.png")
            h = amb.http(ev, f"/fotos/{foto}", so_cabecalhos=True)
            enviado = sha256_bytes((amb.tmp / "oculos.png").read_bytes())
            baixado = sha256_bytes((amb.tmp / "oculos-baixada.png").read_bytes()) if (amb.tmp / "oculos-baixada.png").exists() else "-"
            ev.nota(f"SHA-256 calculado pelo script de teste (hashlib):\nenviado : {enviado}\nbaixado : {baixado}\niguais  : {enviado == baixado}")
        amb.checar("RF04", "GET /fotos/<nome> -> 200 com o mesmo SHA-256 do arquivo enviado", r.status == 200 and enviado == baixado)
        amb.checar("RF04", "Content-Type da foto é image/png", "content-type: image/png" in h.saida.lower())

        capturar(amb, args, "tarefa4/10-foto-no-navegador.txt", "A URL da foto retornada em GET /itens aberta no navegador (roteiro da Tarefa 4).", f"/fotos/{foto}")

        with amb.evidencia("tarefa4/11-logs-web.txt", "docker compose logs web --tail 20: o Gunicorn registra as requisições recebidas pelo web.") as ev:
            ev.cmd(amb.dc("logs", "web", "--tail", "20"))
        completo = amb.rodar(amb.dc("logs", "web"), check=False, quieto=True)
        amb.checar("T4", "logs do web registram as requisições (POST /itens e GET /health)", "POST /itens" in completo.saida and "GET /health" in completo.saida)


# ---------------------------------------------------------------- verificações complementares
def complementares(amb: Ambiente) -> None:
    p = amb.projeto
    with etapa("Verificações complementares (RNF04, isolamento do banco, DNS, rede, imagem)"):
        with amb.evidencia("complementares/01-usuario-nao-root.txt", "O contêiner web roda como 'appuser' (UID 10001), nunca como root (RNF04).") as ev:
            w = ev.cmd(amb.dc("exec", "-T", "web", "whoami"))
            i = ev.cmd(amb.dc("exec", "-T", "web", "id"))
            ev.cmd(["docker", "image", "inspect", f"{p}-web", "--format", "USER definido na imagem: {{.Config.User}}"])
        amb.checar("RNF04", "docker compose exec web whoami não retorna root", w.saida.strip() not in ("", "root"), w.saida.strip())
        amb.checar("RNF04", "o processo do web não tem UID 0", "uid=0" not in i.saida, i.saida.strip())

        with amb.evidencia(
            "complementares/02-portas-publicadas.txt",
            "Só o nginx publica porta no host; o PostgreSQL (5432) e o web (5000) existem apenas na rede interna.",
        ) as ev:
            ev.cmd(amb.dc("ps", "--format", "table {{.Service}}\\t{{.Ports}}"))
            for svc in ("db", "web", "nginx"):
                ev.cmd(["docker", "inspect", f"{p}-{svc}-1", "--format", f"{svc}: {{{{json .NetworkSettings.Ports}}}}"])
        pub = publicadores(amb)
        amb.checar("RNF/ARQ", "o db não publica nenhuma porta no host", pub.get("db") == [], str(pub.get("db")))
        amb.checar("RNF/ARQ", "o web não publica nenhuma porta no host (bônus A)", pub.get("web") == [], str(pub.get("web")))
        amb.checar("RNF/ARQ", f"o nginx publica apenas a porta {amb.porta}", pub.get("nginx") == [amb.porta] or sorted(set(pub.get("nginx", []))) == [amb.porta], str(pub.get("nginx")))

        with amb.evidencia("complementares/03-dns-interno.txt", "O web encontra o banco pelo nome 'db' usando o DNS embutido do Docker (127.0.0.11), sem IP fixo.") as ev:
            ev.cmd(amb.dc("exec", "-T", "web", "cat", "/etc/resolv.conf"))
            g = ev.cmd(amb.dc("exec", "-T", "web", "getent", "hosts", "db"))
            ip = ev.cmd(["docker", "inspect", f"{p}-db-1", "--format", f'IP do contêiner db na rede_interna: {{{{(index .NetworkSettings.Networks "{p}_rede_interna").IPAddress}}}}'])
        ip_db = ip.saida.strip().split()[-1] if ip.ok and ip.saida.strip() else "?"
        amb.checar("Q1", "o nome 'db' resolve para o IP do contêiner db na rede_interna", ip_db != "?" and ip_db in g.saida, f"{g.saida.strip()} / {ip_db}")

        with amb.evidencia(
            "complementares/04-sistema-de-arquivos-somente-leitura.txt",
            "O sistema de arquivos do web é somente leitura (só /app/uploads e /tmp aceitam escrita) e o init.sql é montado :ro no db.",
        ) as ev:
            a = ev.cmd(amb.dc("exec", "-T", "web", "sh", "-c", "touch /app/teste-gravacao"), check=False)
            b = ev.cmd(amb.dc("exec", "-T", "web", "sh", "-c", "touch /app/uploads/.teste && rm /app/uploads/.teste && echo 'gravacao em /app/uploads: OK'"), check=False)
            d = ev.cmd(amb.dc("exec", "-T", "db", "sh", "-c", "echo '-- alteracao indevida' >> /docker-entrypoint-initdb.d/init.sql"), check=False)
        amb.checar("SEG", "o web não consegue gravar fora dos volumes (read_only)", a.codigo != 0 and "Read-only" in a.saida, a.saida.strip()[:100])
        amb.checar("SEG", "o web consegue gravar em /app/uploads (volume fotos)", b.ok)
        amb.checar("T3", "o bind mount do init.sql é somente leitura", d.codigo != 0 and "Read-only" in d.saida, d.saida.strip()[:100])

        with amb.evidencia("complementares/05-sem-segredos-na-imagem.txt", "A imagem do web não contém senhas: nenhuma variável embutida é de banco e o .env não está em /app; as credenciais só chegam em tempo de execução (RNF03).") as ev:
            ev.nota("Nomes das variáveis de ambiente embutidas na IMAGEM do web (só os nomes; o teste automático também procurou o VALOR da senha em todas elas):")
            nomes = ev.cmd(["docker", "image", "inspect", f"{p}-web", "--format", '{{range .Config.Env}}{{index (split . "=") 0}}{{println}}{{end}}'])
            ls = ev.cmd(amb.dc("exec", "-T", "web", "ls", "-la", "/app"))
        valores = amb.rodar(["docker", "image", "inspect", f"{p}-web", "--format", "{{json .Config.Env}}"], quieto=True)  # sem gravar: só para a verificação
        amb.checar("RNF03", "variáveis embutidas na imagem do web não incluem senha (nomes e valores verificados)", "********" not in valores.saida and "PASSWORD" not in valores.saida.upper() and "PASSWORD" not in nomes.saida.upper())
        amb.checar("RNF03", "o arquivo .env não está dentro da imagem (/app)", ".env" not in ls.saida)

        with amb.evidencia("complementares/06-docker-network-inspect.txt", "docker network inspect da rede_interna: rede bridge definida pelo usuário com os contêineres db, web e nginx.") as ev:
            r = ev.cmd(["docker", "network", "inspect", f"{p}_rede_interna"])
        try:
            rede = json.loads(r.saida)[0]
            nomes = sorted(v["Name"] for v in rede.get("Containers", {}).values())
            amb.checar("T3", "rede_interna é do tipo bridge e contém db, web e nginx", rede["Driver"] == "bridge" and nomes == sorted(f"{p}-{s}-1" for s in ("db", "web", "nginx")), str(nomes))
        except (ValueError, KeyError, IndexError) as exc:
            amb.checar("T3", "rede_interna é do tipo bridge e contém db, web e nginx", False, str(exc))

        with amb.evidencia("complementares/07-docker-image-ls.txt", "docker image ls: tamanho da imagem do web (base python:3.12-slim + dependências) comparado às imagens oficiais usadas.") as ev:
            ev.cmd(["docker", "image", "ls", f"{p}-web"])
            ev.cmd(["docker", "image", "ls", "python:3.12-slim"])
            ev.cmd(["docker", "image", "ls", "postgres:16-alpine"])
            ev.cmd(["docker", "image", "ls", "nginx:1.30-alpine"])
            t = ev.cmd(["docker", "image", "inspect", f"{p}-web", "--format", "{{.Size}}"])
        try:
            mb = int(t.saida.strip()) / 1_000_000
            amb.checar("T2", f"imagem do web enxuta (< {TAMANHO_MAXIMO_IMAGEM_MB} MB)", mb < TAMANHO_MAXIMO_IMAGEM_MB, info=f"docker image inspect: {mb:.0f} MB")
        except ValueError:
            amb.checar("T2", "tamanho da imagem do web medido", False, t.saida[:80])


# ---------------------------------------------------------------- Tarefa 5
def tarefa5_recriacao(amb: Ambiente, c: Contagem, args) -> None:
    p = amb.projeto
    with etapa("Tarefa 5.1 - recriação dos contêineres (down + up -d)"):
        with amb.evidencia(
            "tarefa5/01-recriacao-conteineres.txt",
            "docker compose down + up -d recria os contêineres e, mesmo assim, itens e fotos continuam lá (RNF02).",
        ) as ev:
            ev.nota("PASSO 0 - estatísticas antes de começar")
            conferir(amb, ev, "T5.1", "antes dos cadastros", c)
            ev.nota("PASSO 1 - cadastrar dois objetos com foto")
            cadastrar(amb, ev, c, "Carregador de celular", "Biblioteca", "carregador.png")
            cadastrar(amb, ev, c, "Mochila azul", "Laboratorio 3", "mochila.png")
            ev.nota("PASSO 2 - estado ANTES do down")
            conferir(amb, ev, "T5.1", "antes do down", c)
            antes = amb.http(ev, "/itens")
            hash_antes = ev.cmd(amb.dc("exec", "-T", "web", "sh", "-c", "cd /app/uploads && sha256sum * | sort -k2"))
            ev.cmd(amb.dc("exec", "-T", "web", "ls", "-l", "/app/uploads"))
            ev.nota("PASSO 3 - docker compose down (remove contêineres e rede; os volumes são mantidos)")
            ev.cmd(amb.dc("down"))
            ev.cmd(amb.dc("ps", "-a"))
            vol = ev.cmd(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={p}"])
            ev.nota("PASSO 4 - docker compose up -d (sem --build)")
            ev.cmd(amb.dc("up", "-d"))
            amb.aguardar_pronto()
            ev.nota("PASSO 5 - estado DEPOIS do up")
            conferir(amb, ev, "RNF02", "depois de down + up -d", c)
            depois = amb.http(ev, "/itens")
            hash_depois = ev.cmd(amb.dc("exec", "-T", "web", "sh", "-c", "cd /app/uploads && sha256sum * | sort -k2"))
            ev.cmd(amb.dc("exec", "-T", "web", "ls", "-l", "/app/uploads"))
        por_id = lambda r: sorted(json_ou_vazio(r), key=lambda i: i["id"])  # noqa: E731
        amb.checar("RNF02", "a lista de itens (ids, textos, fotos, datas) é idêntica depois de down + up", antes.status == depois.status == 200 and por_id(antes) == por_id(depois) and len(por_id(depois)) == c.itens)
        amb.checar("RNF02", "os arquivos de foto têm os mesmos SHA-256 depois de down + up", bool(hash_antes.saida.strip()) and hash_antes.saida == hash_depois.saida)
        amb.checar("T5.1", "o down manteve os dois volumes nomeados", f"{p}_dados_banco" in vol.saida and f"{p}_fotos" in vol.saida)
        nome = next((i["foto"] for i in por_id(depois) if i.get("foto")), None)
        if nome:
            capturar(amb, args, "tarefa5/04-foto-apos-recriacao.txt", "A mesma foto aberta no navegador DEPOIS do down + up: o arquivo sobreviveu no volume fotos.", nome)


def tarefa5_volumes(amb: Ambiente, c: Contagem) -> None:
    p = amb.projeto
    fmt_mounts = "{{range .Mounts}}{{.Type}} {{.Name}} -> {{.Destination}} (leitura/escrita: {{.RW}}){{println}}{{end}}"
    with etapa("Tarefa 5.2 - inspeção dos volumes"):
        with amb.evidencia(
            "tarefa5/02-inspecao-volumes.txt",
            "docker volume ls/inspect: os dois volumes nomeados, onde ficam fisicamente (Mountpoint) e o conteúdo do volume de fotos.",
        ) as ev:
            conferir(amb, ev, "T5.2", "antes da inspeção", c)
            ev.cmd(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={p}"])
            vi = ev.cmd(["docker", "volume", "inspect", f"{p}_dados_banco", f"{p}_fotos"])
            ev.nota(
                "O Mountpoint é um caminho dentro do Docker (no Docker Desktop, dentro da VM Linux; no Linux nativo é um\n"
                "diretório real do host em /var/lib/docker/volumes). Em ambos os casos os dados não ficam na pasta do projeto."
            )
            ev.cmd(amb.dc("exec", "-T", "web", "ls", "-l", "/app/uploads"))
            ev.cmd(amb.dc("exec", "-T", "db", "ls", "/var/lib/postgresql/data"))
            ev.nota("Pontos de montagem de cada contêiner (o init.sql é um bind mount somente leitura; os dados são volumes nomeados):")
            ev.cmd(["docker", "inspect", f"{p}-web-1", "--format", fmt_mounts])
            m_db = ev.cmd(["docker", "inspect", f"{p}-db-1", "--format", fmt_mounts])
        try:
            vols = {v["Name"]: v for v in json.loads(vi.saida)}
            ok = set(vols) == {f"{p}_dados_banco", f"{p}_fotos"} and all(v["Driver"] == "local" and v["Name"] in v["Mountpoint"] for v in vols.values())
        except (ValueError, KeyError):
            ok = False
        amb.checar("T5.2", "docker volume inspect mostra os volumes dados_banco e fotos (driver local) com Mountpoint próprio", ok)
        amb.checar("T3", "db monta dados_banco em /var/lib/postgresql/data e o init.sql como bind somente leitura", "volume" in m_db.saida and "/var/lib/postgresql/data" in m_db.saida and "init.sql (leitura/escrita: false)" in m_db.saida, m_db.saida[:200])


def bonus_backup(amb: Ambiente) -> None:
    p = amb.projeto
    with etapa("Bônus B - backup e restauração do volume fotos"):
        pasta = amb.tmp / "backups"
        novo = f"{p}_fotos_restaurado"
        amb.volumes_extras.append(novo)
        script = "scripts/backup_fotos.py"
        hashes = lambda ev, vol: ev.cmd(  # noqa: E731
            ["docker", "run", "--rm", "--mount", f"type=volume,source={vol},target=/dados,readonly", "alpine:3.24", "sh", "-c", "cd /dados && sha256sum * | sort -k2"]
        )
        with amb.evidencia(
            "bonus/05-backup-e-restauracao-fotos.txt",
            "Backup do volume fotos em .tar.gz com um contêiner temporário (docker run --rm) e restauração em um volume novo, com SHA-256 idênticos.",
        ) as ev:
            b = ev.cmd([sys.executable, script, "backup", "--volume", f"{p}_fotos", "--saida", str(pasta)])
            arquivos = sorted(pasta.glob("fotos-*.tar.gz"))
            amb.checar("BONUS-B", "o backup gerou um arquivo .tar.gz não vazio", b.ok and bool(arquivos) and arquivos[-1].stat().st_size > 0)
            r = ev.cmd([sys.executable, script, "restaurar", "--arquivo", str(arquivos[-1]), "--volume-destino", novo])
            h1, h2 = hashes(ev, f"{p}_fotos"), hashes(ev, novo)
            ev.nota("Os dois volumes (original e restaurado) têm exatamente os mesmos arquivos com os mesmos SHA-256 se as duas listas acima forem iguais.")
            ev.cmd(["docker", "volume", "rm", novo])
        amb.checar("BONUS-B", "a restauração em volume novo preserva o dono dos arquivos (UID 10001)", r.ok and "10001" in r.saida)
        amb.checar("BONUS-B", "volume restaurado tem os mesmos arquivos e SHA-256 do volume original", bool(h1.saida.strip()) and h1.saida == h2.saida)


def tarefa5_remocao(amb: Ambiente, c: Contagem) -> None:
    p = amb.projeto
    with etapa("Tarefa 5.3 - remoção dos volumes (down -v)"):
        with amb.evidencia(
            "tarefa5/03-remocao-volumes.txt",
            "docker compose down -v apaga os volumes: itens e fotos cadastrados somem e o init.sql recria os 3 itens de exemplo (contraprova do RNF02).",
        ) as ev:
            ev.nota("PASSO 0 - estatísticas antes")
            conferir(amb, ev, "T5.3", "antes do down -v", c)
            antes = json_ou_vazio(amb.http(ev, "/itens"))
            foto_antiga = next(i["foto"] for i in antes if i.get("foto"))
            ev.nota("PASSO 1 - docker compose down -v (apaga contêineres, rede E volumes)")
            ev.cmd(amb.dc("down", "-v"))
            vol = ev.cmd(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={p}"])
            ev.nota("PASSO 2 - docker compose up -d (banco novo, diretório de dados vazio)")
            ev.cmd(amb.dc("up", "-d"))
            amb.aguardar_pronto()
            c.itens, c.fotos = 3, 0
            ev.nota("PASSO 3 - estado DEPOIS")
            conferir(amb, ev, "T5.3", "depois do down -v + up -d", c)
            depois = amb.http(ev, "/itens")
            foto = amb.http(ev, foto_antiga, so_cabecalhos=True)
            ev.cmd(amb.dc("exec", "-T", "web", "ls", "-l", "/app/uploads"))
            ev.nota("PASSO 4 - log de inicialização do db: o init.sql voltou a ser executado")
            logs = ev.cmd(amb.dc("logs", "db"))
        amb.checar("T5.3", "o down -v removeu os dois volumes", f"{p}_dados_banco" not in vol.saida and f"{p}_fotos" not in vol.saida)
        amb.checar("T5.3", "depois do down -v só existem os 3 itens de exemplo do init.sql", {i["descricao"] for i in json_ou_vazio(depois)} == ITENS_DE_EXEMPLO)
        amb.checar("T5.3", "a foto cadastrada antes do down -v não existe mais (404)", foto.status == 404, f"HTTP {foto.status}")
        amb.checar("T5.3", "o log do db mostra o init.sql executado de novo (CREATE TABLE + INSERT 0 3)", "init.sql" in logs.saida and "CREATE TABLE" in logs.saida and "INSERT 0 3" in logs.saida)


# ---------------------------------------------------------------- bônus A e C
def bonus_nginx(amb: Ambiente, c: Contagem) -> None:
    with etapa("Bônus A - nginx como proxy reverso"):
        with amb.evidencia("bonus/01-nginx-unico-publicador.txt", "Só o nginx expõe a porta do host; as respostas chegam com 'Server: nginx' (sem versão), passando pelo proxy até o web.") as ev:
            ev.cmd(amb.dc("ps"))
            h = amb.http(ev, "/health", so_cabecalhos=True)
        amb.checar("BONUS-A", "a resposta passa pelo nginx (Server: nginx, sem número de versão)", bool(re.search(r"(?im)^server: nginx\s*$", h.saida)), h.saida[:80])

        with amb.evidencia("bonus/02-nginx-upload-grande.txt", "Foto de ~2 MB passa pelo proxy (client_max_body_size 10m); arquivo de ~11 MB é recusado com 413.") as ev:
            r1 = cadastrar(amb, ev, c, "Foto grande", "Teste", "foto-2mb.png")
            r2 = amb.http(ev, "/itens", campos={"descricao": "foto enorme", "local": "Teste"}, arquivo="foto-11mb.png")
            conferir(amb, ev, "BONUS-A", "depois dos uploads", c)
        amb.checar("BONUS-A", "upload de ~2 MB pelo proxy -> 201", r1.status == 201, f"HTTP {r1.status}")
        amb.checar("BONUS-A", "upload de ~11 MB é recusado pelo proxy -> 413 (limite de 10 MB)", r2.status == 413, f"HTTP {r2.status}")

        with amb.evidencia(
            "bonus/03-nginx-fotos-cabecalhos-de-seguranca.txt",
            "Em /fotos/ o nginx força download de arquivos que não são imagem (ex.: .html enviado como foto) e adiciona nosniff e CSP.",
        ) as ev:
            rh = cadastrar(amb, ev, c, "Arquivo html enviado como foto", "Teste", "nao-e-foto.html")
            rp = cadastrar(amb, ev, c, "Foto pequena", "Teste", "pequena.png")
            hh = amb.http(ev, f"/fotos/{json_ou_vazio(rh).get('foto')}", so_cabecalhos=True)
            hp = amb.http(ev, f"/fotos/{json_ou_vazio(rp).get('foto')}", so_cabecalhos=True)
        n = lambda r: len(re.findall(r"(?im)^content-disposition:", r.saida))  # noqa: E731
        amb.checar("BONUS-A", "o .html enviado como foto é servido com Content-Disposition: attachment (único cabeçalho)", n(hh) == 1 and re.search(r"(?im)^content-disposition: attachment\s*$", hh.saida) is not None)
        amb.checar("BONUS-A", "a imagem PNG é servida inline (único Content-Disposition)", n(hp) == 1 and re.search(r"(?im)^content-disposition: inline\s*$", hp.saida) is not None)
        amb.checar("BONUS-A", "as fotos levam X-Content-Type-Options: nosniff e Content-Security-Policy com sandbox", all("nosniff" in x.saida.lower() and "sandbox" in x.saida.lower() for x in (hh, hp)))


def bonus_adminer(amb: Ambiente) -> None:
    p = amb.projeto
    url = f"http://127.0.0.1:{amb.porta_adminer}/"
    with etapa("Bônus C - adminer no profile debug"):
        amb.checar("BONUS-C", "sem o profile debug o adminer não está no ambiente", "adminer" not in amb.estado())
        with amb.evidencia(
            "bonus/04-adminer-profile-debug.txt",
            "O Adminer só sobe com --profile debug, escuta apenas em 127.0.0.1, alcança o db pela rede interna (sem publicar 5432) e é encerrado sozinho.",
        ) as ev:
            ev.nota("PASSO 1 - sem o profile: serviços do ambiente e contêineres existentes (adminer ausente)")
            sv = ev.cmd(amb.dc("config", "--services"))
            ev.cmd(amb.dc("ps", "-a"))
            ev.nota("PASSO 2 - docker compose --profile debug up -d")
            ev.cmd(amb.dc("--profile", "debug", "up", "-d"))
            import urllib.request

            def adminer_responde() -> bool:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    return resp.status == 200

            amb.esperar(adminer_responde, "Adminer responder 200", timeout=90)
            ev.cmd(amb.dc("ps"))
            h = ev.cmd([amb.curl, "-sI", url], cwd=amb.tmp, check=False)
            php = ev.cmd(
                amb.dc("exec", "-T", "adminer", "php", "-r", "$s=@fsockopen('db',5432,$e,$m,3); echo $s ? 'conectado a db:5432 pela rede interna' : 'falhou: '.$m; echo PHP_EOL;"),
                check=False,
            )
            ev.cmd(["docker", "inspect", f"{p}-db-1", "--format", "portas do db publicadas no host: {{json .NetworkSettings.Ports}}"])
            ev.nota("PASSO 3 - encerrar só o adminer (db, web e nginx continuam)")
            ev.cmd(amb.dc("rm", "-sf", "adminer"))
            ev.cmd(amb.dc("ps", "-a"))
        amb.checar("BONUS-C", "o adminer não aparece entre os serviços sem o profile", "adminer" not in sv.saida.split())
        amb.checar("BONUS-C", "com --profile debug o Adminer responde HTTP 200 em 127.0.0.1", " 200" in h.saida.splitlines()[0] if h.saida.strip() else False)
        amb.checar("BONUS-C", "o Adminer alcança db:5432 pela rede interna", "conectado a db:5432" in php.saida, php.saida.strip()[:80])
        pub = publicadores(amb)
        amb.checar("BONUS-C", "o db continua sem porta publicada no host", pub.get("db") == [])
        est = amb.estado()
        amb.checar("BONUS-C", "docker compose rm -sf adminer remove só o adminer", "adminer" not in est and {"db", "web", "nginx"} <= set(est))


# ---------------------------------------------------------------- principal
def executar(amb: Ambiente, args) -> None:
    c = Contagem()
    preparar_arquivos(amb)
    tarefa4(amb, c, args)
    complementares(amb)
    tarefa5_recriacao(amb, c, args)
    tarefa5_volumes(amb, c)
    bonus_backup(amb)
    tarefa5_remocao(amb, c)
    bonus_nginx(amb, c)
    bonus_adminer(amb)


def main() -> int:
    configurar_saida()
    ap = argparse.ArgumentParser(description="Testes funcionais e de persistência do Achados & Perdidos (projeto Compose isolado).")
    ap.add_argument("--projeto", default="achados-perdidos-evidencias", help="nome do projeto Compose de teste (deve começar com 'achados-perdidos-')")
    ap.add_argument("--porta", type=int, default=8080, help="porta do host onde o nginx publica o site (padrão: 8080)")
    ap.add_argument("--porta-adminer", type=int, default=8081, help="porta do host (127.0.0.1) do Adminer (padrão: 8081)")
    ap.add_argument("--evidencias", type=Path, help="pasta onde gravar as evidências (ex.: docs/evidencias)")
    ap.add_argument("--capturas", action="store_true", help="tira prints da foto em navegador headless (Edge/Chrome)")
    ap.add_argument("--manter", action="store_true", help="não remove o ambiente de teste ao final")
    args = ap.parse_args()

    pasta = args.evidencias.resolve() if args.evidencias else None
    amb = Ambiente(args.projeto, porta=args.porta, porta_adminer=args.porta_adminer, pasta_evid=pasta)
    try:
        pre_voo(amb, args)
        amb.configurar_portas()
        if pasta:
            for sub in SUBPASTAS_GERADAS:
                shutil.rmtree(pasta / sub, ignore_errors=True)
            gravar_ambiente(amb)
        executar(amb, args)
    except Falha as e:
        print(f"\nERRO: {e}", file=sys.stderr)
        amb.checar("EXEC", "execução completa dos testes", False, str(e)[:300])
    except KeyboardInterrupt:
        amb.checar("EXEC", "execução completa dos testes", False, "interrompida pelo usuário")
    finally:
        if args.manter:
            print(f"\n(--manter) ambiente '{amb.projeto}' mantido. Remova com: docker compose -p {amb.projeto} down -v")
        else:
            with etapa("Limpeza do ambiente de teste"):
                amb.derrubar()
        if pasta:
            problemas = varrer_vazamentos(pasta, amb.segredos)
            amb.checar("RNF03", "evidências geradas não contêm a senha do .env nem caminhos do computador do autor", not problemas, "; ".join(problemas))
            escrever_resumo(
                pasta / "resumo-testes.md",
                "Resumo das verificações automáticas",
                amb.checagens,
                "Gerado por `scripts/testar_ambiente.py`; cada linha corresponde a uma asserção executada contra o ambiente real.",
            )
            gerar_indice(pasta)
        resumo_ci("Testes do ambiente", amb.checagens)
        amb.encerrar()

    falhas = [x for x in amb.checagens if not x.ok]
    print(f"\n{len(amb.checagens) - len(falhas)}/{len(amb.checagens)} verificações aprovadas.")
    for x in falhas:
        print(f"  FALHOU [{x.req}] {x.descricao} {' '.join(x.detalhe.split())[:200]}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
