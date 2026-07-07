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
    assert 'rel="manifest"' in r.text  # PWA instalável


def test_pwa_manifesto_sw_e_icone():
    m = cliente.get("/manifest.webmanifest")
    assert m.status_code == 200
    dados = m.json()
    assert dados["short_name"] == "Fiscaliza"
    assert dados["display"] == "standalone"
    assert dados["icons"]

    sw = cliente.get("/sw.js")
    assert sw.status_code == 200
    assert "application/javascript" in sw.headers["content-type"]

    icone = cliente.get("/icone.svg")
    assert icone.status_code == 200
    assert "image/svg+xml" in icone.headers["content-type"]


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
    assert "ConnectError" in d["detalhe"]  # diagnóstico visível
    assert "Traceback" not in str(d)  # sem stacktrace vazado


def test_candidato_erro_http_503_mostra_codigo(monkeypatch):
    def boom_403(self, *a, **k):
        req = httpx.Request("GET", "https://divulgacandcontas.tse.jus.br/x")
        raise httpx.HTTPStatusError(
            "403", request=req, response=httpx.Response(403, request=req)
        )

    monkeypatch.setattr(TSE, "buscar_candidato", boom_403)
    r = cliente.get("/api/candidato", params={"nome": "ze"})
    assert r.status_code == 503
    d = r.json()
    assert "HTTP 403" in d["detalhe"]
    assert "divulgacandcontas.tse.jus.br" in d["detalhe"]


def test_diagnostico_ok(monkeypatch):
    monkeypatch.setattr(TSE, "get_json", lambda self, *a, **k: {"eleicoes": []})
    r = cliente.get("/api/diagnostico")
    assert r.status_code == 200
    assert r.json()["tse"] == "ok"


def test_diagnostico_falha_de_rede(monkeypatch):
    def boom(self, *a, **k):
        raise httpx.ConnectTimeout("tempo esgotado")

    monkeypatch.setattr(TSE, "get_json", boom)
    r = cliente.get("/api/diagnostico")
    assert r.status_code == 503
    d = r.json()
    assert d["tse"] == "falha"
    assert "ConnectTimeout" in d["detalhe"]
    assert "IP brasileiro" in d["conclusao"]


def test_cliente_base_envia_user_agent_de_navegador():
    from fiscaliza.fontes.base import ClienteBase

    c = ClienteBase()
    assert c._http.headers["user-agent"].startswith("Mozilla/5.0")
    assert "pt-BR" in c._http.headers["accept-language"]
    assert c._http.follow_redirects is True
