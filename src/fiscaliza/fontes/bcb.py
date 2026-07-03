"""Banco Central — SGS (séries temporais) para deflacionar valores históricos."""

from __future__ import annotations

from .base import ClienteBase


class BancoCentral(ClienteBase):
    base_url = "https://api.bcb.gov.br"
    SERIE_IPCA = 433  # IPCA variação mensal (%)

    def serie(self, codigo: int, data_inicial: str, data_final: str) -> list[dict]:
        """Série SGS (datas em dd/MM/aaaa)."""
        return self.get_json(
            f"/dados/serie/bcdata.sgs.{codigo}/dados",
            formato="json",
            dataInicial=data_inicial,
            dataFinal=data_final,
        )

    def fator_ipca(self, data_inicial: str, data_final: str) -> float:
        """Fator acumulado de inflação entre duas datas (p/ comparar patrimônios)."""
        fator = 1.0
        for ponto in self.serie(self.SERIE_IPCA, data_inicial, data_final):
            fator *= 1 + float(ponto["valor"]) / 100
        return fator
