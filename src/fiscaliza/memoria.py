"""Segundo cérebro: memória investigativa persistente do Fiscaliza.

Mantém dossiês Markdown por entidade (pessoas/empresas/contratos), um índice
geral (`INDICE.md`) e hipóteses de conexão entre entidades (`hipoteses/`),
conforme `.claude/skills/segundo-cerebro/SKILL.md`.

Regra jurídica inegociável: CPFs nunca podem aparecer completos em texto
salvo em `memoria/`. Só o formato mascarado do Portal da Transparência
(`***XXXXXX**`) é aceito; qualquer sequência de 11 dígitos contíguos ou o
formato `000.000.000-00` levanta `ValueError` antes de gravar.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

_CABECALHO_INDICE = (
    "# Índice — memória investigativa\n\n"
    "| Entidade | Arquivo | Índice de risco | Faixa | Atualizado |\n"
    "|---|---|---|---|---|\n"
)

_CPF_11_DIGITOS = re.compile(r"\b\d{11}\b")
_CPF_FORMATADO = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")


def slug(texto: str) -> str:
    """Normaliza `texto` para um identificador `[a-z0-9-]`, sem acentos.

    Remove marcas diacríticas via `unicodedata` (NFKD + descarte de
    combining marks), depois substitui qualquer sequência de caracteres que
    não sejam letras/dígitos por um único hífen, sem hífen nas pontas.
    """
    sem_acentos = unicodedata.normalize("NFKD", texto)
    sem_acentos = "".join(c for c in sem_acentos if not unicodedata.combining(c))
    minusculo = sem_acentos.lower()
    com_hifens = re.sub(r"[^a-z0-9]+", "-", minusculo)
    return com_hifens.strip("-")


def _validar_cpf_mascarado(conteudo_md: str) -> None:
    """Levanta `ValueError` se houver CPF não mascarado no conteúdo.

    Padrões proibidos: 11 dígitos contíguos (`\\b\\d{11}\\b`) ou o formato
    completo `000.000.000-00`. O formato mascarado oficial `***123456**`
    tem apenas 6 dígitos contíguos, portanto não colide com a regra.

    Limitação conhecida (aceita pela especificação): a regra de 11 dígitos
    contíguos pode colidir com outros números grandes não relacionados a
    CPF (ex.: valores monetários sem separadores). É uma simplificação
    deliberada da spec.
    """
    if _CPF_11_DIGITOS.search(conteudo_md) or _CPF_FORMATADO.search(conteudo_md):
        raise ValueError(
            "CPF não mascarado encontrado no conteúdo do dossiê — "
            "use o formato mascarado ***XXXXXX** (como publicado pelo "
            "Portal da Transparência)."
        )


def _formatar_indice_risco(indice_risco: float | None) -> str:
    if indice_risco is None:
        return "-"
    return f"{indice_risco:.1f}%"


def _formatar_faixa(faixa: str | None) -> str:
    return faixa if faixa is not None else "-"


def _parse_linhas_indice(conteudo: str) -> list[list[str]]:
    """Extrai as linhas de dados da tabela do INDICE.md (sem cabeçalho/separador)."""
    linhas: list[list[str]] = []
    for linha in conteudo.splitlines():
        linha = linha.strip()
        if not linha.startswith("|"):
            continue
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        if not celulas or celulas[0] in ("Entidade",):
            continue
        if set(celulas[0]) <= {"-"} and celulas[0] != "":
            continue
        if all(set(c) <= {"-"} for c in celulas):
            continue
        linhas.append(celulas)
    return linhas


class Memoria:
    """Ponto único de acesso à memória investigativa persistente."""

    def __init__(self, raiz: Path | str = Path("memoria")):
        self.raiz = Path(raiz)

    # ------------------------------------------------------------------ #

    def _caminho_dossie(self, tipo: str, chave: str) -> Path:
        return self.raiz / tipo / f"{slug(chave)}.md"

    def _caminho_indice(self) -> Path:
        return self.raiz / "INDICE.md"

    def _caminho_hipotese(self, entidade_a: str, entidade_b: str) -> Path:
        slug_a, slug_b = sorted([slug(entidade_a), slug(entidade_b)])
        return self.raiz / "hipoteses" / f"{slug_a}--{slug_b}.md"

    # ------------------------------------------------------------------ #

    def salvar_dossie(
        self,
        tipo: str,
        chave: str,
        conteudo_md: str,
        indice_risco: float | None = None,
        faixa: str | None = None,
    ) -> Path:
        """Grava (ou substitui) o dossiê Markdown de `chave` e atualiza o índice.

        Levanta `ValueError` se `conteudo_md` contiver um CPF não mascarado.
        """
        _validar_cpf_mascarado(conteudo_md)
        caminho = self._caminho_dossie(tipo, chave)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo_md, encoding="utf-8")

        arquivo_relativo = f"{tipo}/{slug(chave)}.md"
        self.atualizar_indice(
            entidade=chave,
            arquivo=arquivo_relativo,
            indice_risco=indice_risco,
            faixa=faixa,
        )
        return caminho

    def ler_dossie(self, tipo: str, chave: str) -> str | None:
        """Retorna o conteúdo do dossiê ou `None` se não existir."""
        caminho = self._caminho_dossie(tipo, chave)
        if not caminho.exists():
            return None
        return caminho.read_text(encoding="utf-8")

    def atualizar_indice(
        self,
        entidade: str,
        arquivo: str,
        indice_risco: float | None,
        faixa: str | None,
    ) -> Path:
        """Insere ou atualiza (idempotente por `slug(entidade)`) a linha de `entidade`."""
        caminho = self._caminho_indice()
        linhas: list[list[str]] = []
        if caminho.exists():
            linhas = _parse_linhas_indice(caminho.read_text(encoding="utf-8"))

        nova_linha = [
            entidade,
            arquivo,
            _formatar_indice_risco(indice_risco),
            _formatar_faixa(faixa),
            date.today().isoformat(),
        ]

        slug_alvo = slug(entidade)
        atualizado = False
        for i, linha in enumerate(linhas):
            if slug(linha[0]) == slug_alvo:
                linhas[i] = nova_linha
                atualizado = True
                break
        if not atualizado:
            linhas.append(nova_linha)

        corpo = "".join("| " + " | ".join(linha) + " |\n" for linha in linhas)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(_CABECALHO_INDICE + corpo, encoding="utf-8")
        return caminho

    def registrar_conexao(self, entidade_a: str, entidade_b: str, descricao: str) -> Path:
        """Cria/atualiza `memoria/hipoteses/<slug-a>--<slug-b>.md` (slugs ordenados).

        Não duplica `descricao` já registrada (comparação exata, após trim).
        """
        caminho = self._caminho_hipotese(entidade_a, entidade_b)
        caminho.parent.mkdir(parents=True, exist_ok=True)

        descricao = descricao.strip()

        if caminho.exists():
            conteudo = caminho.read_text(encoding="utf-8")
        else:
            conteudo = (
                f"# Hipótese: {entidade_a} × {entidade_b}\n\n"
                "## Dossiês envolvidos\n"
                f"- {entidade_a}\n"
                f"- {entidade_b}\n\n"
                "## Descrições\n"
            )

        ja_presente = any(
            linha.strip().lstrip("-").strip() == descricao
            for linha in conteudo.splitlines()
        )
        if not ja_presente:
            if not conteudo.endswith("\n"):
                conteudo += "\n"
            conteudo += f"- {descricao}\n"

        caminho.write_text(conteudo, encoding="utf-8")
        return caminho

    def resumo(self) -> dict:
        """Contagens por tipo (a partir da coluna Arquivo) + top-5 por índice de risco."""
        caminho = self._caminho_indice()
        if not caminho.exists():
            return {"total": 0, "por_tipo": {}, "top_5": []}

        linhas = _parse_linhas_indice(caminho.read_text(encoding="utf-8"))

        por_tipo: dict[str, int] = {}
        registros = []
        for linha in linhas:
            entidade, arquivo, indice_risco_str, faixa, atualizado = linha
            tipo = arquivo.split("/")[0] if "/" in arquivo else arquivo
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1

            valor_risco = None
            if indice_risco_str.endswith("%"):
                try:
                    valor_risco = float(indice_risco_str[:-1])
                except ValueError:
                    valor_risco = None

            registros.append({
                "entidade": entidade,
                "arquivo": arquivo,
                "indice_risco": valor_risco,
                "faixa": faixa,
                "atualizado": atualizado,
            })

        top_5 = sorted(
            (r for r in registros if r["indice_risco"] is not None),
            key=lambda r: r["indice_risco"],
            reverse=True,
        )[:5]

        return {
            "total": len(registros),
            "por_tipo": por_tipo,
            "top_5": top_5,
        }
