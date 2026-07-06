"""Carga de dumps CSV/ZIP em um banco SQLite local, por lotes.

Usa apenas a biblioteca padrão (`sqlite3`, `zipfile`, `csv`, `io`) — sem
pandas. Pensado para os dumps de TSE/CNPJ: arquivos grandes, sem cabeçalho
padronizado consistente entre datasets, tipicamente zipados e em
`latin-1`/`;`-separado.
"""

from __future__ import annotations

import csv
import io
import logging
import sqlite3
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


class BancoLocal:
    """Banco SQLite local para carga em massa de dumps públicos.

    `carregar_csv` infere colunas posicionais `TEXT` (`col_0`, `col_1`, ...)
    quando `colunas=None`, porque os dumps públicos de TSE/RFB não têm um
    único cabeçalho estável entre arquivos/anos — o chamador que conhece o
    esquema de um arquivo específico pode passar `colunas={"cnpj": "TEXT",
    "capital_social": "REAL", ...}` para nomear e tipar os campos.
    """

    def __init__(self, caminho: str | Path = "dados/fiscaliza.db"):
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(caminho))

    def __enter__(self) -> "BancoLocal":
        return self

    def __exit__(self, *_exc) -> None:
        self.fechar()

    def _abrir_texto(
        self, caminho: Path, encoding: str, membro_zip: str | None
    ) -> io.TextIOBase:
        if caminho.suffix.lower() == ".zip" or membro_zip is not None:
            zf = zipfile.ZipFile(caminho)
            nome_membro = membro_zip
            if nome_membro is None:
                candidatos = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                nome_membro = candidatos[0] if candidatos else zf.namelist()[0]
            return io.TextIOWrapper(zf.open(nome_membro), encoding=encoding, newline="")
        return open(caminho, encoding=encoding, newline="")

    def carregar_csv(
        self,
        caminho: str | Path,
        tabela: str,
        colunas: dict[str, str] | None = None,
        separador: str = ";",
        encoding: str = "latin-1",
        lote: int = 50_000,
        membro_zip: str | None = None,
    ) -> int:
        """Carrega um CSV (opcionalmente dentro de um ZIP) em `tabela`.

        Retorna o número de linhas efetivamente inseridas. Linhas com número
        de campos diferente do esperado são logadas e puladas — não entram
        na contagem retornada (decisão de simplicidade: a função reporta
        apenas o volume inserido com sucesso, não uma tupla inseridas/
        ignoradas).
        """
        caminho = Path(caminho)
        f = self._abrir_texto(caminho, encoding, membro_zip)
        linhas_inseridas = 0
        try:
            leitor = csv.reader(f, delimiter=separador)
            try:
                primeira_linha = next(leitor)
            except StopIteration:
                return 0

            if colunas is None:
                n_campos = len(primeira_linha)
                nomes_colunas = [f"col_{i}" for i in range(n_campos)]
                tipos_colunas = ["TEXT"] * n_campos
            else:
                nomes_colunas = list(colunas.keys())
                tipos_colunas = list(colunas.values())
                n_campos = len(nomes_colunas)

            definicao = ", ".join(
                f'"{nome}" {tipo}' for nome, tipo in zip(nomes_colunas, tipos_colunas)
            )
            self._conn.execute(f'CREATE TABLE IF NOT EXISTS "{tabela}" ({definicao})')

            marcadores = ", ".join("?" for _ in nomes_colunas)
            colunas_sql = ", ".join(f'"{nome}"' for nome in nomes_colunas)
            sql_insert = f'INSERT INTO "{tabela}" ({colunas_sql}) VALUES ({marcadores})'

            def linhas_validas():
                for linha in (primeira_linha, *leitor):
                    if len(linha) != n_campos:
                        logger.warning(
                            "linha ignorada em %s: esperado %d campos, recebido %d",
                            caminho, n_campos, len(linha),
                        )
                        continue
                    yield tuple(linha)

            buffer: list[tuple] = []
            with self._conn:
                for linha in linhas_validas():
                    buffer.append(linha)
                    if len(buffer) >= lote:
                        self._conn.executemany(sql_insert, buffer)
                        linhas_inseridas += len(buffer)
                        buffer.clear()
                if buffer:
                    self._conn.executemany(sql_insert, buffer)
                    linhas_inseridas += len(buffer)

            return linhas_inseridas
        finally:
            f.close()

    def criar_indice(self, tabela: str, coluna: str) -> None:
        """Cria (se ainda não existir) um índice `idx_<tabela>_<coluna>`."""
        nome_indice = f"idx_{tabela}_{coluna}"
        self._conn.execute(
            f'CREATE INDEX IF NOT EXISTS "{nome_indice}" ON "{tabela}"("{coluna}")'
        )
        self._conn.commit()

    def executar(self, sql: str, params: tuple = ()) -> None:
        with self._conn:
            self._conn.execute(sql, params)

    def consultar(self, sql: str, params: tuple = ()) -> list[tuple]:
        cursor = self._conn.execute(sql, params)
        return cursor.fetchall()

    def fechar(self) -> None:
        self._conn.close()
