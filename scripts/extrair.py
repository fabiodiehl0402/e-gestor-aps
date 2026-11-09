"""Robô e-Gestor APS: baixa os relatórios públicos da APS para todos os municípios.

Fontes (APIs públicas do Ministério da Saúde, sem login):
  relatorioaps-prd.saude.gov.br  (Relatórios Públicos da APS / e-Gestor)
  apisiaps.saude.gov.br          (SIAPS: classificação de qualidade e vínculo)

Saída em dados/ (CSV UTF-8, separador vírgula, compactado .csv.gz):
  financiamento/AAAAMM.csv.gz        pagamento completo por município e parcela
  financiamento_resumo_uf/AAAAMM...  resumo por plano orçamentário, por UF
  egestor/abas/<Aba>/download-pagamento-01-MM-AAAA.xlsx
                                     planilhas iguais ao download do e-Gestor (Power BI)
  cobertura_aps/AAAAMM.csv.gz        cobertura potencial da APS por município
  cobertura_acs/AAAAMM.csv.gz        cobertura de ACS por município
  qualidade_componente/AAAAQn.csv.gz classificação final (Qualidade e CVAT) por equipe
  qualidade_indicador/AAAAQn.csv.gz  conceito por indicador de qualidade
  qualidade_cvat/AAAAQn.csv.gz       classificação por dimensão do CVAT
  suspensao_equipes/AAAAMM.csv.gz    equipes com suspensão de repasse
  suspensao_estabelecimentos/...     estabelecimentos com suspensão
  suspensao_profissionais/...        profissionais com suspensão
  homologacao_equipes/AAAAMM.csv.gz  foto das equipes homologadas (mês da execução)
  homologacao_estabelecimentos/...   foto dos estabelecimentos homologados
  _arquivos.txt                      índice lido pelo Power BI

Regras:
  * Período já baixado é pulado, exceto os 3 mais recentes de cada série
    (o Ministério corrige parcelas e competências depois de publicar).
  * Se uma UF falhar, o período inteiro não é gravado (nada de arquivo pela metade).
  * Arquivo só é regravado se o conteúdo mudou (histórico do git limpo).

Uso:
  python scripts/extrair.py                  # tudo, incremental
  python scripts/extrair.py --desde 202401   # define o início do histórico
  python scripts/extrair.py --so financiamento,qualidade
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import abas_pagamento

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"

API = "https://relatorioaps-prd.saude.gov.br"
SIAPS = "https://apisiaps.saude.gov.br"

UFS = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
}
HEADERS_SIAPS = {**HEADERS, "Origin": "https://siaps.saude.gov.br",
                 "Referer": "https://siaps.saude.gov.br/"}

ABAS = DADOS / "egestor" / "abas"
ABAS_DESDE = os.environ.get("ABAS_DESDE") or "202601"   # planilhas por aba a partir desta parcela
RENOVAR = 3          # quantos períodos mais recentes são sempre baixados de novo
TENTATIVAS = 5
PARALELO = int(os.environ.get("PARALELO", "6"))


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- HTTP

def http(url: str, params: dict | None = None, body: dict | None = None,
         headers: dict | None = None, timeout: int = 600):
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    h = dict(headers or HEADERS)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    ultimo = None
    for t in range(1, TENTATIVAS + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=h,
                                         method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(min(60, 5 * t))
    raise RuntimeError(f"falhou após {TENTATIVAS} tentativas: {url} ({ultimo})")


# ---------------------------------------------------------------- CSV

_MILHAR = re.compile(r"^-?\d{1,3}(,\d{3})+$")


def limpa(v):
    """Ajusta valores para leitura direta no Power BI."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, str):
        s = v.strip()
        if _MILHAR.match(s):          # "22,787" (cobertura ACS) -> 22787
            return s.replace(",", "")
        return s
    return v


def grava(rel: str, linhas: list[dict]) -> bool:
    """Grava dados/<rel>.csv.gz de forma determinística. Retorna True se mudou."""
    destino = DADOS / f"{rel}.csv.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)
    colunas: list[str] = []
    for ln in linhas:
        for k in ln:
            if k not in colunas:
                colunas.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=colunas, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    chave = lambda d: json.dumps([d.get(c) for c in colunas], ensure_ascii=False, default=str)  # noqa: E731
    for ln in sorted(linhas, key=chave):
        w.writerow({k: limpa(v) for k, v in ln.items()})
    bruto = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=bruto, mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    novo = bruto.getvalue()
    if destino.exists() and destino.read_bytes() == novo:
        return False
    destino.write_bytes(novo)
    return True


def existe(rel: str) -> bool:
    return (DADOS / f"{rel}.csv.gz").exists()


