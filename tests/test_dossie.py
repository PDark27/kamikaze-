"""Testes de fiscaliza.dossie — sem rede, fakes simples (estilo de
test_tse_foto.py/test_risco.py: classes stub, sem herdar ClienteBase)."""

from pathlib import Path

from fiscaliza.dossie import dossie_para_markdown, montar_dossie
from fiscaliza.risco import MotorDeRisco

DETALHE = {
    "id": 250001609124,
    "nomeCompleto": "JOSÉ DA SILVA EXEMPLO",
    "nomeUrna": "ZÉ EXEMPLO",
    "numero": 12345,
    "partido": {"sigla": "XYZ"},
    "cargo": {"nome": "Vereador"},
    "fotoUrl": "https://divulgacandcontas.tse.jus.br/fotos/F123.jpg",
    "eleicao": {"ano": 2024},
    "bens": [{"valor": 100000.0}],
    "bens_eleicao_anterior": [{"valor": 40000.0}],
}

CNPJ_HOMONIMO = "00000000000191"
CNPJ_SEM_ACHADO = "11111111000191"


class TSEFake:
    def __init__(self, detalhe=DETALHE, foto=None, erro_busca=None, erro_foto=None):
        self._detalhe = detalhe
        self._foto = foto
        self._erro_busca = erro_busca
        self._erro_foto = erro_foto

    def buscar_candidato(self, ano, uf, nome, cargo, codigo_eleicao=None):
        if self._erro_busca:
            raise self._erro_busca
        return self._detalhe

    def identidade(self, detalhe):
        from fiscaliza.fontes.tse import TSE

        return TSE.identidade(detalhe)

    def baixar_foto(self, detalhe):
        if self._erro_foto:
            raise self._erro_foto
        return self._foto


class ReceitaFake:
    def __init__(self, socios_por_cnpj=None, erro=None):
        self._socios_por_cnpj = socios_por_cnpj or {}
        self._erro = erro

    def socios(self, cnpj):
        if self._erro:
            raise self._erro
        return self._socios_por_cnpj.get(cnpj, [])


class PortalFake:
    def __init__(self, contratos_por_cnpj=None, erro_contratos=None, erro_sancoes=None):
        self._contratos_por_cnpj = contratos_por_cnpj or {}
        self._erro_contratos = erro_contratos
        self._erro_sancoes = erro_sancoes

    def contratos_por_cnpj(self, cnpj):
        if self._erro_contratos:
            raise self._erro_contratos
        return self._contratos_por_cnpj.get(cnpj, [])

    def sancoes_ceis(self, cnpj):
        if self._erro_sancoes:
            raise self._erro_sancoes
        return []


class BCBFake:
    def __init__(self, fator=1.1, erro=None):
        self._fator = fator
        self._erro = erro

    def fator_ipca(self, data_inicial, data_final):
        if self._erro:
            raise self._erro
        return self._fator


def _fontes_completas():
    tse = TSEFake()
    receita = ReceitaFake(
        socios_por_cnpj={
            CNPJ_HOMONIMO: [{"nome_socio": "José da Silva Exemplo"}],
            CNPJ_SEM_ACHADO: [{"nome_socio": "Outra Pessoa Qualquer"}],
        }
    )
    portal = PortalFake(
        contratos_por_cnpj={
            CNPJ_HOMONIMO: [
                {
                    "data_abertura_empresa": "2026-01-10",
                    "data_contrato": "2026-02-01",
                    "valor": 500000,
                }
            ],
        }
    )
    motor = MotorDeRisco()
    bcb = BCBFake(fator=1.1)
    return tse, receita, portal, motor, bcb


def _montar_completo():
    tse, receita, portal, motor, bcb = _fontes_completas()
    return montar_dossie(
        "Zé Exemplo",
        2024,
        "SP",
        13,
        tse=tse,
        receita=receita,
        portal=portal,
        motor=motor,
        bcb=bcb,
        cnpjs_relacionados=[CNPJ_HOMONIMO, CNPJ_SEM_ACHADO],
    )


