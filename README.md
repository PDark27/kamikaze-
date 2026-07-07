# Fiscaliza — Detecção de Risco em Dados Públicos

Plataforma aberta que cruza bases de dados públicas brasileiras para calcular
**índices de risco** associados a candidatos, agentes públicos, empresas e
contratos — inspirada na ferramenta do desenvolvedor Bruno César (projeto
*br/acc*), que processou ~1 TB de dados públicos em grafos Neo4j e identificou
indícios de funcionários fantasmas, superfaturamento e direcionamento de emendas.

> **Aviso legal**: esta ferramenta NÃO acusa ninguém de corrupção. Ela calcula
> **percentuais de risco** e **sinais de alerta** a partir de dados 100% públicos,
> para uso de jornalistas, órgãos de controle e cidadãos. Todo alerta exige
> verificação humana. Presunção de inocência sempre.

## Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│  FONTES PÚBLICAS (conectores em src/fiscaliza/fontes/)  │
│  Portal da Transparência · TSE · Receita/CNPJ ·          │
│  Banco Central · IBGE · Painel de Preços · TCU           │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│  NORMALIZAÇÃO  → entidades canônicas (Pessoa, Empresa,  │
│  Contrato, Emenda, Doação, Vínculo) chaveadas por        │
│  CPF (mascarado) / CNPJ                                  │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌──────────────────────────────┐   ┌──────────────────────┐
│  GRAFO (networkx → Neo4j)    │──▶│  MOTOR DE RISCO       │
│  laços familiares, sócios,   │   │  indicadores em       │
│  contratos, doações          │   │  config/parametros_   │
└──────────────────────────────┘   │  risco.yaml           │
                                   └──────────┬───────────┘
                                              ▼
                        ┌─────────────────────────────────┐
                        │  CAMADA DE IA PLUGÁVEL (llm.py) │
                        │  Claude · GPT · Gemini · Ollama │
                        │  (a IA da preferência do cliente)│
                        │  explica alertas em linguagem    │
                        │  neutra e sugere próximos passos │
                        └─────────────────────────────────┘
```

## Fontes de dados públicas usadas

| Fonte | O que fornece | API |
|---|---|---|
| Portal da Transparência | contratos, licitações, servidores, emendas, sanções (CEIS/CNEP) | `api.portaldatransparencia.gov.br` (chave gratuita) |
| TSE (DivulgaCand / dadosabertos) | candidaturas, bens declarados, doações de campanha | `dadosabertos.tse.jus.br` (CKAN) |
| Receita Federal (CNPJ aberto) | quadro societário, data de abertura, CNAE, endereço | dados abertos CNPJ / `minhareceita.org` |
| Banco Central | indicadores, câmbio p/ deflacionar séries | `api.bcb.gov.br` / Olinda |
| IBGE | população, PIB municipal (per-capita de gastos) | `servicodados.ibge.gov.br` |

## Indicadores de risco iniciais (resumo)

Definidos e ponderados em [`config/parametros_risco.yaml`](config/parametros_risco.yaml):

1. **Vínculo societário direto** — agente público (ou parente) sócio de empresa contratada pelo próprio órgão.
2. **Empresa recém-criada vencedora** — CNPJ aberto < 180 dias antes de vencer licitação.
3. **Sobrepreço** — preço unitário acima da mediana de mercado (Painel de Preços) além do limiar.
4. **Indício de servidor fantasma** — mesmo CPF em folhas de municípios distantes / vínculos simultâneos incompatíveis.
5. **Emenda direcionada** — emenda parlamentar → município de base eleitoral → empresa doadora de campanha.
6. **Evolução patrimonial atípica** — crescimento de bens declarados ao TSE incompatível com renda conhecida.
7. **Doador contratado** — doador de campanha ganha contratos do eleito após a posse.
8. **Fracionamento de despesa** — múltiplas contratações logo abaixo do limite de dispensa de licitação.
9. **Perfil de empresa de fachada** — capital social ínfimo, endereço residencial, sem quadro de funcionários, CNAE incompatível com o objeto do contrato.
10. **Concentração de fornecedor** — um CNPJ vence fração desproporcional das licitações de um órgão.

Cada indicador gera pontos; a soma normalizada (0–100) vira o **índice de risco**,
sempre exibido como percentual + evidências, nunca como acusação.

## Uso rápido

```bash
pip install -e .
export TRANSPARENCIA_API_KEY=...     # chave gratuita do Portal da Transparência
export FISCALIZA_LLM=anthropic       # ou openai | gemini | ollama
export ANTHROPIC_API_KEY=...

