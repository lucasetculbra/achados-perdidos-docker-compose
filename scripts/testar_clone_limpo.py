#!/usr/bin/env python3
"""Repete os testes completos em um CLONE LIMPO do repositório.

Prova o primeiro item do checklist de entrega: "docker compose up -d --build funciona em uma
pasta recém-clonada, após copiar .env.example para .env". O script:

  1. confere que não há alterações não commitadas (o clone só contém o que está no Git);
  2. clona o repositório em uma pasta temporária e confirma que o clone NÃO tem .env;
  3. copia .env.example para .env (senha fictícia do modelo);
  4. roda, DENTRO do clone, scripts/testar_ambiente.py (projeto isolado achados-perdidos-clone)
     e scripts/verificar_config.py --final;
  5. grava a saída real em docs/evidencias/clone-limpo.txt.

    python scripts/testar_clone_limpo.py [--porta 18080] [--porta-adminer 18081]
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path

from comum import RAIZ, Ambiente, Falha, agora, configurar_saida, gerar_indice

PROJETO = "achados-perdidos-clone"


def apagar(caminho: Path) -> None:
    """rmtree que também remove os arquivos somente leitura do .git (Windows)."""

    def tratar(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    shutil.rmtree(caminho, onerror=tratar)


def main() -> int:
    configurar_saida()
    ap = argparse.ArgumentParser(description="Roda os testes em um clone recém-feito do repositório.")
    ap.add_argument("--porta", type=int, default=8080, help="porta do host do nginx (padrão: 8080)")
    ap.add_argument("--porta-adminer", type=int, default=8081)
    ap.add_argument("--permitir-sujo", action="store_true", help="não exige que a árvore de trabalho esteja commitada")
    ap.add_argument("--sem-evidencia", action="store_true", help="não grava docs/evidencias/clone-limpo.txt")
    args = ap.parse_args()

    amb = Ambiente(PROJETO, porta=args.porta, porta_adminer=args.porta_adminer)
    blocos: list[str] = []

    def passo(texto: str) -> None:
        blocos.append(amb.limpar(texto).rstrip() + "\n")

    try:
        sujo = amb.rodar(["git", "status", "--porcelain", "--untracked-files=no"], check=True, quieto=True).saida.strip()
        if sujo and not args.permitir_sujo:
            raise Falha("há alterações não commitadas em arquivos versionados; o clone não as contém. Faça o commit ou use --permitir-sujo.\n" + sujo)
        clone = amb.tmp / RAIZ.name
        r = amb.rodar(["git", "clone", "--quiet", "--no-hardlinks", str(RAIZ), str(clone)])
        commit = amb.rodar(["git", "rev-parse", "HEAD"], cwd=clone, quieto=True).saida.strip()
        passo(f"$ {r.exibicao}\n(clonado o commit {commit})")
        tem_env = (clone / ".env").exists()
        passo(f"# O clone recém-feito contém um arquivo .env? {'SIM (inesperado)' if tem_env else 'não (o .env nunca é versionado)'}")
        if tem_env:
            raise Falha("o clone contém .env: o arquivo está versionado!")
        shutil.copyfile(clone / ".env.example", clone / ".env")
        passo("$ cp .env.example .env      # feito pelo script de teste\n# (valores fictícios do modelo; a senha é a do .env.example)")

        teste = amb.rodar(
            [sys.executable, "scripts/testar_ambiente.py", "--projeto", PROJETO, "--porta", str(args.porta), "--porta-adminer", str(args.porta_adminer), "--evidencias", str(amb.tmp / "evidencias-do-clone")],
            cwd=clone, check=False, timeout=3000,
        )
        passo(f"$ {teste.exibicao}\n{teste.saida}")
        verif = amb.rodar([sys.executable, "scripts/verificar_config.py", "--final"], cwd=clone, check=False, timeout=600)
        passo(f"$ {verif.exibicao}\n{verif.saida}")
        ok = teste.ok and verif.ok
        passo(f"# Resultado: testar_ambiente.py -> código {teste.codigo}; verificar_config.py --final -> código {verif.codigo}")
    except Falha as e:
        print(f"\nERRO: {e}", file=sys.stderr)
        ok = False
        passo(f"# ERRO: {e}")
    finally:
        amb.derrubar()
        try:
            apagar(amb.tmp)
        except OSError:
            pass

    if not args.sem_evidencia:
        destino = RAIZ / "docs/evidencias/clone-limpo.txt"
        cabecalho = (
            "# Legenda: Os testes completos repetidos em um clone recém-feito do repositório, depois de cp .env.example .env: o ambiente sobe e passa só com o que está no Git.\n"
            f"# Gerado em: {agora()} | Projeto Compose: {PROJETO}\n"
        )
        if args.porta != 8080:
            cabecalho += f"# Nota: porta do host usada neste teste: {args.porta} (a 8080 estava ocupada por outro programa nesta máquina).\n"
        destino.write_text(cabecalho + "\n" + "\n".join(blocos), encoding="utf-8", newline="\n")
        gerar_indice(RAIZ / "docs/evidencias")
        print(f"\nevidência gravada em {destino.relative_to(RAIZ)}")
    print("RESULTADO:", "OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