# ---------------------------------------------------------------- períodos

def parcelas_financiamento(desde: str) -> list[str]:
    anos = http(f"{API}/data/anos")
    out = []
    for ano in anos:
        out += http(f"{API}/data/parcelas", {"ano": ano})
    return sorted({p for p in out if p >= desde})


def competencias_cnes(desde: str) -> list[str]:
    return sorted({c for c in http(f"{API}/data/competencias-cnes", {"compInicio": desde}) if c >= desde})


def quadrimestres(desde: str) -> list[str]:
    lista = http(f"{SIAPS}/api/public/filtros/competencias", headers=HEADERS_SIAPS)
    q = [x["nuCompetencia"] for x in lista if x.get("quadrimestre")]
    ano_ini = int(desde[:4])
    return sorted(x for x in q if int(x[:4]) >= ano_ini)


def suspensao_competencias(desde: str) -> list[str]:
    return sorted(c for c in http(f"{API}/credenciamento/sujeitos-suspensao/competencias") if c >= desde)


def a_baixar(periodos: list[str], pastas: list[str]) -> list[str]:
    """Períodos novos + os RENOVAR mais recentes."""
    recentes = set(periodos[-RENOVAR:])
    return [p for p in periodos if p in recentes or not all(existe(f"{d}/{p}") for d in pastas)]


# ---------------------------------------------------------------- consultas por UF

def q_financiamento(uf: str, parcela: str):
    d = http(f"{API}/financiamento/pagamento", {
        "unidadeGeografica": "MUNICIPIO", "coUf": uf, "coUfIbge": uf,
        "nuParcelaInicio": parcela, "nuParcelaFim": parcela, "tipoRelatorio": "COMPLETO"})
    return {"financiamento": d.get("pagamentos") or [],
            "financiamento_resumo_uf": d.get("resumosPlanosOrcamentarios") or []}


def q_cobertura(uf: str, comp: str):
    p = {"unidadeGeografica": "MUNICIPIO", "coUf": uf, "nuCompInicio": comp, "nuCompFim": comp}
    aps = http(f"{API}/cobertura/aps", p)
    acs = http(f"{API}/cobertura/acs", p)
    return {"cobertura_aps": aps if isinstance(aps, list) else [],
            "cobertura_acs": acs if isinstance(acs, list) else []}


def q_qualidade(uf: str, quad: str):
    d = http(f"{SIAPS}/api/public/componente/indicador-quadrimestre/filtro",
             body={"uf": [UFS[uf]], "nuQuadrimestre": [quad]}, headers=HEADERS_SIAPS)
    return {"qualidade_componente": d.get("classificacaoFinalComponente") or [],
            "qualidade_indicador": d.get("conceitoPorIndicadorQualidade") or [],
            "qualidade_cvat": d.get("classificacaoFinalPorDimensaoCvat") or []}


def q_homologacao(uf: str, _p: str):
    return {"homologacao_equipes": http(f"{API}/financiamento/homologacao/equipes", {"coUf": uf}) or [],
            "homologacao_estabelecimentos": http(f"{API}/financiamento/homologacao/estabelecimentos",
                                                 {"coUf": uf}) or []}


def depois_financiamento(per: str, resultado: dict, mudou: bool):
    """Gera as planilhas por aba (formato do e-Gestor) usadas pelo Power BI."""
    if per < ABAS_DESDE or not resultado.get("financiamento"):
        return
    if mudou or not abas_pagamento.existe(ABAS, per):
        n = abas_pagamento.gera(ABAS, per, resultado["financiamento"], resultado["financiamento_resumo_uf"])
        log(f"[financiamento] {per}: {n} planilhas por aba gravadas")


def executa_por_uf(nome: str, periodos: list[str], consulta, pastas: list[str], depois=None) -> list[str]:
    """Roda consulta(uf, periodo) para todas as UFs e grava um arquivo por período."""
    if not periodos:
        log(f"[{nome}] nada novo")
        return []
    log(f"[{nome}] {len(periodos)} período(s): {', '.join(periodos)}")
    erros = []
    for per in periodos:
        resultado = {p: [] for p in pastas}
        falhou = False
        with ThreadPoolExecutor(PARALELO) as ex:
            fut = {ex.submit(consulta, uf, per): uf for uf in UFS}
            for f in as_completed(fut):
                try:
                    for pasta, linhas in f.result().items():
                        resultado[pasta] += linhas
                except Exception as e:  # noqa: BLE001
                    falhou = True
                    erros.append(f"{nome} {per} UF {fut[f]}: {e}")
        if falhou:
            log(f"[{nome}] {per}: ERRO em alguma UF, período não gravado")
            continue
        algum = False
        for pasta, linhas in resultado.items():
            if not linhas:
                log(f"[{nome}] {per} {pasta}: vazio (não publicado ainda)")
                continue
            mudou = grava(f"{pasta}/{per}", linhas)
            algum = algum or mudou
            log(f"[{nome}] {per} {pasta}: {len(linhas)} linhas {'(atualizado)' if mudou else '(sem mudança)'}")
        if depois:
            depois(per, resultado, algum)
    return erros


