"""Testes da memória investigativa persistente (segundo cérebro)."""

import pytest

from fiscaliza.memoria import Memoria, slug


def test_slug_trata_acentos_maiusculas():
    assert slug("João D'Ávila SILVA") == "joao-d-avila-silva"
    assert slug("  Múltiplos   Espaços--e--Hífens  ") == "multiplos-espacos-e-hifens"


def test_salvar_dossie_cria_arquivo_e_linha_no_indice(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    caminho = memoria.salvar_dossie(
        "pessoas",
        "Fulano De Tal",
        "# Fulano De Tal\n- Chave: ***123456**\n",
        indice_risco=42.0,
        faixa="Risco moderado",
    )

    assert caminho.exists()
    assert caminho.read_text(encoding="utf-8").startswith("# Fulano De Tal")

    indice = (tmp_path / "memoria" / "INDICE.md").read_text(encoding="utf-8")
    assert "Fulano De Tal" in indice
    assert "pessoas/fulano-de-tal.md" in indice
    assert "42.0%" in indice
    assert "Risco moderado" in indice


def test_salvar_dossie_mesma_entidade_atualiza_sem_duplicar(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    memoria.salvar_dossie("pessoas", "Fulano De Tal", "conteudo v1", indice_risco=10.0, faixa="Baixo")
    memoria.salvar_dossie(
        "pessoas", "fulano de tal", "conteudo v2", indice_risco=55.5, faixa="Risco alto"
    )

    indice = (tmp_path / "memoria" / "INDICE.md").read_text(encoding="utf-8")
    # apenas uma linha de dados referente à entidade, com o valor atualizado
    assert indice.count("fulano-de-tal.md") == 1
    assert "55.5%" in indice
    assert "10.0%" not in indice
    assert "Risco alto" in indice


def test_ler_dossie_inexistente_retorna_none(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    assert memoria.ler_dossie("pessoas", "ninguem") is None


def test_ler_dossie_existente_retorna_conteudo(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    memoria.salvar_dossie("empresas", "Empresa X", "# Empresa X\nconteudo")
    assert memoria.ler_dossie("empresas", "Empresa X") == "# Empresa X\nconteudo"


def test_cpf_nao_mascarado_levanta_valueerror_11_digitos(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    with pytest.raises(ValueError):
        memoria.salvar_dossie("pessoas", "Alguem", "CPF: 12345678901")


def test_cpf_nao_mascarado_levanta_valueerror_formato_pontuado(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    with pytest.raises(ValueError):
        memoria.salvar_dossie("pessoas", "Alguem", "CPF: 123.456.789-01")


def test_cpf_mascarado_permitido(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    caminho = memoria.salvar_dossie("pessoas", "Alguem", "- Chave: ***123456**")
    assert caminho.exists()


def test_registrar_conexao_cria_hipotese_e_nao_duplica(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    caminho = memoria.registrar_conexao(
        "Fulano De Tal", "Empresa X", "Sócio da empresa contratada pelo mesmo órgão."
    )
    assert caminho.exists()
    assert caminho.name == "empresa-x--fulano-de-tal.md"

    conteudo_v1 = caminho.read_text(encoding="utf-8")
    assert conteudo_v1.count("Sócio da empresa contratada pelo mesmo órgão.") == 1

    # ordem inversa dos argumentos deve resolver para o mesmo arquivo
    memoria.registrar_conexao(
        "Empresa X", "Fulano De Tal", "Sócio da empresa contratada pelo mesmo órgão."
    )
    conteudo_v2 = caminho.read_text(encoding="utf-8")
    assert conteudo_v2.count("Sócio da empresa contratada pelo mesmo órgão.") == 1

    memoria.registrar_conexao(
        "Fulano De Tal", "Empresa X", "Doação recebida antes da contratação."
    )
    conteudo_v3 = caminho.read_text(encoding="utf-8")
    assert "Doação recebida antes da contratação." in conteudo_v3
    assert conteudo_v3.count("Sócio da empresa contratada pelo mesmo órgão.") == 1


def test_resumo_conta_certo(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    memoria.salvar_dossie("pessoas", "A", "dossie a", indice_risco=90.0, faixa="Risco alto")
    memoria.salvar_dossie("pessoas", "B", "dossie b", indice_risco=10.0, faixa="Baixo")
    memoria.salvar_dossie("empresas", "C", "dossie c", indice_risco=50.0, faixa="Moderado")
    memoria.salvar_dossie("contratos", "D", "dossie d")

    resumo = memoria.resumo()

    assert resumo["total"] == 4
    assert resumo["por_tipo"] == {"pessoas": 2, "empresas": 1, "contratos": 1}
    assert len(resumo["top_5"]) == 3
    assert resumo["top_5"][0]["entidade"] == "A"
    assert resumo["top_5"][0]["indice_risco"] == 90.0


def test_resumo_vazio_sem_indice(tmp_path):
    memoria = Memoria(raiz=tmp_path / "memoria")
    resumo = memoria.resumo()
    assert resumo == {"total": 0, "por_tipo": {}, "top_5": []}
