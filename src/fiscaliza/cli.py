"""Interface de linha de comando do Fiscaliza."""

from __future__ import annotations

import json

import typer

app = typer.Typer(help="Cruzamento de bases públicas com índices de risco.")


@app.command()
def empresa(cnpj: str, com_ia: bool = typer.Option(False, help="Resumo via IA configurada")):
    """Perfil de risco de um CNPJ: cadastro, sócios, contratos e sanções."""
    from .fontes import PortalTransparencia, ReceitaCNPJ
    from .risco import MotorDeRisco

    receita = ReceitaCNPJ()
    dados = receita.empresa(cnpj)
    idade = receita.idade_em_dias(cnpj)

    portal = PortalTransparencia()
    contratos = portal.contratos_por_cnpj(cnpj)
    sancoes = portal.sancoes_ceis(cnpj)

    motor = MotorDeRisco()
    total_contratado = sum(float(c.get("valorInicial") or 0) for c in contratos)
    alertas = [
        motor.empresa_fachada([{
            "cnpj": cnpj,
            "capital_social": float(dados.get("capital_social") or 0),
            "valor_contratado": total_contratado,
            "tem_empregados": None,
            "endereco_residencial": False,
            "cnae_compativel": None,
        }]),
    ]
    resultado = motor.consolidar(alertas)
    resultado["cadastro"] = {
        "razao_social": dados.get("razao_social"),
        "abertura": dados.get("data_inicio_atividade"),
        "idade_dias": idade,
        "socios": [s.get("nome_socio") for s in (dados.get("qsa") or [])],
        "contratos_federais": len(contratos),
        "sancoes_ceis": len(sancoes),
    }
    typer.echo(json.dumps(resultado, ensure_ascii=False, indent=2))

    if com_ia and resultado["alertas"]:
        from .llm import obter_provedor
        typer.echo("\n--- Resumo da IA ---\n")
        typer.echo(obter_provedor().explicar(resultado["alertas"]))


@app.command()
def analisar(nome: str = typer.Option(..., help="Nome do agente público/candidato"),
             uf: str = typer.Option("", help="UF"),
             com_ia: bool = typer.Option(False)):
    """Busca vínculos de servidor no Executivo federal e monta dossiê inicial."""
    from .fontes import PortalTransparencia

    portal = PortalTransparencia()
    vinculos = portal.servidores_por_nome(nome)
    typer.echo(json.dumps({
        "consulta": nome, "uf": uf,
        "vinculos_encontrados": len(vinculos),
        "vinculos": vinculos[:10],
        "nota": "Use `fiscaliza empresa <cnpj>` para investigar CNPJs relacionados.",
    }, ensure_ascii=False, indent=2))


@app.command()
def candidato(
    nome: str = typer.Option(..., help="Nome de urna OU nome civil completo"),
    ano: int = typer.Option(2024, help="Ano da eleição"),
    uf: str = typer.Option(..., help="UF (ex.: SP) ou BR para presidente"),
    cargo: int = typer.Option(13, help="Código do cargo TSE (11=prefeito, 13=vereador, 6=dep. federal...)"),
    saida: str = typer.Option("cartoes", help="Diretório dos cartões HTML"),
    com_ia: bool = typer.Option(False, help="Resumo via IA configurada"),
):
    """Busca candidato no TSE (foto oficial + nome de urna) e gera cartão HTML."""
    from .cartao import gerar_cartao
    from .fontes import TSE
    from .risco import MotorDeRisco

    tse = TSE()
    detalhe = tse.buscar_candidato(ano, uf.upper(), nome, cargo)
    if not detalhe:
        typer.echo(f"Candidato '{nome}' não encontrado em {uf}/{ano} para o cargo {cargo}.")
        raise typer.Exit(1)

    ident = tse.identidade(detalhe)
    foto = tse.baixar_foto(detalhe)

    motor = MotorDeRisco()
    bens = detalhe.get("bens") or []
    total_bens = sum(float(b.get("valor") or 0) for b in bens)
    resultado = motor.consolidar([])  # indicadores dependem de cruzamentos posteriores
    resultado["contexto"] = {
        **ident,
        "total_bens_declarados": total_bens,
        "foto_local": str(foto) if foto else None,
    }

    from pathlib import Path
    cartao = gerar_cartao(ident, resultado, foto,
                          Path(saida) / f"{ident['sqcand']}.html")
    typer.echo(json.dumps(resultado, ensure_ascii=False, indent=2))
    typer.echo(f"\nCartão gerado: {cartao}")

    if com_ia and resultado["alertas"]:
        from .llm import obter_provedor
        typer.echo("\n--- Resumo da IA ---\n")
        typer.echo(obter_provedor().explicar(resultado["alertas"]))


