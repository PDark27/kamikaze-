"""Servidor web local do Fiscaliza (FastAPI) — app instalável (PWA).

Roda na máquina do usuário; nenhum dado é enviado a terceiros além das
consultas às fontes públicas oficiais (TSE). O grafo é desenhado com
vis-network carregado via CDN, então a visualização exige internet no
navegador. O app é um PWA: aberto no Chrome/Edge/Android, o navegador
oferece "Instalar aplicativo" / "Adicionar à tela inicial" — instalação
gratuita, sem loja.

Iniciar:
    uvicorn webapp.app:app --reload
    # ou: fiscaliza web
Depois abrir http://127.0.0.1:8000/
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Query, Response
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


def _consultar_tse_cru(tse: TSE) -> httpx.Response:
    """Consulta crua ao TSE (sem raise_for_status/parse), para diagnóstico."""
    return tse._http.get("/eleicao/ordinarias")


@app.get("/api/diagnostico")
def api_diagnostico():
    """Testa a conectividade do servidor com o TSE e devolve o veredito.

    Abra /api/diagnostico no navegador para saber se a hospedagem consegue
    alcançar o TSE (geobloqueio de IP estrangeiro é a suspeita usual quando
    o app roda fora do Brasil). Mostra o status HTTP, o content-type e uma
    amostra do corpo devolvido — o suficiente para diferenciar API saudável,
    página de bloqueio e queda de rede. Nunca levanta 500: qualquer surpresa
    vira relatório.
    """
    import time as _time

    tse = TSE(timeout_segundos=12)
    inicio = _time.monotonic()
    try:
        resposta = _consultar_tse_cru(tse)
        latencia = int((_time.monotonic() - inicio) * 1000)
        tipo = resposta.headers.get("content-type", "")
        if resposta.status_code == 200 and "json" in tipo:
            return {
                "tse": "ok",
                "latencia_ms": latencia,
                "conclusao": "O servidor alcança o TSE; buscas devem funcionar.",
            }
        return JSONResponse(status_code=503, content={
            "tse": "falha",
            "detalhe": f"HTTP {resposta.status_code}, content-type '{tipo}'",
            "amostra_resposta": resposta.text[:300],
            "latencia_ms": latencia,
            "conclusao": (
                "O TSE respondeu, mas não com a API (provável página de "
                "bloqueio a IP estrangeiro/robô). Solução: hospedar em "
                "servidor com IP brasileiro."
            ),
        })
    except Exception as e:  # diagnóstico nunca pode virar 500
        return JSONResponse(status_code=503, content={
            "tse": "falha",
            "detalhe": f"{type(e).__name__}: {e}",
            "conclusao": (
                "O servidor não conseguiu conexão com o TSE (provável "
                "bloqueio de rede/geolocalização; considere hospedar em "
                "IP brasileiro)."
            ),
        })


@app.get("/api/candidato")
def api_candidato(
    nome: str = Query(..., min_length=1),
    ano: int = Query(2024),
    uf: str = Query(""),
    cargo: str = Query("vereador"),
):
    # timeout curto: melhor um 503 com diagnóstico do que o proxy da
    # hospedagem cortar a conexão e o navegador ver erro genérico
    tse = TSE(timeout_segundos=20)
    codigo_cargo = CARGOS.get(cargo.lower().replace(" ", "_"), CARGOS["vereador"])
    try:
        detalhe = tse.buscar_candidato(ano, uf.upper(), nome, codigo_cargo)
    except ValueError as e:  # resposta 200 porém não-JSON (página de bloqueio)
        return JSONResponse(
            status_code=503,
            content={
                "erro": "fonte TSE indisponível",
                "detalhe": "TSE devolveu conteúdo inesperado (não-JSON) — "
                           "consulte /api/diagnostico",
            },
        )
    except (httpx.HTTPError, ConnectionError, OSError) as e:
        if isinstance(e, httpx.HTTPStatusError):
            diagnostico = (
                f"HTTP {e.response.status_code} ao consultar "
                f"{e.request.url.host}"
            )
        else:
            diagnostico = f"{type(e).__name__}: {e}"
        return JSONResponse(
            status_code=503,
            content={"erro": "fonte TSE indisponível", "detalhe": diagnostico},
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


# ------------------------------------------------------------------ #
# PWA: manifesto, service worker e ícone — instalação gratuita
# ------------------------------------------------------------------ #

_ICONE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<rect width="128" height="128" rx="28" fill="#14343B"/>
<ellipse cx="64" cy="64" rx="42" ry="26" fill="none" stroke="#F2F4F3" stroke-width="7"/>
<circle cx="64" cy="64" r="13" fill="#E8A61A"/>
<circle cx="64" cy="64" r="5" fill="#14343B"/>
</svg>"""


