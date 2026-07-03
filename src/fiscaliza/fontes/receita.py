"""Receita Federal — cadastro público de CNPJ.

Usa a API aberta minhareceita.org (espelho dos dados abertos de CNPJ da RFB).
Para volume alto, baixe os dumps oficiais em
https://arquivos.receitafederal.gov.br/dados/cnpj/ e carregue localmente.
"""

from __future__ import annotations

from datetime import date

from .base import ClienteBase


class ReceitaCNPJ(ClienteBase):
    base_url = "https://minhareceita.org"

    def empresa(self, cnpj: str) -> dict:
        digitos = "".join(c for c in cnpj if c.isdigit())
        return self.get_json(f"/{digitos}")

    def socios(self, cnpj: str) -> list[dict]:
        return self.empresa(cnpj).get("qsa") or []

    def idade_em_dias(self, cnpj: str) -> int | None:
        dados = self.empresa(cnpj)
        inicio = dados.get("data_inicio_atividade")
        if not inicio:
            return None
        return (date.today() - date.fromisoformat(inicio)).days
