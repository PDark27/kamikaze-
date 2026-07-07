"""Carrega os parâmetros de risco de config/parametros_risco.yaml.

Ordem de busca do arquivo (primeiro que existir):
1. caminho passado explicitamente à função;
2. variável de ambiente FISCALIZA_PARAMETROS;
3. config/ relativo à árvore do código-fonte (instalação editável);
4. config/ relativo ao diretório de trabalho atual (instalação normal via
   pip/Docker, onde o código vai para site-packages mas o config/ é copiado
   junto da aplicação, como no Dockerfile deste projeto).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_RELATIVO_FONTE = Path(__file__).resolve().parents[2] / "config" / "parametros_risco.yaml"
_RELATIVO_CWD = Path("config") / "parametros_risco.yaml"


def _localizar() -> Path:
    ambiente = os.environ.get("FISCALIZA_PARAMETROS")
    candidatos = [Path(ambiente)] if ambiente else []
    candidatos += [_RELATIVO_FONTE, _RELATIVO_CWD.resolve()]
    for candidato in candidatos:
        if candidato.exists():
            return candidato
    raise FileNotFoundError(
        "parametros_risco.yaml não encontrado. Defina FISCALIZA_PARAMETROS "
        f"ou coloque o arquivo em ./config/. Caminhos tentados: "
        f"{[str(c) for c in candidatos]}"
    )


def carregar_parametros(caminho: str | Path | None = None) -> dict:
    caminho = Path(caminho) if caminho else _localizar()
    with open(caminho, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def faixa_de_risco(indice: float, parametros: dict) -> str:
    for faixa in parametros["escala"]["faixas"]:
        if indice <= faixa["ate"]:
            return faixa["rotulo"]
    return parametros["escala"]["faixas"][-1]["rotulo"]
