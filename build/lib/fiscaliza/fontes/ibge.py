"""IBGE — localidades e agregados (população/PIB para gasto per-capita)."""

from __future__ import annotations

from .base import ClienteBase


class IBGE(ClienteBase):
    base_url = "https://servicodados.ibge.gov.br/api"

    def municipio(self, codigo_ibge: str) -> dict:
        return self.get_json(f"/v1/localidades/municipios/{codigo_ibge}")

    def populacao(self, codigo_ibge: str) -> int | None:
        """População estimada mais recente (agregado 6579)."""
        dados = self.get_json(
            f"/v3/agregados/6579/periodos/-1/variaveis/9324",
            localidades=f"N6[{codigo_ibge}]",
        )
        try:
            series = dados[0]["resultados"][0]["series"][0]["serie"]
            return int(next(iter(series.values())))
        except (KeyError, IndexError, StopIteration, ValueError):
            return None
