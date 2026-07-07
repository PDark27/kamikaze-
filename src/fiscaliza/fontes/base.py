"""Cliente HTTP comum aos conectores, com repetição e limite de taxa simples."""

from __future__ import annotations

import time

import httpx


# APIs governamentais costumam recusar user-agents de biblioteca (python-httpx);
# cabeçalhos de navegador evitam 403/406 indevidos em consultas legítimas.
_CABECALHOS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


class ClienteBase:
    base_url: str = ""

    def __init__(self, cabecalhos: dict | None = None, pausa_segundos: float = 0.5,
                 timeout_segundos: float = 60):
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={**_CABECALHOS_NAVEGADOR, **(cabecalhos or {})},
            timeout=timeout_segundos,
            follow_redirects=True,
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
