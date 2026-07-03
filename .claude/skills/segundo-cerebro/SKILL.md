---
name: segundo-cerebro
description: Segundo cérebro do projeto Fiscaliza — memória investigativa persistente. Use ao iniciar qualquer análise de candidato, empresa ou contrato; ao registrar um achado/alerta; ou quando o usuário perguntar "o que já sabemos sobre X". Mantém dossiês em memoria/ com hipóteses, evidências, fontes consultadas e próximos passos, sempre em linguagem neutra de risco.
---

# Segundo Cérebro — memória investigativa do Fiscaliza

Você mantém a memória de longo prazo das análises deste projeto no diretório
`memoria/` na raiz do repositório. Cada entidade investigada tem um dossiê
Markdown próprio.

## Estrutura

```
memoria/
  INDICE.md                     # tabela: entidade → arquivo → índice de risco → status
  pessoas/<slug-do-nome>.md
  empresas/<cnpj>.md
  contratos/<id>.md
  hipoteses/<slug>.md           # padrões suspeitos entre múltiplas entidades
```

## Fluxo obrigatório

1. **Antes de analisar** qualquer entidade: leia `memoria/INDICE.md` e o dossiê
   correspondente, se existir. Nunca refaça do zero uma consulta já registrada —
   retome de onde parou.
2. **Durante a análise**: use os conectores de `src/fiscaliza/fontes/` e o
   `MotorDeRisco` de `src/fiscaliza/risco.py`. Os limiares vêm de
   `config/parametros_risco.yaml` — não invente limiares próprios.
3. **Depois da análise**: atualize (ou crie) o dossiê e a linha no `INDICE.md`.

## Modelo de dossiê

```markdown
# <Nome / Razão Social>
- Chave: <cpf mascarado | cnpj>
- Nome de urna: <NOME POLÍTICO NAS URNAS>          # candidatos: sempre registrar
- Nome civil completo: <NOME CIVIL>                # busca em outras bases usa este
- Foto oficial: fotos/<ano>/<sqcand>.jpg           # via TSE.baixar_foto()
- Índice de risco atual: <N>% (<faixa>)
- Última atualização: <data>

## Fontes já consultadas
- [ ] Portal da Transparência (contratos, sanções, servidores)
- [ ] TSE (candidaturas, bens, doações)
- [ ] Receita/CNPJ (quadro societário, abertura)
- [ ] IBGE / BCB (contexto e deflação)

## Achados (evidências, nunca acusações)
| Data | Indicador | Pontos | Evidência | Fonte/URL |

## Relações mapeadas (para o grafo)
- <pessoa> —SOCIO_DE→ <empresa>

## Hipóteses em aberto
## Próximos passos
```

## Regras de redação (inegociáveis)

- **Nunca** escreva "corrupção", "fraude", "crime" ou equivalentes ao descrever
  uma pessoa/empresa. Use "índice de risco de N%", "sinal de alerta",
  "padrão atípico". Isso é requisito jurídico do projeto, não estilo.
- Toda evidência precisa de fonte pública verificável (URL ou conjunto de dados
  + data da consulta).
- Registre também o que **inocenta**: um sinal explicado (ex.: empresa nova
  porém herdeira de outra) deve ser anotado e o índice recalculado para baixo.
- CPFs sempre mascarados (`***XXXXXX**`), como o Portal da Transparência publica.
- Candidatos têm **duas formas de nome**: registre ambas. O nome civil completo é a
  chave para cruzar com Receita/Transparência; o nome de urna é o que vai em cartões
  e comunicação. A foto oficial (dado público do TSE) entra no dossiê e no cartão
  gerado por `fiscaliza.cartao.gerar_cartao`.

## Conexões entre dossiês

Ao notar a mesma pessoa/CNPJ em dois dossiês, crie/atualize um arquivo em
`memoria/hipoteses/` descrevendo o padrão e liste os dossiês envolvidos.
Rode `GrafoDeRelacoes.ciclos_suspeitos()` quando uma hipótese envolver 3+
entidades — ciclos fechados (emenda → órgão → contrato → empresa → doação →
autor da emenda) são os padrões de maior prioridade.
