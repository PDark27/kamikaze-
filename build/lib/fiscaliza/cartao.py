"""Cartão visual do candidato: HTML autocontido com foto oficial da urna,
nome de urna em destaque, nome civil completo e índice de risco.

Sem servidor web: o arquivo abre direto no navegador e a foto vai embutida
em base64, então o cartão pode ser arquivado ou compartilhado sozinho.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

_CORES_FAIXA = [
    (25, "#2e7d32"),   # risco baixo — verde
    (55, "#f9a825"),   # moderado — âmbar
    (80, "#e65100"),   # alto — laranja
    (100, "#b71c1c"),  # muito alto — vermelho
]


def _cor(indice: float) -> str:
    for ate, cor in _CORES_FAIXA:
        if indice <= ate:
            return cor
    return _CORES_FAIXA[-1][1]


def _foto_data_uri(foto: Path | None) -> str | None:
    if not foto or not Path(foto).exists():
        return None
    dados = base64.b64encode(Path(foto).read_bytes()).decode()
    return f"data:image/jpeg;base64,{dados}"


def gerar_cartao(candidato: dict, resultado_risco: dict,
                 foto: Path | None, saida: str | Path) -> Path:
    """candidato: dict de TSE.identidade(); resultado_risco: MotorDeRisco.consolidar()."""
    indice = resultado_risco.get("indice_de_risco_percentual", 0)
    cor = _cor(indice)
    e = html.escape

    nome_urna = e(str(candidato.get("nome_urna") or "—"))
    nome_completo = e(str(candidato.get("nome_completo") or "—"))
    subtitulo = " · ".join(
        e(str(v)) for v in (candidato.get("numero"), candidato.get("partido"),
                            candidato.get("cargo")) if v
    )

    uri = _foto_data_uri(foto)
    bloco_foto = (
        f'<img src="{uri}" alt="Foto oficial da urna (TSE)">' if uri
        else '<div class="sem-foto">foto não disponível</div>'
    )

    alertas_html = "".join(
        f'<li><strong>{e(a["indicador"])}</strong> (+{a["pontos"]} pts) — '
        f'{e(a["descricao"])}</li>'
        for a in resultado_risco.get("alertas", [])
    ) or "<li>Nenhum sinal de alerta encontrado nas fontes consultadas.</li>"

    pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{nome_urna} — Fiscaliza</title>
<style>
 body {{ font-family: system-ui, sans-serif; background:#f4f4f4; margin:0; padding:2rem; }}
 .cartao {{ max-width:640px; margin:auto; background:#fff; border-radius:12px;
            box-shadow:0 2px 12px rgba(0,0,0,.15); overflow:hidden; }}
 header {{ display:flex; gap:1.25rem; padding:1.5rem; align-items:center; }}
 header img, .sem-foto {{ width:120px; height:160px; object-fit:cover;
            border-radius:8px; background:#ddd; }}
 .sem-foto {{ display:flex; align-items:center; justify-content:center;
            color:#888; font-size:.8rem; text-align:center; }}
 h1 {{ margin:0; font-size:1.6rem; }}
 .nome-civil {{ color:#555; margin:.25rem 0 0; }}
 .subtitulo {{ color:#777; margin:.25rem 0 0; font-size:.9rem; }}
 .risco {{ padding:1rem 1.5rem; color:#fff; background:{cor};
           display:flex; justify-content:space-between; align-items:center; }}
 .risco .valor {{ font-size:2rem; font-weight:700; }}
 section {{ padding:1rem 1.5rem; }}
 footer {{ padding:1rem 1.5rem; font-size:.75rem; color:#666;
           border-top:1px solid #eee; }}
</style></head><body>
<div class="cartao">
 <header>
  {bloco_foto}
  <div>
   <h1>{nome_urna}</h1>
   <p class="nome-civil">{nome_completo}</p>
   <p class="subtitulo">{subtitulo}</p>
  </div>
 </header>
 <div class="risco">
  <span>Índice de risco</span>
  <span class="valor">{indice}%</span>
  <span>{e(resultado_risco.get("faixa", ""))}</span>
 </div>
 <section>
  <h2>Sinais de alerta</h2>
  <ul>{alertas_html}</ul>
 </section>
 <footer>{e(resultado_risco.get("nota_juridica", ""))}
  Foto: divulgação oficial de candidatura (TSE).</footer>
</div>
</body></html>"""

    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(pagina, encoding="utf-8")
    return saida
