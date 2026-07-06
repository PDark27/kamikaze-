"""Download de dumps públicos em escala: TSE (CKAN) e CNPJ (Receita Federal).

IMPORTANTE — execução real: este repositório roda em um sandbox que bloqueia
acesso a domínios `.gov.br`/`.jus.br`. As classes abaixo devem ser executadas
de verdade na máquina do usuário (fora do sandbox), onde a rede está
liberada. Nos testes automatizados deste projeto, injeta-se um
`httpx.Client(transport=httpx.MockTransport(...))` no parâmetro `http=` de
cada classe, para simular as respostas sem qualquer acesso de rede real.

Ambas as classes compartilham a mesma rotina de download resumível e atômico
(`_BaixadorHTTP._baixar_arquivo`): grava em um arquivo temporário `.part` e só
renomeia para o nome final ao terminar o streaming — assim uma queda de rede
no meio do download nunca deixa um arquivo corrompido marcado como "já
baixado". Se o arquivo final já existe, o download é pulado (retomada entre
execuções).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx

_TAMANHO_BLOCO = 1024 * 1024  # 1 MiB


class _BaixadorHTTP:
    """Mixin com o download resumível/atômico comum a TSE e CNPJ.

    Não é pensado para uso direto — apenas como base de `DumpsTSE` e
    `DumpsCNPJ`, que fornecem `self._http` (um `httpx.Client`, real ou com
    `MockTransport` injetado nos testes).
    """

    _http: httpx.Client

    def _baixar_arquivo(
        self,
        url: str,
        caminho: Path,
        progresso: Callable[[str, int, int], None] | None = None,
    ) -> Path:
        """Baixa `url` para `caminho` via streaming, com retomada e escrita
        atômica. Se `caminho` já existir, retorna sem baixar de novo."""
        if caminho.exists():
            return caminho

        caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo_tmp = caminho.with_suffix(caminho.suffix + ".part")

        with self._http.stream("GET", url) as resposta:
            resposta.raise_for_status()
            total = int(resposta.headers.get("content-length", 0))
            baixado = 0
            with open(arquivo_tmp, "wb") as f:
                for bloco in resposta.iter_bytes(_TAMANHO_BLOCO):
                    f.write(bloco)
                    baixado += len(bloco)
                    if progresso is not None:
                        progresso(caminho.name, baixado, total)

        arquivo_tmp.rename(caminho)
        return caminho


class DumpsTSE(_BaixadorHTTP):
    """Dumps do TSE via CKAN (`dadosabertos.tse.jus.br`).

    Os conjuntos de dados do TSE (candidaturas, bens, doações de campanha
    etc.) são publicados como pacotes CKAN: cada "pacote" tem vários
    "recursos" (arquivos), tipicamente CSVs zipados. `listar_recursos` usa o
    endpoint irmão de `package_search` (já usado em `fontes/tse.py`):
    `package_show?id=<id_pacote>`, que retorna os metadados completos do
    pacote incluindo a lista de `resources`.
    """

    base_ckan = "https://dadosabertos.tse.jus.br/api/3/action"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http if http is not None else httpx.Client(timeout=60)

    def listar_recursos(self, id_pacote: str) -> list[dict]:
        """Lista os recursos (arquivos) de um pacote CKAN do TSE.

        Cada item retornado tem, entre outras chaves, `url`, `name` e
        `format` (ex.: `"CSV"`, `"ZIP"`).
        """
        resposta = self._http.get(
            f"{self.base_ckan}/package_show", params={"id": id_pacote}
        )
        resposta.raise_for_status()
        return resposta.json()["result"]["resources"]

    def baixar_recursos(
        self,
        id_pacote: str,
        destino: str | Path = "dados/tse",
        somente_zip: bool = True,
        progresso: Callable[[str, int, int], None] | None = None,
    ) -> list[Path]:
        """Baixa todos os recursos CSV/ZIP de um pacote CKAN para `destino`.

        Arquivos já presentes em `destino` são pulados (retomada). Se
        `somente_zip` for `True` (padrão), filtra apenas recursos cujo
        `format` seja `"CSV"` ou `"ZIP"` (os dumps do TSE são csvs zipados;
        outros formatos do pacote, como documentação em PDF, são ignorados).
        """
        destino = Path(destino)
        recursos = self.listar_recursos(id_pacote)
        caminhos: list[Path] = []
        for recurso in recursos:
            formato = (recurso.get("format") or "").upper()
            if somente_zip and formato not in {"CSV", "ZIP"}:
                continue
            nome = recurso.get("name") or Path(recurso["url"]).name
            caminho = destino / nome
            caminhos.append(self._baixar_arquivo(recurso["url"], caminho, progresso))
        return caminhos


class DumpsCNPJ(_BaixadorHTTP):
    """Dumps de CNPJ da Receita Federal (arquivos abertos mensais).

    A Receita publica, mensalmente, um conjunto de arquivos ZIP (empresas,
    estabelecimentos, sócios e tabelas de domínio) em subpastas datadas, ex.
    `https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/2024-05/Empresas0.zip`.
    Nomes de arquivo reais e estáveis entre meses: `Empresas0.zip`,
    `Estabelecimentos0.zip`, `Socios0.zip`, `Cnaes.zip`, `Municipios.zip`,
    `Naturezas.zip`, `Qualificacoes.zip`, `Paises.zip` (o índice numérico
    varia conforme o particionamento do mês, ex. `Empresas0.zip` ...
    `Empresas9.zip`).
    """

    base_url = "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http if http is not None else httpx.Client(timeout=60)

    def baixar(
        self,
        nomes_arquivos: list[str],
        destino: str | Path = "dados/cnpj",
        subpasta: str | None = None,
        progresso: Callable[[str, int, int], None] | None = None,
    ) -> list[Path]:
        """Baixa uma lista de arquivos do dump de CNPJ para `destino`.

        `subpasta`, quando informada (ex. `"2024-05"`), é inserida na URL
        entre `base_url` e o nome do arquivo, refletindo o padrão real de
        pastas mensais da Receita Federal.
        """
        destino = Path(destino)
        prefixo = f"{subpasta}/" if subpasta else ""
        caminhos: list[Path] = []
        for nome in nomes_arquivos:
            url = f"{self.base_url}{prefixo}{nome}"
            caminho = destino / nome
            caminhos.append(self._baixar_arquivo(url, caminho, progresso))
        return caminhos
