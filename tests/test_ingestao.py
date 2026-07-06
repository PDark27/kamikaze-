"""Testes do módulo `fiscaliza.ingestao` — sem rede real.

Todos os downloads são simulados via `httpx.MockTransport`; cargas de CSV
usam `tmp_path` e zips sintéticos em memória. Nenhum teste acessa domínios
`.gov.br`/`.jus.br` (bloqueados neste sandbox); a execução real (rede
liberada) deve rodar na máquina do usuário.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import zipfile
from pathlib import Path

import httpx
import pytest

from fiscaliza.ingestao.carga import BancoLocal
from fiscaliza.ingestao.dumps import DumpsCNPJ, DumpsTSE
from fiscaliza.ingestao.neo4j_export import ExportadorNeo4j


# --------------------------------------------------------------------------
# DumpsTSE
# --------------------------------------------------------------------------

def test_dumps_tse_lista_e_baixa_recurso(tmp_path):
    conteudo = b"conteudo-fixo-do-dump-tse"

    def handler(request: httpx.Request) -> httpx.Response:
        if "package_show" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "resources": [
                            {
                                "url": "https://dadosabertos.tse.jus.br/dataset/arquivo.zip",
                                "name": "arquivo.zip",
                                "format": "ZIP",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200, content=conteudo, headers={"content-length": str(len(conteudo))}
        )

    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    dumps = DumpsTSE(http=cliente)

    recursos = dumps.listar_recursos("pacote-teste")
    assert recursos[0]["name"] == "arquivo.zip"
    assert recursos[0]["format"] == "ZIP"

    caminhos = dumps.baixar_recursos("pacote-teste", destino=tmp_path)
    assert len(caminhos) == 1
    assert caminhos[0].exists()
    assert caminhos[0].read_bytes() == conteudo
    # download atômico: nenhum .part deve sobrar
    assert not caminhos[0].with_suffix(caminhos[0].suffix + ".part").exists()


def test_dumps_tse_pula_arquivo_existente(tmp_path):
    destino = tmp_path
    arquivo_existente = destino / "ja_baixado.zip"
    arquivo_existente.parent.mkdir(parents=True, exist_ok=True)
    arquivo_existente.write_bytes(b"conteudo-sentinela")

    chamou_download = {"valor": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if "package_show" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "resources": [
                            {
                                "url": "https://dadosabertos.tse.jus.br/dataset/ja_baixado.zip",
                                "name": "ja_baixado.zip",
                                "format": "ZIP",
                            }
                        ]
                    }
                },
            )
        chamou_download["valor"] = True
        return httpx.Response(200, content=b"nao-deveria-ser-usado")

    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    dumps = DumpsTSE(http=cliente)

    caminhos = dumps.baixar_recursos("pacote-teste", destino=destino)

    assert not chamou_download["valor"], "não deveria ter baixado arquivo já existente"
    assert caminhos[0].read_bytes() == b"conteudo-sentinela"


# --------------------------------------------------------------------------
# DumpsCNPJ
# --------------------------------------------------------------------------

def test_dumps_cnpj_baixa_com_subpasta(tmp_path):
    conteudo = b"conteudo-fixo-socios"
    urls_chamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls_chamadas.append(str(request.url))
        return httpx.Response(
            200, content=conteudo, headers={"content-length": str(len(conteudo))}
        )

    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    dumps = DumpsCNPJ(http=cliente)

    caminhos = dumps.baixar(["Socios0.zip"], destino=tmp_path, subpasta="2024-05")

    assert len(caminhos) == 1
    assert caminhos[0].exists()
    assert caminhos[0].read_bytes() == conteudo
    assert urls_chamadas == [
        "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/2024-05/Socios0.zip"
    ]


# --------------------------------------------------------------------------
# BancoLocal
# --------------------------------------------------------------------------

def _criar_zip_csv(caminho_zip: Path, nome_membro: str, linhas: list[list[str]],
                    encoding: str, separador: str) -> None:
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=separador)
    for linha in linhas:
        escritor.writerow(linha)
    with zipfile.ZipFile(caminho_zip, "w") as zf:
        zf.writestr(nome_membro, buffer.getvalue().encode(encoding))


def test_carregar_csv_zip_latin1(tmp_path):
    caminho_zip = tmp_path / "socios.zip"
    linhas = [
        ["11111111111", "ANTÔNIO DA SILVA", "49"],
        ["22222222222", "MARIA JOSÉ", "22"],
    ]
    _criar_zip_csv(caminho_zip, "socios.csv", linhas, encoding="latin-1", separador=";")

    banco = BancoLocal(tmp_path / "t.db")
    try:
        inseridas = banco.carregar_csv(
            caminho_zip,
            "socios_raw",
            colunas={"cpf": "TEXT", "nome": "TEXT", "qualificacao": "TEXT"},
            separador=";",
            encoding="latin-1",
        )
        assert inseridas == 2

        linhas_bd = banco.consultar("SELECT cpf, nome, qualificacao FROM socios_raw ORDER BY cpf")
        assert linhas_bd == [
            ("11111111111", "ANTÔNIO DA SILVA", "49"),
            ("22222222222", "MARIA JOSÉ", "22"),
        ]
    finally:
        banco.fechar()


def test_carregar_csv_infere_colunas_posicionais(tmp_path):
    caminho_csv = tmp_path / "dados.csv"
    caminho_csv.write_text("a;b;c\nd;e;f\n", encoding="latin-1")

    with BancoLocal(tmp_path / "t2.db") as banco:
        inseridas = banco.carregar_csv(caminho_csv, "bruto", separador=";", encoding="latin-1")
        assert inseridas == 2
        linhas = banco.consultar("SELECT col_0, col_1, col_2 FROM bruto ORDER BY col_0")
        assert linhas == [("a", "b", "c"), ("d", "e", "f")]


def test_criar_indice(tmp_path):
    caminho_csv = tmp_path / "pequeno.csv"
    caminho_csv.write_text("11111111111;NOME UM\n22222222222;NOME DOIS\n", encoding="latin-1")

    with BancoLocal(tmp_path / "idx.db") as banco:
        banco.carregar_csv(
            caminho_csv, "pessoas_raw",
            colunas={"cpf": "TEXT", "nome": "TEXT"},
            separador=";", encoding="latin-1",
        )
        banco.criar_indice("pessoas_raw", "cpf")

        indices = banco.consultar("PRAGMA index_list('pessoas_raw')")
        nomes_indices = [linha[1] for linha in indices]
        assert "idx_pessoas_raw_cpf" in nomes_indices


# --------------------------------------------------------------------------
# ExportadorNeo4j
# --------------------------------------------------------------------------

def _popular_banco_grafo(banco: BancoLocal) -> None:
    banco.executar("CREATE TABLE pessoas (cpf TEXT PRIMARY KEY, nome TEXT)")
    banco.executar("CREATE TABLE empresas (cnpj TEXT PRIMARY KEY, razao_social TEXT)")
    banco.executar("CREATE TABLE orgaos (codigo TEXT PRIMARY KEY, nome TEXT)")
    banco.executar("CREATE TABLE socios (cpf TEXT, cnpj TEXT, qualificacao TEXT)")
    banco.executar("CREATE TABLE contratos (orgao_codigo TEXT, cnpj TEXT, valor REAL, objeto TEXT)")
    banco.executar("CREATE TABLE doacoes (cpf_doador TEXT, cpf_candidato TEXT, valor REAL)")

    banco.executar("INSERT INTO pessoas VALUES (?, ?)", ("11111111111", "Fulano"))
    banco.executar("INSERT INTO pessoas VALUES (?, ?)", ("22222222222", "Beltrano"))
    banco.executar("INSERT INTO empresas VALUES (?, ?)", ("11222333000144", "Empresa X LTDA"))
    banco.executar("INSERT INTO orgaos VALUES (?, ?)", ("26000", "Ministério Y"))
    banco.executar(
        "INSERT INTO socios VALUES (?, ?, ?)", ("11111111111", "11222333000144", "Sócio-Administrador")
    )
    banco.executar(
        "INSERT INTO contratos VALUES (?, ?, ?, ?)",
        ("26000", "11222333000144", 150000.0, "Serviços de consultoria"),
    )
    banco.executar(
        "INSERT INTO doacoes VALUES (?, ?, ?)", ("22222222222", "11111111111", 5000.0)
    )


def test_gerar_csv_bulk_e_comando_import(tmp_path):
    with BancoLocal(tmp_path / "grafo.db") as banco:
        _popular_banco_grafo(banco)

        exportador = ExportadorNeo4j()
        saida = tmp_path / "export"
        gerados = exportador.gerar_csv_bulk(banco, saida)

        assert set(gerados.keys()) == {
            "pessoas", "empresas", "orgaos", "socios", "contratos", "doacoes"
        }

        with open(saida / "pessoas_nodes.csv", newline="", encoding="utf-8") as f:
            linhas = list(csv.reader(f))
        assert linhas[0] == ["cpf:ID(Pessoa)", "nome", ":LABEL"]
        assert ["11111111111", "Fulano", "Pessoa"] in linhas[1:]

        with open(saida / "empresas_nodes.csv", newline="", encoding="utf-8") as f:
            linhas = list(csv.reader(f))
        assert linhas[0] == ["cnpj:ID(Empresa)", "razao_social", ":LABEL"]
        assert ["11222333000144", "Empresa X LTDA", "Empresa"] in linhas[1:]

        with open(saida / "orgaos_nodes.csv", newline="", encoding="utf-8") as f:
            linhas = list(csv.reader(f))
        assert linhas[0] == ["codigo:ID(Orgao)", "nome", ":LABEL"]
        assert ["26000", "Ministério Y", "Orgao"] in linhas[1:]

        with open(saida / "socios_rels.csv", newline="", encoding="utf-8") as f:
            linhas = list(csv.reader(f))
        assert linhas[0] == [":START_ID(Pessoa)", ":END_ID(Empresa)", "qualificacao", ":TYPE"]
        assert ["11111111111", "11222333000144", "Sócio-Administrador", "SOCIO_DE"] in linhas[1:]

        with open(saida / "contratos_rels.csv", newline="", encoding="utf-8") as f:
            linhas = list(csv.reader(f))
        assert linhas[0] == [":START_ID(Orgao)", ":END_ID(Empresa)", "valor", "objeto", ":TYPE"]
        assert ["26000", "11222333000144", "150000.0", "Serviços de consultoria", "CONTRATOU"] in linhas[1:]

        with open(saida / "doacoes_rels.csv", newline="", encoding="utf-8") as f:
            linhas = list(csv.reader(f))
        assert linhas[0] == [":START_ID(Pessoa)", ":END_ID(Pessoa)", "valor", ":TYPE"]
        assert ["22222222222", "11111111111", "5000.0", "DOOU_PARA"] in linhas[1:]

        comando = exportador.comando_import(saida)
        assert comando.startswith("neo4j-admin database import full fiscaliza")
        assert f"--nodes=Pessoa={saida}/pessoas_nodes.csv" in comando
        assert f"--nodes=Empresa={saida}/empresas_nodes.csv" in comando
        assert f"--nodes=Orgao={saida}/orgaos_nodes.csv" in comando
        assert f"--relationships=SOCIO_DE={saida}/socios_rels.csv" in comando
        assert f"--relationships=CONTRATOU={saida}/contratos_rels.csv" in comando
        assert f"--relationships=DOOU_PARA={saida}/doacoes_rels.csv" in comando
        assert comando.endswith("--overwrite-destination")


def test_gerar_csv_bulk_tolera_tabelas_ausentes(tmp_path):
    with BancoLocal(tmp_path / "parcial.db") as banco:
        banco.executar("CREATE TABLE pessoas (cpf TEXT PRIMARY KEY, nome TEXT)")
        banco.executar("INSERT INTO pessoas VALUES (?, ?)", ("11111111111", "Fulano"))

        exportador = ExportadorNeo4j()
        saida = tmp_path / "export_parcial"
        gerados = exportador.gerar_csv_bulk(banco, saida)

        assert set(gerados.keys()) == {"pessoas"}
        assert (saida / "pessoas_nodes.csv").exists()
        assert not (saida / "empresas_nodes.csv").exists()

        comando = exportador.comando_import(saida)
        assert "--nodes=Pessoa=" in comando
        assert "--nodes=Empresa=" not in comando
        assert "--relationships=" not in comando
