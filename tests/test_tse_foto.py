"""Testes de foto oficial, nome de urna e cartão HTML — sem rede (mocks)."""

from pathlib import Path
from unittest.mock import patch

import httpx

from fiscaliza.cartao import gerar_cartao
from fiscaliza.fontes.tse import TSE, _normalizar
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
}

LISTA = {"candidatos": [
    {"id": 1, "nomeUrna": "OUTRO NOME", "nomeCompleto": "OUTRA PESSOA"},
    {"id": 250001609124, "nomeUrna": "ZÉ EXEMPLO",
     "nomeCompleto": "JOSÉ DA SILVA EXEMPLO"},
]}


def test_normalizar_remove_acentos_e_caixa():
    assert _normalizar("Zé Exemplo") == "ZE EXEMPLO"


def test_foto_url_extraida_e_ausente():
    assert TSE.foto_url(DETALHE) == DETALHE["fotoUrl"]
    assert TSE.foto_url({}) is None


def test_identidade_normaliza_campos():
    ident = TSE.identidade(DETALHE)
    assert ident["nome_urna"] == "ZÉ EXEMPLO"
    assert ident["nome_completo"] == "JOSÉ DA SILVA EXEMPLO"
    assert ident["partido"] == "XYZ"
    assert ident["cargo"] == "Vereador"
    assert ident["foto_url"].endswith("F123.jpg")


def _tse_mockado():
    tse = TSE.__new__(TSE)
    return tse


def test_buscar_por_nome_de_urna_e_por_nome_civil():
    tse = _tse_mockado()
    with patch.object(TSE, "candidatos", return_value=LISTA), \
         patch.object(TSE, "candidato", return_value=DETALHE):
        assert tse.buscar_candidato(2024, "SP", "ze exemplo", 13)["id"] == DETALHE["id"]
        assert tse.buscar_candidato(2024, "SP", "José da Silva Exemplo", 13) is not None
        assert tse.buscar_candidato(2024, "SP", "NINGUEM ASSIM", 13) is None


def test_baixar_foto_salva_e_usa_cache(tmp_path: Path):
    tse = _tse_mockado()
    tse._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=b"jpegfake")
        )
    )
    caminho = tse.baixar_foto(DETALHE, destino=tmp_path)
    assert caminho == tmp_path / "2024" / "250001609124.jpg"
    assert caminho.read_bytes() == b"jpegfake"

    # cache: segundo download não refaz a requisição
    tse._http = httpx.Client(transport=httpx.MockTransport(
        lambda req: (_ for _ in ()).throw(AssertionError("não deveria baixar de novo"))
    ))
    assert tse.baixar_foto(DETALHE, destino=tmp_path) == caminho


def test_baixar_foto_sem_url_retorna_none(tmp_path: Path):
    assert _tse_mockado().baixar_foto({"id": 1}, destino=tmp_path) is None


def test_gerar_cartao_com_e_sem_foto(tmp_path: Path):
    ident = TSE.identidade(DETALHE)
    resultado = MotorDeRisco().consolidar([])

    foto = tmp_path / "f.jpg"
    foto.write_bytes(b"jpegfake")
    saida = gerar_cartao(ident, resultado, foto, tmp_path / "cartao.html")
    conteudo = saida.read_text(encoding="utf-8")
    assert "ZÉ EXEMPLO" in conteudo                # nome de urna em destaque
    assert "JOSÉ DA SILVA EXEMPLO" in conteudo     # nome civil completo
    assert "presunção de inocência" in conteudo
    assert "data:image/jpeg;base64" in conteudo

    sem_foto = gerar_cartao(ident, resultado, None, tmp_path / "sem_foto.html")
    assert "foto não disponível" in sem_foto.read_text(encoding="utf-8")
