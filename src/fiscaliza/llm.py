"""Camada de IA plugável — o cliente escolhe o provedor via FISCALIZA_LLM.

Provedores suportados: anthropic (Claude), openai (GPT), ollama (modelos
locais). Todos implementam a mesma interface: ``explicar(alertas) -> str``.
A IA nunca gera acusações: recebe instrução de sistema para redigir em
linguagem neutra, citar evidências e sugerir passos de verificação.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

import httpx

INSTRUCAO_SISTEMA = (
    "Você é um analista de integridade pública. Receberá alertas gerados por "
    "cruzamento de dados públicos brasileiros, cada um com um índice de risco "
    "percentual e evidências. Redija um resumo em português, em linguagem "
    "estritamente neutra e factual: NUNCA afirme que houve corrupção, fraude ou "
    "crime; descreva apenas os sinais encontrados, o percentual de risco e os "
    "passos de verificação recomendados (fontes oficiais a consultar, documentos "
    "a requisitar via LAI, órgãos de controle competentes). Lembre o leitor da "
    "presunção de inocência."
)


class ProvedorLLM(ABC):
    @abstractmethod
    def explicar(self, alertas: list[dict]) -> str: ...

    def _prompt(self, alertas: list[dict]) -> str:
        return (
            "Alertas gerados pelo motor de risco (JSON):\n"
            + json.dumps(alertas, ensure_ascii=False, indent=2)
            + "\n\nProduza o resumo analítico."
        )


class Anthropic(ProvedorLLM):
    def __init__(self, modelo: str | None = None):
        import anthropic

        self.cliente = anthropic.Anthropic()
        self.modelo = modelo or os.environ.get("FISCALIZA_LLM_MODELO", "claude-sonnet-5")

    def explicar(self, alertas: list[dict]) -> str:
        resposta = self.cliente.messages.create(
            model=self.modelo,
            max_tokens=2000,
            system=INSTRUCAO_SISTEMA,
            messages=[{"role": "user", "content": self._prompt(alertas)}],
        )
        return resposta.content[0].text


class OpenAI(ProvedorLLM):
    def __init__(self, modelo: str | None = None):
        import openai

        self.cliente = openai.OpenAI()
        self.modelo = modelo or os.environ.get("FISCALIZA_LLM_MODELO", "gpt-4o")

    def explicar(self, alertas: list[dict]) -> str:
        resposta = self.cliente.chat.completions.create(
            model=self.modelo,
            messages=[
                {"role": "system", "content": INSTRUCAO_SISTEMA},
                {"role": "user", "content": self._prompt(alertas)},
            ],
        )
        return resposta.choices[0].message.content


class Ollama(ProvedorLLM):
    """Modelos locais (privacidade total dos dados analisados)."""

    def __init__(self, modelo: str | None = None, host: str | None = None):
        self.modelo = modelo or os.environ.get("FISCALIZA_LLM_MODELO", "llama3.1")
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def explicar(self, alertas: list[dict]) -> str:
        resposta = httpx.post(
            f"{self.host}/api/chat",
            json={
                "model": self.modelo,
                "stream": False,
                "messages": [
                    {"role": "system", "content": INSTRUCAO_SISTEMA},
                    {"role": "user", "content": self._prompt(alertas)},
                ],
            },
            timeout=300,
        )
        resposta.raise_for_status()
        return resposta.json()["message"]["content"]


_PROVEDORES = {"anthropic": Anthropic, "openai": OpenAI, "ollama": Ollama}


def obter_provedor(nome: str | None = None) -> ProvedorLLM:
    nome = (nome or os.environ.get("FISCALIZA_LLM", "anthropic")).lower()
    if nome not in _PROVEDORES:
        raise ValueError(f"Provedor desconhecido: {nome}. Opções: {sorted(_PROVEDORES)}")
    return _PROVEDORES[nome]()