def test_dossie_completo_candidato_encontrado():
    dossie = _montar_completo()

    assert dossie["encontrado"] is True
    assert dossie["identidade"]["nome_urna"] == "ZÉ EXEMPLO"
    assert dossie["identidade"]["nome_completo"] == "JOSÉ DA SILVA EXEMPLO"
    assert dossie["total_bens_declarados"] == 100000.0

    indicadores = {a["indicador"] for a in dossie["risco"]["alertas"]}
    assert "vinculo_societario" in indicadores
    assert "empresa_recem_criada" in indicadores

    assert dossie["erros_de_coleta"] == []
    assert "TSE" in dossie["fontes_consultadas"]
    assert "Receita" in dossie["fontes_consultadas"]
    assert "Portal" in dossie["fontes_consultadas"]
    assert "BCB" in dossie["fontes_consultadas"]

    assert dossie["homonimos"][0]["cnpj"] == CNPJ_HOMONIMO


def test_candidato_nao_encontrado():
    tse = TSEFake(detalhe=None)
    dossie = montar_dossie("Ninguém Assim", 2024, "SP", 13, tse=tse)

    assert dossie["encontrado"] is False
    assert "não encontrado" in dossie["erro"]
    assert dossie["fontes_consultadas"] == ["TSE"]
    assert dossie["erros_de_coleta"] == []


def test_falha_na_busca_inicial_do_tse_e_diferenciada_de_nao_encontrado():
    tse = TSEFake(erro_busca=ConnectionError("TSE fora do ar"))
    dossie = montar_dossie("Zé Exemplo", 2024, "SP", 13, tse=tse)

    assert dossie["encontrado"] is False
    assert "TSE fora do ar" in dossie["erro"]
    assert dossie["erros_de_coleta"][0]["fonte"] == "TSE.buscar_candidato"


def test_falha_de_rede_em_uma_fonte_nao_derruba_o_dossie():
    tse, receita, _, motor, bcb = _fontes_completas()
    portal_com_falha = PortalFake(erro_contratos=ConnectionError("Portal fora do ar"))

    dossie = montar_dossie(
        "Zé Exemplo",
        2024,
        "SP",
        13,
        tse=tse,
        receita=receita,
        portal=portal_com_falha,
        motor=motor,
        bcb=bcb,
        cnpjs_relacionados=[CNPJ_HOMONIMO],
    )

    assert dossie["encontrado"] is True
    assert dossie["risco"] is not None
    assert any(
        e["fonte"] == "Portal.contratos_por_cnpj" for e in dossie["erros_de_coleta"]
    )
    # vínculo societário (via sócios) ainda é identificado, mesmo sem contratos
    indicadores = {a["indicador"] for a in dossie["risco"]["alertas"]}
    assert "vinculo_societario" in indicadores


def test_falha_ao_baixar_foto_vira_erro_de_coleta_sem_foto_local():
    tse = TSEFake(erro_foto=ConnectionError("timeout"))
    dossie = montar_dossie("Zé Exemplo", 2024, "SP", 13, tse=tse)

    assert dossie["encontrado"] is True
    assert dossie["foto_local"] is None
    assert any(e["fonte"] == "TSE.baixar_foto" for e in dossie["erros_de_coleta"])


def test_markdown_contem_nome_de_urna_nome_civil_e_presuncao_de_inocencia():
    dossie = _montar_completo()
    markdown = dossie_para_markdown(dossie)

    assert "ZÉ EXEMPLO" in markdown
    assert "JOSÉ DA SILVA EXEMPLO" in markdown
    assert "presunção de inocência" in markdown
    assert "SOCIO_DE" in markdown


def test_markdown_de_candidato_nao_encontrado_tambem_traz_presuncao_de_inocencia():
    tse = TSEFake(detalhe=None)
    dossie = montar_dossie("Ninguém Assim", 2024, "SP", 13, tse=tse)
    markdown = dossie_para_markdown(dossie)

    assert "presunção de inocência" in markdown
    assert "não encontrado" in markdown


def test_foto_local_aparece_como_string_no_dossie(tmp_path: Path):
    foto = tmp_path / "foto.jpg"
    foto.write_bytes(b"jpegfake")
    tse = TSEFake(foto=foto)
    dossie = montar_dossie("Zé Exemplo", 2024, "SP", 13, tse=tse)

    assert dossie["foto_local"] == str(foto)
    assert "foto.jpg" in dossie_para_markdown(dossie)
