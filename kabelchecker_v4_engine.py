"""Rekenkern Kabelchecker v4.

Leest regeltemplate_v4 (Excel) en toetst tracédelen in vier vaste stappen:
feiten afleiden -> vergunningplicht (2.15) -> regimes -> zorgplichtregels.
Elke toets heeft drie uitkomsten: waar, onwaar of onbekend (gegeven ontbreekt).

Gebruik vanaf de opdrachtregel (testgevallen draaien en terugschrijven):
    python kabelchecker_v4_engine.py regeltemplate_v4_AGV.xlsx --test
"""
from __future__ import annotations

import ast
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


# ---------------------------------------------------------------- drie-waardige logica
class _Onbekend:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "onbekend"

    def __bool__(self):
        raise TypeError("onbekend heeft geen waarheidswaarde")


ONBEKEND = _Onbekend()


def is_onbekend(v) -> bool:
    return v is ONBEKEND


class ExpressieFout(Exception):
    pass


def _vertaal(expr: str) -> str:
    s = re.sub(r"\bAND\b", " and ", expr)
    s = re.sub(r"\bOR\b", " or ", s)
    s = re.sub(r"\bNOT\b", " not ", s)
    return s.strip()


_CACHE: dict[str, ast.AST] = {}


def parse(expr: str) -> ast.AST:
    if expr not in _CACHE:
        try:
            _CACHE[expr] = ast.parse(_vertaal(expr), mode="eval").body
        except SyntaxError as e:
            raise ExpressieFout(f"Kan expressie niet lezen: {expr!r} ({e.msg})") from None
    return _CACHE[expr]


def _norm(v):
    if isinstance(v, str):
        return v.strip().lower()
    return v


class Context:
    """Zoekt namen op: invoer, geo-feiten, parameters en (recursief) begrippen."""

    def __init__(self, invoer: dict, geo: dict, params: dict, begrippen: dict[str, str]):
        self.invoer = {k: v for k, v in invoer.items() if v not in (None, "")}
        self.geo = geo
        self.params = params
        self.begrippen = begrippen
        self._memo: dict[str, Any] = {}
        self.gebruikt_onbekend: set[str] = set()

    def waarde(self, naam: str):
        if naam in self._memo:
            return self._memo[naam]
        if naam in self.params:
            v = self.params[naam]
        elif naam in self.invoer:
            v = self.invoer[naam]
        elif naam in self.geo:
            v = self.geo[naam]
            if v is None:
                v = ONBEKEND
        elif naam in self.begrippen and not self.begrippen[naam].startswith("geo"):
            self._memo[naam] = ONBEKEND  # bescherming tegen kringverwijzing
            v = evalueer(self.begrippen[naam], self)
        else:
            v = ONBEKEND
        if is_onbekend(v) and naam not in self.begrippen and naam not in self.params:
            self.gebruikt_onbekend.add(naam)
        self._memo[naam] = v
        return v


def _vergelijk(op, a, b):
    if is_onbekend(a) or is_onbekend(b):
        return ONBEKEND
    if isinstance(op, ast.In):
        return _norm(a) in [_norm(x) for x in b]
    if isinstance(op, ast.NotIn):
        return _norm(a) not in [_norm(x) for x in b]
    a, b = _norm(a), _norm(b)
    try:
        if isinstance(op, ast.Eq):
            return a == b
        if isinstance(op, ast.NotEq):
            return a != b
        a, b = float(a), float(b)
        return {ast.Lt: a < b, ast.LtE: a <= b, ast.Gt: a > b, ast.GtE: a >= b}[type(op)]
    except (TypeError, ValueError, KeyError):
        raise ExpressieFout(f"Kan {a!r} en {b!r} niet vergelijken")


