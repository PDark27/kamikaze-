"""TSE — Dados Abertos (CKAN) e DivulgaCandContas.

Candidaturas, bens declarados, doações de campanha, foto oficial da urna e
nomes (civil completo e de urna). Os conjuntos anuais são CSVs zipados no
CKAN; o DivulgaCand tem API JSON não documentada porém pública.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path


from .base import ClienteBase

# Códigos de eleição ordinária mais recentes no DivulgaCand
CODIGOS_ELEICAO = {2024: "2045202024", 2022: "2040602022", 2020: "2030402020"}

# Códigos de cargo do TSE
CARGOS = {
    "presidente": 1, "governador": 3, "senador": 5,
    "deputado_federal": 6, "deputado_estadual": 7, "deputado_distrital": 8,
    "prefeito": 11, "vereador": 13,
}


def _normalizar(texto: str) -> str:
    """Caixa alta e sem acentos, para comparação tolerante de nomes."""
    sem_acentos = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acentos if not unicodedata.combining(c)).upper().strip()


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
        """Detalhe do candidato: bens declarados, partido, situação, foto."""
        return self.get_json(
            f"/candidatura/buscar/{ano}/{sigla_uf}/{codigo_eleicao}/candidato/{id_candidato}"
        )

    # ------------------------------------------------------------------ #
    # Busca amigável: por nome de urna OU nome civil completo
    # ------------------------------------------------------------------ #

    def buscar_candidato(self, ano: int, sigla_uf: str, nome: str,
                         codigo_cargo: int,
                         codigo_eleicao: str | None = None) -> dict | None:
        """Encontra um candidato pelo nome de urna ou pelo nome civil completo
        (comparação sem acentos/caixa) e devolve o detalhe completo."""
        codigo_eleicao = codigo_eleicao or CODIGOS_ELEICAO.get(ano)
        if not codigo_eleicao:
            raise ValueError(
                f"Sem código de eleição conhecido para {ano}; informe codigo_eleicao."
            )
        alvo = _normalizar(nome)
        lista = self.candidatos(ano, sigla_uf, codigo_cargo, codigo_eleicao)
        for cand in lista.get("candidatos", []):
            nomes = {
                _normalizar(cand.get("nomeUrna") or cand.get("nomeUrnaCandidato") or ""),
                _normalizar(cand.get("nomeCompleto") or cand.get("nome") or ""),
            }
            if alvo in nomes or any(alvo in n for n in nomes if n):
                return self.candidato(ano, sigla_uf, codigo_eleicao, cand["id"])
        return None

    @staticmethod
    def identidade(detalhe: dict) -> dict:
        """Normaliza os campos de identificação do candidato, tolerando as
        variações de nome de campo entre eleições."""
        return {
            "nome_completo": detalhe.get("nomeCompleto") or detalhe.get("nome"),
            "nome_urna": detalhe.get("nomeUrna") or detalhe.get("nomeUrnaCandidato"),
            "numero": detalhe.get("numero") or detalhe.get("numeroCandidato"),
            "partido": (detalhe.get("partido") or {}).get("sigla")
            if isinstance(detalhe.get("partido"), dict) else detalhe.get("partido"),
            "cargo": (detalhe.get("cargo") or {}).get("nome")
            if isinstance(detalhe.get("cargo"), dict) else detalhe.get("cargo"),
            "sqcand": detalhe.get("id") or detalhe.get("sqCandidato"),
            "foto_url": TSE.foto_url(detalhe),
        }

    # ------------------------------------------------------------------ #
    # Foto oficial da urna
    # ------------------------------------------------------------------ #

    @staticmethod
    def foto_url(detalhe: dict) -> str | None:
        """Extrai a URL da foto oficial do JSON de detalhe do candidato."""
        return detalhe.get("fotoUrl") or detalhe.get("foto_url") or None

    def baixar_foto(self, detalhe: dict, destino: str | Path = "fotos") -> Path | None:
        """Baixa a foto oficial para fotos/<ano>/<sqcand>.jpg (com cache)."""
        url = self.foto_url(detalhe)
        sqcand = detalhe.get("id") or detalhe.get("sqCandidato")
        if not url or not sqcand:
            return None
        ano = detalhe.get("eleicao", {}).get("ano") or detalhe.get("ano") or "geral"
        caminho = Path(destino) / str(ano) / f"{sqcand}.jpg"
        if caminho.exists():
            return caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        resposta = self._http.get(url, follow_redirects=True, timeout=60)
        resposta.raise_for_status()
        caminho.write_bytes(resposta.content)
        return caminho

    # ------------------------------------------------------------------ #

    def conjuntos_ckan(self, consulta: str) -> dict:
        """Busca conjuntos de dados no CKAN (ex.: 'fotos dos candidatos 2024')."""
        import httpx

        resposta = httpx.get(
            f"{self.CKAN}/package_search", params={"q": consulta}, timeout=60
        )
        resposta.raise_for_status()
        return resposta.json()
