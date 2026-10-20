"""Biblioteca comum dos scripts de teste e de evidências (somente biblioteca padrão).

Roda igual no PowerShell/Windows e no Ubuntu do GitHub Actions. Tudo o que é
executado de verdade (docker, curl) tem a saída gravada em docs/evidencias/ com
uma legenda de uma linha; nada é escrito "à mão".
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROJETO_REAL = "achados-perdidos"  # nome do projeto do docker-compose.yml: nunca é destruído por estes scripts
URL_REPO = "https://github.com/lucasetculbra/achados-perdidos-docker-compose"
EM_CI = os.getenv("GITHUB_ACTIONS") == "true"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Arquivos cujo conteúdo as evidências comprovam (hash gravado em 00-ambiente.txt).
ARQUIVOS_INFRA = [
    "app/Dockerfile",
    "app/.dockerignore",
    "app/app.py",
    "app/requirements.txt",
    "db/init.sql",
    "docker-compose.yml",
    "nginx/default.conf",
    ".env.example",
    "scripts/backup_fotos.py",
]


class Falha(Exception):
    """Erro que interrompe a execução (comando falhou, ambiente inesperado...)."""


def configurar_saida() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - melhor esforço
            pass


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def sha256_arquivo(caminho: Path, normalizar_eol: bool = False) -> str:
    dados = Path(caminho).read_bytes()
    if normalizar_eol:  # o hash não muda se o Windows converter LF em CRLF
        dados = dados.replace(b"\r\n", b"\n")
    return sha256_bytes(dados)


def ler_env(caminho: Path | None = None) -> dict[str, str]:
    caminho = caminho or RAIZ / ".env"
    valores: dict[str, str] = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, valor = linha.split("=", 1)
                valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def exibir(args: list[str]) -> str:
    """Formata o comando como ele seria digitado em um terminal."""
    partes = []
    for a in args:
        partes.append(a if re.fullmatch(r"[\w@%+=:,./\\{}-]+", a) else '"' + a.replace('"', '\\"') + '"')
    return " ".join(partes)


def porta_em_uso(porta: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=1):
            return True
    except OSError:
        return False


def json_linhas(texto: str) -> list[dict]:
    """Interpreta a saída de `docker ... --format json` (lista JSON ou um objeto por linha)."""
    texto = texto.strip()
    if not texto:
        return []
    try:
        dados = json.loads(texto)
        return dados if isinstance(dados, list) else [dados]
    except json.JSONDecodeError:
        return [json.loads(l) for l in texto.splitlines() if l.strip().startswith("{")]


# ---------------------------------------------------------------- imagens sintéticas
def _chunk(tipo: bytes, dados: bytes) -> bytes:
    corpo = tipo + dados
    return struct.pack(">I", len(dados)) + corpo + struct.pack(">I", zlib.crc32(corpo) & 0xFFFFFFFF)


def _png(largura: int, altura: int, linhas: list[bytes], nivel: int = 6) -> bytes:
    bruto = b"".join(b"\x00" + l for l in linhas)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bruto, nivel))
        + _chunk(b"IEND", b"")
    )


def png_sintetico(cor: tuple[int, int, int] = (200, 60, 60), largura: int = 320, altura: int = 240) -> bytes:
    """Imagem de teste (degradê com listras): não contém nenhuma foto de pessoa."""
    linhas = []
    for y in range(altura):
        linha = bytearray()
        for x in range(largura):
            listra = 40 if ((x + y) // 24) % 2 == 0 else 0
            borda = 255 if x < 4 or y < 4 or x >= largura - 4 or y >= altura - 4 else 0
            linha += bytes(
                (
                    max(borda, min(255, cor[0] * x // largura + listra)),
                    max(borda, min(255, cor[1] * y // altura + listra)),
                    max(borda, min(255, cor[2] + listra)),
                )
            )
        linhas.append(bytes(linha))
    return _png(largura, altura, linhas)


def png_ruidoso(alvo_bytes: int) -> bytes:
    """PNG válido com ruído aleatório (não comprime), de tamanho aproximado `alvo_bytes`."""
    lado = max(8, int((alvo_bytes / 3) ** 0.5))
    return _png(lado, lado, [os.urandom(lado * 3) for _ in range(lado)], nivel=0)


@contextmanager
def etapa(titulo: str):
    """Agrupa a saída (colapsável no GitHub Actions)."""
    print(f"::group::{titulo}" if EM_CI else f"\n=== {titulo} ===", flush=True)
    try:
        yield
    finally:
        if EM_CI:
            print("::endgroup::", flush=True)


# ---------------------------------------------------------------- registro de verificações
@dataclass
class Checagem:
    req: str
    descricao: str
    ok: bool
    detalhe: str = ""


@dataclass
class Resultado:
    args: list[str]
    codigo: int
    saida: str
    exibicao: str
    segundos: float

    @property
    def ok(self) -> bool:
        return self.codigo == 0


@dataclass
class Resposta:
    status: int
    corpo: str
    saida: str

    @property
    def json(self):
        return json.loads(self.corpo)


class Evidencia:
    """Agrupa comandos executados em um único arquivo de evidência legendado."""

    def __init__(self, amb: "Ambiente", caminho: str, legenda: str) -> None:
        if "\n" in legenda:
            raise ValueError("a legenda deve ter uma linha")
        self.amb, self.caminho, self.legenda = amb, caminho, legenda
        self.blocos: list[tuple[str, str]] = []

    def __enter__(self) -> "Evidencia":
        print(f"\n--- {self.caminho}: {self.legenda}", flush=True)
        return self

    def __exit__(self, tipo, valor, tb) -> bool:
        if tipo is not None:
            self.nota(f"EXECUÇÃO INTERROMPIDA: {tipo.__name__}")
        self.amb.gravar_evidencia(self.caminho, self.legenda, self.blocos)
        return False

    def cmd(self, args: list[str], **kw) -> Resultado:
        return self.amb.rodar(args, ev=self, **kw)

    def nota(self, texto: str) -> None:
        self.blocos.append(("nota", texto))


# ---------------------------------------------------------------- ambiente de teste
class Ambiente:
    """Projeto Docker Compose ISOLADO usado pelos testes (nunca o ambiente real do usuário)."""

    def __init__(
        self,
        projeto: str,
        *,
        porta: int = 8080,
        porta_adminer: int = 8081,
        pasta_evid: Path | None = None,
    ) -> None:
        if projeto == PROJETO_REAL or not projeto.startswith(PROJETO_REAL + "-"):
            raise Falha(
                f"projeto de teste inválido: '{projeto}'. Use um nome que comece com "
                f"'{PROJETO_REAL}-' (ex.: {PROJETO_REAL}-evidencias) para nunca tocar no ambiente real."
            )
        self.projeto = projeto
        self.porta = porta
        self.porta_adminer = porta_adminer
        self.pasta_evid = pasta_evid
        self.tmp = Path(tempfile.mkdtemp(prefix="achados-"))
        self.checagens: list[Checagem] = []
        self.env = dict(os.environ)
        for chave in ("COMPOSE_FILE", "COMPOSE_PROFILES", "COMPOSE_PATH_SEPARATOR"):
            self.env.pop(chave, None)
        self.env.update({"COMPOSE_PROJECT_NAME": projeto, "BUILDKIT_PROGRESS": "plain", "NO_COLOR": "1"})
        self.segredos = [v for k, v in ler_env().items() if "PASSWORD" in k.upper() and len(v) >= 8]
        self.curl = shutil.which("curl.exe") or shutil.which("curl") or "curl"
        self.overrides: list[Path] = []
        self.notas_cabecalho: list[str] = []
        self.volumes_extras: list[str] = []  # volumes criados pelos testes fora do Compose (ex.: restauração de backup)

    # ---- comandos
    def dc(self, *args: str) -> list[str]:
        return ["docker", "compose", *args]

    def limpar(self, texto: str) -> str:
        """Remove cores ANSI, normaliza fim de linha e esconde a senha e os caminhos do computador."""
        texto = ANSI.sub("", texto).replace("\r\n", "\n").replace("\r", "\n")
        for segredo in self.segredos:
            texto = texto.replace(segredo, "********")
        home = str(Path.home())
        # caminhos: os mais específicos primeiro; no Windows a caixa das letras varia (c:\ x C:\)
        for origem, destino in ((str(self.tmp), "<tmp>"), (str(RAIZ), "<repo>"), (home, "~")):
            for variante in {origem, origem.replace("\\", "/")}:
                if variante:
                    texto = re.sub(re.escape(variante), lambda _m, d=destino: d, texto, flags=re.IGNORECASE)
        return texto

    def rodar(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        entrada: str | None = None,
        timeout: int = 900,
        check: bool = True,
        env_extra: dict[str, str] | None = None,
        ev: Evidencia | None = None,
        quieto: bool = False,
    ) -> Resultado:
        env = dict(self.env)
        env.update(env_extra or {})
        inicio = time.monotonic()
        try:
            p = subprocess.run(
                args,
                cwd=str(cwd or RAIZ),
                env=env,
                input=entrada,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            codigo, saida = p.returncode, p.stdout or ""
        except subprocess.TimeoutExpired as e:
            raise Falha(f"tempo esgotado ({timeout}s): {exibir(args)}") from e
        except FileNotFoundError as e:
            raise Falha(f"programa não encontrado: {args[0]}") from e
        dur = time.monotonic() - inicio
        saida_limpa = self.limpar(saida)
        # nas evidências o interpretador aparece como "python", sem o caminho do computador
        nomes = {sys.executable: "python", self.curl: Path(self.curl).name}
        exibicao = self.limpar(exibir([nomes.get(a, a) for a in args]))
        if not quieto:
            print(f"  $ {exibicao[:160]}  ({dur:.1f}s, código {codigo})", flush=True)
        r = Resultado(args, codigo, saida_limpa, exibicao, dur)
        if ev is not None:
            texto = f"$ {exibicao}\n{saida_limpa.rstrip()}\n"
            if codigo != 0:
                texto += f"[código de saída: {codigo}]\n"
            ev.blocos.append(("cmd", texto))
        if check and codigo != 0:
            raise Falha(f"comando falhou (código {codigo}): {exibicao}\n{saida_limpa[-2000:]}")
        return r

    # ---- HTTP (curl de verdade, como no roteiro do PDF)
    def url(self, caminho: str) -> str:
        return f"http://localhost:{self.porta}{caminho}"

    def http(
        self,
        ev: Evidencia | None,
        caminho: str,
        *,
        campos: dict[str, str] | None = None,
        arquivo: str | None = None,
        so_cabecalhos: bool = False,
        salvar_em: str | None = None,
    ) -> Resposta:
        """Executa curl com cwd=<tmp>; `arquivo` e `salvar_em` são nomes relativos a <tmp>."""
        args = [self.curl, "-s"]
        if so_cabecalhos:
            args.append("-I")
        elif salvar_em:
            args += ["-o", salvar_em, "-w", "HTTP %{http_code} tipo=%{content_type} bytes=%{size_download}\\n"]
        else:
            args += ["-w", "\\nHTTP %{http_code}\\n"]
        for chave, valor in (campos or {}).items():
            args += ["-F", f"{chave}={valor}"]
        if arquivo:
            args += ["-F", f"foto=@{arquivo}"]
        args.append(self.url(caminho))
        r = self.rodar(args, cwd=self.tmp, ev=ev, check=False)
        if so_cabecalhos:
            m = re.match(r"HTTP/\S+\s+(\d+)", r.saida)
            return Resposta(int(m.group(1)) if m else 0, r.saida, r.saida)
        if salvar_em:
            m = re.search(r"HTTP (\d+)", r.saida)
            return Resposta(int(m.group(1)) if m else 0, r.saida, r.saida)
        corpo, _, final = r.saida.rpartition("\nHTTP ")
        return Resposta(int(final.strip() or 0), corpo.strip(), r.saida)

    def status_silencioso(self, caminho: str, timeout: float = 3) -> int:
        """GET sem registrar nada (usado só para esperar o ambiente ficar pronto)."""
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.porta}{caminho}", timeout=timeout) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:  # noqa: BLE001
            return 0

    def esperar(self, condicao, descricao: str, timeout: int = 150, intervalo: float = 2) -> float:
        inicio = time.monotonic()
        while time.monotonic() - inicio < timeout:
            try:
                if condicao():
                    return time.monotonic() - inicio
            except Exception:  # noqa: BLE001
                pass
            time.sleep(intervalo)
        raise Falha(f"tempo esgotado esperando: {descricao}")

    # ---- estado do projeto
    def estado(self) -> dict[str, dict]:
        r = self.rodar(self.dc("ps", "-a", "--format", "json"), check=False, quieto=True)
        return {o.get("Service", "?"): o for o in json_linhas(r.saida)}

    def aguardar_pronto(self, servicos: tuple[str, ...] = ("db", "web", "nginx")) -> float:
        def pronto() -> bool:
            est = self.estado()
            for s in servicos:
                o = est.get(s)
                if not o or o.get("State") != "running" or o.get("Health") != "healthy":
                    return False
            return self.status_silencioso("/health") == 200

        return self.esperar(pronto, f"serviços {', '.join(servicos)} saudáveis e /health 200")

    def id_conteiner(self, servico: str) -> str:
        r = self.rodar(self.dc("ps", "-a", "-q", servico), check=False, quieto=True)
        return r.saida.strip().splitlines()[0] if r.saida.strip() else ""

    def recursos_existentes(self) -> list[str]:
        filtro = f"label=com.docker.compose.project={self.projeto}"
        achados = []
        for tipo, args in (
            ("contêiner", ["docker", "ps", "-a", "-q", "--filter", filtro]),
            ("volume", ["docker", "volume", "ls", "-q", "--filter", filtro]),
            ("rede", ["docker", "network", "ls", "-q", "--filter", filtro]),
        ):
            r = subprocess.run(args, capture_output=True, text=True, env=self.env)
            achados += [f"{tipo} {i}" for i in r.stdout.split()]
        return achados

    def configurar_portas(self) -> None:
        """Cria um override (fora do repositório) se as portas padrão estiverem ocupadas."""
        linhas = []
        if self.porta != 8080:
            linhas += ["  nginx:", "    ports: !override", f'      - "{self.porta}:80"']
            self.notas_cabecalho.append(
                f"Porta do host usada neste teste: {self.porta} (a 8080 estava ocupada por outro programa nesta máquina; "
                "o docker-compose.yml entregue publica 8080 e foi executado sem alterações, apenas com override de porta)."
            )
        if self.porta_adminer != 8081:
            linhas += ["  adminer:", "    ports: !override", f'      - "127.0.0.1:{self.porta_adminer}:8080"']
            self.notas_cabecalho.append(f"Porta do Adminer usada neste teste: {self.porta_adminer} (a 8081 estava ocupada).")
        if linhas:
            self.adicionar_override("override-portas.yml", "services:\n" + "\n".join(linhas) + "\n")

    def adicionar_override(self, nome: str, conteudo: str) -> Path:
        """Acrescenta um arquivo de override ao COMPOSE_FILE (arquivo temporário, fora do repositório)."""
        caminho = self.tmp / nome
        caminho.write_text(conteudo, encoding="utf-8", newline="\n")
        self.overrides.append(caminho)
        self._atualizar_compose_file()
        return caminho

    def remover_override(self, caminho: Path) -> None:
        self.overrides = [o for o in self.overrides if o != caminho]
        self._atualizar_compose_file()

    def _atualizar_compose_file(self) -> None:
        if self.overrides:
            self.env["COMPOSE_FILE"] = os.pathsep.join(["docker-compose.yml", *map(str, self.overrides)])
        else:
            self.env.pop("COMPOSE_FILE", None)

    # ---- verificações
    def checar(self, req: str, descricao: str, ok: bool, detalhe: str = "") -> bool:
        self.checagens.append(Checagem(req, descricao, bool(ok), detalhe))
        print(f"  [{'OK' if ok else 'FALHOU'}] {req}: {descricao}" + (f" -> {detalhe}" if detalhe and not ok else ""), flush=True)
        if EM_CI and not ok:
            print(f"::error title={req}::{descricao} {detalhe}".replace("\n", " "))
        return bool(ok)

    # ---- evidências
    def evidencia(self, caminho: str, legenda: str) -> Evidencia:
        return Evidencia(self, caminho, legenda)

    def gravar_evidencia(self, caminho: str, legenda: str, blocos: list[tuple[str, str]]) -> None:
        if self.pasta_evid is None:
            return
        destino = self.pasta_evid / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        cab = [f"# Legenda: {legenda}", f"# Gerado em: {agora()} | Projeto Compose: {self.projeto}"]
        cab += [f"# Nota: {n}" for n in self.notas_cabecalho]
        corpo = []
        for tipo, texto in blocos:
            if tipo == "nota":
                corpo.append("\n".join("# " + l for l in self.limpar(texto).splitlines()) + "\n")
            else:
                corpo.append(texto)
        conteudo = "\n".join(cab) + "\n\n" + "\n".join(corpo)
        destino.write_text(conteudo, encoding="utf-8", newline="\n")

    # ---- encerramento
    def derrubar(self, *, volumes: bool = True, imagens: bool = True) -> None:
        """Remove SOMENTE o projeto isolado deste objeto."""
        args = self.dc("--profile", "*", "down", "--remove-orphans")
        if volumes:
            args.append("-v")
        if imagens:
            args += ["--rmi", "local"]
        self.rodar(args, check=False, timeout=300)
        for volume in self.volumes_extras:
            self.rodar(["docker", "volume", "rm", "-f", volume], check=False)

    def limpar_anterior(self) -> None:
        sobras = self.recursos_existentes()
        if sobras:
            print(f"  (!) sobras de uma execução anterior do projeto '{self.projeto}': removendo ({len(sobras)} recursos)")
            self.derrubar()

    def encerrar(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- saída: índice, resumo, varredura
def legenda_de(caminho: Path) -> str:
    try:
        primeira = caminho.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError, UnicodeDecodeError):
        return ""
    return primeira.removeprefix("# Legenda:").strip() if primeira.startswith("# Legenda:") else ""


def gerar_indice(pasta: Path) -> None:
    """Gera docs/evidencias/README.md a partir da legenda (1ª linha) de cada arquivo .txt."""
    linhas = [
        "# Evidências",
        "",
        f"Saídas **reais** dos comandos executados pelos scripts [`testar_ambiente.py`]({URL_REPO}/blob/main/scripts/testar_ambiente.py) e",
        f"[`experimentos_reflexao.py`]({URL_REPO}/blob/main/scripts/experimentos_reflexao.py). Cada arquivo começa com uma legenda de uma linha;",
        "este índice é gerado automaticamente a partir delas. Contexto da execução (versões, portas, hashes dos arquivos): "
        "[`00-ambiente.txt`](00-ambiente.txt). Resultado de cada verificação: [`resumo-testes.md`](resumo-testes.md).",
        "",
        "> Para regenerar: `python scripts/testar_ambiente.py --evidencias docs/evidencias` e "
        "`python scripts/experimentos_reflexao.py --evidencias docs/evidencias` (veja o README).",
        "",
    ]
    por_pasta: dict[str, list[Path]] = {}
    for arq in sorted(pasta.rglob("*.txt")):
        rel = arq.relative_to(pasta)
        por_pasta.setdefault(str(rel.parent) if str(rel.parent) != "." else "", []).append(arq)
    for nome_pasta, arquivos in por_pasta.items():
        linhas += [f"## {nome_pasta or 'Geral'}", "", "| Arquivo | O que demonstra |", "|---|---|"]
        for arq in arquivos:
            rel = arq.relative_to(pasta).as_posix()
            extra = ""
            png = arq.with_suffix(".png")
            if png.exists():
                extra = f" ([captura]({png.relative_to(pasta).as_posix()}))"
            linhas.append(f"| [`{rel}`]({rel}) | {legenda_de(arq) or '—'}{extra} |")
        linhas.append("")
    (pasta / "README.md").write_text("\n".join(linhas), encoding="utf-8", newline="\n")


def escrever_resumo(destino: Path, titulo: str, checagens: list[Checagem], rodape: str = "") -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    ok = sum(c.ok for c in checagens)
    linhas = [
        f"# {titulo}",
        "",
        f"Gerado em {agora()} — **{ok}/{len(checagens)} verificações aprovadas**.",
        "",
        "| Requisito | Verificação | Resultado |",
        "|---|---|---|",
    ]
    for c in checagens:
        detalhe = f" — {c.detalhe}" if c.detalhe else ""
        linhas.append(f"| {c.req} | {c.descricao}{detalhe} | {'✅ passou' if c.ok else '❌ FALHOU'} |".replace("\n", " "))
    if rodape:
        linhas += ["", rodape]
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")


def resumo_ci(titulo: str, checagens: list[Checagem]) -> None:
    arq = os.getenv("GITHUB_STEP_SUMMARY")
    if not arq:
        return
    ok = sum(c.ok for c in checagens)
    with open(arq, "a", encoding="utf-8") as f:
        f.write(f"### {titulo}: {ok}/{len(checagens)} verificações aprovadas\n\n| Requisito | Verificação | |\n|---|---|---|\n")
        for c in checagens:
            f.write(f"| {c.req} | {c.descricao} | {'✅' if c.ok else '❌'} |\n")
        f.write("\n")


def varrer_vazamentos(pasta: Path, segredos: list[str]) -> list[str]:
    """Procura senha do .env e caminhos do computador do autor nos arquivos de texto gerados."""
    termos = [(s, "senha do .env") for s in segredos]
    home = str(Path.home())
    termos += [(home, "diretório do usuário"), (home.replace("\\", "/"), "diretório do usuário")]
    usuario = Path.home().name
    if len(usuario) >= 4:
        termos.append((usuario, "nome de usuário do computador"))
    problemas = []
    for arq in pasta.rglob("*"):
        if arq.is_file() and arq.suffix.lower() in {".txt", ".md", ".json", ".yml"}:
            texto = arq.read_text(encoding="utf-8", errors="replace")
            for termo, motivo in termos:
                if termo and termo in texto:
                    problemas.append(f"{arq.relative_to(pasta)}: contém {motivo}")
    return problemas


def info_ambiente() -> list[str]:
    def saida(args: list[str]) -> str:
        try:
            return subprocess.run(args, capture_output=True, text=True, cwd=RAIZ, timeout=30).stdout.strip()
        except Exception:  # noqa: BLE001
            return "(indisponível)"

    linhas = [
        f"Data: {agora()}",
        f"Sistema: {platform.platform()}",
        f"Python (scripts): {platform.python_version()}",
        f"Git: {saida(['git', '--version'])}",
        f"Docker: {saida(['docker', 'version', '--format', 'cliente {{.Client.Version}} / servidor {{.Server.Version}}'])}",
        f"Docker Compose: {saida(['docker', 'compose', 'version', '--short'])}",
        f"Commit (HEAD): {saida(['git', 'rev-parse', '--short', 'HEAD']) or '(sem commits)'}",
    ]
    sujo = saida(["git", "status", "--porcelain", "--", *ARQUIVOS_INFRA])
    linhas.append("Arquivos de infraestrutura modificados em relação ao HEAD: " + ("nenhum" if not sujo else "SIM (ver hashes)"))
    linhas += ["", "SHA-256 dos arquivos de infraestrutura (fim de linha normalizado para LF):"]
    for rel in ARQUIVOS_INFRA:
        arq = RAIZ / rel
        linhas.append(f"  {sha256_arquivo(arq, normalizar_eol=True) if arq.exists() else '(ausente)':64}  {rel}")
    return linhas
