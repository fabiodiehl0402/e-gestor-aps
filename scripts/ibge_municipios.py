"""Perfil dos municípios pelo Censo 2022 (IBGE/SIDRA), para a tabela TC - IBGE - Municipios do Power BI.

Gera dados/ibge_municipios.csv.gz com as mesmas colunas da planilha usada antes
(id_municipio com 7 dígitos, nome, UF, domicílios, população, área, alfabetização,
envelhecimento, idade mediana, razão de sexo, população indígena e quilombola).
Fonte: API pública do SIDRA (apisidra.ibge.gov.br), sem login. Dado do Censo 2022,
então só precisa ser baixado uma vez (o robô refaz se o arquivo não existir).
"""
from __future__ import annotations

import json
import time
import urllib.request

SIDRA = "https://apisidra.ibge.gov.br/values"


def sidra(caminho: str) -> list[dict]:
    ultimo = None
    for t in range(1, 6):
        try:
            req = urllib.request.Request(f"{SIDRA}/{caminho}", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read().decode("utf-8"))[1:]
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(10 * t)
    raise RuntimeError(f"SIDRA falhou: {caminho} ({ultimo})")


def _num(v):
    return None if v in (None, "", "-", "...", "X") else v


def coleta() -> list[dict]:
    mun: dict[str, dict] = {}

    def reg(cod, nome=None):
        r = mun.setdefault(cod, {"id_municipio": cod})
        if nome and "id_municipio_nome" not in r:
            sep = " - " if " - " in nome else " ("
            n, _, uf = nome.rpartition(sep)
            r["id_municipio_nome"] = n.strip()
            r["sigla_uf"] = uf.rstrip(")").strip()
        return r

    for x in sidra("t/4714/n6/all/v/93,6318/p/2022"):
        r = reg(x["D1C"], x["D1N"])
        if x["D2C"] == "93":
            r["populacao"] = _num(x["V"])
        elif x["D2C"] == "6318" and _num(x["V"]):
            r["area"] = str(round(float(x["V"])))          # km², inteiro
    for x in sidra("t/4712/n6/all/v/381/p/2022"):
        reg(x["D1C"], x["D1N"])["domicilios"] = _num(x["V"])
    for x in sidra("t/9543/n6/all/v/2513/p/2022"):
        if all(x.get(k) in (None, "Total", "15 anos ou mais") for k in ("D4N", "D5N", "D6N")):
            reg(x["D1C"], x["D1N"]).setdefault("taxa_alfabetizacao", _num(x["V"]))
    nomes = {"10612": "indice_envelhecimento", "10613": "idade_mediana", "8845": "razao_sexo"}
    for x in sidra("t/9515/n6/all/v/10612,10613,8845/p/2022"):
        reg(x["D1C"], x["D1N"])[nomes[x["D2C"]]] = _num(x["V"])
    for x in sidra("t/9718/n6/all/v/350/p/2022/c1714/60024/c2661/32776,12869"):
        campo = "populacao_indigena" if x["D5C"] == "32776" else "populacao_indigena_terra_indigena"
        reg(x["D1C"], x["D1N"])[campo] = _num(x["V"])
    for x in sidra("t/9578/n6/all/v/4709/p/2022/c2661/32776,60027"):
        campo = "populacao_quilombola" if x["D4C"] == "32776" else "populacao_quilombola_territorio_quilombola"
        reg(x["D1C"], x["D1N"])[campo] = _num(x["V"])

    colunas = ["id_municipio", "id_municipio_nome", "sigla_uf", "domicilios", "populacao", "area",
               "taxa_alfabetizacao", "indice_envelhecimento", "idade_mediana", "razao_sexo",
               "populacao_indigena", "populacao_indigena_terra_indigena", "populacao_quilombola",
               "populacao_quilombola_territorio_quilombola"]
    return [{c: r.get(c) for c in colunas} for _, r in sorted(mun.items())]