def _ev(node, ctx: Context):
    if isinstance(node, ast.BoolOp):
        waarden = [_ev(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            if any(v is False for v in waarden):
                return False
            return ONBEKEND if any(is_onbekend(v) for v in waarden) else True
        if any(v is True for v in waarden):
            return True
        return ONBEKEND if any(is_onbekend(v) for v in waarden) else False
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        v = _ev(node.operand, ctx)
        return ONBEKEND if is_onbekend(v) else (not _als_bool(v))
    if isinstance(node, ast.Compare):
        links = _ev(node.left, ctx)
        uitkomst: Any = True
        for op, rechts_node in zip(node.ops, node.comparators):
            rechts = _ev(rechts_node, ctx)
            r = _vergelijk(op, links, rechts)
            if r is False:
                return False
            if is_onbekend(r):
                uitkomst = ONBEKEND
            links = rechts
        return uitkomst
    if isinstance(node, ast.Name):
        if node.id in ("True", "False"):
            return node.id == "True"
        return ctx.waarde(node.id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_ev(e, ctx) for e in node.elts]
    raise ExpressieFout(f"Niet toegestaan in expressie: {ast.dump(node)[:60]}")


def _als_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("ja", "true", "waar", "1")
    return bool(v)


def evalueer(expr: str, ctx: Context):
    """Geeft True, False of ONBEKEND. Lege expressie = True."""
    if not expr or not str(expr).strip():
        return True
    v = _ev(parse(str(expr)), ctx)
    return v if is_onbekend(v) else _als_bool(v)


# ---------------------------------------------------------------- template
@dataclass
class Template:
    params: dict[str, Any]
    begrippen: dict[str, str]
    zones: list[str]
    invoervelden: list[dict]
    vergunning: list[dict]
    regimes: list[dict]
    zorgplicht: list[dict]
    pad: Path | None = None


def _rijen(ws):
    it = ws.iter_rows(values_only=True)
    koppen = [str(k).strip() if k is not None else "" for k in next(it)]
    for r in it:
        if r is None or all(v in (None, "") for v in r):
            continue
        yield {k: v for k, v in zip(koppen, r) if k}


def laad_template(pad) -> Template:
    wb = load_workbook(pad, data_only=True)
    params = {}
    for r in _rijen(wb["Parameters"]):
        if r.get("naam"):
            params[str(r["naam"]).strip()] = float(r["waarde"])
    zones = [str(r["code"]).strip() for r in _rijen(wb["Zones"])
             if r.get("code") and re.fullmatch(r"[A-Z]+-[A-Z]+", str(r["code"]).strip())]
    begrippen = {str(r["naam"]).strip(): str(r.get("formule") or "").strip()
                 for r in _rijen(wb["Begrippen"]) if r.get("naam")}
    invoervelden = [r for r in _rijen(wb["Invoervelden"]) if r.get("veld")]

    def zones_van(r):
        return {z for z in zones if str(r.get(z, "")).strip().lower() == "ja"}

    vergunning = [dict(id=r["id"], lid=str(r["lid"]), zones=zones_van(r), voorwaarde=str(r.get("voorwaarde") or ""),
                       tekst=r.get("wsv-tekst") or "") for r in _rijen(wb["Vergunning_2.15"]) if r.get("id")]
    regimes = [dict(code=str(r["code"]).strip(), artikel=str(r.get("artikel") or ""), voorwaarde=str(r.get("voorwaarde") or ""),
                    omschrijving=r.get("omschrijving") or "") for r in _rijen(wb["Regimes"]) if r.get("code")]
    zorg = []
    for r in _rijen(wb["Zorgplicht"]):
        if not r.get("artikel"):
            continue
        zorg.append(dict(artikel=str(r["artikel"]).strip(), regime=str(r.get("regime") or "").strip(), zones=zones_van(r),
                         van_toepassing=str(r.get("van toepassing als") or ""), toets=str(r.get("toets") or ""),
                         soort=str(r.get("soort") or "voorschrift").strip().lower(),
                         voorschrift=r.get("voorschrift (bij voldoen)") or "", niet=r.get("tekst bij niet voldoen") or "",
                         wsv=r.get("wsv-tekst") or ""))
    return Template(params, begrippen, zones, invoervelden, vergunning, regimes, zorg, Path(pad))


# ---------------------------------------------------------------- toetsing van één deel
OORDELEN = ["vergunning", "maatwerk", "onvolledig", "aandacht", "voorschriften",
            "geen_specifieke_regels", "buiten_beperkingengebied"]


@dataclass
class Regeluitkomst:
    stap: str            # vergunning / regime / zorgplicht
    artikel: str
    uitkomst: str        # vergunning, voldoet, voldoet_niet, onbekend, voorschrift, aandacht, n.v.t.
    tekst: str = ""
    ontbrekend: list[str] = field(default_factory=list)


@dataclass
class Deeluitkomst:
    oordeel: str
    zones: list[str]
    regimes: list[str]
    regels: list[Regeluitkomst]
    vragen: list[str]    # velden om aan de vergunningverlener te vragen

    def artikelen(self, *uitkomsten):
        return [r.artikel for r in self.regels if r.uitkomst in uitkomsten]


def toets_deel(t: Template, invoer: dict, zones: set[str], geo: dict) -> Deeluitkomst:
    zones = {z for z in zones if z in t.zones}
    regels: list[Regeluitkomst] = []
    vragen: set[str] = set()
    if not zones:
        return Deeluitkomst("buiten_beperkingengebied", [], [], [], [])

    def ctx():
        return Context(invoer, geo, t.params, t.begrippen)

    # stap 2: vergunning
    for v in t.vergunning:
        if not (v["zones"] & zones):
            continue
        c = ctx()
        r = evalueer(v["voorwaarde"], c)
        if r is True:
            regels.append(Regeluitkomst("vergunning", v["lid"], "vergunning", v["tekst"]))
        elif is_onbekend(r):
            ontbr = sorted(c.gebruikt_onbekend)
            vragen |= set(ontbr)
            regels.append(Regeluitkomst("vergunning", v["lid"], "onbekend",
                                        f"Vergunningplicht {v['lid']} niet vast te stellen", ontbr))

    # stap 3: regimes
    regimes = []
    for rg in t.regimes:
        c = ctx()
        r = evalueer(rg["voorwaarde"], c)
        if r is True:
            regimes.append(rg["code"])
        elif is_onbekend(r):
            ontbr = sorted(c.gebruikt_onbekend)
            vragen |= set(ontbr)
            regels.append(Regeluitkomst("regime", rg["code"], "onbekend",
                                        f"Niet vast te stellen of {rg['artikel']} geldt", ontbr))

    # stap 4: zorgplicht
    for z in t.zorgplicht:
        if z["regime"] not in regimes or not (z["zones"] & zones):
            continue
        c = ctx()
        vta = evalueer(z["van_toepassing"], c)
        if vta is False:
            continue
        if is_onbekend(vta):
            ontbr = sorted(c.gebruikt_onbekend)
            vragen |= set(ontbr)
            regels.append(Regeluitkomst("zorgplicht", z["artikel"], "onbekend", z["wsv"], ontbr))
            continue
        if z["soort"] == "aandacht":
            regels.append(Regeluitkomst("zorgplicht", z["artikel"], "aandacht", z["wsv"]))
        elif z["soort"] == "toets" and z["toets"]:
            r = evalueer(z["toets"], c)
            if r is True:
                regels.append(Regeluitkomst("zorgplicht", z["artikel"], "voldoet", z["voorschrift"]))
            elif r is False:
                regels.append(Regeluitkomst("zorgplicht", z["artikel"], "voldoet_niet", z["niet"]))
            else:
                ontbr = sorted(c.gebruikt_onbekend)
                vragen |= set(ontbr)
                regels.append(Regeluitkomst("zorgplicht", z["artikel"], "onbekend", z["wsv"], ontbr))
        else:
            regels.append(Regeluitkomst("zorgplicht", z["artikel"], "voorschrift", z["voorschrift"]))

    soorten = {r.uitkomst for r in regels}
    if "vergunning" in soorten:
        oordeel = "vergunning"
    elif "voldoet_niet" in soorten:
        oordeel = "maatwerk"
    elif "onbekend" in soorten:
        oordeel = "onvolledig"
    elif "aandacht" in soorten:
        oordeel = "aandacht"
    elif soorten & {"voldoet", "voorschrift"}:
        oordeel = "voorschriften"
    else:
        oordeel = "geen_specifieke_regels"
    return Deeluitkomst(oordeel, sorted(zones), regimes, regels, sorted(vragen))


def zwaarste(oordelen) -> str:
    oordelen = list(oordelen)
    return min(oordelen, key=OORDELEN.index) if oordelen else "buiten_beperkingengebied"


# ---------------------------------------------------------------- geometrie
DIJKTYPE = {"waterkerend": "WK", "half-verholen": "HV", "half verholen": "HV", "verholen": "VH"}
ZONETYPE = {"kernzone": "KZ", "beschermingszone": "BZ", "buitenbeschermingszone": "BBZ"}


def zonecode(dijktype, zone) -> str | None:
    a = DIJKTYPE.get(str(dijktype).strip().lower())
    b = ZONETYPE.get(str(zone).strip().lower())
    return f"{a}-{b}" if a and b else None


@dataclass
class GeoLagen:
    zones: Any           # GeoDataFrame met kolommen code, zonecode
    referentielijnen: Any  # GeoDataFrame met kolommen code, dijktype
    kruin: Any           # GeoDataFrame met kolom keringtype (WK/HV/VH)


def laad_geolagen(data_agv: Path) -> GeoLagen:
    import geopandas as gpd
    import pandas as pd
    lv = data_agv / "Legger_verwerkt" / "Alle_keringen"
    zones = gpd.read_file(lv / "Zones_alle_keringen.shp")
    zones["zonecode"] = [zonecode(d, z) for d, z in zip(zones["dijktype"], zones["zone"])]
    zones = zones[zones["zonecode"].notna()].to_crs(28992)
    refl = gpd.read_file(lv / "Referentielijnen_alle_keringen.shp").to_crs(28992)
    kr = []
    for namen, kt in [(("waterkerend_kruin.shp", "19_kruin_waterkerend.shp"), "WK"),
                      (("half-verholen_kruin.shp", "20_kruin_half_verholen.shp"), "HV"),
                      (("verholen_kruin.shp", "21_kruin_verholen.shp"), "VH")]:
        opties = [lv / namen[0], data_agv / "kruinlagen" / namen[1]]
        p = next((o for o in opties if o.exists()), None)
        if p is not None:
            g = gpd.read_file(p).to_crs(28992)
            g = g.explode(index_parts=False)
            g["keringtype"] = kt
            kr.append(g[["keringtype", "geometry"]])
    kruin = gpd.GeoDataFrame(pd.concat(kr, ignore_index=True), crs=28992) if kr else None
    return GeoLagen(zones, refl, kruin)


def _hoek(geom) -> float | None:
    cs = list(geom.coords) if geom.geom_type == "LineString" else None
    if not cs or len(cs) < 2:
        return None
    (x0, y0), (x1, y1) = cs[0][:2], cs[-1][:2]
    if x0 == x1 and y0 == y1:
        return None
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180


def _lokale_richting(lijn, punt) -> tuple[float, tuple[float, float]] | None:
    """Richting (graden) en voetpunt van het stuk referentielijn het dichtst bij punt."""
    from shapely.geometry import LineString
    d = lijn.project(punt)
    a = lijn.interpolate(max(d - 2.0, 0))
    b = lijn.interpolate(min(d + 2.0, lijn.length))
    if a.equals(b):
        return None
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x)) % 180, (lijn.interpolate(d).x, lijn.interpolate(d).y)


