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
```

## Referências sobre o caso Bruno César

- [DN: IA contra a corrupção — programador brasileiro cria algoritmo](https://www.dn.pt/economia/ia-contra-a-corrupo-programador-brasileiro-cria-algoritmo-que-expe-os-esquemas-invisveis-do-estado)
- [Showmetech: Brasileiro de 20 anos cria IA que detecta corrupção](https://www.showmetech.com.br/brasileiro-de-20-anos-cria-ia-que-detecta-corrupcao-entenda/)
- [Naweb IA: Desenvolvedor brasileiro cria IA que detecta corrupção e viraliza](https://naweb.ia.br/brasileiro-cria-ia-mostra-corrupcao/)
