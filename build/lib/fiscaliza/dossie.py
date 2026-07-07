"""Monta o dossiê investigativo de um candidato, cruzando TSE, Receita,
Portal da Transparência e Banco Central através do ``MotorDeRisco``.

Este módulo não altera nenhuma fonte existente (``fiscaliza.fontes.*``) nem o
motor de risco; ele apenas orquestra as chamadas já expostas por eles e monta
o dossiê em Markdown no formato definido em
``.claude/skills/segundo-cerebro/SKILL.md``.

Contrato de erros (regra central deste módulo): qualquer chamada de rede
feita *depois* da busca inicial no TSE é envolvida em ``try/except`` — uma
falha vira uma entrada em ``erros_de_coleta`` e o dossiê continua sendo
montado com os dados disponíveis (listas vazias, fator de inflação neutro
etc.), sem derrubar a análise inteira por causa de uma fonte fora do ar.

Só a busca inicial do candidato no TSE é tratada como bloqueante:
- se ``tse.buscar_candidato(...)`` devolver ``None``, o candidato não foi
  encontrado nas bases do TSE para os parâmetros informados;
- se ``tse.buscar_candidato(...)`` *lançar* uma exceção (ex.: TSE fora do
  ar), a falha é capturada e reportada com o mesmo formato de retorno do
  caso anterior, mas com o texto real do erro em ``erro`` — para permitir
  diferenciar "não encontrado" de "falha de rede na busca inicial".

Em ambos os casos bloqueantes o retorno é
``{"encontrado": False, "erro": <mensagem>, "fontes_consultadas": [...],
"erros_de_coleta": [...]}`` (nunca ``None``), para manter visíveis as fontes
já tentadas mesmo quando a análise não pôde prosseguir.
"""

from __future__ import annotations

from datetime import date

from .fontes.tse import _normalizar

_SENTINELA_ORGAO = "candidato"


