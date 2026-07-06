"""Testes do webapp FastAPI — sem rede (TestClient + monkeypatch)."""

import httpx
from fastapi.testclient import TestClient

from fiscaliza.fontes.tse import TSE
from webapp.app import app

cliente = TestClient(app)

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


def test_home_200_e_nota_juridica():
    r = cliente.get("/")
    assert r.status_code == 200
    assert "presunção de inocência" in r.text
    assert "vis-network" in r.text  # CDN do grafo presente


def test_grafo_exemplo():
    r = cliente.get("/api/grafo/exemplo")
    assert r.status_code == 200
    d = r.json()
    assert d["nodes"] and d["edges"]
    ids = {n["id"] for n in d["nodes"]}
    assert {"pessoa:exemplo-1", "empresa:00000000000191", "orgao:26000"} <= ids
    # laço que fecha o ciclo: empresa -> parlamentar via DOOU_PARA
    assert any(
        e["from"] == "empresa:00000000000191"
        and e["to"] == "pessoa:exemplo-1"
        and e["label"] == "DOOU_PARA"
        for e in d["edges"]
    )


def test_candidato_stub_ok(monkeypatch):
    monkeypatch.setattr(TSE, "buscar_candidato", lambda self, *a, **k: DETALHE)
    r = cliente.get("/api/candidato", params={"nome": "ze exemplo", "uf": "sp"})
    assert r.status_code == 200
    d = r.json()
    assert d["identidade"]["nome_urna"] == "ZÉ EXEMPLO"
    assert d["total_bens"] == 100000.0
    assert d["risco"]["cor"]  # cor calculada com _cor no backend


def test_candidato_nao_encontrado_404(monkeypatch):
    monkeypatch.setattr(TSE, "buscar_candidato", lambda self, *a, **k: None)
    r = cliente.get("/api/candidato", params={"nome": "ninguem"})
    assert r.status_code == 404
    assert r.json()["erro"] == "candidato não encontrado"


def test_candidato_erro_rede_503(monkeypatch):
    def boom(self, *a, **k):
        raise httpx.ConnectError("conexão recusada")

    monkeypatch.setattr(TSE, "buscar_candidato", boom)
    r = cliente.get("/api/candidato", params={"nome": "ze"})
    assert r.status_code == 503
    d = r.json()
    assert d["erro"] == "fonte TSE indisponível"
    assert "Traceback" not in str(d)  # sem stacktrace vazado
