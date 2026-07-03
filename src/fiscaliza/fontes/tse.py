"""TSE — Dados Abertos (CKAN) e DivulgaCandContas.

Candidaturas, bens declarados e doações de campanha. Os conjuntos anuais são
CSVs zipados no CKAN; o DivulgaCand tem API JSON não documentada porém pública.
"""

from __future__ import annotations

from .base import ClienteBase


class TSE(ClienteBase):
    base_url = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1"
    CKAN = "https://dadosabertos.tse.jus.br/api/3/action"

    def candidatos(self, ano: int, sigla_uf: str, codigo_cargo: int,
                   codigo_eleicao: str) -> dict:
        """Lista de candidatos por eleição/UF/cargo (DivulgaCand)."""
        return self.get_json(
            f"/candidatura/listar/{ano}/{sigla_uf}/{codigo_eleicao}/{codigo_cargo}/candidatos"
        )

    def candidato(self, ano: int, sigla_uf: str, codigo_eleicao: str,
                  id_candidato: int) -> dict:
        """Detalhe do candidato: bens declarados, partido, situação."""
        return self.get_json(
            f"/candidatura/buscar/{ano}/{sigla_uf}/{codigo_eleicao}/candidato/{id_candidato}"
        )

    def conjuntos_ckan(self, consulta: str) -> dict:
        """Busca conjuntos de dados no CKAN (ex.: 'prestacao de contas 2024')."""
        import httpx

        resposta = httpx.get(
            f"{self.CKAN}/package_search", params={"q": consulta}, timeout=60
        )
        resposta.raise_for_status()
        return resposta.json()