def montar_dossie(
    nome: str,
    ano: int,
    uf: str,
    cargo: int,
    *,
    tse=None,
    receita=None,
    portal=None,
    motor=None,
    bcb=None,
    cnpjs_relacionados: list[str] | None = None,
    codigo_eleicao: str | None = None,
    ano_eleicao_anterior: int | None = None,
) -> dict:
    """Monta o dossiê investigativo de um candidato.

    Parâmetros de fonte (``tse``, ``receita``, ``portal``, ``motor``,
    ``bcb``) aceitam qualquer objeto com a mesma interface das classes reais
    de ``fiscaliza.fontes``/``fiscaliza.risco`` — usado pelos testes para
    injetar fakes sem rede. Quando omitidos (``None``), as classes reais são
    instanciadas sob demanda (import local), evitando custo de import/rede
    quando um fake já foi injetado.

    ``cnpjs_relacionados``: lista de CNPJs a cruzar com Receita (sócios) e
    Portal da Transparência (contratos, sanções CEIS) em busca de vínculo
    societário do candidato (homônimo no quadro societário) e de sinais de
    empresa recém-criada/fachada nos contratos encontrados.

    Vínculo societário: como o cruzamento aqui não tem um "órgão contratante"
    real (é feito a partir do nome do candidato, não de um contrato
    específico de um órgão), usa-se o valor sentinela ``"candidato"`` tanto
    em ``orgao_contratante`` quanto em ``orgao_do_agente`` de cada vínculo
    homônimo — isso faz a regra existente de
    ``MotorDeRisco.vinculo_societario`` (que compara os dois campos) disparar
    de forma consistente sem inventar um indicador novo no motor.

    Ver o docstring do módulo para o contrato completo de tratamento de
    erros.
    """
    cnpjs_relacionados = cnpjs_relacionados or []
    erros: list[dict] = []
    fontes_consultadas: list[str] = []

    if tse is None:
        from .fontes import TSE

        tse = TSE()

    try:
        detalhe = tse.buscar_candidato(ano, uf, nome, cargo, codigo_eleicao)
    except Exception as exc:
        return {
            "encontrado": False,
            "erro": (
                f"Falha ao consultar o TSE para '{nome}' em {uf}/{ano} "
                f"(cargo {cargo}): {exc}"
            ),
            "fontes_consultadas": ["TSE"],
            "erros_de_coleta": [{"fonte": "TSE.buscar_candidato", "erro": str(exc)}],
        }

    fontes_consultadas.append("TSE")

    if detalhe is None:
        return {
            "encontrado": False,
            "erro": (
                f"Candidato '{nome}' não encontrado em {uf}/{ano} "
                f"para o cargo {cargo}."
            ),
            "fontes_consultadas": fontes_consultadas,
            "erros_de_coleta": erros,
        }

    identidade = tse.identidade(detalhe)

    try:
        foto = tse.baixar_foto(detalhe)
    except Exception as exc:
        foto = None
        erros.append({"fonte": "TSE.baixar_foto", "erro": str(exc)})

    bens = detalhe.get("bens") or []
    total_bens_declarados = sum(float(b.get("valor") or 0) for b in bens)

    if receita is None:
        from .fontes import ReceitaCNPJ

        receita = ReceitaCNPJ()
    if portal is None:
        from .fontes import PortalTransparencia

        portal = PortalTransparencia()
    if motor is None:
        from .risco import MotorDeRisco

        motor = MotorDeRisco()

    # ------------------------------------------------------------------ #
    # Evolução patrimonial: aceita tanto declarações já prontas quanto os
    # bens da eleição anterior (mesmo formato de `detalhe["bens"]`). Se
    # nenhuma das duas fontes existir, o indicador é apenas pulado (None),
    # sem gerar erro — candidato sem histórico não é uma falha de coleta.
    # ------------------------------------------------------------------ #
    declaracoes = detalhe.get("declaracoes_patrimoniais")
    if not declaracoes and detalhe.get("bens_eleicao_anterior") is not None:
        bens_anteriores = detalhe.get("bens_eleicao_anterior") or []
        total_anterior = sum(float(b.get("valor") or 0) for b in bens_anteriores)
        ano_anterior = ano_eleicao_anterior or (ano - 4)
        declaracoes = [
            {"ano": ano_anterior, "total_bens": total_anterior},
            {"ano": ano, "total_bens": total_bens_declarados},
        ]

    evolucao_alerta = None
    if declaracoes and len(declaracoes) >= 2:
        ordenadas = sorted(declaracoes, key=lambda d: d["ano"])
        fator = 1.0
        try:
            cliente_bcb = bcb
            if cliente_bcb is None:
                from .fontes import BancoCentral

                cliente_bcb = BancoCentral()
            fator = cliente_bcb.fator_ipca(
                f"01/01/{ordenadas[0]['ano']}", f"01/01/{ordenadas[-1]['ano']}"
            )
            fontes_consultadas.append("BCB")
        except Exception as exc:
            erros.append({"fonte": "BCB.fator_ipca", "erro": str(exc)})
            fator = 1.0
        evolucao_alerta = motor.evolucao_patrimonial(declaracoes, fator_inflacao=fator)

    # ------------------------------------------------------------------ #
    # Cruzamentos por CNPJ relacionado: contratos/sanções (Portal) e
    # sócios (Receita), em busca de homônimo do candidato no quadro
    # societário e de sinais de empresa recém-criada.
    # ------------------------------------------------------------------ #
    nome_candidato_normalizado = _normalizar(identidade.get("nome_completo") or "")
    vinculos_para_motor: list[dict] = []
    contratos_para_motor: list[dict] = []
    empresas_para_motor: list[dict] = []
    homonimos: list[dict] = []
    detalhe_por_cnpj: list[dict] = []

    for cnpj in cnpjs_relacionados:
        try:
            contratos = portal.contratos_por_cnpj(cnpj)
            if "Portal" not in fontes_consultadas:
                fontes_consultadas.append("Portal")
        except Exception as exc:
            contratos = []
            erros.append(
                {"fonte": "Portal.contratos_por_cnpj", "cnpj": cnpj, "erro": str(exc)}
            )

        try:
            sancoes = portal.sancoes_ceis(cnpj)
            if "Portal" not in fontes_consultadas:
                fontes_consultadas.append("Portal")
        except Exception as exc:
            sancoes = []
            erros.append(
                {"fonte": "Portal.sancoes_ceis", "cnpj": cnpj, "erro": str(exc)}
            )

        try:
            socios = receita.socios(cnpj)
            if "Receita" not in fontes_consultadas:
                fontes_consultadas.append("Receita")
        except Exception as exc:
            socios = []
            erros.append({"fonte": "Receita.socios", "cnpj": cnpj, "erro": str(exc)})

        detalhe_por_cnpj.append(
            {"cnpj": cnpj, "contratos": contratos, "sancoes": sancoes, "socios": socios}
        )

        for socio in socios:
            nome_socio = socio.get("nome_socio") or socio.get("nome") or ""
            if nome_candidato_normalizado and _normalizar(nome_socio) == (
                nome_candidato_normalizado
            ):
                homonimos.append(
                    {"cnpj": cnpj, "socio": nome_socio, "homonimo_do_candidato": True}
                )
                vinculos_para_motor.append(
                    {
                        "agente": nome_socio,
                        "parentesco_grau": 0,
                        "empresa_cnpj": cnpj,
                        "orgao_contratante": _SENTINELA_ORGAO,
                        "orgao_do_agente": _SENTINELA_ORGAO,
                    }
                )

        for contrato in contratos:
            data_abertura = contrato.get("data_abertura_empresa") or contrato.get(
                "dataAberturaEmpresa"
            )
            data_contrato = contrato.get("data_contrato") or contrato.get(
                "dataInicioVigencia"
            )
            if data_abertura and data_contrato:
                valor = contrato.get("valor") or contrato.get("valorInicial") or 0
                contratos_para_motor.append(
                    {
                        "cnpj": cnpj,
                        "data_abertura_empresa": data_abertura,
                        "data_contrato": data_contrato,
                        "valor": float(valor),
                    }
                )

        if socios:
            valor_contratado = sum(
                float(c.get("valor") or c.get("valorInicial") or 0) for c in contratos
            )
            empresas_para_motor.append(
                {
                    "cnpj": cnpj,
                    "capital_social": None,
                    "valor_contratado": valor_contratado,
                    "tem_empregados": None,
                    "endereco_residencial": False,
                    "cnae_compativel": None,
                }
            )

    alertas = [
        motor.vinculo_societario(vinculos_para_motor),
        motor.empresa_recem_criada(contratos_para_motor),
        motor.empresa_fachada(empresas_para_motor),
        evolucao_alerta,
    ]
    risco = motor.consolidar(alertas)

    return {
        "encontrado": True,
        "identidade": identidade,
        "foto_local": str(foto) if foto else None,
        "total_bens_declarados": total_bens_declarados,
        "risco": risco,
        "cnpjs_relacionados": cnpjs_relacionados,
        "homonimos": homonimos,
        "detalhe_por_cnpj": detalhe_por_cnpj,
        "fontes_consultadas": fontes_consultadas,
        "erros_de_coleta": erros,
    }


