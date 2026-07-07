"""Portal da Transparência (Controladoria-Geral da União).

API oficial: https://api.portaldatransparencia.gov.br/swagger-ui/
Requer chave gratuita (cadastro por e-mail) no header ``chave-api-dados``,
exposta aqui via variável de ambiente TRANSPARENCIA_API_KEY.
"""

from __future__ import annotations

import os

from .base import ClienteBase


class PortalTransparencia(ClienteBase):
    base_url = "https://api.portaldatransparencia.gov.br/api-de-dados"

    def __init__(self, chave: str | None = None):
        chave = chave or os.environ.get("TRANSPARENCIA_API_KEY", "")
        super().__init__(cabecalhos={"chave-api-dados": chave})

    def servidores_por_nome(self, nome: str, pagina: int = 1) -> list[dict]:
        """Vínculos de servidores do Executivo federal (busca textual)."""
        return self.get_json("/servidores", nome=nome, pagina=pagina)

    def contratos_por_cnpj(self, cnpj: str, pagina: int = 1) -> list[dict]:
        """Contratos federais firmados com o CNPJ contratado."""
        return self.get_json(
            "/contratos/cpf-cnpj", cpfCnpj=_somente_digitos(cnpj), pagina=pagina
        )

    def licitacoes(self, codigo_orgao: str, data_inicial: str, data_final: str,
                   pagina: int = 1) -> list[dict]:
        """Licitações de um órgão (datas em dd/mm/aaaa)."""
        return self.get_json(
            "/licitacoes",
            codigoOrgao=codigo_orgao,
            dataInicial=data_inicial,
            dataFinal=data_final,
            pagina=pagina,
        )

    def emendas(self, nome_autor: str | None = None, ano: int | None = None,
                pagina: int = 1) -> list[dict]:
        """Emendas parlamentares por autor e/ou ano."""
        params: dict = {"pagina": pagina}
        if nome_autor:
            params["nomeAutor"] = nome_autor
        if ano:
            params["ano"] = ano
        return self.get_json("/emendas", **params)

    def sancoes_ceis(self, cnpj: str, pagina: int = 1) -> list[dict]:
        """Empresas inidôneas/suspensas (CEIS) para o CNPJ."""
        return self.get_json(
            "/ceis", cnpjSancionado=_somente_digitos(cnpj), pagina=pagina
        )

    def beneficios_por_cpf(self, cpf_mascarado: str, pagina: int = 1) -> list[dict]:
        """Benefícios sociais recebidos (CPF já vem mascarado da própria API)."""
        return self.get_json(
            "/bolsa-familia-disponivel-por-cpf-ou-nis",
            codigo=cpf_mascarado,
            pagina=pagina,
        )


def _somente_digitos(valor: str) -> str:
    return "".join(c for c in valor if c.isdigit())
