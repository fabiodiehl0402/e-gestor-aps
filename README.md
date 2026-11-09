# e-Gestor APS · robô de dados públicos (todos os municípios)

Baixa sozinho, sem login e sem planilha manual, os relatórios públicos da Atenção Primária
publicados pelo Ministério da Saúde (e-Gestor APS / Relatórios Públicos da APS / SIAPS),
para **todos os municípios do Brasil**, e deixa tudo pronto para o Power BI
**RELATÓRIO SITUACIONAL APS 2026**.

Complementa o repositório [aps-cnes-ine](https://github.com/fabiodiehl0402/aps-cnes-ine)
(equipes e profissionais por INE).

## Como funciona

1. O GitHub Actions roda `scripts/extrair.py` **toda segunda-feira e todo dia 15**
   (e quando você clicar em *Actions > Atualizar e-Gestor APS > Run workflow*).
2. O robô consulta as APIs públicas UF por UF e grava um arquivo por período em `dados/`.
3. Períodos novos entram automaticamente. Os 3 mais recentes de cada série são sempre
   baixados de novo, porque o Ministério corrige parcelas depois de publicar.
4. Se alguma UF falhar, o período não é gravado pela metade: ele é tentado de novo na
   próxima execução.
5. O Power BI lê direto do link "raw" do GitHub (funciona no Desktop e na atualização
   agendada do Power BI Service).

## O que é baixado

| Pasta em `dados/` | Conteúdo | Período do arquivo |
|---|---|---|
| `financiamento/` | Pagamento completo da APS por município: eSF, eAP, eSB, eMulti, ACS, eCR, UBSF, ribeirinhas, prisional, PSE, Academia, IAF, residência, per capita, transição, qualidade, vínculo, tetos e quantidades credenciadas/homologadas/pagas | parcela (AAAAMM) |
| `cobertura_aps/` | Cobertura potencial da APS (população, equipes, capacidade, % cobertura) | competência CNES |
| `cobertura_acs/` | Cobertura de ACS (ACS ativos, população coberta, %) | competência CNES |
| `qualidade_componente/` | Classificação final das equipes nos componentes Qualidade e Vínculo (CVAT): Ótimo, Bom, Suficiente, Regular | quadrimestre (AAAAQn) |
| `qualidade_indicador/` | Conceito por indicador de qualidade, por tipo de equipe | quadrimestre |
| `qualidade_cvat/` | Classificação por dimensão do CVAT | quadrimestre |
| `suspensao_equipes/`, `suspensao_estabelecimentos/`, `suspensao_profissionais/` | Sujeitos a suspensão de repasse e o motivo | competência CNES |
| `homologacao_equipes/`, `homologacao_estabelecimentos/` | Foto das equipes e estabelecimentos homologados, com a portaria | mês da execução |

Arquivos: CSV UTF-8, separador vírgula, ponto decimal, compactados em `.csv.gz`.
`dados/_arquivos.txt` é o índice que o Power BI usa. `dados/_atualizacao.json` mostra a
última execução e os erros, se houver.

Fontes: `relatorioaps-prd.saude.gov.br` (financiamento, cobertura, homologação, suspensão)
e `apisiaps.saude.gov.br` (qualidade e vínculo).

## Power BI

1. Crie o parâmetro `EGESTOR_URL_BASE` com o texto de `powerbi/00_EGESTOR_URL_BASE.pq`.
2. Crie uma consulta em branco chamada `fnEGestor` e cole `powerbi/01_fnEGestor.pq`
   no Editor Avançado.
3. Crie as consultas `EG_*` colando os arquivos `powerbi/EG_*.pq` (só as que for usar).
4. Chave para relacionar com o resto do relatório: `coMunicipioIbge` (IBGE 6 dígitos).
   Nas tabelas de homologação a chave é `codigoMunicipio`.
5. Coluna `periodo` em todas as tabelas: AAAAMM (ou AAAAQn na qualidade).

No Power BI Service, em *Configurações > Credenciais da fonte de dados*, use
autenticação **Anônima** para `raw.githubusercontent.com`.

## Rodar no computador (opcional)

```
python scripts/extrair.py --desde 202401
python scripts/extrair.py --so financiamento,qualidade
```

Precisa só de Python 3.10+ (sem bibliotecas extras).