@app.command()
def dossie(
    nome: str = typer.Option(..., help="Nome de urna OU nome civil completo"),
    ano: int = typer.Option(2024, help="Ano da eleição"),
    uf: str = typer.Option(..., help="UF (ex.: SP)"),
    cargo: int = typer.Option(13, help="Código do cargo TSE (11=prefeito, 13=vereador...)"),
    cnpj: list[str] = typer.Option([], help="CNPJs relacionados a cruzar (repetível)"),
    salvar: bool = typer.Option(False, help="Persistir no segundo cérebro (memoria/)"),
    com_ia: bool = typer.Option(False, help="Resumo via IA configurada"),
):
    """Dossiê completo: TSE + Receita + Transparência → índice de risco + markdown."""
    from .dossie import dossie_para_markdown, montar_dossie

    resultado = montar_dossie(nome, ano, uf.upper(), cargo, cnpjs_relacionados=list(cnpj))
    md = dossie_para_markdown(resultado)
    typer.echo(md)

    if salvar and resultado.get("encontrado", True):
        from .memoria import Memoria

        risco = resultado.get("risco", {})
        caminho = Memoria().salvar_dossie(
            "pessoas",
            resultado.get("identidade", {}).get("nome_completo") or nome,
            md,
            risco.get("indice_de_risco_percentual"),
            risco.get("faixa"),
        )
        typer.echo(f"\nDossiê salvo em {caminho}")

    if com_ia and resultado.get("risco", {}).get("alertas"):
        from .llm import obter_provedor

        typer.echo("\n--- Resumo da IA ---\n")
        typer.echo(obter_provedor().explicar(resultado["risco"]["alertas"]))


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", help="Endereço de escuta"),
    porta: int = typer.Option(8000, help="Porta"),
):
    """Sobe o aplicativo web local (busca de candidato + cartão + grafo)."""
    import uvicorn

    typer.echo(f"Fiscaliza web em http://{host}:{porta}/ (Ctrl+C para sair)")
    uvicorn.run("webapp.app:app", host=host, port=porta)


@app.command()
def ingerir(
    conjunto_tse: str = typer.Option("", help="Id do conjunto CKAN do TSE a baixar (ex.: candidatos-2024)"),
    destino: str = typer.Option("dados", help="Diretório de destino dos dumps"),
):
    """Baixa dumps públicos em massa (execute na sua máquina; exige rede .gov.br)."""
    from pathlib import Path

    from .ingestao import DumpsTSE

    if not conjunto_tse:
        typer.echo("Informe --conjunto-tse (ex.: candidatos-2024). "
                   "Depois carregue com BancoLocal e exporte com ExportadorNeo4j.")
        raise typer.Exit(1)
    dumps = DumpsTSE()
    baixados = dumps.baixar_recursos(conjunto_tse, Path(destino) / "tse")
    typer.echo(f"{len(baixados)} arquivo(s) em {destino}/tse")


@app.command()
def grafo(saida: str = typer.Option("grafo.graphml", help="Arquivo GraphML de saída")):
    """Exporta um grafo de exemplo com o esquema de relações do projeto."""
    from .grafo import GrafoDeRelacoes

    g = GrafoDeRelacoes()
    parlamentar = g.pessoa("exemplo-1", "Parlamentar Exemplo")
    parente = g.pessoa("exemplo-2", "Parente Exemplo")
    emp = g.empresa("00000000000191", "Empresa Exemplo LTDA")
    org = g.orgao("26000", "Ministério Exemplo")
    g.parente_de(parlamentar, parente, grau=1)
    g.socio_de(parente, emp)
    g.emendou_para(parlamentar, org, valor=1_000_000)
    g.contratou(org, emp, valor=950_000)
    g.salvar_graphml(saida)
    typer.echo(f"Grafo de exemplo salvo em {saida}. Ciclos: {g.ciclos_suspeitos()}")


if __name__ == "__main__":
    app()