def _offsetbereik(geom, richting, voet) -> tuple[float, float]:
    """Bereik van afstanden haaks op de kering (min, max) van alle punten van geom."""
    r = math.radians(richting)
    nx, ny = -math.sin(r), math.cos(r)
    pts = []
    if hasattr(geom, "geoms"):
        for g in geom.geoms:
            pts += list(g.exterior.coords) if g.geom_type == "Polygon" else list(g.coords)
    elif geom.geom_type == "Polygon":
        pts = list(geom.exterior.coords)
    else:
        pts = list(geom.coords)
    offs = [(p[0] - voet[0]) * nx + (p[1] - voet[1]) * ny for p in pts]
    return (min(offs), max(offs)) if offs else (0.0, 0.0)


def _aandeel(deel, vlak, richting, voet, straal=50.0):
    """Welk deel van de breedte van 'vlak' (lokaal rond voet) het deel overbrugt."""
    from shapely.geometry import Point
    lokaal = vlak.intersection(Point(voet).buffer(straal))
    if lokaal.is_empty:
        return None
    vmin, vmax = _offsetbereik(lokaal, richting, voet)
    stuk = deel.intersection(lokaal)
    if stuk.is_empty or vmax - vmin <= 0:
        return 0.0
    dmin, dmax = _offsetbereik(stuk, richting, voet) if stuk.geom_type in ("LineString", "MultiLineString") else (0, 0)
    return max(0.0, min(1.0, (min(dmax, vmax) - max(dmin, vmin)) / (vmax - vmin)))


