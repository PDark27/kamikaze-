"""Ingestão em escala: baixar dumps públicos (TSE/CNPJ), carregar em um
banco SQLite local e exportar para CSVs de importação em massa do Neo4j.

Diferença em relação a `fiscaliza.fontes`: os conectores em `fontes/` fazem
consultas pontuais via API JSON (ex.: candidato específico, contrato
específico). Este pacote (`ingestao/`) trata o caso de baixar datasets
inteiros (dumps CSV/ZIP de milhões de linhas) e prepará-los para análise em
lote — download resumível, carga em SQLite por lotes e exportação para o
formato de importação em massa do `neo4j-admin`.
"""

from __future__ import annotations

from .carga import BancoLocal
from .dumps import DumpsCNPJ, DumpsTSE
from .neo4j_export import ExportadorNeo4j

__all__ = ["DumpsTSE", "DumpsCNPJ", "BancoLocal", "ExportadorNeo4j"]