_NOTA_JURIDICA = (
    "Índice estatístico baseado exclusivamente em dados públicos. Não constitui\n"
    "acusação; exige verificação humana e garante presunção de inocência."
)


def dossie_para_markdown(dossie: dict) -> str:
    """Converte o dict retornado por ``montar_dossie`` no Markdown do
    modelo de dossiê descrito em
    ``.claude/skills/segundo-cerebro/SKILL.md``.

    Quando ``dossie["encontrado"]`` é ``False`` (candidato não encontrado ou
    falha na busca inicial), gera um Markdown curto com o erro em vez da
    tabela de achados — ainda assim mantendo a nota de presunção de
    inocência.
    """
    if not dossie.get("encontrado", False):
        erro = dossie.get("erro") or "Candidato não encontrado."
        return (
            "# Dossiê não concluído\n"
            f"- Erro: {erro}\n\n"
            "---\n"
            f"*{_NOTA_JURIDICA}*\n"
        )

    identidade = dossie.get("identidade") or {}
    risco = dossie.get("risco") or {}
    fontes = dossie.get("fontes_consultadas") or []
    foto = dossie.get("foto_local")
    nome_urna = identidade.get("nome_urna") or "não disponível"
    nome_civil = identidade.get("nome_completo") or "não disponível"
    titulo = nome_civil if nome_civil != "não disponível" else nome_urna

    def marca(fonte: str) -> str:
        return "x" if fonte in fontes else " "

    linhas = [
        f"# {titulo}",
        "- Chave: não disponível (TSE não expõe CPF)",
        f"- Nome de urna: {nome_urna}",
        f"- Nome civil completo: {nome_civil}",
        f"- Foto oficial: {foto or 'não disponível'}",
        (
            f"- Índice de risco atual: "
            f"{risco.get('indice_de_risco_percentual', 0)}% "
            f"({risco.get('faixa', 'não calculado')})"
        ),
        f"- Última atualização: {date.today().isoformat()}",
        "",
        "## Fontes já consultadas",
        f"- [{marca('Portal')}] Portal da Transparência (contratos, sanções, servidores)",
        f"- [{marca('TSE')}] TSE (candidaturas, bens, doações)",
        f"- [{marca('Receita')}] Receita/CNPJ (quadro societário, abertura)",
        f"- [{marca('BCB')}] IBGE / BCB (contexto e deflação)",
        "",
        "## Achados (evidências, nunca acusações)",
        "| Data | Indicador | Pontos | Evidência | Fonte/URL |",
        "|---|---|---|---|---|",
    ]

    hoje = date.today().isoformat()
    for alerta in risco.get("alertas") or []:
        evidencia = repr(alerta.get("evidencias"))
        if len(evidencia) > 200:
            evidencia = evidencia[:200] + "..."
        linhas.append(
            f"| {hoje} | {alerta.get('indicador')} | {alerta.get('pontos')} | "
            f"{evidencia} | dados públicos citados nas fontes acima |"
        )

    linhas += ["", "## Relações mapeadas (para o grafo)"]
    homonimos = dossie.get("homonimos") or []
    if homonimos:
        for homonimo in homonimos:
            linhas.append(f"- {nome_civil} —SOCIO_DE→ {homonimo.get('cnpj')}")
    else:
        linhas.append("_(nenhuma relação societária mapeada até o momento)_")

    linhas += [
        "",
        "## Hipóteses em aberto",
        "_(preenchido manualmente pelo investigador)_",
        "",
        "## Próximos passos",
        "_(preenchido manualmente pelo investigador)_",
        "",
        "---",
        f"*{_NOTA_JURIDICA}*",
    ]
    return "\n".join(linhas) + "\n"
