"""Adres of plaats zoeken via de PDOK Locatieserver (geeft RD-coordinaten)."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

LOCATIESERVER = "https://api.pdok.nl/bzk/locatieserver/search/v3_1"


def _get(pad: str, **params) -> dict:
    url = f"{LOCATIESERVER}/{pad}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def _punt(wkt: str) -> tuple[float, float]:
    x, y = re.findall(r"[-\d.]+", wkt)[:2]
    return float(x), float(y)


def zoek(tekst: str, aantal: int = 8) -> list[dict]:
    """Zoekresultaten als [{'naam', 'type', 'x', 'y'}] in RD (EPSG:28992)."""
    tekst = tekst.strip()
    if not tekst:
        return []
    # losse RD-coordinaten ("123140 483706") direct teruggeven
    m = re.fullmatch(r"\s*(\d{5,6}(?:[.,]\d+)?)[\s,;]+(\d{6}(?:[.,]\d+)?)\s*", tekst)
    if m:
        x, y = (float(v.replace(",", ".")) for v in m.groups())
        return [{"naam": f"RD {x:.0f}, {y:.0f}", "type": "coordinaat", "x": x, "y": y}]
    d = _get("free", q=tekst, rows=aantal, fl="weergavenaam,type,centroide_rd",
             fq="type:(adres OR weg OR postcode OR woonplaats OR perceel OR buurt OR wijk)")
    uit = []
    for doc in d.get("response", {}).get("docs", []):
        if "centroide_rd" in doc:
            x, y = _punt(doc["centroide_rd"])
            uit.append({"naam": doc["weergavenaam"], "type": doc.get("type", ""), "x": x, "y": y})
    return uit
