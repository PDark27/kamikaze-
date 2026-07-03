"""Motor de risco: aplica os indicadores de config/parametros_risco.yaml sobre
entidades normalizadas e produz alertas com índice percentual e evidências.

As funções recebem estruturas simples (dicts/listas) já normalizadas pelos
conectores, para permitir teste sem rede.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import carregar_parametros, faixa_de_risco


@dataclass
class Alerta:
    indicador: str
    pontos: float
    descricao: str
    evidencias: list[dict] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {
            "indicador": self.indicador,
            "pontos": round(self.pontos, 1),
            "descricao": self.descricao,
            "evidencias": self.evidencias,
        }


class MotorDeRisco:
    def __init__(self, parametros: dict | None = None):
        self.parametros = parametros or carregar_parametros()
        self.indicadores = self.parametros["indicadores"]

    # ------------------------------------------------------------------ #
    # Indicadores individuais. Cada um devolve Alerta ou None.
    # ------------------------------------------------------------------ #

    def empresa_recem_criada(self, contratos: list[dict]) -> Alerta | None:
        """contratos: [{cnpj, data_abertura_empresa: iso, data_contrato: iso, valor}]"""
        cfg = self.indicadores["empresa_recem_criada"]
        minimo = cfg["parametros"]["dias_minimos_existencia"]
        suspeitos = []
        for c in contratos:
            if not c.get("data_abertura_empresa") or not c.get("data_contrato"):
                continue
            dias = (
                date.fromisoformat(c["data_contrato"])
                - date.fromisoformat(c["data_abertura_empresa"])
            ).days
            if 0 <= dias < minimo:
                suspeitos.append({**c, "dias_de_existencia_no_contrato": dias})
        if not suspeitos:
            return None
        return Alerta("empresa_recem_criada", cfg["peso"], cfg["descricao"], suspeitos)

    def sobrepreco(self, itens: list[dict]) -> Alerta | None:
        """itens: [{descricao, preco_unitario, mediana_mercado}]"""
        cfg = self.indicadores["sobrepreco"]
        limiar = cfg["parametros"]["limiar_percentual_acima_mediana"]
        suspeitos = []
        for item in itens:
            mediana = item.get("mediana_mercado") or 0
            if mediana <= 0:
                continue
            excesso = (item["preco_unitario"] / mediana - 1) * 100
            if excesso >= limiar:
                suspeitos.append({**item, "percentual_acima_mediana": round(excesso, 1)})
        if not suspeitos:
            return None
        # escala proporcional: quanto mais itens acima do limiar, mais pontos
        fracao = min(len(suspeitos) / max(len(itens), 1) * 2, 1.0)
        return Alerta("sobrepreco", cfg["peso"] * fracao, cfg["descricao"], suspeitos)

    def vinculo_societario(self, vinculos: list[dict]) -> Alerta | None:
        """vinculos: [{agente, parentesco_grau, empresa_cnpj, orgao_contratante,
        orgao_do_agente}] — pontua quando órgão contratante == órgão do agente."""
        cfg = self.indicadores["vinculo_societario"]
        grau_max = cfg["parametros"]["graus_parentesco"]
        suspeitos = [
            v for v in vinculos
            if v.get("parentesco_grau", 0) <= grau_max
            and v.get("orgao_contratante") == v.get("orgao_do_agente")
        ]
        if not suspeitos:
            return None
        return Alerta("vinculo_societario", cfg["peso"], cfg["descricao"], suspeitos)

    def servidor_fantasma(self, vinculos_remuneratorios: list[dict]) -> Alerta | None:
        """vinculos_remuneratorios: [{cpf_mascarado, orgao, municipio, distancia_km}]
        agrupados por CPF antes da chamada; distancia_km entre lotações simultâneas."""
        cfg = self.indicadores["servidor_fantasma"]
        p = cfg["parametros"]
        suspeitos = [
            v for v in vinculos_remuneratorios
            if v.get("vinculos_simultaneos", 1) > p["max_vinculos_simultaneos"]
            or v.get("distancia_km", 0) >= p["distancia_km_incompativel"]
        ]
        if not suspeitos:
            return None
        return Alerta("servidor_fantasma", cfg["peso"], cfg["descricao"], suspeitos)

    def evolucao_patrimonial(self, declaracoes: list[dict],
                             fator_inflacao: float = 1.0) -> Alerta | None:
        """declaracoes: [{ano, total_bens}] ordenadas; compara pleitos consecutivos."""
        cfg = self.indicadores["evolucao_patrimonial"]
        limiar = cfg["parametros"]["limiar_crescimento_percentual"]
        suspeitos = []
        ordenadas = sorted(declaracoes, key=lambda d: d["ano"])
        for anterior, atual in zip(ordenadas, ordenadas[1:]):
            base = anterior["total_bens"] * fator_inflacao
            if base <= 0:
                continue
            crescimento = (atual["total_bens"] / base - 1) * 100
            if crescimento >= limiar:
                suspeitos.append({
                    "de": anterior["ano"], "para": atual["ano"],
                    "crescimento_real_percentual": round(crescimento, 1),
                })
        if not suspeitos:
            return None
        return Alerta("evolucao_patrimonial", cfg["peso"], cfg["descricao"], suspeitos)

    def doador_contratado(self, casos: list[dict]) -> Alerta | None:
        """casos: [{doador, valor_doacao, contrato_valor, meses_apos_posse}]"""
        cfg = self.indicadores["doador_contratado"]
        janela = cfg["parametros"]["janela_meses_apos_posse"]
        suspeitos = [c for c in casos if c.get("meses_apos_posse", 999) <= janela]
        if not suspeitos:
            return None
        return Alerta("doador_contratado", cfg["peso"], cfg["descricao"], suspeitos)

    def fracionamento(self, contratos: list[dict]) -> Alerta | None:
        """contratos: [{fornecedor_cnpj, objeto, valor, ano}] de um mesmo órgão."""
        cfg = self.indicadores["fracionamento"]
        p = cfg["parametros"]
        piso = p["limite_dispensa_reais"] * p["percentual_proximidade"] / 100
        teto = p["limite_dispensa_reais"]
        por_chave: dict[tuple, list[dict]] = {}
        for c in contratos:
            if piso <= c["valor"] <= teto:
                por_chave.setdefault((c["fornecedor_cnpj"], c["ano"]), []).append(c)
        suspeitos = [
            {"fornecedor_cnpj": chave[0], "ano": chave[1], "contratos": grupo}
            for chave, grupo in por_chave.items()
            if len(grupo) >= p["minimo_ocorrencias_ano"]
        ]
        if not suspeitos:
            return None
        return Alerta("fracionamento", cfg["peso"], cfg["descricao"], suspeitos)

    def empresa_fachada(self, empresas: list[dict]) -> Alerta | None:
        """empresas: [{cnpj, capital_social, valor_contratado, tem_empregados,
        endereco_residencial, cnae_compativel}]"""
        cfg = self.indicadores["empresa_fachada"]
        p = cfg["parametros"]
        suspeitos = []
        for e in empresas:
            sinais = []
            capital = e.get("capital_social") or 0
            if capital > 0 and e.get("valor_contratado", 0) / capital > p["razao_maxima_contrato_capital"]:
                sinais.append("contrato muito acima do capital social")
            if e.get("tem_empregados") is False:
                sinais.append("sem quadro de empregados conhecido")
            if e.get("endereco_residencial"):
                sinais.append("endereço residencial")
            if e.get("cnae_compativel") is False:
                sinais.append("CNAE incompatível com o objeto")
            minimo = 2 if p.get("exigir_dois_sinais") else 1
            if len(sinais) >= minimo:
                suspeitos.append({"cnpj": e["cnpj"], "sinais": sinais})
        if not suspeitos:
            return None
        return Alerta("empresa_fachada", cfg["peso"], cfg["descricao"], suspeitos)

    def concentracao_fornecedor(self, contratos_orgao: list[dict]) -> Alerta | None:
        """contratos_orgao: [{fornecedor_cnpj, valor}] de um órgão no período."""
        cfg = self.indicadores["concentracao_fornecedor"]
        p = cfg["parametros"]
        if len(contratos_orgao) < p["minimo_contratos_orgao"]:
            return None
        total = sum(c["valor"] for c in contratos_orgao) or 1
        por_fornecedor: dict[str, float] = {}
        for c in contratos_orgao:
            por_fornecedor[c["fornecedor_cnpj"]] = (
                por_fornecedor.get(c["fornecedor_cnpj"], 0) + c["valor"]
            )
        suspeitos = [
            {"fornecedor_cnpj": cnpj, "percentual_do_total": round(v / total * 100, 1)}
            for cnpj, v in por_fornecedor.items()
            if v / total * 100 >= p["percentual_limiar"]
        ]
        if not suspeitos:
            return None
        return Alerta("concentracao_fornecedor", cfg["peso"], cfg["descricao"], suspeitos)

    # ------------------------------------------------------------------ #

    def consolidar(self, alertas: list[Alerta | None]) -> dict:
        """Soma os alertas em um índice 0-100 com rótulo de faixa."""
        validos = [a for a in alertas if a is not None]
        indice = min(sum(a.pontos for a in validos), self.parametros["escala"]["maximo"])
        return {
            "indice_de_risco_percentual": round(indice, 1),
            "faixa": faixa_de_risco(indice, self.parametros),
            "alertas": [a.como_dict() for a in validos],
            "nota_juridica": (
                "Índice estatístico baseado exclusivamente em dados públicos. "
                "Não constitui acusação; exige verificação humana e garante "
                "presunção de inocência."
            ),
        }
