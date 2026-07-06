"""Servidor web local do Fiscaliza (FastAPI).

Roda na máquina do usuário; nenhum dado é enviado a terceiros além das
consultas às fontes públicas oficiais (TSE). O grafo é desenhado com
vis-network carregado via CDN, então a visualização exige internet no
navegador.

Iniciar:
    uvicorn webapp.app:app --reload
    # ou: python -m uvicorn webapp.app:app
Depois abrir http://127.0.0.1:8000/
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from fiscaliza.cartao import _cor
from fiscaliza.fontes.tse import CARGOS, TSE
from fiscaliza.grafo import GrafoDeRelacoes
from fiscaliza.risco import MotorDeRisco

app = FastAPI(title="Fiscaliza", description="Índices de risco a partir de dados públicos")

# Nota jurídica carregada do YAML local (sem rede) para o rodapé.
NOTA_JURIDICA = MotorDeRisco().consolidar([])["nota_juridica"]


def _grafo_exemplo() -> dict:
    """Ciclo parlamentar -> emenda -> orgao -> contrato -> empresa -> doacao ->
    parlamentar, materializando o padrao de maior interesse."""
    g = GrafoDeRelacoes()
    parlamentar = g.pessoa("exemplo-1", "Parlamentar Exemplo")
    parente = g.pessoa("exemplo-2", "Parente Exemplo")
    emp = g.empresa("00000000000191", "Empresa Exemplo LTDA")
    org = g.orgao("26000", "Ministério Exemplo")
    g.parente_de(parlamentar, parente, grau=1)
    g.socio_de(parente, emp)
    g.emendou_para(parlamentar, org, valor=1_000_000)
    g.contratou(org, emp, valor=950_000)
    g.doou_para(emp, parlamentar, valor=50_000)  # fecha o ciclo

    nodes = []
    for no, dados in g.g.nodes(data=True):
        item = {"id": no, "label": dados.get("nome", no), "group": dados.get("tipo", "No")}
        if dados.get("foto"):
            item["foto"] = dados["foto"]
        nodes.append(item)

    edges = []
    for origem, destino, dados in g.g.edges(data=True):
        aresta = {"from": origem, "to": destino, "label": dados.get("relacao", "")}
        if "valor" in dados:
            aresta["valor"] = dados["valor"]
        edges.append(aresta)

    return {"nodes": nodes, "edges": edges}


@app.get("/api/grafo/exemplo")
def grafo_exemplo() -> dict:
    return _grafo_exemplo()


@app.get("/api/candidato")
def api_candidato(
    nome: str = Query(..., min_length=1),
    ano: int = Query(2024),
    uf: str = Query(""),
    cargo: str = Query("vereador"),
):
    tse = TSE()
    codigo_cargo = CARGOS.get(cargo.lower().replace(" ", "_"), CARGOS["vereador"])
    try:
        detalhe = tse.buscar_candidato(ano, uf.upper(), nome, codigo_cargo)
    except (httpx.HTTPError, ConnectionError, OSError) as e:
        return JSONResponse(
            status_code=503,
            content={"erro": "fonte TSE indisponível", "detalhe": str(e)},
        )
    if detalhe is None:
        return JSONResponse(status_code=404, content={"erro": "candidato não encontrado"})

    ident = TSE.identidade(detalhe)
    total_bens = sum(float(b.get("valor") or 0) for b in (detalhe.get("bens") or []))
    risco = MotorDeRisco().consolidar([])
    risco["cor"] = _cor(risco["indice_de_risco_percentual"])
    return {
        "identidade": ident,
        "foto_url": ident["foto_url"],
        "total_bens": total_bens,
        "risco": risco,
    }


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _PAGINA


_PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fiscaliza</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
 body{font-family:system-ui,sans-serif;background:#f4f4f4;margin:0;padding:1.5rem;color:#222}
 h1.topo{margin:.2rem 0 1rem}
 form{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem}
 form input,form button{padding:.5rem;font-size:1rem}
 #cartao{max-width:640px;background:#fff;border-radius:12px;
   box-shadow:0 2px 12px rgba(0,0,0,.15);overflow:hidden;margin-bottom:1.5rem;display:none}
 #cartao header{display:flex;gap:1.25rem;padding:1.5rem;align-items:center}
 #cartao img,.sem-foto{width:120px;height:160px;object-fit:cover;border-radius:8px;background:#ddd}
 .sem-foto{display:flex;align-items:center;justify-content:center;color:#888;font-size:.8rem;text-align:center}
 #cartao h2{margin:0;font-size:1.6rem}
 .nome-civil{color:#555;margin:.25rem 0 0}
 .subtitulo{color:#777;margin:.25rem 0 0;font-size:.9rem}
 .badge-risco{padding:1rem 1.5rem;color:#fff;display:flex;justify-content:space-between;align-items:center}
 .badge-risco .valor{font-size:2rem;font-weight:700}
 #grafo{width:100%;height:460px;border:1px solid #ddd;border-radius:12px;background:#fff}
 footer{margin-top:1.5rem;font-size:.75rem;color:#666}
 #erro{color:#b71c1c;margin:.5rem 0}
</style></head><body>
<h1 class="topo">Fiscaliza</h1>
<form id="busca">
 <input id="nome" placeholder="Nome de urna ou civil" required>
 <input id="ano" value="2024" size="5" placeholder="Ano">
 <input id="uf" size="3" placeholder="UF">
 <input id="cargo" value="vereador" placeholder="Cargo">
 <button type="submit">Buscar</button>
</form>
<div id="erro"></div>

<div id="cartao">
 <header>
  <div id="foto-box"></div>
  <div>
   <h2 id="nome-urna"></h2>
   <p class="nome-civil" id="nome-civil"></p>
   <p class="subtitulo" id="subtitulo"></p>
   <p class="subtitulo" id="bens"></p>
  </div>
 </header>
 <div class="badge-risco" id="badge-risco">
  <span>Índice de risco</span>
  <span class="valor" id="risco-valor"></span>
  <span id="risco-faixa"></span>
 </div>
</div>

<h3>Grafo de relações (exemplo do padrão investigado)</h3>
<div id="grafo"></div>

<footer id="nota">__NOTA_JURIDICA__</footer>

<script>
const CORES_GRUPO = {Pessoa:"#1565c0", Empresa:"#6a1b9a", Orgao:"#2e7d32"};

async function buscar(ev){
  ev.preventDefault();
  const erro = document.getElementById("erro"); erro.textContent = "";
  const q = new URLSearchParams({
    nome: document.getElementById("nome").value,
    ano: document.getElementById("ano").value,
    uf: document.getElementById("uf").value,
    cargo: document.getElementById("cargo").value,
  });
  let r, d;
  try { r = await fetch("/api/candidato?"+q); d = await r.json(); }
  catch(e){ erro.textContent = "Falha de conexão."; return; }
  if(!r.ok){ erro.textContent = d.erro || "Erro na busca."; document.getElementById("cartao").style.display="none"; return; }
  preencherCartao(d);
}

function preencherCartao(d){
  const id = d.identidade;
  document.getElementById("nome-urna").textContent = id.nome_urna || "—";
  document.getElementById("nome-civil").textContent = id.nome_completo || "—";
  document.getElementById("subtitulo").textContent =
    [id.numero, id.partido, id.cargo].filter(Boolean).join(" · ");
  document.getElementById("bens").textContent =
    "Bens declarados: R$ " + (d.total_bens || 0).toLocaleString("pt-BR");
  const fb = document.getElementById("foto-box");
  fb.innerHTML = d.foto_url
    ? '<img src="'+d.foto_url+'" alt="Foto oficial da urna (TSE)">'
    : '<div class="sem-foto">foto não disponível</div>';
  const badge = document.getElementById("badge-risco");
  badge.style.background = d.risco.cor;   // cor calculada no backend com _cor
  document.getElementById("risco-valor").textContent = d.risco.indice_de_risco_percentual + "%";
  document.getElementById("risco-faixa").textContent = d.risco.faixa || "";
  document.getElementById("cartao").style.display = "block";
}

async function desenharGrafo(){
  const d = await (await fetch("/api/grafo/exemplo")).json();
  const nodes = d.nodes.map(n => ({id:n.id, label:n.label, group:n.group,
      color: CORES_GRUPO[n.group], title:"["+n.group+"] "+n.label}));
  const edges = d.edges.map(e => ({from:e.from, to:e.to,
      label:e.label + (e.valor!=null ? " (R$ "+e.valor.toLocaleString("pt-BR")+")" : ""),
      arrows:"to"}));
  const container = document.getElementById("grafo");
  const network = new vis.Network(container,
    {nodes:new vis.DataSet(nodes), edges:new vis.DataSet(edges)},
    {physics:{stabilization:true}, edges:{font:{size:11, align:"middle"}}});
  network.on("click", p => {
    if(p.nodes.length){ const n = nodes.find(x=>x.id===p.nodes[0]); alert(n.title); }
  });
}

document.getElementById("busca").addEventListener("submit", buscar);
desenharGrafo();
</script>
</body></html>""".replace("__NOTA_JURIDICA__", NOTA_JURIDICA)
