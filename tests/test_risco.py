"""Testes do motor de risco com dados sintéticos (sem rede)."""

from fiscaliza.risco import MotorDeRisco


def motor():
    return MotorDeRisco()


def test_empresa_recem_criada_dispara():
    alerta = motor().empresa_recem_criada([{
        "cnpj": "00000000000191",
        "data_abertura_empresa": "2026-01-10",
        "data_contrato": "2026-02-01",
        "valor": 500000,
    }])
    assert alerta is not None
    assert alerta.evidencias[0]["dias_de_existencia_no_contrato"] == 22


def test_empresa_antiga_nao_dispara():
    assert motor().empresa_recem_criada([{
        "cnpj": "1", "data_abertura_empresa": "2010-01-01",
        "data_contrato": "2026-02-01", "valor": 1,
    }]) is None


def test_sobrepreco():
    alerta = motor().sobrepreco([
        {"descricao": "notebook", "preco_unitario": 9000, "mediana_mercado": 4000},
        {"descricao": "cadeira", "preco_unitario": 400, "mediana_mercado": 380},
    ])
    assert alerta is not None
    assert len(alerta.evidencias) == 1


def test_fracionamento():
    contratos = [
        {"fornecedor_cnpj": "X", "objeto": "obra", "valor": 58000, "ano": 2025}
        for _ in range(4)
    ]
    alerta = motor().fracionamento(contratos)
    assert alerta is not None


def test_consolidacao_gera_indice_e_faixa():
    m = motor()
    resultado = m.consolidar([
        m.sobrepreco([{"descricao": "x", "preco_unitario": 200, "mediana_mercado": 100}]),
        None,
    ])
    assert 0 < resultado["indice_de_risco_percentual"] <= 100
    assert "risco" in resultado["faixa"]
    assert "presunção de inocência" in resultado["nota_juridica"]


def test_evolucao_patrimonial():
    alerta = motor().evolucao_patrimonial(
        [{"ano": 2020, "total_bens": 100000}, {"ano": 2024, "total_bens": 350000}],
        fator_inflacao=1.25,
    )
    assert alerta is not None
