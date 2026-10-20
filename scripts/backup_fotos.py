#!/usr/bin/env python3
"""Backup e restauração do volume de fotos (bônus B), usando contêineres temporários.

O volume nunca é montado no host: um contêiner `alpine` descartável (`docker run --rm`)
monta o volume e uma pasta do host e roda o `tar` dentro dele. Funciona igual no
Windows, Linux e macOS.

Exemplos (o nome do volume é "<projeto>_fotos"; o projeto padrão é "achados-perdidos"):

    python scripts/backup_fotos.py backup
    python scripts/backup_fotos.py backup --volume achados-perdidos_fotos --saida backups
    python scripts/backup_fotos.py restaurar --arquivo backups/fotos-20261019-231500.tar.gz
    python scripts/backup_fotos.py restaurar --arquivo backups/fotos-....tar.gz --volume-destino fotos_novo

ATENÇÃO: os backups contêm as fotos enviadas pelos usuários (podem mostrar documentos
pessoais). A pasta "backups/" e os arquivos *.tar.gz estão no .gitignore: não os versione.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

IMAGEM_AUXILIAR = "alpine:3.24"
VOLUME_PADRAO = "achados-perdidos_fotos"


def docker(*args: str, capturar: bool = False) -> subprocess.CompletedProcess:
    print("$ docker " + " ".join(f'"{a}"' if " " in a else a for a in args), flush=True)
    return subprocess.run(
        ["docker", *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capturar else None,
        stderr=subprocess.STDOUT if capturar else None,
    )


def volume_existe(nome: str) -> bool:
    return subprocess.run(["docker", "volume", "inspect", nome], capture_output=True).returncode == 0


def backup(volume: str, pasta: Path) -> int:
    if not volume_existe(volume):
        print(f"erro: o volume '{volume}' não existe (docker volume ls).", file=sys.stderr)
        return 1
    pasta = pasta.resolve()
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = f"fotos-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    r = docker(
        "run", "--rm",
        "--mount", f"type=volume,source={volume},target=/origem,readonly",  # volume só para leitura
        "--mount", f"type=bind,source={pasta},target=/backup",
        IMAGEM_AUXILIAR,
        "tar", "czf", f"/backup/{arquivo}", "-C", "/origem", ".",
    )
    if r.returncode != 0:
        return r.returncode
    destino = pasta / arquivo
    print(f"\nbackup criado: {destino} ({destino.stat().st_size} bytes)")
    print("conteúdo do arquivo:")
    docker(
        "run", "--rm",
        "--mount", f"type=bind,source={pasta},target=/backup,readonly",
        IMAGEM_AUXILIAR,
        "tar", "tzvf", f"/backup/{arquivo}",
    )
    return 0


def restaurar(arquivo: Path, volume_destino: str, forcar: bool) -> int:
    arquivo = arquivo.resolve()
    if not arquivo.is_file():
        print(f"erro: arquivo de backup não encontrado: {arquivo}", file=sys.stderr)
        return 1
    if volume_existe(volume_destino) and not forcar:
        print(
            f"erro: o volume '{volume_destino}' já existe. Restaurar por cima de dados existentes pode misturar "
            "arquivos; use um nome novo em --volume-destino (recomendado) ou --forcar.",
            file=sys.stderr,
        )
        return 1
    r = docker("volume", "create", volume_destino)
    if r.returncode != 0:
        return r.returncode
    r = docker(
        "run", "--rm",
        "--mount", f"type=volume,source={volume_destino},target=/destino",
        "--mount", f"type=bind,source={arquivo.parent},target=/backup,readonly",
        IMAGEM_AUXILIAR,
        "tar", "xzf", f"/backup/{arquivo.name}", "-C", "/destino",
    )
    if r.returncode != 0:
        return r.returncode
    print(f"\nrestaurado no volume '{volume_destino}'. Conteúdo (com dono numérico):")
    docker(
        "run", "--rm",
        "--mount", f"type=volume,source={volume_destino},target=/destino,readonly",
        IMAGEM_AUXILIAR,
        "ls", "-ln", "/destino",
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup/restauração do volume de fotos com contêiner temporário.")
    sub = ap.add_subparsers(dest="comando", required=True)

    b = sub.add_parser("backup", help="gera um arquivo .tar.gz com o conteúdo do volume")
    b.add_argument("--volume", default=VOLUME_PADRAO, help=f"volume de origem (padrão: {VOLUME_PADRAO})")
    b.add_argument("--saida", type=Path, default=Path("backups"), help="pasta do host onde salvar (padrão: backups/)")

    r = sub.add_parser("restaurar", help="restaura um .tar.gz em um volume NOVO")
    r.add_argument("--arquivo", type=Path, required=True, help="arquivo .tar.gz gerado pelo comando backup")
    r.add_argument("--volume-destino", default="achados-perdidos_fotos_restaurado", help="nome do volume a criar")
    r.add_argument("--forcar", action="store_true", help="permite usar um volume que já existe")

    args = ap.parse_args()
    if args.comando == "backup":
        return backup(args.volume, args.saida)
    return restaurar(args.arquivo, args.volume_destino, args.forcar)


if __name__ == "__main__":
    sys.exit(main())