fiscaliza analisar --cpf-mascarado '***123456**' --nome "FULANO DE TAL" --uf SP
fiscaliza empresa 00.000.000/0001-91
fiscaliza grafo --saida grafo.graphml   # abre no Gephi / importa no Neo4j
fiscaliza candidato --nome "ZÉ EXEMPLO" --ano 2024 --uf SP --cargo 13
fiscaliza dossie --nome "ZÉ EXEMPLO" --uf SP --cargo 13 --salvar   # dossiê completo → memoria/
fiscaliza web                                                       # app web em http://127.0.0.1:8000
fiscaliza ingerir --conjunto-tse candidatos-2024                    # dumps em massa (na sua máquina)
```

## Aplicativo instalável e gratuito (PWA)

`fiscaliza web` sobe o app (FastAPI, `webapp/`): busca por nome de urna ou civil,
cartão do candidato com foto oficial e índice de risco, e grafo interativo de
relações (vis-network). Endpoints JSON: `/api/candidato` e `/api/grafo/exemplo`.

**Como a busca funciona**: o site DivulgaCand do TSE tem escudo anti-robô
(F5/TSPD) que bloqueia servidores — por isso a busca consulta primeiro os
**Dados Abertos oficiais** (`cdn.tse.jus.br`, canal correto para programas)
carregados em banco local, e só usa a API ao vivo como reserva (funciona de
IPs residenciais). Carregue a base com `fiscaliza ingerir-candidatos --ano
2024 --uf SP` ou, em hospedagens, defina `FISCALIZA_INGERIR_UF=SP` (e
opcionalmente `FISCALIZA_INGERIR_ANO`) para a ingestão automática no boot.
O endpoint `/api/diagnostico` mostra a saúde da conexão com o TSE.

O app é um **PWA de instalação gratuita**: hospedado em qualquer servidor (ou
rodando localmente), o Chrome/Edge/Android oferece **"Instalar aplicativo" /
"Adicionar à tela inicial"** — sem loja de aplicativos, sem custo, com ícone
próprio e funcionamento em janela dedicada (manifesto em `/manifest.webmanifest`,
service worker em `/sw.js` mantém a casca do app offline; os dados são sempre
buscados frescos nas fontes oficiais). Identidade visual de jornalismo de dados,
apartidária, com tema claro/escuro automático. Licença MIT (livre e gratuito).

### Publicar de graça (endereço público com HTTPS)

1. **Render (recomendado, 1 clique)**: crie conta gratuita em render.com →
   *New + → Blueprint* → aponte para este repositório (o `render.yaml` já
   configura tudo) → defina `TRANSPARENCIA_API_KEY` no painel. Em minutos o
   app ganha um endereço `https://fiscaliza-*.onrender.com` e o botão
   **Instalar aplicativo** aparece para qualquer visitante.
2. **Qualquer host com Docker**: `docker build -t fiscaliza . && docker run -p 8000:8000 fiscaliza`.

## Ingestão em massa (estilo Neo4j)

`src/fiscaliza/ingestao/` baixa os dumps públicos completos (TSE via CKAN, CNPJ
da Receita), carrega em SQLite local (`BancoLocal`, com zip/latin-1 em lotes) e
gera CSVs no formato do `neo4j-admin database import` (`ExportadorNeo4j`) — o
caminho para análises em escala com o Estado inteiro como grafo.

## Segundo cérebro programático

`fiscaliza.memoria.Memoria` persiste dossiês em `memoria/` com índice idempotente
e bloqueio de CPF não mascarado (`ValueError`); `fiscaliza.dossie.montar_dossie`
cruza TSE + Receita + Transparência tolerando fontes fora do ar e gera o markdown
no formato da skill `segundo-cerebro`.

## Fotos e nome de urna dos candidatos (TSE)

O comando `fiscaliza candidato` busca no DivulgaCandContas do TSE por **nome de
urna ou nome civil completo** (sem precisar de acentos), baixa a **foto oficial
da urna** para `fotos/<ano>/<sqcand>.jpg` e gera um **cartão HTML autocontido**
em `cartoes/` com foto, nome de urna em destaque, nome civil, partido/cargo e o
índice de risco. Códigos de cargo comuns: 11 prefeito, 13 vereador, 6 deputado
federal, 7 deputado estadual, 5 senador, 3 governador, 1 presidente.

As fotos são dados públicos de divulgação oficial de candidatura (TSE). Use-as
apenas nesse contexto de fiscalização; o cartão sempre inclui a nota de
presunção de inocência.

> Validação real (a API do TSE não é acessível de sandboxes com proxy):
> rode na sua máquina `fiscaliza candidato --nome "<nome de urna>" --ano 2024
> --uf <UF> --cargo 11` e confira a foto salva em `fotos/` e o cartão em
> `cartoes/<sqcand>.html`.

## Referências sobre o caso Bruno César

- [DN: IA contra a corrupção — programador brasileiro cria algoritmo](https://www.dn.pt/economia/ia-contra-a-corrupo-programador-brasileiro-cria-algoritmo-que-expe-os-esquemas-invisveis-do-estado)
- [Showmetech: Brasileiro de 20 anos cria IA que detecta corrupção](https://www.showmetech.com.br/brasileiro-de-20-anos-cria-ia-que-detecta-corrupcao-entenda/)
- [Naweb IA: Desenvolvedor brasileiro cria IA que detecta corrupção e viraliza](https://naweb.ia.br/brasileiro-cria-ia-mostra-corrupcao/)
