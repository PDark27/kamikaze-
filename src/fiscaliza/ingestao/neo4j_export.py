"""Exportação de um `BancoLocal` (SQLite) para CSVs de importação em massa
do Neo4j (`neo4j-admin database import full`).

Esquema de tabelas convencionado (apenas para este módulo de ingestão — não
é imposto ao resto do projeto):

- `pessoas(cpf TEXT PRIMARY KEY, nome TEXT)`
- `empresas(cnpj TEXT PRIMARY KEY, razao_social TEXT)`
- `orgaos(codigo TEXT PRIMARY KEY, nome TEXT)`
- `socios(cpf TEXT, cnpj TEXT, qualificacao TEXT)` → aresta `SOCIO_DE`
- `contratos(orgao_codigo TEXT, cnpj TEXT, valor REAL, objeto TEXT)` →
  aresta `CONTRATOU`
- `doacoes(cpf_doador TEXT, cpf_candidato TEXT, valor REAL)` → aresta
  `DOOU_PARA`

Os rótulos de nó (`Pessoa`, `Empresa`, `Orgao`) e os tipos de relação
(`SOCIO_DE`, `CONTRATOU`, `DOOU_PARA`) são os mesmos já usados por
`fiscaliza.grafo.GrafoDeRelacoes`, para que o grafo importado no Neo4j fique
semanticamente alinhado ao que o módulo `grafo.py` já produz via networkx.

`gerar_csv_bulk` tolera ausência parcial de tabelas (dataset carregado
incrementalmente): só gera os CSVs cujas tabelas de origem existem no banco,
e `comando_import` só inclui as flags `--nodes`/`--relationships`
correspondentes aos arquivos efetivamente gerados.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .carga import BancoLocal

# Cada entrada: nome lógico, arquivo de saída, rótulo/tipo, tabela de origem,
# cabeçalho do CSV neo4j-admin, SQL de seleção das colunas na ordem do header.
_NOS = [
    (
        "pessoas",
        "pessoas_nodes.csv",
        "Pessoa",
        ("cpf:ID(Pessoa)", "nome", ":LABEL"),
        "SELECT cpf, nome FROM pessoas",
    ),
    (
        "empresas",
        "empresas_nodes.csv",
        "Empresa",
        ("cnpj:ID(Empresa)", "razao_social", ":LABEL"),
        "SELECT cnpj, razao_social FROM empresas",
    ),
    (
        "orgaos",
        "orgaos_nodes.csv",
        "Orgao",
        ("codigo:ID(Orgao)", "nome", ":LABEL"),
        "SELECT codigo, nome FROM orgaos",
    ),
]

_RELACOES = [
    (
        "socios",
        "socios_rels.csv",
        "SOCIO_DE",
        (":START_ID(Pessoa)", ":END_ID(Empresa)", "qualificacao", ":TYPE"),
        "SELECT cpf, cnpj, qualificacao FROM socios",
    ),
    (
        "contratos",
        "contratos_rels.csv",
        "CONTRATOU",
        (":START_ID(Orgao)", ":END_ID(Empresa)", "valor", "objeto", ":TYPE"),
        "SELECT orgao_codigo, cnpj, valor, objeto FROM contratos",
    ),
    (
        "doacoes",
        "doacoes_rels.csv",
        "DOOU_PARA",
        (":START_ID(Pessoa)", ":END_ID(Pessoa)", "valor", ":TYPE"),
        "SELECT cpf_doador, cpf_candidato, valor FROM doacoes",
    ),
]


class ExportadorNeo4j:
    """Gera CSVs no formato `neo4j-admin` a partir de um `BancoLocal`."""

    def _tabela_existe(self, banco: BancoLocal, tabela: str) -> bool:
        linhas = banco.consultar(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)
        )
        return bool(linhas)

    def gerar_csv_bulk(self, banco: BancoLocal, saida: str | Path) -> dict[str, Path]:
        """Gera os CSVs de nós/relações em `saida/`.

        Retorna um dict nome_lógico -> `Path` gerado, incluindo apenas as
        tabelas presentes no banco (para não gerar CSV vazio de tabela
        inexistente).
        """
        saida = Path(saida)
        saida.mkdir(parents=True, exist_ok=True)
        gerados: dict[str, Path] = {}

        for nome_tabela, nome_arquivo, rotulo, header, sql in _NOS:
            if not self._tabela_existe(banco, nome_tabela):
                continue
            caminho = saida / nome_arquivo
            with open(caminho, "w", newline="", encoding="utf-8") as f:
                escritor = csv.writer(f)
                escritor.writerow(header)
                for linha in banco.consultar(sql):
                    escritor.writerow((*linha, rotulo))
            gerados[nome_tabela] = caminho

        for nome_tabela, nome_arquivo, tipo, header, sql in _RELACOES:
            if not self._tabela_existe(banco, nome_tabela):
                continue
            caminho = saida / nome_arquivo
            with open(caminho, "w", newline="", encoding="utf-8") as f:
                escritor = csv.writer(f)
                escritor.writerow(header)
                for linha in banco.consultar(sql):
                    escritor.writerow((*linha, tipo))
            gerados[nome_tabela] = caminho

        return gerados

    def comando_import(self, saida: str | Path, banco_destino: str = "fiscaliza") -> str:
        """Monta o comando `neo4j-admin database import full` correspondente
        aos CSVs presentes em `saida` (só inclui flags cujos arquivos
        existem, para o comando ficar coerente com dados parciais)."""
        saida = Path(saida)
        partes = ["neo4j-admin", "database", "import", "full", banco_destino]

        for _, nome_arquivo, rotulo, _, _ in _NOS:
            caminho = saida / nome_arquivo
            if caminho.exists():
                partes.append(f"--nodes={rotulo}={caminho}")

        for _, nome_arquivo, tipo, _, _ in _RELACOES:
            caminho = saida / nome_arquivo
            if caminho.exists():
                partes.append(f"--relationships={tipo}={caminho}")

        partes.append("--overwrite-destination")
        return " ".join(partes)
