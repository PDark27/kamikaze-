"""Testes da busca local pelos Dados Abertos do TSE — sem rede."""

import io
import zipfile

import httpx

from fiscaliza.busca_local import BuscaLocal, ingerir_candidatos

CABECALHO = (
    "ANO_ELEICAO;SG_UF;CD_CARGO;DS_CARGO;SQ_CANDIDATO;NM_CANDIDATO;"
    "NM_URNA_CANDIDATO;NR_CANDIDATO;SG_PARTIDO"
)
LINHAS_SP = [
    '2024;SP;13;VEREADOR;250001;JOSÉ DA SILVA EXEMPLO;ZÉ EXEMPLO;12345;XYZ',
    '2024;SP;13;VEREADOR;250002;MARIA SOUZA;MARIA DA ESCOLA;54321;ABC',
]


def _zip_consulta_cand(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        conteudo = "\r\n".join([CABECALHO, *LINHAS_SP])
        zf.writestr("consulta_cand_2024_SP.csv", conteudo.encode("latin-1"))
        zf.writestr("leiame.pdf", b"nao-e-csv")
    return buf.getvalue()


def _ingerir(tmp_path):
    corpo = _zip_consulta_cand(tmp_path)
    http = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=corpo))
    )
    return ingerir_candidatos(
        2024, ufs=["SP"],
        caminho_db=tmp_path / "f.db", pasta_dumps=tmp_path / "dumps", http=http,
    )


def test_ingerir_e_buscar_por_nome_de_urna(tmp_path):
    assert _ingerir(tmp_path) == 2
    busca = BuscaLocal(tmp_path / "f.db")
    r = busca.buscar("ze exemplo", 2024, "sp", 13)
    assert r is not None
    assert r["nome_completo"] == "JOSÉ DA SILVA EXEMPLO"
    assert r["partido"] == "XYZ"
    assert r["sqcand"] == "250001"


def test_buscar_por_nome_civil_e_ausente(tmp_path):
    _ingerir(tmp_path)
    busca = BuscaLocal(tmp_path / "f.db")
    assert busca.buscar("maria souza", 2024, "SP", 13)["nome_urna"] == "MARIA DA ESCOLA"
    assert busca.buscar("ninguem assim", 2024, "SP", 13) is None
    assert busca.buscar("ze exemplo", 2024, "RJ", 13) is None  # UF errada


def test_reingerir_nao_duplica(tmp_path):
    _ingerir(tmp_path)
    _ingerir(tmp_path)  # idempotente por (ano, uf)
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "f.db"))
    (total,) = conn.execute("SELECT COUNT(*) FROM candidatos").fetchone()
    conn.close()
    assert total == 2


def test_busca_sem_banco_retorna_none(tmp_path):
    assert BuscaLocal(tmp_path / "inexistente.db").buscar("x", 2024, "SP", 13) is None
