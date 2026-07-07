"""Busca de candidatos nos Dados Abertos oficiais do TSE, carregados em
banco local — o canal correto para acesso programático.

O site DivulgaCandContas é protegido por um escudo anti-robô (F5/TSPD) que
exige um navegador executando JavaScript; servidores não passam, e não é
papel deste projeto contornar proteções. O TSE distribui os mesmos dados em
massa, oficialmente, em ``cdn.tse.jus.br`` (conjunto "consulta_cand"): este
módulo baixa o zip anual, carrega as colunas relevantes em SQLite e responde
buscas por nome de urna ou nome civil em milissegundos, sem depender do site.

Uso típico (na máquina do usuário ou no boot do servidor):

    from fiscaliza.busca_local import ingerir_candidatos, BuscaLocal
    ingerir_candidatos(2024, ufs=["SP"])          # baixa e carrega uma vez
    BuscaLocal().buscar("ZE EXEMPLO", 2024, "SP", 13)
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import httpx

from .fontes.tse import _normalizar
from .ingestao.dumps import _BaixadorHTTP

URL_CONSULTA_CAND = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/"
    "consulta_cand_{ano}.zip"
)

# Colunas do dump oficial → colunas da tabela local (nome oficial é estável
# entre anos recentes; a leitura é pelo cabeçalho, não por posição).
_MAPA_COLUNAS = {
    "SQ_CANDIDATO": "sq_candidato",
    "NM_CANDIDATO": "nome",
    "NM_URNA_CANDIDATO": "nome_urna",
    "NR_CANDIDATO": "numero",
    "SG_PARTIDO": "partido",
    "DS_CARGO": "cargo",
    "CD_CARGO": "cd_cargo",
    "SG_UF": "uf",
    "ANO_ELEICAO": "ano",
}

_DDL = """CREATE TABLE IF NOT EXISTS candidatos (
    ano INTEGER, uf TEXT, cd_cargo INTEGER, cargo TEXT,
    sq_candidato TEXT, nome TEXT, nome_urna TEXT,
    nome_norm TEXT, nome_urna_norm TEXT, numero TEXT, partido TEXT
)"""


class _Baixador(_BaixadorHTTP):
    def __init__(self, http: httpx.Client | None = None):
        self._http = http if http is not None else httpx.Client(
            timeout=300, follow_redirects=True
        )


def ingerir_candidatos(
    ano: int,
    ufs: list[str] | None = None,
    caminho_db: str | Path = "dados/fiscaliza.db",
    pasta_dumps: str | Path = "dados/tse",
    http: httpx.Client | None = None,
    lote: int = 20_000,
) -> int:
    """Baixa o consulta_cand oficial do ano e carrega as UFs pedidas
    (todas, se ``ufs=None``) na tabela ``candidatos``. Idempotente por
    (ano, uf): re-ingerir substitui os registros daquele recorte.
    Retorna o total de candidatos inseridos."""
    import sqlite3

    zip_path = Path(pasta_dumps) / f"consulta_cand_{ano}.zip"
    _Baixador(http)._baixar_arquivo(URL_CONSULTA_CAND.format(ano=ano), zip_path)

    caminho_db = Path(caminho_db)
    caminho_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(caminho_db))
    conn.execute(_DDL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cand_busca ON candidatos"
                 "(ano, uf, cd_cargo)")

    alvo_ufs = {u.upper() for u in ufs} if ufs else None
    inseridos = 0
    with zipfile.ZipFile(zip_path) as zf:
        for membro in zf.namelist():
            if not membro.lower().endswith(".csv"):
                continue
            uf_membro = membro.rsplit("_", 1)[-1].removesuffix(".csv").upper()
            if alvo_ufs is not None and uf_membro not in alvo_ufs:
                continue
            with io.TextIOWrapper(zf.open(membro), encoding="latin-1",
                                  newline="") as f:
                leitor = csv.reader(f, delimiter=";")
                cabecalho = next(leitor, None)
                if not cabecalho:
                    continue
                indices = {}
                for oficial, local in _MAPA_COLUNAS.items():
                    if oficial in cabecalho:
                        indices[local] = cabecalho.index(oficial)
                if "sq_candidato" not in indices or "nome" not in indices:
                    continue  # csv de outro leiaute (ex.: complementar)

                with conn:
                    conn.execute(
                        "DELETE FROM candidatos WHERE ano=? AND uf=?",
                        (ano, uf_membro),
                    )
                    buffer = []
                    for linha in leitor:
                        def campo(chave: str) -> str:
                            i = indices.get(chave)
                            return linha[i] if i is not None and i < len(linha) else ""

                        nome, nome_urna = campo("nome"), campo("nome_urna")
                        buffer.append((
                            ano, uf_membro,
                            int(campo("cd_cargo") or 0), campo("cargo"),
                            campo("sq_candidato"), nome, nome_urna,
                            _normalizar(nome), _normalizar(nome_urna),
                            campo("numero"), campo("partido"),
                        ))
                        if len(buffer) >= lote:
                            conn.executemany(
                                "INSERT INTO candidatos VALUES "
                                "(?,?,?,?,?,?,?,?,?,?,?)", buffer)
                            inseridos += len(buffer)
                            buffer.clear()
                    if buffer:
                        conn.executemany(
                            "INSERT INTO candidatos VALUES "
                            "(?,?,?,?,?,?,?,?,?,?,?)", buffer)
                        inseridos += len(buffer)
    conn.close()
    return inseridos


class BuscaLocal:
    """Consulta a tabela ``candidatos`` carregada pelos Dados Abertos."""

    def __init__(self, caminho_db: str | Path = "dados/fiscaliza.db"):
        self._caminho = Path(caminho_db)

    def disponivel(self) -> bool:
        if not self._caminho.exists():
            return False
        import sqlite3

        conn = sqlite3.connect(str(self._caminho))
        try:
            existe = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='candidatos'").fetchone()
            return bool(existe)
        finally:
            conn.close()

    def buscar(self, nome: str, ano: int, uf: str,
               cd_cargo: int) -> dict | None:
        """Busca por nome de urna OU nome civil (sem acentos/caixa);
        devolve dict no formato de ``TSE.identidade`` ou ``None``."""
        if not self.disponivel():
            return None
        import sqlite3

        alvo = _normalizar(nome)
        conn = sqlite3.connect(str(self._caminho))
        try:
            linhas = conn.execute(
                "SELECT nome, nome_urna, numero, partido, cargo, sq_candidato,"
                " nome_norm, nome_urna_norm FROM candidatos "
                "WHERE ano=? AND uf=? AND cd_cargo=?",
                (ano, uf.upper(), cd_cargo),
            ).fetchall()
        finally:
            conn.close()

        for nome_c, urna, numero, partido, cargo, sq, n_norm, u_norm in linhas:
            if alvo in (n_norm, u_norm) or (
                alvo and (alvo in n_norm or alvo in u_norm)
            ):
                return {
                    "nome_completo": nome_c,
                    "nome_urna": urna,
                    "numero": numero,
                    "partido": partido,
                    "cargo": cargo,
                    "sqcand": sq,
                    "foto_url": None,  # fotos vêm em zip separado dos dados abertos
                }
        return None
