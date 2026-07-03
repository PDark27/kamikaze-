"""Mapeamento em grafos: pessoas, empresas, órgãos, contratos, doações e
emendas como nós/arestas. Exporta GraphML (Gephi) e Cypher (Neo4j)."""

from __future__ import annotations

from pathlib import Path

import networkx as nx


class GrafoDeRelacoes:
    def __init__(self):
        self.g = nx.MultiDiGraph()

    # nós ---------------------------------------------------------------
    def pessoa(self, chave: str, nome: str, **atributos):
        self.g.add_node(f"pessoa:{chave}", tipo="Pessoa", nome=nome, **atributos)
        return f"pessoa:{chave}"

    def empresa(self, cnpj: str, razao_social: str = "", **atributos):
        self.g.add_node(f"empresa:{cnpj}", tipo="Empresa",
                        nome=razao_social or cnpj, **atributos)
        return f"empresa:{cnpj}"

    def orgao(self, codigo: str, nome: str = "", **atributos):
        self.g.add_node(f"orgao:{codigo}", tipo="Orgao", nome=nome or codigo, **atributos)
        return f"orgao:{codigo}"

    # arestas -----------------------------------------------------------
    def socio_de(self, pessoa: str, empresa: str, **atributos):
        self.g.add_edge(pessoa, empresa, relacao="SOCIO_DE", **atributos)

    def parente_de(self, a: str, b: str, grau: int, **atributos):
        self.g.add_edge(a, b, relacao="PARENTE_DE", grau=grau, **atributos)

    def contratou(self, orgao: str, empresa: str, valor: float, **atributos):
        self.g.add_edge(orgao, empresa, relacao="CONTRATOU", valor=valor, **atributos)

    def doou_para(self, doador: str, candidato: str, valor: float, **atributos):
        self.g.add_edge(doador, candidato, relacao="DOOU_PARA", valor=valor, **atributos)

    def emendou_para(self, parlamentar: str, orgao: str, valor: float, **atributos):
        self.g.add_edge(parlamentar, orgao, relacao="EMENDA_PARA", valor=valor, **atributos)

    # análise -----------------------------------------------------------
    def ciclos_suspeitos(self) -> list[list[str]]:
        """Ciclos fechados (ex.: parlamentar → emenda → órgão → contrato →
        empresa → doação → parlamentar) são os padrões de maior interesse."""
        return list(nx.simple_cycles(nx.DiGraph(self.g)))

    def caminhos(self, origem: str, destino: str, maximo: int = 4) -> list[list[str]]:
        try:
            return list(nx.all_simple_paths(self.g, origem, destino, cutoff=maximo))
        except nx.NodeNotFound:
            return []

    # exportação ---------------------------------------------------------
    def salvar_graphml(self, caminho: str | Path):
        nx.write_graphml(nx.DiGraph(self.g), str(caminho))

    def como_cypher(self) -> str:
        """Gera comandos Cypher para importar o grafo no Neo4j."""
        linhas = []
        for no, dados in self.g.nodes(data=True):
            props = ", ".join(f'{k}: "{v}"' for k, v in dados.items())
            linhas.append(f'MERGE (n:`{dados.get("tipo", "No")}` {{id: "{no}", {props}}});')
        for origem, destino, dados in self.g.edges(data=True):
            rel = dados.pop("relacao", "RELACIONADO")
            props = ", ".join(f'{k}: "{v}"' for k, v in dados.items())
            linhas.append(
                f'MATCH (a {{id: "{origem}"}}), (b {{id: "{destino}"}}) '
                f"MERGE (a)-[:{rel} {{{props}}}]->(b);"
            )
        return "\n".join(linhas)
