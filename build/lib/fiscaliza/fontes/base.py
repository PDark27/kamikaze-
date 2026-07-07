"""Cliente HTTP comum aos conectores, com repetição e limite de taxa simples."""

from __future__ import annotations

import time

import httpx


class ClienteBase:
    base_url: str = ""

    def __init__(self, cabecalhos: dict | None = None, pausa_segundos: float = 0.5):
        self._http = httpx.Client(
            base_url=self.base_url, headers=cabecalhos or {}, timeout=60
        )
        self._pausa = pausa_segundos

    def _get(self, caminho: str, **params) -> httpx.Response:
        for tentativa in range(4):
            resposta = self._http.get(caminho, params=params)
            if resposta.status_code == 429:  # limite de taxa da API pública
                time.sleep(2 ** (tentativa + 1))
                continue
            resposta.raise_for_status()
            time.sleep(self._pausa)
            return resposta
        resposta.raise_for_status()
        return resposta

    def get_json(self, caminho: str, **params):
        return self._get(caminho, **params).json()