@app.get("/icone.svg")
def icone() -> Response:
    return Response(content=_ICONE_SVG, media_type="image/svg+xml")


@app.get("/manifest.webmanifest")
def manifesto() -> Response:
    import json

    manifesto = {
        "name": "Fiscaliza — dados públicos, olhos abertos",
        "short_name": "Fiscaliza",
        "description": "Índices de risco calculados a partir de bases públicas oficiais.",
        "lang": "pt-BR",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#F2F4F3",
        "theme_color": "#14343B",
        "icons": [
            {"src": "/icone.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
            {"src": "/icone.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "maskable"},
        ],
    }
    return Response(
        content=json.dumps(manifesto, ensure_ascii=False),
        media_type="application/manifest+json",
    )


_SW_JS = """// Service worker do Fiscaliza: casca offline, APIs sempre pela rede.
const CACHE = "fiscaliza-v1";
const CASCA = ["/", "/manifest.webmanifest", "/icone.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CASCA)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) =>
      Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return; // dados sempre frescos
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copia = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copia));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
"""


@app.get("/sw.js")
def service_worker() -> Response:
    return Response(content=_SW_JS, media_type="application/javascript")


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _PAGINA


# Identidade visual: "jornalismo de dados" apartidário — papel frio, tinta
# petróleo, manchete serifada, números em mono tabular, âmbar como único
# acento de ação. As cores de risco (verde→vermelho) são semânticas e não
# participam do acento. Temas claro/escuro por tokens (data-theme vence a
# preferência do sistema nas duas direções).
_PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#14343B">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icone.svg" type="image/svg+xml">
<title>Fiscaliza — dados públicos, olhos abertos</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
:root{
  --papel:#F2F4F3; --cartao:#FFFFFF; --tinta:#14343B; --texto:#22333A;
  --suave:#5C7078; --linha:#D8DFDE; --acento:#C98A00; --acento-tinta:#FFFFFF;
  --grafo-fundo:#FFFFFF;
}
@media (prefers-color-scheme: dark){
  :root{
    --papel:#0E1B1E; --cartao:#15262B; --tinta:#E8EEEC; --texto:#C9D4D2;
    --suave:#8CA0A0; --linha:#24393E; --acento:#E8A61A; --acento-tinta:#14343B;
    --grafo-fundo:#15262B;
  }
}
:root[data-theme="dark"]{
  --papel:#0E1B1E; --cartao:#15262B; --tinta:#E8EEEC; --texto:#C9D4D2;
  --suave:#8CA0A0; --linha:#24393E; --acento:#E8A61A; --acento-tinta:#14343B;
  --grafo-fundo:#15262B;
}
:root[data-theme="light"]{
  --papel:#F2F4F3; --cartao:#FFFFFF; --tinta:#14343B; --texto:#22333A;
  --suave:#5C7078; --linha:#D8DFDE; --acento:#C98A00; --acento-tinta:#FFFFFF;
  --grafo-fundo:#FFFFFF;
}
*{box-sizing:border-box}
body{margin:0;background:var(--papel);color:var(--texto);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.pagina{max-width:840px;margin:0 auto;padding:1.25rem 1.25rem 3rem;
  display:flex;flex-direction:column;gap:1.75rem}

/* masthead de jornal */
.masthead{display:flex;align-items:baseline;justify-content:space-between;
  border-bottom:3px double var(--linha);padding-bottom:.75rem}
.nome-jornal{font:700 clamp(2rem,6vw,2.75rem)/1 Georgia,"Times New Roman",serif;
  color:var(--tinta);letter-spacing:-.01em;margin:0}
.nome-jornal .olho{color:var(--acento)}
.lema{margin:.35rem 0 0;color:var(--suave);font-size:.85rem;
  text-transform:uppercase;letter-spacing:.14em}
.tema-btn{border:1px solid var(--linha);background:var(--cartao);color:var(--texto);
  border-radius:999px;padding:.35rem .8rem;font-size:.8rem;cursor:pointer}
.tema-btn:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{
  outline:2px solid var(--acento);outline-offset:2px}

/* busca = ação principal */
.busca{background:var(--cartao);border:1px solid var(--linha);border-radius:14px;
  padding:1.25rem;display:flex;flex-direction:column;gap:.75rem}
.busca h2{margin:0;font:600 1.05rem/1.3 Georgia,serif;color:var(--tinta)}
.campos{display:grid;grid-template-columns:2fr repeat(3,minmax(72px,1fr)) auto;gap:.6rem}
@media (max-width:640px){.campos{grid-template-columns:1fr 1fr}}
.campos input,.campos select{padding:.65rem .75rem;border:1px solid var(--linha);
  border-radius:9px;background:var(--papel);color:var(--texto);font-size:1rem;min-width:0}
.campos button{padding:.65rem 1.3rem;border:0;border-radius:9px;cursor:pointer;
  background:var(--acento);color:var(--acento-tinta);font-weight:700;font-size:1rem}
.campos button[disabled]{opacity:.6;cursor:wait}
#erro{color:#b71c1c;font-size:.9rem;min-height:1.2em;margin:0}
:root[data-theme="dark"] #erro{color:#ef9a9a}
@media (prefers-color-scheme: dark){#erro{color:#ef9a9a}}
:root[data-theme="light"] #erro{color:#b71c1c}

/* cartão do candidato */
#cartao{display:none;background:var(--cartao);border:1px solid var(--linha);
  border-radius:14px;overflow:hidden}
#cartao .corpo{display:flex;gap:1.25rem;padding:1.5rem;align-items:center;flex-wrap:wrap}
#cartao img,.sem-foto{width:112px;height:150px;object-fit:cover;border-radius:9px;
  background:var(--linha);flex:none}
.sem-foto{display:flex;align-items:center;justify-content:center;color:var(--suave);
  font-size:.75rem;text-align:center;padding:.5rem}
#nome-urna{margin:0;font:700 1.9rem/1.1 Georgia,serif;color:var(--tinta);text-wrap:balance}
#nome-civil{margin:.3rem 0 0;color:var(--suave)}
.dados-mono{margin:.3rem 0 0;color:var(--suave);font:.85rem/1.5 ui-monospace,Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums}
.faixa-risco{display:flex;justify-content:space-between;align-items:center;gap:1rem;
  padding:1rem 1.5rem;color:#fff}
.faixa-risco .rotulo{text-transform:uppercase;letter-spacing:.12em;font-size:.75rem}
.faixa-risco .valor{font:700 2rem/1 ui-monospace,Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums}

/* grafo */
.secao-grafo h2,.fontes h2{margin:0 0 .6rem;font:600 1.05rem/1.3 Georgia,serif;color:var(--tinta)}
#grafo{width:100%;height:440px;border:1px solid var(--linha);border-radius:14px;
  background:var(--grafo-fundo)}
.legenda{display:flex;gap:1.25rem;flex-wrap:wrap;margin:.6rem 0 0;padding:0;list-style:none;
  color:var(--suave);font-size:.85rem}
.legenda .ponto{display:inline-block;width:.7em;height:.7em;border-radius:50%;margin-right:.4em}

/* fontes oficiais */
.fontes ul{margin:0;padding-left:1.2rem;color:var(--suave);font-size:.9rem}

footer{border-top:1px solid var(--linha);padding-top:1rem;color:var(--suave);
  font-size:.78rem;max-width:65ch}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<div class="pagina">

<header class="masthead">
  <div>
    <h1 class="nome-jornal">Fiscaliza<span class="olho">.</span></h1>
    <p class="lema">Dados públicos, olhos abertos</p>
  </div>
  <button class="tema-btn" id="tema" type="button" aria-label="Alternar tema">Tema</button>
</header>

<section class="busca" aria-label="Busca de candidato">
  <h2>Consulte quem pede o seu voto</h2>
  <form id="busca-form" class="campos">
    <input id="nome" placeholder="Nome de urna ou nome civil" required aria-label="Nome">
    <input id="ano" value="2024" inputmode="numeric" aria-label="Ano" placeholder="Ano">
    <input id="uf" maxlength="2" placeholder="UF" aria-label="UF">
    <select id="cargo" aria-label="Cargo">
      <option value="vereador">Vereador</option>
      <option value="prefeito">Prefeito</option>
      <option value="deputado_federal">Dep. federal</option>
      <option value="deputado_estadual">Dep. estadual</option>
      <option value="senador">Senador</option>
      <option value="governador">Governador</option>
      <option value="presidente">Presidente</option>
    </select>
    <button type="submit" id="btn-buscar">Buscar</button>
  </form>
  <p id="erro" role="status"></p>
</section>

<section id="cartao" aria-label="Cartão do candidato">
  <div class="corpo">
    <div id="foto-box"></div>
    <div>
      <h2 id="nome-urna"></h2>
      <p id="nome-civil"></p>
      <p class="dados-mono" id="subtitulo"></p>
      <p class="dados-mono" id="bens"></p>
    </div>
  </div>
  <div class="faixa-risco" id="badge-risco">
    <span class="rotulo">Índice de risco</span>
    <span class="valor" id="risco-valor"></span>
    <span id="risco-faixa"></span>
  </div>
</section>

<section class="secao-grafo" aria-label="Grafo de relações">
  <h2>O padrão que investigamos, em rede</h2>
  <div id="grafo"></div>
  <ul class="legenda">
    <li><span class="ponto" style="background:#1565c0"></span>Pessoa</li>
    <li><span class="ponto" style="background:#6a1b9a"></span>Empresa</li>
    <li><span class="ponto" style="background:#2e7d32"></span>Órgão público</li>
  </ul>
</section>

<section class="fontes" aria-label="Fontes oficiais">
  <h2>De onde vêm os dados</h2>
  <ul>
    <li>TSE — candidaturas, bens declarados e foto oficial da urna</li>
    <li>Portal da Transparência (CGU) — contratos, emendas e sanções</li>
    <li>Receita Federal — cadastro público de CNPJ e quadros societários</li>
    <li>Banco Central e IBGE — correção monetária e contexto populacional</li>
  </ul>
</section>

<footer id="nota">__NOTA_JURIDICA__ Foto: divulgação oficial de candidatura (TSE).
Projeto gratuito e de código aberto.</footer>
</div>

<script>
// tema: o toggle estampa data-theme e vence a preferência do sistema
const raiz = document.documentElement;
document.getElementById("tema").addEventListener("click", () => {
  const escuroAgora = raiz.dataset.theme
    ? raiz.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  raiz.dataset.theme = escuroAgora ? "light" : "dark";
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");

const CORES_GRUPO = {Pessoa:"#1565c0", Empresa:"#6a1b9a", Orgao:"#2e7d32"};

async function buscar(ev){
  ev.preventDefault();
  const erro = document.getElementById("erro"); erro.textContent = "";
  const btn = document.getElementById("btn-buscar");
  btn.disabled = true; btn.textContent = "Buscando…";
  const q = new URLSearchParams({
    nome: document.getElementById("nome").value,
    ano: document.getElementById("ano").value,
    uf: document.getElementById("uf").value,
    cargo: document.getElementById("cargo").value,
  });
  let r, d;
  try { r = await fetch("/api/candidato?"+q); d = await r.json(); }
  catch(e){ erro.textContent = "O servidor não respondeu. Verifique /api/diagnostico "
      + "ou tente novamente em instantes."; }
  btn.disabled = false; btn.textContent = "Buscar";
  if(!r) return;
  if(!r.ok){
    erro.textContent = (d.erro || "Erro na busca.") + (d.detalhe ? " — " + d.detalhe : "");
    document.getElementById("cartao").style.display = "none";
    return;
  }
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
  badge.style.background = d.risco.cor;   // cor semântica calculada no backend
  document.getElementById("risco-valor").textContent =
    d.risco.indice_de_risco_percentual + "%";
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
  const network = new vis.Network(document.getElementById("grafo"),
    {nodes:new vis.DataSet(nodes), edges:new vis.DataSet(edges)},
    {physics:{stabilization:true},
     edges:{font:{size:11, align:"middle", color:"#5C7078", strokeWidth:0}},
     nodes:{font:{color:"#5C7078"}}});
  network.on("click", p => {
    if(p.nodes.length){ const n = nodes.find(x=>x.id===p.nodes[0]); alert(n.title); }
  });
}

document.getElementById("busca-form").addEventListener("submit", buscar);
desenharGrafo();
</script>
</body></html>""".replace("__NOTA_JURIDICA__", NOTA_JURIDICA)