def executa_suspensao(desde: str) -> list[str]:
    pastas = ["suspensao_equipes", "suspensao_estabelecimentos", "suspensao_profissionais"]
    periodos = a_baixar(suspensao_competencias(desde), pastas)
    log(f"[suspensao] {len(periodos)} período(s)")
    erros = []
    for comp in periodos:
        try:
            d = http(f"{API}/credenciamento/sujeitos-suspensao", {"nuCompCnes": comp})
        except Exception as e:  # noqa: BLE001
            erros.append(f"suspensao {comp}: {e}")
            continue
        for chave, pasta in zip(["equipes", "estabelecimentos", "profissionais"], pastas):
            linhas = d.get(chave) or []
            if linhas:
                mudou = grava(f"{pasta}/{comp}", linhas)
                log(f"[suspensao] {comp} {pasta}: {len(linhas)} linhas {'(atualizado)' if mudou else '(sem mudança)'}")
    return erros


def indice():
    arquivos = sorted(str(p.relative_to(DADOS)).replace(os.sep, "/") for p in DADOS.rglob("*.csv.gz"))
    (DADOS / "_arquivos.txt").write_text("\n".join(arquivos) + "\n", encoding="utf-8")
    log(f"índice: {len(arquivos)} arquivos")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default=os.environ.get("DESDE") or "202401",
                    help="primeira competência/parcela AAAAMM (padrão 202401)")
    ap.add_argument("--so", default=os.environ.get("SO") or "",
                    help="lista: financiamento,cobertura,qualidade,suspensao,homologacao")
    ap.add_argument("--ufs", default=os.environ.get("UFS_TESTE") or "",
                    help="restringe UFs (códigos IBGE, só para teste)")
    a = ap.parse_args()
    if a.ufs:
        for k in list(UFS):
            if k not in a.ufs.split(","):
                del UFS[k]
    so = {s.strip() for s in a.so.split(",") if s.strip()}
    quer = lambda n: not so or n in so  # noqa: E731
    erros: list[str] = []

    etapas = []
    if quer("financiamento"):
        def per_fin():
            todas = parcelas_financiamento(a.desde)
            base = a_baixar(todas, ["financiamento", "financiamento_resumo_uf"])
            faltam_abas = [p for p in todas if p >= ABAS_DESDE and not abas_pagamento.existe(ABAS, p)]
            return sorted(set(base) | set(faltam_abas))
        etapas.append(("financiamento", per_fin, q_financiamento,
                       ["financiamento", "financiamento_resumo_uf"], depois_financiamento))
    if quer("cobertura"):
        etapas.append(("cobertura", lambda: a_baixar(competencias_cnes(a.desde), ["cobertura_aps", "cobertura_acs"]),
                       q_cobertura, ["cobertura_aps", "cobertura_acs"], None))
    if quer("qualidade"):
        pq = ["qualidade_componente", "qualidade_indicador", "qualidade_cvat"]
        etapas.append(("qualidade", lambda: a_baixar(quadrimestres(a.desde), pq), q_qualidade, pq, None))
    if quer("homologacao"):
        mes = dt.date.today().strftime("%Y%m")
        etapas.append(("homologacao", lambda: [mes], q_homologacao,
                       ["homologacao_equipes", "homologacao_estabelecimentos"], None))

    for nome, periodos, consulta, pastas, depois in etapas:
        try:
            erros += executa_por_uf(nome, periodos(), consulta, pastas, depois)
        except Exception as e:  # noqa: BLE001
            erros.append(f"{nome}: {e}")
            log(f"[{nome}] ERRO: {e}")
    if quer("suspensao"):
        try:
            erros += executa_suspensao(a.desde)
        except Exception as e:  # noqa: BLE001
            erros.append(f"suspensao: {e}")

    indice()
    if any(ABAS.glob("*/download-pagamento-*.xlsx")):
        abas_pagamento.indice(ABAS)
    (DADOS / "_atualizacao.json").write_text(json.dumps({
        "executado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "erros": erros}, ensure_ascii=False, indent=1), encoding="utf-8")
    if erros:
        log(f"{len(erros)} erro(s):")
        for e in erros:
            log("  ", e)
        sys.exit(1)
    log("concluído sem erros")


if __name__ == "__main__":
    main()