def splits_trace(lijn, lagen: GeoLagen, params: dict) -> list[dict]:
    """Knipt een lijn op bij zonegrenzen. Geeft delen met geometrie, zones, keringcodes en geo-feiten."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import split, unary_union, linemerge

    kandidaten = lagen.zones[lagen.zones.intersects(lijn.buffer(1))]
    grenzen = unary_union([g.boundary for g in kandidaten.geometry]) if len(kandidaten) else None
    if grenzen is not None and not grenzen.is_empty:
        try:
            stukken = list(split(lijn, grenzen).geoms)
        except Exception:
            stukken = [lijn]
    else:
        stukken = [lijn]

    snap = params.get("SNAP_AFSTAND_M", 0.5)
    delen: list[dict] = []
    for s in stukken:
        if s.length <= 0:
            continue
        mid = s.interpolate(0.5, normalized=True)
        bevat = kandidaten[kandidaten.contains(mid)]
        zset = frozenset(bevat["zonecode"])
        kering = frozenset(bevat["code"])
        if delen and (delen[-1]["zones"] == zset or s.length < snap):
            delen[-1]["stukken"].append(s)
            continue
        delen.append(dict(zones=zset, keringen=kering, stukken=[s]))
    uit = []
    for d in delen:
        g = linemerge(MultiLineString(d["stukken"])) if len(d["stukken"]) > 1 else d["stukken"][0]
        uit.append(dict(geometry=g, zones=set(d["zones"]), keringen=sorted(d["keringen"]),
                        geo=geo_feiten(g, d["zones"], d["keringen"], lagen, params)))
    return uit


def geo_feiten(deel, zones, keringen, lagen: GeoLagen, params: dict) -> dict:
    from shapely.ops import unary_union
    zonder_kruin = lagen.kruin is None
    feiten = dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.0, hoek_met_kering=None,
                  raakt_kruin=None if zonder_kruin else False, dwars_door_kruin=None if zonder_kruin else False)
    if not zones:
        return feiten
    refl = lagen.referentielijnen
    refl = refl[refl["code"].isin(keringen)] if keringen else refl.iloc[0:0]
    if len(refl) == 0:
        refl = lagen.referentielijnen[lagen.referentielijnen.distance(deel) < 100]
    if len(refl):
        lijn = unary_union(list(refl.geometry))
        feiten["kruist_referentielijn"] = bool(deel.intersects(lijn))
        from shapely.ops import linemerge
        if lijn.geom_type == "MultiLineString":
            lijn = linemerge(lijn)
        if lijn.geom_type == "MultiLineString":
            lijn = min(lijn.geoms, key=lambda g: g.distance(deel))
        mid = deel.interpolate(0.5, normalized=True)
        lr = _lokale_richting(lijn, mid)
        hd = _hoek(deel) if deel.geom_type == "LineString" else None
        if lr and hd is not None:
            verschil = abs(hd - lr[0]) % 180
            feiten["hoek_met_kering"] = round(min(verschil, 180 - verschil), 1)
        if lr:
            richting, _ = lr
            voet_d = lijn.project(mid)
            vp = lijn.interpolate(voet_d)
            voet = (vp.x, vp.y)
            kz = lagen.zones[(lagen.zones["zonecode"] == "WK-KZ") & (lagen.zones["code"].isin(keringen))]
            if len(kz) and "WK-KZ" in zones:
                kzv = unary_union(list(kz.geometry))
                # meet bij het midden en bij elk punt waar het deel de referentielijn kruist; neem het grootste
                punten = [voet]
                kruis = deel.intersection(lijn)
                for p in getattr(kruis, "geoms", [kruis]):
                    if p.geom_type == "Point":
                        punten.append((p.x, p.y))
                beste = None
                for pt in punten:
                    from shapely.geometry import Point as _P
                    lr2 = _lokale_richting(lijn, _P(pt))
                    if not lr2:
                        continue
                    a = _aandeel(deel, kzv, lr2[0], lr2[1])
                    if a is not None and (beste is None or a > beste):
                        beste = a
                feiten["dwars_aandeel_kernzone"] = round(beste, 2) if beste is not None else None
            if lagen.kruin is not None:
                kt = {z.split("-")[0] for z in zones}
                kr = lagen.kruin[lagen.kruin["keringtype"].isin(kt) & lagen.kruin.intersects(deel.buffer(0.01))]
                if len(kr):
                    kv = unary_union(list(kr.geometry))
                    feiten["raakt_kruin"] = True
                    a = _aandeel(deel, kv, richting, voet)
                    feiten["dwars_door_kruin"] = bool(a is not None and a >= params.get("DWARS_AANDEEL", 0.75))
    return feiten


def toets_trace(t: Template, lijn, invoer: dict, lagen: GeoLagen):
    delen = splits_trace(lijn, lagen, t.params)
    resultaten = []
    for d in delen:
        resultaten.append((d, toets_deel(t, invoer, d["zones"], d["geo"])))
    return zwaarste(r.oordeel for _, r in resultaten), resultaten


# ---------------------------------------------------------------- testgevallen
def _lees_kv(s) -> dict:
    uit = {}
    for paar in str(s or "").split(";"):
        if "=" not in paar:
            continue
        k, v = (x.strip() for x in paar.split("=", 1))
        if v in ("True", "False"):
            v = v == "True"
        else:
            try:
                v = float(v) if "." in v else int(v)
            except ValueError:
                pass
        uit[k] = v
    return uit


def draai_testgevallen(pad, schrijf=True) -> int:
    t = laad_template(pad)
    wb = load_workbook(pad)
    ws = wb["Testgevallen"]
    koppen = [c.value for c in ws[1]]
    k = {n: i for i, n in enumerate(koppen)}
    fout = 0
    for row in ws.iter_rows(min_row=2):
        if not row[0].value:
            continue
        zones = {z.strip() for z in str(row[k["zone"]].value or "").split(",") if z.strip()}
        r = toets_deel(t, _lees_kv(row[k["eigenschappen"]].value), zones, _lees_kv(row[k["geo-feiten"]].value))
        verwacht = str(row[k["verwacht oordeel"]].value).strip()
        ok = r.oordeel == verwacht
        fout += not ok
        arts = []
        for soort in ("vergunning", "voldoet_niet", "onbekend", "aandacht"):
            a = r.artikelen(soort)
            if a:
                arts.append(f"{soort}: {', '.join(a)}")
        if r.vragen:
            arts.append("vragen: " + ", ".join(r.vragen))
        row[k["uitkomst rekenkern"]].value = r.oordeel
        row[k["geraakte artikelen"]].value = " | ".join(arts)
        row[k["status"]].value = "OK" if ok else "AFWIJKING"
        print(f"{row[0].value}: {'OK ' if ok else 'XX '} verwacht={verwacht:<24} uitkomst={r.oordeel:<24} {' | '.join(arts)}")
    if schrijf:
        wb.save(pad)
    print(f"{fout} afwijking(en)")
    return fout


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[2] == "--test":
        sys.exit(1 if draai_testgevallen(sys.argv[1]) else 0)
    print(__doc__)
