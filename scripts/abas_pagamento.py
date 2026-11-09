"""Gera as planilhas download-pagamento-01-MM-AAAA.xlsx (uma por aba) iguais às do e-Gestor.

O e-Gestor monta o Excel do "Relatório de pagamento" no navegador a partir da mesma API
que o robô consulta. Este módulo repete esse passo: mesmas abas, mesmos nomes de coluna,
mesmos formatos (Comp. CNES "AGO/2026", Parcela "10/12", IBGE como texto).

Saída: dados/egestor/abas/<Aba>/download-pagamento-01-MM-AAAA.xlsx
       dados/egestor/abas/_arquivos.txt   (só os nomes dos arquivos, lido pelo Power BI)
O mapa aba -> colunas -> campo da API está em abas_pagamento.json (extraído do e-Gestor).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from collections import OrderedDict
from pathlib import Path

MAPA = json.loads((Path(__file__).with_name("abas_pagamento.json")).read_text(encoding="utf-8"))
MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
COMUNS = [("UF", "sgUf"), ("MUNICÍPIO", "noMunicipio"), ("IBGE", "coMunicipioIbge"),
          ("Comp. CNES", "nuCompCnes"), ("Parcela", "nuParcela")]


def comp_fmt(v):
    v = str(v or "")
    return f"{MESES[int(v[4:6]) - 1]}/{v[:4]}" if len(v) == 6 else v


def parcela_fmt(v):
    v = str(v or "")
    return f"{int(v[4:6])}/12" if len(v) == 6 else v


def pasta_da_aba(aba: str) -> str:
    """Mesmo nome de pasta que a função fn_Aba_GitHub do Power BI calcula."""
    s = unicodedata.normalize("NFKD", aba).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]", "_", s)
    return "_".join(p for p in s.split("_") if p)


def nome_arquivo(parcela: str) -> str:
    return f"download-pagamento-01-{parcela[4:6]}-{parcela[:4]}.xlsx"


def _valor(campo, reg):
    if campo.startswith("soma:"):      # soma de vários campos (eAPP no layout antigo)
        rx = re.compile(campo[5:])
        return sum((reg.get(k) or 0) for k in reg if rx.match(k))
    if campo.startswith("nd:"):        # coluna que a API não publica mais
        return 0
    v = reg.get(campo)
    if campo == "nuCompCnes":
        return comp_fmt(v)
    if campo == "nuParcela":
        return parcela_fmt(v)
    if campo == "coMunicipioIbge":
        return None if v is None else str(v)
    return v


def _grava_xlsx(destino: Path, aba: str, cab: list[str], linhas: list[list]):
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    fixo = dt.datetime(2000, 1, 1)
    wb.properties.created = fixo
    wb.properties.modified = fixo
    ws = wb.create_sheet(aba[:31])
    ws.append(cab)
    for ln in linhas:
        ws.append(ln)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)


def resumo_nacional(resumos_uf: list[dict]) -> list[dict]:
    """Soma os resumos por UF para ter o resumo Brasil (como o download do e-Gestor)."""
    vals = ["vlIntegral", "vlAjuste", "vlDesconto", "vlEfetivoRepasse", "vlImplantacao",
            "vlAjusteImplantacao", "vlDescontoImplantacao", "vlTotalImplantacao"]
    acc: "OrderedDict[tuple, dict]" = OrderedDict()
    for r in resumos_uf:
        k = (r.get("nuCompCnes"), r.get("nuParcela"), r.get("dsPlanoOrcamentario"), r.get("dsEsferaAdministrativa"))
        a = acc.setdefault(k, {"nuCompCnes": k[0], "nuParcela": k[1], "dsPlanoOrcamentario": k[2],
                               "dsEsferaAdministrativa": k[3], **{v: 0 for v in vals}})
        for v in vals:
            a[v] = round(a[v] + (r.get(v) or 0), 2)
    for a in acc.values():
        for v in vals:
            if float(a[v]).is_integer():
                a[v] = int(a[v])
    ordem = {}
    for k in acc:
        ordem.setdefault(k[2], len(ordem))
    return sorted(acc.values(), key=lambda a: (ordem[a["dsPlanoOrcamentario"]], a["dsEsferaAdministrativa"] or ""))


def gera(base: Path, parcela: str, pagamentos: list[dict], resumos_uf: list[dict]) -> int:
    """Grava todas as abas de uma parcela. Retorna quantos arquivos foram gravados."""
    pag = sorted(pagamentos, key=lambda r: (r.get("sgUf") or "", r.get("noMunicipio") or ""))
    arq = nome_arquivo(parcela)
    n = 0
    for aba, cols in MAPA.items():
        if aba == "Resumo":
            regs = resumo_nacional(resumos_uf)
            pares = [tuple(c) for c in cols]
        else:
            regs = pag
            pares = COMUNS + [tuple(c) for c in cols]
        cab = [c[0] for c in pares]
        linhas = [[_valor(c[1], r) for c in pares] for r in regs]
        _grava_xlsx(base / pasta_da_aba(aba) / arq, aba, cab, linhas)
        n += 1
    return n


def existe(base: Path, parcela: str) -> bool:
    arq = nome_arquivo(parcela)
    return all((base / pasta_da_aba(a) / arq).exists() for a in MAPA)


def indice(base: Path):
    nomes = set()
    for p in base.glob("*/download-pagamento-*.xlsx"):
        nomes.add(p.name)
    chave = lambda s: (s[25:29], s[22:24])  # noqa: E731  (ano, mês)
    base.mkdir(parents=True, exist_ok=True)
    (base / "_arquivos.txt").write_text("\n".join(sorted(nomes, key=chave)) + "\n", encoding="utf-8")
