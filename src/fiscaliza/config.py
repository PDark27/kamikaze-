"""Carrega os parâmetros de risco de config/parametros_risco.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_DEFAULT = Path(__file__).resolve().parents[2] / "config" / "parametros_risco.yaml"


def carregar_parametros(caminho: str | Path | None = None) -> dict:
    caminho = Path(caminho or os.environ.get("FISCALIZA_PARAMETROS", _DEFAULT))
    with open(caminho, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def faixa_de_risco(indice: float, parametros: dict) -> str:
    for faixa in parametros["escala"]["faixas"]:
        if indice <= faixa["ate"]:
            return faixa["rotulo"]
    return parametros["escala"]["faixas"][-1]["rotulo"]
