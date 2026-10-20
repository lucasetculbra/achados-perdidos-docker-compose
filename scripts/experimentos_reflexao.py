#!/usr/bin/env python3
"""Experimentos reais que sustentam as respostas de docs/REFLEXAO.md (Q1, Q3, Q5 e Q7).

Cada experimento roda comandos de verdade (docker, curl), confere o resultado e grava a saída em
docs/evidencias/reflexao/. Usa projeto Compose próprio (achados-perdidos-experimentos) e recursos
docker com o prefixo "achados-perdidos-exp-": nada do ambiente real do usuário é tocado.

    python scripts/experimentos_reflexao.py --evidencias docs/evidencias [--porta 18080]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from comum import (
    RAIZ,
    Ambiente,
    Falha,
    configurar_saida,
    escrever_resumo,
    etapa,
    gerar_indice,
    info_ambiente,
    json_linhas,
    png_sintetico,
    porta_em_uso,
    resumo_ci,
    varrer_vazamentos,
)

PREFIXO = "achados-perdidos-exp-"
ALPINE = "alpine:3.24"
IMAGEM_CACHE = f"{PREFIXO}cache"
PORTA_CONFLITO = 18090


# ---------------------------------------------------------------- Q1: DNS interno do Docker
def q1(amb: Ambiente) -> None:
    a, b, rede = f"{PREFIXO}q1-a", f"{PREFIXO}q1-b", f"{PREFIXO}q1-rede"
    with etapa("Q1 - DNS interno: rede bridge padrão x rede definida pelo usuário"):
        with amb.evidencia(
            "reflexao/q1-dns-bridge-padrao-x-rede-definida.txt",
            "Na bridge padrão um contêiner não resolve outro pelo nome; em uma rede definida pelo usuário o DNS embutido (127.0.0.11) resolve.",
        ) as ev:
            ev.nota(
                "Resolução feita com `getent hosts` (resolvedor da libc): ele respeita a lista de domínios de busca do host. O `nslookup` do BusyBox\n"
                "acrescenta o domínio de busca do host (ex.: *.cloudapp.net no GitHub Actions) e não tenta o nome puro, o que dá falso NXDOMAIN."
            )
            ev.nota("A) Rede bridge PADRÃO (docker run sem --network): sobe um contêiner e tenta resolver o nome dele a partir de outro.")
            ev.cmd(["docker", "run", "-d", "--name", a, ALPINE, "sleep", "300"])
            ev.cmd(["docker", "run", "--rm", ALPINE, "cat", "/etc/resolv.conf"])
            r1 = ev.cmd(["docker", "run", "--rm", ALPINE, "getent", "hosts", a], check=False)
            ev.nota(f"(código de saída do getent acima: {r1.codigo}; 2 = nome não encontrado)")
            ev.nota("B) Rede DEFINIDA PELO USUÁRIO (como a rede_interna do Compose): o mesmo teste.")
            ev.cmd(["docker", "network", "create", rede])
            ev.cmd(["docker", "run", "-d", "--name", b, "--network", rede, ALPINE, "sleep", "300"])
            ip = ev.cmd(["docker", "inspect", b, "--format", f'IP de {b}: {{{{(index .NetworkSettings.Networks "{rede}").IPAddress}}}}'])
            conf = ev.cmd(["docker", "run", "--rm", "--network", rede, ALPINE, "cat", "/etc/resolv.conf"])
            r2 = ev.cmd(["docker", "run", "--rm", "--network", rede, ALPINE, "getent", "hosts", b], check=False)
        ip_b = ip.saida.strip().split()[-1] if ip.ok and ip.saida.strip() else "?"
        amb.checar("Q1", "na rede bridge padrão o nome do outro contêiner NÃO é resolvido", r1.codigo != 0 and not r1.saida.strip(), r1.saida.strip()[-80:])
        amb.checar("Q1", "em rede definida pelo usuário o nome é resolvido para o IP do contêiner", r2.ok and ip_b != "?" and ip_b in r2.saida, r2.saida.strip()[-80:])
        amb.checar("Q1", "o resolvedor da rede definida é o DNS embutido 127.0.0.11", "nameserver 127.0.0.11" in conf.saida)


# ---------------------------------------------------------------- Q5: cache de camadas
def etapa_em_cache(saida: str, trecho: str) -> bool | None:
    """True/False se a etapa do build cujo comando contém `trecho` foi reaproveitada do cache; None se não achou."""
    m = re.search(rf"(?m)^#(\d+) \[[^\]]*\] .*{re.escape(trecho)}", saida)
    if not m:
        return None
    return re.search(rf"(?m)^#{m.group(1)} CACHED\s*$", saida) is not None


def q5(amb: Ambiente) -> None:
    def contexto(nome: str, arquivo: str | None = None, texto: str = "") -> list[str]:
        """Comando de build sobre uma CÓPIA NOVA de app/ (como um checkout limpo); `arquivo` recebe `texto` no fim."""
        destino = amb.tmp / nome
        shutil.copytree(RAIZ / "app", destino)
        if arquivo:
            with open(destino / arquivo, "a", encoding="utf-8", newline="\n") as f:
                f.write(texto)
        return ["docker", "build", "--progress=plain", "-t", IMAGEM_CACHE, str(destino)]

    with etapa("Q5 - cache de camadas do Dockerfile"):
        with amb.evidencia(
            "reflexao/q5-cache-de-camadas.txt",
            "Build com cache: sem mudanças tudo é reaproveitado; mudando só o app.py o pip install continua em cache; mudando o requirements.txt ele é refeito.",
        ) as ev:
            marca = uuid.uuid4().hex[:8]
            ev.nota(
                "Cada build usa uma cópia nova da pasta app/ (como um checkout limpo da CI); o app.py e o requirements.txt do repositório NÃO são alterados.\n"
                f"O cache do Docker é endereçado por CONTEÚDO: por isso o comentário acrescentado nas cópias leva um texto único desta execução ({marca}).\n"
                "Se o mesmo conteúdo já tivesse sido construído antes, o Docker o reaproveitaria (acerto de cache legítimo) e o experimento não mostraria a invalidação."
            )
            ev.nota("1) Build do zero (--no-cache): todas as etapas são executadas.")
            r1 = ev.cmd(["docker", "build", "--no-cache", *contexto("contexto-1")[2:]], timeout=900)
            ev.nota("2) Conteúdo idêntico: todas as etapas vêm do cache.")
            r2 = ev.cmd(contexto("contexto-2"), timeout=900)
            ev.nota("3) Só o app.py mudou (um comentário acrescentado na CÓPIA): o pip install continua em cache e só a cópia do código é refeita.")
            r3 = ev.cmd(contexto("contexto-3", "app.py", f"\n# alteracao de teste {marca}\n"), timeout=900)
            ev.nota("4) O requirements.txt mudou (um comentário acrescentado na CÓPIA): a camada do pip install é invalidada e as dependências são reinstaladas.")
            r4 = ev.cmd(contexto("contexto-4", "requirements.txt", f"# alteracao de teste {marca}\n"), timeout=900)
            ev.nota(
                "Tempos medidos (segundos): "
                f"do zero={r1.segundos:.1f} | sem mudanças={r2.segundos:.1f} | só app.py={r3.segundos:.1f} | requirements.txt={r4.segundos:.1f}"
            )
        pip, copia = "RUN pip install", "COPY app.py"
        amb.checar("Q5", "build do zero executa o pip install (sem cache)", etapa_em_cache(r1.saida, pip) is False)
        amb.checar("Q5", "sem mudanças: pip install e COPY app.py vêm do cache", etapa_em_cache(r2.saida, pip) is True and etapa_em_cache(r2.saida, copia) is True)
        amb.checar("Q5", "só o app.py mudou: pip install CACHED, COPY app.py refeito", etapa_em_cache(r3.saida, pip) is True and etapa_em_cache(r3.saida, copia) is False)
        amb.checar("Q5", "requirements.txt mudou: pip install é refeito", etapa_em_cache(r4.saida, pip) is False)
        amb.checar("Q5", "reconstruir só com o app.py alterado é mais rápido que reinstalar as dependências", r3.segundos < r4.segundos, info=f"só app.py {r3.segundos:.1f}s x requirements.txt {r4.segundos:.1f}s (do zero {r1.segundos:.1f}s, sem mudanças {r2.segundos:.1f}s)")


# ---------------------------------------------------------------- Q3: init.sql depois da primeira execução
def q3(amb: Ambiente) -> None:
    psql = lambda sql: ["exec", "-T", "db", "sh", "-c", f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "{sql}"']  # noqa: E731
    with etapa("Q3 - alterar o init.sql depois que o banco já foi inicializado"):
        original = (RAIZ / "db/init.sql").read_text(encoding="utf-8")
        trecho = "    criado_em TIMESTAMP NOT NULL DEFAULT NOW()\n);"
        if trecho not in original.replace("\r\n", "\n"):
            raise Falha("db/init.sql mudou: ajuste o experimento Q3")
        alterado = amb.tmp / "init-alterado.sql"
        alterado.write_text(original.replace("\r\n", "\n").replace(trecho, "    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),\n    contato    VARCHAR(100)\n);"), encoding="utf-8", newline="\n")
        yaml = (
            "services:\n  db:\n    volumes: !override\n"
            "      - type: volume\n        source: dados_banco\n        target: /var/lib/postgresql/data\n"
            f"      - type: bind\n        source: '{alterado}'\n        target: /docker-entrypoint-initdb.d/init.sql\n        read_only: true\n"
        )
        with amb.evidencia(
            "reflexao/q3-init-sql-alterado.txt",
            "Com o volume dados_banco já populado, um init.sql alterado NÃO é reaplicado (initdb é ignorado); a coluna nova só entra com ALTER TABLE, sem perder dados.",
        ) as ev:
            ev.nota("PASSO 1 - registrar um item novo (prova de que os dados não se perdem) e o número de linhas")
            amb.http(ev, "/itens", campos={"descricao": "Item cadastrado antes da alteracao", "local": "Q3"})
            antes = ev.cmd(amb.dc(*psql("SELECT count(*) AS itens FROM itens")))
            ev.nota("PASSO 2 - trocar o init.sql montado por uma versão com a coluna 'contato' (override temporário; o db/init.sql do repositório não é alterado)")
            override = amb.adicionar_override("override-init-alterado.yml", yaml)
            ev.nota("Conteúdo do override:\n" + yaml)
            ev.cmd(amb.dc("up", "-d"))
            amb.aguardar_pronto()
            ev.nota("PASSO 3 - o db foi recriado com o novo init.sql montado. A coluna existe?")
            logs = ev.cmd(amb.dc("logs", "db", "--tail", "30"))
            d1 = ev.cmd(amb.dc(*psql("\\d itens")))
            ev.nota("PASSO 4 - aplicar a mudança SEM perder dados: ALTER TABLE direto no banco em execução (migração)")
            ev.cmd(amb.dc(*psql("ALTER TABLE itens ADD COLUMN IF NOT EXISTS contato VARCHAR(100)")))
            d2 = ev.cmd(amb.dc(*psql("\\d itens")))
            depois = ev.cmd(amb.dc(*psql("SELECT count(*) AS itens FROM itens")))
            lista = amb.http(ev, "/itens")
            ev.nota("PASSO 5 - voltar ao init.sql original do repositório")
            amb.remover_override(override)
            ev.cmd(amb.dc("up", "-d"))
            amb.aguardar_pronto()
        amb.checar("Q3", "o log do db mostra que a inicialização foi ignorada (Skipping initialization)", "Skipping initialization" in logs.saida)
        amb.checar("Q3", "com o init.sql alterado, a coluna 'contato' NÃO foi criada", "contato" not in d1.saida)
        amb.checar("Q3", "o ALTER TABLE criou a coluna 'contato'", "contato" in d2.saida)
        contagem = lambda r: re.search(r"(?m)^\s*(\d+)\s*$", r.saida)  # noqa: E731
        amb.checar("Q3", "nenhuma linha foi perdida (mesma contagem antes e depois da migração)", bool(contagem(antes)) and contagem(antes).group(1) == contagem(depois).group(1) == "4", info=f"{contagem(antes) and contagem(antes).group(1)} linhas antes e {contagem(depois) and contagem(depois).group(1)} depois")
        amb.checar("Q3", "a aplicação continua funcionando depois da migração (GET /itens)", lista.status == 200 and "Item cadastrado antes da alteracao" in lista.corpo)


# ---------------------------------------------------------------- Q7: --scale web=3
def replicas_web(amb: Ambiente) -> list[dict]:
    r = amb.rodar(amb.dc("ps", "-a", "--format", "json"), check=False, quieto=True)
    return [o for o in json_linhas(r.saida) if o.get("Service") == "web"]


def q7(amb: Ambiente) -> None:
    (amb.tmp / "pequena.png").write_bytes(png_sintetico((90, 160, 230), 64, 64))
    distribui = 'for i in $(seq 1 18); do wget -qO- http://127.0.0.1/health; done'
    with etapa("Q7 - docker compose up -d --scale web=3"):
        with amb.evidencia(
            "reflexao/q7-scale-com-nginx.txt",
            "Com o nginx na frente e sem porta fixa no web, --scale web=3 funciona: 3 réplicas respondem e compartilham o volume fotos (no mesmo host).",
        ) as ev:
            r = ev.cmd(amb.dc("up", "-d", "--scale", "web=3"), timeout=300)
            amb.esperar(lambda: len([o for o in replicas_web(amb) if o.get("State") == "running" and o.get("Health") == "healthy"]) == 3, "3 réplicas do web saudáveis", timeout=120)
            ev.cmd(amb.dc("ps"))
            ev.nota("Distribuição: 18 requisições GET /health feitas de dentro do nginx; o campo 'container' mostra qual réplica respondeu.\n"
                    "O nginx renova o DNS a cada 10 s (resolver ... valid=10s), então a primeira rodada pode usar poucas réplicas; repetimos até aparecerem as três.")
            hosts: set[str] = set()
            for _ in range(8):
                d = ev.cmd(amb.dc("exec", "-T", "nginx", "sh", "-c", distribui), check=False)
                hosts = set(re.findall(r'"container":"([0-9a-f]+)"', d.saida))
                if len(hosts) >= 3:
                    break
                time.sleep(4)
            ev.nota(f"Réplicas distintas que responderam na última rodada: {len(hosts)}")
            ev.nota("Volume compartilhado: cadastra uma foto pelo nginx e lista /app/uploads em CADA réplica (as três montam o mesmo volume 'fotos').")
            amb.http(ev, "/itens", campos={"descricao": "Foto enviada com 3 replicas", "local": "Q7"}, arquivo="pequena.png")
            listas = [ev.cmd(amb.dc("exec", "-T", "--index", str(n), "web", "ls", "/app/uploads")) for n in (1, 2, 3)]
        amb.checar("Q7", "up -d --scale web=3 termina com sucesso (com o nginx e sem porta fixa no web)", r.ok)
        amb.checar("Q7", "existem 3 réplicas do web em execução", len(replicas_web(amb)) == 3)
        amb.checar("Q7", "as 3 réplicas atendem requisições (campo 'container' do /health tem 3 valores)", len(hosts) == 3, info=f"{len(hosts)} réplicas distintas responderam")
        nomes = [sorted(x.saida.split()) for x in listas]
        amb.checar("Q7", "as 3 réplicas enxergam os mesmos arquivos no volume fotos compartilhado", all(n == nomes[0] for n in nomes) and len(nomes[0]) >= 1, str(nomes[0]))

        with amb.evidencia(
            "reflexao/q7-scale-conflito-de-porta.txt",
            "Se o web publicasse uma porta fixa no host (como no enunciado básico, 8080:5000), --scale web=3 falha: só um contêiner pode ocupar a porta.",
        ) as ev:
            ev.cmd(amb.dc("up", "-d", "--scale", "web=1"), timeout=300)
            if porta_em_uso(PORTA_CONFLITO):
                raise Falha(f"a porta {PORTA_CONFLITO} (usada na simulação do conflito) está ocupada")
            yaml = f'services:\n  web:\n    ports: !override\n      - "{PORTA_CONFLITO}:5000"\n'
            ev.nota("Override temporário que simula o desenho do enunciado básico (web com porta fixa publicada no host):\n" + yaml)
            override = amb.adicionar_override("override-web-porta-fixa.yml", yaml)
            falha = ev.cmd(amb.dc("up", "-d", "--scale", "web=3"), check=False, timeout=300)
            ev.cmd(amb.dc("ps", "-a"))
            ev.nota("Restaurando o desenho final (sem porta fixa no web) e voltando para 1 réplica.")
            amb.remover_override(override)
            ev.cmd(amb.dc("up", "-d", "--scale", "web=1"), timeout=300)
            amb.aguardar_pronto()
        amb.checar("Q7", "com porta fixa no web, up --scale web=3 falha (conflito de porta no host)", falha.codigo != 0 and re.search(r"(?i)already allocated|ports are not available|address already in use|only one usage|bind", falha.saida) is not None, falha.saida.strip()[-160:])
        amb.checar("Q7", "depois de remover o override o ambiente volta ao normal com 1 réplica", len(replicas_web(amb)) == 1)


# ---------------------------------------------------------------- principal
def limpar_recursos_docker(amb: Ambiente) -> None:
    for nome in (f"{PREFIXO}q1-a", f"{PREFIXO}q1-b"):
        amb.rodar(["docker", "rm", "-f", nome], check=False, quieto=True)
    amb.rodar(["docker", "network", "rm", f"{PREFIXO}q1-rede"], check=False, quieto=True)
    amb.rodar(["docker", "rmi", "-f", IMAGEM_CACHE], check=False, quieto=True)


def main() -> int:
    configurar_saida()
    ap = argparse.ArgumentParser(description="Experimentos reais que sustentam docs/REFLEXAO.md (Q1, Q3, Q5, Q7).")
    ap.add_argument("--projeto", default="achados-perdidos-experimentos")
    ap.add_argument("--porta", type=int, default=8080, help="porta do host do nginx (padrão: 8080)")
    ap.add_argument("--evidencias", type=Path, help="pasta de evidências (ex.: docs/evidencias); grava em <pasta>/reflexao/")
    ap.add_argument("--manter", action="store_true", help="não remove o ambiente ao final")
    args = ap.parse_args()

    pasta = args.evidencias.resolve() if args.evidencias else None
    amb = Ambiente(args.projeto, porta=args.porta, pasta_evid=pasta)
    try:
        if not amb.rodar(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, quieto=True).ok:
            raise Falha("o daemon do Docker não está respondendo.")
        if not (RAIZ / ".env").exists():
            raise Falha("arquivo .env ausente: copie .env.example para .env.")
        amb.limpar_anterior()
        limpar_recursos_docker(amb)
        if porta_em_uso(args.porta):
            raise Falha(f"a porta {args.porta} está em uso; escolha outra com --porta (ex.: 1{args.porta}).")
        amb.configurar_portas()
        if pasta:
            shutil.rmtree(pasta / "reflexao", ignore_errors=True)
            (pasta / "reflexao").mkdir(parents=True, exist_ok=True)
            (pasta / "reflexao/00-contexto.txt").write_text(
                amb.limpar("\n".join(["# Legenda: Contexto da execução dos experimentos da reflexão (versões, projeto isolado e hashes dos arquivos).", "", f"Projeto Compose isolado: {amb.projeto}", f"Porta do host (nginx): {amb.porta}", *[f"Nota: {n}" for n in amb.notas_cabecalho], "", *info_ambiente()])) + "\n",
                encoding="utf-8", newline="\n",
            )
        q1(amb)
        q5(amb)
        with etapa("Subindo o ambiente para os experimentos Q3 e Q7"):
            amb.rodar(amb.dc("up", "-d", "--build"), timeout=1500)
            amb.aguardar_pronto()
        q3(amb)
        q7(amb)
    except Falha as e:
        print(f"\nERRO: {e}", file=sys.stderr)
        amb.checar("EXEC", "execução completa dos experimentos", False, str(e)[:300])
    except KeyboardInterrupt:
        amb.checar("EXEC", "execução completa dos experimentos", False, "interrompida pelo usuário")
    finally:
        limpar_recursos_docker(amb)
        if args.manter:
            print(f"\n(--manter) ambiente '{amb.projeto}' mantido. Remova com: docker compose -p {amb.projeto} down -v")
        else:
            with etapa("Limpeza do ambiente de experimentos"):
                amb.derrubar()
        if pasta:
            problemas = varrer_vazamentos(pasta / "reflexao", amb.segredos)
            amb.checar("RNF03", "evidências dos experimentos não contêm a senha do .env nem caminhos do computador do autor", not problemas, "; ".join(problemas))
            escrever_resumo(pasta / "reflexao/resumo-experimentos.md", "Resumo dos experimentos da reflexão", amb.checagens,
                            "Gerado por `scripts/experimentos_reflexao.py`; cada linha é uma asserção executada contra o ambiente real.")
            gerar_indice(pasta)
        resumo_ci("Experimentos da reflexão", amb.checagens)
        amb.encerrar()

    falhas = [x for x in amb.checagens if not x.ok]
    print(f"\n{len(amb.checagens) - len(falhas)}/{len(amb.checagens)} verificações aprovadas.")
    for x in falhas:
        print(f"  FALHOU [{x.req}] {x.descricao} {' '.join(x.detalhe.split())[:200]}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
