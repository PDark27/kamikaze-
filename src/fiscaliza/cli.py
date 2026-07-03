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
