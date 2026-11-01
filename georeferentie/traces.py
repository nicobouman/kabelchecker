"""Tracés uit een AutoCAD-PDF halen en als shapefiles per soort wegschrijven.

Werkwijze:
1. Lijnen lezen uit de PDF-lagen (NLCS-laagnamen, bijv. N-OI-RI-DWA_RIOOLLEIDING_PVC_250-G).
   De laagnaam geeft status (N nieuw, V vervallen), soort, materiaal en diameter.
2. Alleen lijnen in het kaartvenster waarin de paspunten liggen. Legenda, titelblok,
   situatiekaartje en details vallen daarmee weg.
3. Losse lijnstukjes (ook streepjeslijnen) aan elkaar rijgen tot tracés.
4. Labels, boringen en BOB-hoogtes uit de tekst rond de lijn halen.
5. Met de georeferentie omrekenen naar RD en per soort een shapefile maken.
6. Met alle=True ook de overige leidinglagen (bestaand, van anderen) teruggeven; laagkeuzes()
   koppelt ze aan de legenda (naam en lijnvoorbeeld) zodat de gebruiker zelf kan aanvinken.

Regels (oefenen_traces/regels_tracés.md):
- alleen nieuw en vervallen/verwijderen; bestaand en cyaan gaan niet mee;
- één shapefile per soort voor nieuw (DWA, HWA, drinkwater, ...), één voor vervallen
  (riolering) of verwijderen (drinkwater) met soort als kolom;
- huis- en perceelaansluitingen zitten in de shapefile van de leiding waar ze aan vastzitten;
  kolkaansluitingen bij HWA; vervallen huisaansluitingen gaan alleen mee als de tekening
  zegt dat de aansluiting verwijderd wordt (bijv. "Verwijderen Aansluitleiding" in de legenda);
- volgeschuimd telt als vervallen;
- kabels en leidingen van anderen, ondergrond, hulpstukken en details gaan niet mee.
"""
from __future__ import annotations

import io
import math
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .kern import Transformatie

# ------------------------------------------------------------------ laagnamen
_LAAG = re.compile(r"^([NVB])-[A-Z]{2}-(RI|KL)-(.+)-G$")
_HULPLAGEN = ("BUITENKANT", "BINNENKANT", "STROMINGSRICHTING", "HARTLIJN", "DETAIL", "AANPIJLING",
              "OPSTELLING", "POMP", "PUT", "SCHILDMUUR", "HULPSTUK", "MAATVOERING", "LABEL")
_SOORT_RI = {"DWA": "DWA", "HWA": "HWA", "GWA": "GWA", "DRAINAGE": "drainage", "TRANSPORTRIOOL": "transportriool",
             "PERSLEIDING": "persleiding", "DRUK": "drukriool", "OVERIG": "overig", "VWA": "DWA", "RWA": "HWA"}
_SCHUIM = re.compile(r"VOLSCHUIM|VOLGESCHUIMD")
_LEIDINGWOORD = re.compile(r"LEIDING|DRAIN|RIOOL|MANTELBUIS")


@dataclass
class Laag:
    naam: str            # volledige laagnaam
    status: str          # nieuw / vervallen / verwijderen / volgeschuimd / bestaand
    soort: str           # drinkwater / DWA / HWA / ... (bij anderen: gas, laagspanning, ...)
    functie: str         # leiding / huisaansluiting / kolkaansluiting / mantelbuis
    materiaal: str | None
    diameter: float | None
    discipline: str      # DW, AW, of 'anders' (kabels en leidingen van anderen)
    standaard: bool = True   # gaat volgens de regels mee (nieuw/vervallen, eigen leidingen)


_ANDERS_WOORD = re.compile(r"LEIDING|DRAIN|RIOOL|MANTELBUIS|KABEL|BUIS|MANTEL")


def ontleed_laag(naam: str, alle: bool = False) -> Laag | None:
    """NLCS-laagnaam -> Laag, of None als het geen leidinglaag is.

    Zonder alle: alleen de lagen die volgens de regels meegaan (nieuw en vervallen, eigen
    leidingen). Met alle ook bestaande leidingen en kabels en leidingen van anderen
    (standaard=False), zodat de gebruiker ze zelf kan aanvinken."""
    kort = naam.split("|")[-1].strip()
    m = _LAAG.match(kort)
    if not m:
        return None
    st, thema, rest = m.groups()
    if st == "B" and not alle:
        return None                                   # bestaand: niet mee
    if any(h in rest for h in _HULPLAGEN):
        return None
    delen = rest.split("_")
    if thema == "KL" and delen[0] != "WATER":         # kabels en leidingen van anderen
        if not alle or not _ANDERS_WOORD.search(rest):
            return None
        soort, discipline = delen[0].split("-")[0].lower(), "anders"
    elif thema == "KL":
        soort, discipline = "drinkwater", "DW"
    else:
        hoofd = delen[0].split("-")[0]
        if hoofd not in _SOORT_RI:
            return None
        soort, discipline = _SOORT_RI[hoofd], "AW"
    if discipline != "anders" and not _LEIDINGWOORD.search(rest):
        return None
    if "AANSLUIT" in rest and "KOLK" not in rest:
        functie = "huisaansluiting"
    elif "KOLK" in rest:
        functie = "kolkaansluiting"
    elif "MANTELBUIS" in rest:
        functie = "mantelbuis"
    else:
        functie = "leiding"
    if st == "B":
        status = "bestaand"
    elif _SCHUIM.search(rest):
        status = "volgeschuimd"
    elif st == "N":
        status = "nieuw"
    else:
        status = "verwijderen" if discipline == "DW" else "vervallen"
    materiaal = diameter = None
    staart = [d for d in delen[1:] if not _SCHUIM.search(d)]
    if len(staart) >= 2 and re.fullmatch(r"\d+(?:[.,]\d+)?", staart[-1]):
        diameter = float(staart[-1].replace(",", "."))
        materiaal = staart[-2].strip() or None
    standaard = st != "B" and discipline != "anders"
    return Laag(naam, status, soort, functie, materiaal, diameter, discipline, standaard)


def shapefile_naam(laag: Laag) -> str:
    if laag.status == "nieuw":
        return f"nieuw_{laag.soort}"
    if laag.status == "bestaand":
        return f"bestaand_{laag.soort}"
    if laag.discipline == "anders":
        return f"{laag.status}_{laag.soort}"
    return "verwijderen" if laag.discipline == "DW" else "vervallen"


# ------------------------------------------------------------------ PDF lezen
def _is_cyaan(kleur) -> bool:
    if not kleur:
        return False
    r, g, b = kleur[:3]
    return r < 0.25 and g >= 0.7 and b >= 0.7


def _bezier(p, n=6):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = (np.array([q.x, q.y]) for q in p)
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


@dataclass
class _Pad:
    laag: Laag
    punten: np.ndarray           # (n, 2) in pt van de weergegeven pagina
    venster: tuple               # clip-rechthoek (pt, weergegeven pagina)
    kleur: tuple = ()            # lijnkleur (r, g, b)
    breedte: float = 0.0         # lijndikte (pt)
    streep: str = ""             # streeppatroon, bijv. '[3 2] 0'


def _draai(page):
    """Functie die PDF-coördinaten omzet naar de weergegeven (gedraaide) pagina."""
    if not page.rotation:
        return lambda a: np.asarray(a, float)
    m = page.rotation_matrix
    M = np.array([[m.a, m.c], [m.b, m.d]]); t = np.array([m.e, m.f])
    return lambda a: np.asarray(a, float) @ M.T + t


MIN_PAD_PT = 4.5     # kleinere tekenobjecten zijn versiering van de lijnstijl (1,6 mm op papier)


def lees_paden(page, alle: bool = False) -> tuple[list[_Pad], set]:
    """Alle lijnen op leidinglagen, met het venster (clip) waarin ze getekend zijn.
    Geeft ook alle vensters op de pagina terug. alle: ook bestaand en van anderen."""
    draai = _draai(page)
    lagen: dict[str, Laag | None] = {}
    uit, stapel, vensters = [], [], set()

    def omgezet(clip):
        c = draai([[clip[0], clip[1]], [clip[2], clip[3]]])
        return (float(min(c[:, 0])), float(min(c[:, 1])), float(max(c[:, 0])), float(max(c[:, 1])))

    for d in page.get_drawings(extended=True):
        lvl = d.get("level", 0)
        while stapel and stapel[-1][0] >= lvl:
            stapel.pop()
        if d["type"] == "clip":
            stapel.append((lvl, tuple(d["scissor"])))
            vensters.add(omgezet(d["scissor"]))
            continue
        if d["type"] == "group":
            continue
        naam = d.get("layer") or ""
        if naam not in lagen:
            lagen[naam] = ontleed_laag(naam, alle)
        laag = lagen[naam]
        if laag is None or "DETAIL" in naam.split("|")[0].upper():
            continue
        if _is_cyaan(d.get("color")) and laag.status != "bestaand":   # cyaan = bestaand
            continue
        if math.hypot(d["rect"].width, d["rect"].height) < MIN_PAD_PT:
            continue                                  # puntje of tekentje van de lijnstijl
        venster = omgezet(stapel[-1][1] if stapel else tuple(page.mediabox))
        for it in d["items"]:
            if it[0] == "l":
                pts = np.array([[it[1].x, it[1].y], [it[2].x, it[2].y]])
            elif it[0] == "c":
                pts = _bezier(it[1:5])
            else:
                continue
            uit.append(_Pad(laag, draai(pts), venster, tuple(d.get("color") or ()),
                            float(d.get("width") or 0), d.get("dashes") or ""))
    return uit, vensters


def _binnen(venster, p) -> bool:
    return venster[0] <= p[0] <= venster[2] and venster[1] <= p[1] <= venster[3]


def kies_venster(paden: list[_Pad], page_rect, paspunten_pt=None, alle_vensters=()):
    """Het kaartvenster: waar de paspunten in liggen, anders het venster met de meeste leidingen.

    Een venster zo groot als de hele pagina is papier (legenda, titelblok) en telt alleen
    als de pagina helemaal geen kaartvenster heeft."""
    breedte, hoogte = page_rect[2] - page_rect[0], page_rect[3] - page_rect[1]
    lengte = defaultdict(float)
    for p in paden:
        lengte[p.venster] += float(np.hypot(*np.diff(p.punten, axis=0).T).sum())

    def is_pagina(v):
        return (v[2] - v[0]) >= 0.99 * breedte and (v[3] - v[1]) >= 0.99 * hoogte

    heeft_kaartvenster = any(not is_pagina(v) and (v[2] - v[0]) * (v[3] - v[1]) > 0.05 * breedte * hoogte
                             for v in alle_vensters)
    kandidaten = [v for v in lengte if not is_pagina(v)]
    if not kandidaten and not heeft_kaartvenster:
        kandidaten = list(lengte)
    if not kandidaten:
        return None
    if paspunten_pt is not None and len(paspunten_pt):
        def score(v):
            return sum(_binnen(v, q) for q in paspunten_pt)
        beste = max(score(v) for v in kandidaten)
        if beste:
            kandidaten = [v for v in kandidaten if score(v) == beste]
    return max(kandidaten, key=lambda v: lengte[v])


# ------------------------------------------------------------------ rijgen
class _Knopen:
    """Punten binnen tol samenvoegen tot één knoop (raster + union-find)."""

    def __init__(self, tol: float):
        self.tol, self.xy, self.ouder, self.cel = tol, [], [], defaultdict(list)

    def _wortel(self, i):
        while self.ouder[i] != i:
            self.ouder[i] = self.ouder[self.ouder[i]]
            i = self.ouder[i]
        return i

    def voeg_toe(self, p) -> int:
        cx, cy = int(math.floor(p[0] / self.tol)), int(math.floor(p[1] / self.tol))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in self.cel.get((cx + dx, cy + dy), ()):
                    q = self.xy[j]
                    if (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 <= self.tol ** 2:
                        return self._wortel(j)
        i = len(self.xy)
        self.xy.append((float(p[0]), float(p[1]))); self.ouder.append(i); self.cel[(cx, cy)].append(i)
        return i


def _richting(a, b):
    v = np.asarray(b, float) - np.asarray(a, float)
    n = np.hypot(*v)
    return v / n if n else v


def rijg(lijnen: list[np.ndarray], tol: float = 0.3, gat: float = 16.0, max_hoek: float = 10.0,
         min_stuk: float = 0.6, max_uitsteeksel: float = 8.0) -> list[np.ndarray]:
    """Losse lijnstukken (in pt) aan elkaar rijgen tot doorlopende lijnen.

    tol:  uiteinden binnen deze afstand zijn hetzelfde punt;
    gat:  een uiteinde dat niet recht doorloopt, wordt verbonden met een ander zo'n uiteinde
          dat in het verlengde ligt (streepjeslijn, lijnstijl met tekens), tot deze afstand;
    min_stuk: kortere stukjes (puntjes in een streep-punt-lijn) worden overgeslagen;
    max_uitsteeksel: korte zijstreepjes (// tekens, schuimsymbool) worden weggesnoeid.
    Lijnen worden geknipt waar drie of meer lijnen samenkomen (aftakkingen)."""
    import shapely
    from shapely.geometry import MultiLineString
    # overlappende stukken (bijv. de voet van een driehoekje op de lijn) samenvoegen en
    # lijnen die elkaar raken of kruisen daar knippen
    stukken = [p for p in lijnen if len(p) >= 2 and np.hypot(*np.diff(p, axis=0).T).sum() >= min_stuk]
    if not stukken:
        return []
    samen = shapely.unary_union(shapely.set_precision(MultiLineString(stukken), tol))
    lijnen = [np.asarray(g.coords, float) for g in shapely.get_parts(samen)
              if g.geom_type == "LineString" and len(g.coords) >= 2]
    kn = _Knopen(tol)
    randen: dict[int, tuple[int, int, np.ndarray]] = {}
    gezien_paar = set()
    for pts in lijnen:
        a, b = kn.voeg_toe(pts[0]), kn.voeg_toe(pts[-1])
        if a == b:
            continue
        if len(pts) == 2:
            if (min(a, b), max(a, b)) in gezien_paar:      # dubbel getekend
                continue
            gezien_paar.add((min(a, b), max(a, b)))
        randen[len(randen)] = (a, b, np.asarray(pts, float))
    volgnr = [len(randen)]

    def bij():
        nb = defaultdict(set)
        for e, (a, b, _) in randen.items():
            nb[a].add(e); nb[b].add(e)
        return nb

    def naar_buiten(e, knoop):
        a, b, pts = randen[e]
        return _richting(pts[1], pts[0]) if a == knoop else _richting(pts[-2], pts[-1])

    def lengte(e):
        return float(np.hypot(*np.diff(randen[e][2], axis=0).T).sum())

    cos_max = math.cos(math.radians(max_hoek))

    def verbind():
        nb = bij()
        # 1. open einden: uiteinden waar de lijn niet recht doorloopt
        open_einden = []
        for knoop, es in nb.items():
            for e in es:
                r = naar_buiten(e, knoop)
                if not any(r @ -naar_buiten(f, knoop) >= cos_max for f in es if f != e):
                    open_einden.append((knoop, e, r))
        # 2. open einden in elkaars verlengde verbinden
        if open_einden:
            xy = np.array([kn.xy[k] for k, _, _ in open_einden])
            rc = np.array([r for _, _, r in open_einden])
            paren = []
            for i in range(len(open_einden)):
                d = xy - xy[i]
                afst = np.hypot(d[:, 0], d[:, 1])
                for j in np.where((afst > tol) & (afst <= gat))[0]:
                    if j <= i or open_einden[i][1] == open_einden[j][1]:
                        continue
                    v = d[j] / afst[j]
                    zijwaarts = abs(rc[i][0] * d[j][1] - rc[i][1] * d[j][0])
                    if rc[i] @ v >= cos_max and rc[j] @ -v >= cos_max and zijwaarts <= max(0.6, 0.03 * afst[j]):
                        paren.append((afst[j], i, j))
            bezet = set()
            for _, i, j in sorted(paren):
                if i in bezet or j in bezet:
                    continue
                bezet.update((i, j))
                a, b = open_einden[i][0], open_einden[j][0]
                randen[volgnr[0]] = (a, b, np.array([kn.xy[a], kn.xy[b]]))
                volgnr[0] += 1

    # 3. versiering van de lijnstijl wegsnoeien: korte zijtakjes en kleine lusjes/bultjes
    #    naast de lijn (drainsymbool, schuimsymbool, // tekens)
    def ketens():
        nb = bij()
        gedaan, uit = set(), []
        for start in [k for k, v in nb.items() if len(v) != 2] + list(nb):
            for e in sorted(nb[start]):
                if e in gedaan:
                    continue
                gedaan.add(e)
                knoop, es = start, [e]
                while True:
                    a, b, _ = randen[e]
                    knoop = b if a == knoop else a
                    volgende = [f for f in nb[knoop] if f not in gedaan]
                    if len(nb[knoop]) != 2 or not volgende or knoop == start:
                        break
                    e = volgende[0]
                    gedaan.add(e); es.append(e)
                uit.append((start, knoop, es))
        return uit, nb

    def snoei():
        max_lus = 2.5 * max_uitsteeksel
        for _ in range(50):
            kt, nb = ketens()
            weg = set()
            paren = defaultdict(list)
            for a, b, es in kt:
                lengte_k = sum(lengte(e) for e in es)
                if a == b and lengte_k <= max_lus:
                    weg.update(es)                                  # klein lusje
                elif lengte_k <= max_uitsteeksel and ((len(nb[a]) == 1 and len(nb[b]) >= 3)
                                                       or (len(nb[b]) == 1 and len(nb[a]) >= 3)):
                    weg.update(es)                                  # zijtakje
                elif a != b:
                    paren[(min(a, b), max(a, b))].append((lengte_k, es))
            for opties in paren.values():
                if len(opties) > 1:                                 # bultje naast de lijn: kortste houden
                    opties.sort(key=lambda o: o[0])
                    for lengte_k, es in opties[1:]:
                        if lengte_k <= max_lus:
                            weg.update(es)
            if not weg:
                break
            for e in weg:
                del randen[e]

    for _ in range(2):
        verbind()
        snoei()
    # 4. doorlopende stukken tussen knopen die geen 'doorloop' zijn
    kt, _ = ketens()
    uit = []
    for start, _, es in kt:
        knoop, pts = start, []
        for e in es:
            a, b, seg = randen[e]
            seg = seg if a == knoop else seg[::-1]
            pts.extend(seg if not pts else seg[1:])
            knoop = b if a == knoop else a
        uit.append(np.asarray(pts, float))
    return uit


# ------------------------------------------------------------------ tekst rond de lijn
BOORTERMEN = re.compile(r"gestuurde\s*boring|boogzinker|boogboring|nano[\s_-]?drill|raketboring|persing|\bboring\b|\bhdd\b",
                        re.I)
_BOB = re.compile(r"^(?:BOB\s*[:=]?\s*)?([+-]?\d{1,2}[.,]\d{2})\s*(\+?NAP|-?MV|m)?$", re.I)
_LENGTE = re.compile(r"(\d+[.,]\d{1,2})\s*m\b")


@dataclass
class _Tekst:
    tekst: str
    xy: tuple[float, float]       # midden, pt van de weergegeven pagina
    laag: str
    bestaand: bool = False        # tekst bij een bestaande leiding (B-laag of cyaan)


def lees_teksten(page) -> list[_Tekst]:
    draai = _draai(page)
    uit = []
    for s in page.get_texttrace():
        t = "".join(chr(c[0]) for c in s["chars"]).strip()
        if not t:
            continue
        b = s["bbox"]
        m = draai([[(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]])[0]
        laag = s.get("layer") or ""
        kleur = s.get("color")
        bestaand = laag.split("|")[-1].startswith("B-") or (kleur is not None and _is_cyaan(kleur))
        uit.append(_Tekst(t, (float(m[0]), float(m[1])), laag, bestaand))
    return uit


def _afstand_tot(pts: np.ndarray, p) -> float:
    a, b = pts[:-1], pts[1:]
    ab = b - a
    n = (ab ** 2).sum(1)
    t = np.clip(((np.asarray(p) - a) * ab).sum(1) / np.where(n == 0, 1, n), 0, 1)
    q = a + t[:, None] * ab
    return float(np.hypot(*(q - p).T).min())


MATERIALEN = ("PVC", "PE", "PP", "GN", "GG", "GY", "GIJ", "AC", "STAAL", "BETON", "GRES", "K", "KOPER", "HPE")
_MAT_DIAM = re.compile(r"\b(" + "|".join(MATERIALEN) + r")\b[\s/a-z]*?(?:SDR\s*\d+\s*)?Ø?\s*(\d{2,4})(?:\s*mm)?\b", re.I)


def materiaal_uit_label(label: str) -> tuple[str | None, float | None]:
    """('GG', 125) uit bijv. 'GG 125mm' of 'DWA GY Ø250 19,95m'."""
    for m in _MAT_DIAM.finditer(label or ""):
        if re.match(r"\s*[\"″]", label[m.end():]):     # maat in inches: diameter niet invullen
            return m.group(1).upper(), None
        return m.group(1).upper(), float(m.group(2))
    return None, None


def _zoek_label(pts, laag: Laag, teksten: list[_Tekst], max_pt: float) -> list[str]:
    """Teksten bij de lijn die materiaal, diameter, soort of een boring noemen."""
    sleutels = [laag.soort.upper()]
    if not laag.materiaal:                      # vervallen lagen hebben vaak geen materiaal in de naam
        sleutels += [m + " " for m in MATERIALEN] + ["Ø"]
    if laag.diameter:
        sleutels.append(f"{laag.diameter:g}")
    if laag.materiaal:
        sleutels.append(laag.materiaal.split()[0].upper())
    status = laag.naam.split("|")[-1][:1]
    gevonden = []
    for t in teksten:
        if t.bestaand != (laag.status == "bestaand"):
            continue
        t_status = re.match(r"([NVB])-[A-Z]{2}-", t.laag.split("|")[-1])
        if t_status and t_status.group(1) != status:
            continue                                   # label van een nieuwe leiding hoort niet bij een vervallen
        boven = t.tekst.upper()
        bijzonder = BOORTERMEN.search(t.tekst) or "MANTEL" in boven
        if not (any(s in boven for s in sleutels) or bijzonder):
            continue
        if laag.diameter and not bijzonder and not re.search(rf"(?<![\d.,]){laag.diameter:g}(?![\d])", boven):
            continue                                   # label van een leiding met een andere diameter
        if "LEGENDA" in t.laag.upper() or "TITELBLOK" in t.laag.upper():
            continue
        d = _afstand_tot(pts, t.xy)
        if d <= (2 * max_pt if bijzonder else max_pt):    # boring staat vaak met een verwijslijn verder weg
            gevonden.append((d, t.tekst))
    gezien, uit = set(), []
    for _, s in sorted(gevonden):
        if s not in gezien:
            gezien.add(s); uit.append(s)
    return uit[:3]


def _bob(pts, laag: Laag, teksten: list[_Tekst], max_pt: float):
    """BOB-hoogtes bij begin en eind (alleen riolering). Geeft (begin, eind, ref)."""
    if laag.discipline != "AW":
        return None, None, None
    uit, ref = [], None
    for eind in (pts[0], pts[-1]):
        beste = None
        for t in teksten:
            m = _BOB.match(t.tekst.replace(" ", ""))
            if not m or t.bestaand or "PUT" in t.laag.upper() or "MAAIVELD" in t.laag.upper():
                continue
            if laag.soort.upper() not in t.laag.upper() and "BOB" not in t.tekst.upper():
                continue
            d = math.dist(eind, t.xy)
            if d <= max_pt and (beste is None or d < beste[0]):
                beste = (d, float(m.group(1).replace(",", ".")), m.group(2))
        uit.append(beste[1] if beste else None)
        if beste and beste[2]:
            ref = "MV" if "MV" in beste[2].upper() else "NAP"
    if any(v is not None for v in uit):
        ref = ref or "NAP"
    return uit[0], uit[1], ref


# ------------------------------------------------------------------ legenda
@dataclass
class LegendaRij:
    tekst: str                    # omschrijving zoals in de legenda, bijv. 'Te leggen Drinkwaterleiding'
    rect: tuple                   # lijnvoorbeeld (pt, weergegeven pagina)
    lagen: dict                   # laagnaam -> getekende lengte in het voorbeeld
    kleur: dict                   # laagnaam -> kleur (r, g, b)

    @property
    def hoofdlaag(self) -> str:
        return max(self.lagen, key=self.lagen.get)


_GETAL = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def _is_papier(clip, mediabox) -> bool:
    return (clip[2] - clip[0]) >= 0.99 * mediabox.width or (clip[3] - clip[1]) >= 0.99 * mediabox.height


def legenda(page) -> list[LegendaRij]:
    """De leidingregels uit de legenda: lijnvoorbeeld (op een leidinglaag, buiten het kaartvenster)
    met de tekst die er rechts naast staat."""
    draai = _draai(page)

    def omgezet(r):
        c = draai([[r[0], r[1]], [r[2], r[3]]])
        return (float(min(c[:, 0])), float(min(c[:, 1])), float(max(c[:, 0])), float(max(c[:, 1])))

    mb = page.mediabox
    stukken, stapel = [], []
    for d in page.get_drawings(extended=True):
        lvl = d.get("level", 0)
        while stapel and stapel[-1][0] >= lvl:
            stapel.pop()
        if d["type"] == "clip":
            stapel.append((lvl, tuple(d["scissor"])))
            continue
        if d["type"] == "group":
            continue
        naam = (d.get("layer") or "").split("|")[-1]
        if not _LAAG.match(naam):
            continue
        if stapel and not _is_papier(stapel[-1][1], mb):
            continue                                   # in een kaartvenster: geen legenda
        r = omgezet(tuple(d["rect"]))
        lengte = sum(math.dist((it[1].x, it[1].y), (it[2].x, it[2].y)) for it in d["items"] if it[0] == "l")
        stukken.append((r, naam, lengte, tuple(round(c, 2) for c in (d.get("color") or ())[:3])))
    # stukken op dezelfde regel (zelfde hoogte, dicht bij elkaar) samenvoegen
    stukken.sort(key=lambda s: (round((s[0][1] + s[0][3]) / 2), s[0][0]))
    rijen: list[list] = []
    for r, naam, lengte, kleur in stukken:
        cy = (r[1] + r[3]) / 2
        for rij in rijen:
            R = rij[0]
            if abs(cy - (R[1] + R[3]) / 2) <= 3.5 and r[0] <= R[2] + 25 and r[2] >= R[0] - 25:
                rij[0] = (min(R[0], r[0]), min(R[1], r[1]), max(R[2], r[2]), max(R[3], r[3]))
                rij[1][naam] = rij[1].get(naam, 0) + lengte
                rij[2].setdefault(naam, kleur)
                break
        else:
            rijen.append([r, {naam: lengte}, {naam: kleur}])
    # tekst rechts naast het voorbeeld; een tekstblok kan meerdere regels bevatten, dus per letter
    spans = []
    for sp in page.get_texttrace():
        laag = (sp.get("layer") or "").split("|")[-1]
        stuk, vorige = [], None
        for c in list(sp["chars"]) + [None]:
            if c is not None:
                b = omgezet(c[3])
                cy, h = (b[1] + b[3]) / 2, max(b[3] - b[1], 1.0)
            if stuk and (c is None or abs(cy - vorige[0]) > h / 2 or b[0] - vorige[1] > 1.5 * h):
                t = "".join(ch for ch, _ in stuk).strip()
                if t:
                    bs = [bb for _, bb in stuk]
                    spans.append(((min(q[0] for q in bs), min(q[1] for q in bs), max(q[2] for q in bs),
                                   max(q[3] for q in bs)), t, laag))
                stuk = []
            if c is None:
                break
            stuk.append((chr(c[0]), b)); vorige = (cy, b[2])
    if any("LEGENDA" in l for _, _, l in spans):
        spans = [(b, t) for b, t, l in spans if "LEGENDA" in l]
    else:
        spans = [(b, t) for b, t, l in spans if not _GETAL.match(t) and not _LAAG.match(l)]
    uit = []
    for R, lagen, kleur in rijen:
        if R[2] - R[0] < 8:                            # geen lijnvoorbeeld (los symbool)
            continue
        cy, h = (R[1] + R[3]) / 2, max(4.0, (R[3] - R[1]) / 2 + 2)
        kand = sorted((b, t) for b, t in spans
                      if abs((b[1] + b[3]) / 2 - cy) <= h and R[2] - 3 <= b[0] <= R[2] + 60
                      or abs((b[1] + b[3]) / 2 - cy) <= h and b[0] > R[2] - 3 and b[0] <= R[2] + 300)
        woorden, rechts = [], None
        for b, t in kand:
            if rechts is None and b[0] > R[2] + 60:
                break
            if rechts is not None and b[0] - rechts > 40:
                break
            woorden.append(t); rechts = b[2] if rechts is None else max(rechts, b[2])
        tekst = " ".join(" ".join(woorden).split())
        if tekst:
            uit.append(LegendaRij(tekst, R, lagen, kleur))
    return uit


def _verwant(a: str, b: str) -> int:
    """Hoeveel woorden twee laagnamen delen (na status en thema)."""
    w = lambda n: set(re.split(r"[_\- ]+", n.split("|")[-1][7:]))
    return len(w(a) & w(b))


def koppel_legenda(laagnaam: str, kleur, rijen: list[LegendaRij]) -> LegendaRij | None:
    """De legendaregel bij een laag uit het kaartvenster: dezelfde laagnaam, anders dezelfde
    status, thema en kleur (de legenda gebruikt soms een andere laag in dezelfde stijl)."""
    kort = laagnaam.split("|")[-1]
    for test in (lambda r: r.hoofdlaag == kort, lambda r: kort in r.lagen):
        hits = [r for r in rijen if test(r)]
        if hits:
            return hits[0]
    k = tuple(round(c, 2) for c in (kleur or ())[:3])
    hits = [r for r in rijen if r.hoofdlaag[:1] == kort[:1] and r.hoofdlaag[5:7] == kort[5:7]
            and r.kleur.get(r.hoofdlaag) == k]
    if not hits:
        return None
    return max(hits, key=lambda r: _verwant(r.hoofdlaag, kort))


# ------------------------------------------------------------------ alles samen
@dataclass
class Trace:
    shapefile: str
    laag: Laag
    pt: np.ndarray                # coördinaten in pt (weergegeven pagina)
    rd: np.ndarray                # coördinaten in RD
    label: str = ""
    aanleg: str = "open"          # open / boogzinker / gestuurde boring / ... / mantelbuis
    bob_begin: float | None = None
    bob_eind: float | None = None
    bob_ref: str | None = None
    materiaal: str | None = None
    diameter: float | None = None
    bron_mat: str = ""             # 'laagnaam' of 'label'
    attrs: dict = field(default_factory=dict)
    standaard: bool = True         # gaat volgens de regels mee (voorinvulling van het vinkje)

    @property
    def lengte_m(self) -> float:
        return float(np.hypot(*np.diff(self.rd, axis=0).T).sum())


GAT_M = 2.5          # streepjeslijn: gaten tot zoveel meter overbruggen
MIN_LENGTE_M = 1.2   # kleinere losse stukjes zijn letters in de lijnstijl, // tekens of putjes


_VERWIJDER_HA = re.compile(r"verwijder\w*\W+(?:\w+\W+)?(?:aansluit|huisaansluit|perceelaansluit)"
                          r"|(?:aansluit|huisaansluit|perceelaansluit)\w*\W+(?:\w+\W+)?verwijder", re.I)


def noemt_verwijderen_aansluiting(page) -> bool:
    """Staat er op de tekening (legenda, titelblok, opmerking) dat een aansluiting verwijderd wordt?"""
    tekst = " ".join(page.get_text().split())
    return bool(_VERWIJDER_HA.search(tekst))


def discipline_uit_naam(naam: str) -> str | None:
    """'DW' (drinkwater) of 'AW' (afvalwater) uit de bestandsnaam, anders None."""
    m = re.search(r"(?:^|[^A-Z])(DW|AW)(?:[^A-Z]|$)", naam.upper())
    return m.group(1) if m else None


def maak_traces(page, tr: Transformatie, alleen: str | None = None,
                min_lengte_m: float = MIN_LENGTE_M, alle: bool = False) -> tuple[list[Trace], dict]:
    """Tracés van één PDF-pagina, in RD. Geeft (tracés, info).

    alleen: 'DW' of 'AW' om alleen drinkwater of alleen riolering mee te nemen (een DW-tekening
    toont soms ook het nieuwe riool van een ander team).
    alle: ook alle andere leidinglagen in het kaartvenster teruggeven (bestaand, van anderen,
    andere discipline, vervallen huisaansluitingen). Wat volgens de regels niet meegaat krijgt
    standaard=False, zodat de gebruiker zelf kan kiezen."""
    paden, vensters = lees_paden(page, alle)
    pas = np.array([p.tekening for p in tr.punten], float) if tr.punten else None
    r = page.rect
    standaard_paden = [p for p in paden if p.laag.standaard] or paden
    venster = kies_venster(standaard_paden, (r.x0, r.y0, r.x1, r.y1), pas, vensters)
    info = {"venster": venster, "lagen": {}, "overgeslagen": set(), "kleur": {}}
    if venster is None:
        return [], info
    m_per_pt = tr.schaal_m_per_pt
    per_laag = defaultdict(list)
    buiten_regels = set()             # laagnamen die alleen met alle meegaan
    for p in paden:
        if p.venster != venster:
            continue
        if not p.laag.standaard:
            buiten_regels.add(p.laag.naam)
        if alleen and p.laag.discipline != alleen:
            if p.laag.standaard:
                info["overgeslagen"].add(p.laag.soort)
            if not alle:
                continue
            buiten_regels.add(p.laag.naam)
        per_laag[p.laag.naam].append(p)
    # vervallen huisaansluitingen gaan alleen mee als de tekening zegt dat ze verwijderd worden,
    # bijv. "Verwijderen Aansluitleiding" in de legenda (case 005). Staat er alleen
    # "Verwijderen Drinkwaterleiding" (01.4954), dan blijven ze weg.
    info["ha_verwijderen"] = noemt_verwijderen_aansluiting(page)
    if not info["ha_verwijderen"]:
        for n in [n for n, ps in per_laag.items()
                  if ps[0].laag.status not in ("nieuw", "bestaand") and ps[0].laag.functie == "huisaansluiting"]:
            if alle:
                buiten_regels.add(n)
            else:
                del per_laag[n]
    for n, ps in per_laag.items():
        kl = defaultdict(float)
        for p in ps:
            kl[(tuple(round(c, 2) for c in p.kleur[:3]), round(p.breedte, 2), p.streep)] += \
                float(np.hypot(*np.diff(p.punten, axis=0).T).sum())
        info["kleur"][n] = max(kl, key=kl.get)          # meest gebruikte kleur, dikte en streep
    teksten = [t for t in lees_teksten(page) if _binnen(venster, t.xy)]
    label_pt = 4.0 / m_per_pt          # tekst tot 4 m van de lijn
    bob_pt = 3.0 / m_per_pt            # BOB tot 3 m van het uiteinde
    traces = []
    for naam, ps in per_laag.items():
        laag = ps[0].laag
        lijnen = rijg([p.punten for p in ps], tol=0.3, gat=GAT_M / m_per_pt, max_uitsteeksel=0.7 / m_per_pt)
        n = 0
        for pts in lijnen:
            rd = tr.naar_rd(pts)
            uitgestrekt = np.hypot(*(rd.max(0) - rd.min(0)))
            if uitgestrekt < min_lengte_m:       # letters in de lijnstijl, // tekens, putjes
                continue
            labels = _zoek_label(pts, laag, teksten, label_pt)
            aanleg = "mantelbuis" if laag.functie == "mantelbuis" else "open"
            for s in labels:
                b = BOORTERMEN.search(s)
                if b:
                    aanleg = b.group(0).lower(); break
                if "MANTEL" in s.upper():
                    aanleg = "mantelbuis"; break
            bb, be, ref = _bob(pts, laag, teksten, bob_pt)
            t = Trace(shapefile_naam(laag), laag, pts, rd, "; ".join(labels), aanleg, bb, be, ref)
            t.materiaal, t.diameter, t.bron_mat = laag.materiaal, laag.diameter, "laagnaam"
            if not laag.materiaal and laag.discipline != "anders":   # labels van anderen: te onzeker
                t.materiaal, t.diameter = materiaal_uit_label(t.label)
                t.bron_mat = "label" if t.materiaal else ""
            t.standaard = naam not in buiten_regels
            traces.append(t)
            n += 1
        info["lagen"][naam] = n
    return traces, info


# ------------------------------------------------------------------ lagen kiezen
_STATUSWOORD = re.compile(r"nieuw|te leggen|vervall|verwijder|bestaand|volschuim|buitendienst|vervangen", re.I)
_VOLGORDE = {"nieuw": 0, "verwijderen": 1, "vervallen": 1, "volgeschuimd": 2, "bestaand": 3}


@dataclass
class LaagKeuze:
    """Eén regel in de keuzelijst: een legendaregel (of laag) met de tracés die erbij horen."""
    sleutel: str
    naam: str                     # zoals in de legenda, met de status erbij als die er niet in staat
    bestand: str                  # naam van de shapefile
    standaard: bool               # voorinvulling van het vinkje (volgens de regels)
    status: str
    lagen: list
    eigenschappen: str            # 'PVC 250 / PVC 160' enz.
    lengte: float
    aantal: int
    voorbeeld: bytes              # PNG van het lijnvoorbeeld
    uit_legenda: bool = True
    traces: list = field(default_factory=list, repr=False)


_AFKORTING = {"ET": "elektra", "LS": "laagspanning", "MS": "middenspanning", "HS": "hoogspanning",
              "LD": "lage druk", "HD": "hoge druk", "OV": "openbare verlichting", "DATA": "data"}


def _leesbaar(laagnaam: str) -> str:
    m = _LAAG.match(laagnaam.split("|")[-1])
    if not m:
        return laagnaam
    woorden = m.group(3).replace("_", " ").replace("-", " ").split()
    return " ".join(_AFKORTING.get(w, w.lower()) for w in woorden).capitalize()


def _voorbeeld_legenda(page, rect) -> bytes:
    """PNG van het lijnvoorbeeld uit de legenda (rect in pt van de weergegeven pagina)."""
    import pymupdf
    x0, y0, x1, y1 = rect
    marge = max(3.0, 0.5 * (8 - (y1 - y0)))
    clip = pymupdf.Rect(x0 - 2, y0 - marge, x1 + 2, y1 + marge) & page.rect
    zoom = max(1.0, min(6.0, 140.0 / max(clip.width, 1)))
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False).tobytes("png")


def _voorbeeld_getekend(kleur, breedte, streep) -> bytes:
    """PNG van een lijn in de kleur, dikte en het streeppatroon van de laag (als de legenda hem niet heeft)."""
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page(width=120, height=14)
    sh = pg.new_shape()
    sh.draw_line((4, 7), (116, 7))
    m = re.match(r"\[([^\]]*)\]", streep or "")
    sh.finish(color=tuple(kleur[:3]) if kleur else (0, 0, 0), width=max(1.0, min(3.0, (breedte or 1) * 1.5)),
              dashes=f"[{m.group(1)}] 0" if m and m.group(1).strip() else None)
    sh.commit()
    return pg.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2), alpha=False).tobytes("png")


def _bestandsnaam(naam: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", naam).strip("_")[:60] or "laag"


def laagkeuzes(page, traces: list[Trace], info: dict) -> list[LaagKeuze]:
    """De keuzelijst: per legendaregel (of laag als de legenda hem niet noemt) de tracés,
    het lijnvoorbeeld uit de legenda en de eigenschappen. Volgorde: wat standaard meegaat eerst."""
    rijen = legenda(page)
    groepen: dict[tuple, list[Trace]] = defaultdict(list)
    koppeling = {}
    for t in traces:
        n = t.laag.naam
        if n not in koppeling:
            koppeling[n] = koppel_legenda(n, info.get("kleur", {}).get(n, ((),))[0], rijen)
        rij = koppeling[n]
        groepen[(id(rij) if rij else n, t.standaard)].append(t)
    uit, namen = [], set()
    for (sl, std), ts in groepen.items():
        rij = koppeling[ts[0].laag.naam]
        statussen = sorted({t.laag.status for t in ts}, key=lambda x: _VOLGORDE.get(x, 9))
        status = statussen[0]
        if rij:
            naam = rij.tekst
            if not _STATUSWOORD.search(naam):
                naam = f"{naam} ({'/'.join(statussen)})"
            voorbeeld = _voorbeeld_legenda(page, rij.rect)
        else:
            naam = f"{_leesbaar(ts[0].laag.naam)} ({status})"
            k = info.get("kleur", {}).get(ts[0].laag.naam, ((0, 0, 0), 1.0, ""))
            voorbeeld = _voorbeeld_getekend(*k)
        if naam in namen:
            naam = f"{naam} - {_leesbaar(ts[0].laag.naam)}"
        namen.add(naam)
        eig = []
        for t in ts:
            e = f"{t.materiaal or '?'} {t.diameter:g}" if t.diameter else (t.materiaal or "")
            if e and e not in eig:
                eig.append(e)
        for t in ts:
            if t.aanleg not in ("open", "mantelbuis") and t.aanleg not in eig:
                eig.append(t.aanleg)
        if any(t.aanleg == "mantelbuis" for t in ts):
            eig.append("mantelbuis")
        lagen = sorted({t.laag.naam.split("|")[-1] for t in ts})
        uit.append(LaagKeuze(str(sl) + ("" if std else "_x"), naam, _bestandsnaam(naam), std, status, lagen,
                             " / ".join(eig), round(sum(t.lengte_m for t in ts), 1), len(ts), voorbeeld,
                             rij is not None, ts))
    uit.sort(key=lambda k: (not k.standaard, _VOLGORDE.get(k.status, 9), k.naam))
    bestanden = set()
    for k in uit:                                     # unieke bestandsnamen
        b, i = k.bestand, 2
        while k.bestand in bestanden:
            k.bestand = f"{b}_{i}"; i += 1
        bestanden.add(k.bestand)
    for i, k in enumerate(uit):                       # stabiele sleutel voor de vinkjes
        k.sleutel = f"{i:02d}_{k.bestand}"
    return uit


def gekozen_traces(keuzes: list[LaagKeuze], gekozen) -> list[Trace]:
    """De tracés van de aangevinkte regels, met als shapefile-naam de naam uit de legenda."""
    import dataclasses
    uit = []
    for k in keuzes:
        if k.sleutel in gekozen:
            uit += [dataclasses.replace(t, shapefile=k.bestand) for t in k.traces]
    return uit


def _dbf_veld(v):
    return "" if v is None else v


def naar_geodataframes(traces: list[Trace], bron: str = ""):
    """Eén GeoDataFrame per shapefile, kolomnamen max. 10 tekens (dBase)."""
    import geopandas as gpd
    from shapely.geometry import LineString
    groepen = defaultdict(list)
    for t in traces:
        lab = t.label
        m = _LENGTE.search(lab or "")
        groepen[t.shapefile].append({
            "status": t.laag.status, "soort": t.laag.soort, "functie": t.laag.functie,
            "type": "mantelbuis" if t.aanleg == "mantelbuis" else "leiding",
            "doel": "huisaansluiting" if t.laag.functie == "huisaansluiting" else "",
            "aanleg": t.aanleg, "materiaal": _dbf_veld(t.materiaal), "diameter": t.diameter,
            "bron_mat": t.bron_mat,
            "label": lab[:254], "lengte_lab": float(m.group(1).replace(",", ".")) if m else None,
            "lengte_geo": round(t.lengte_m, 2), "bob_begin": t.bob_begin, "bob_eind": t.bob_eind,
            "bob_ref": _dbf_veld(t.bob_ref), "laag": t.laag.naam.split("|")[-1][:254], "bron": bron[:254],
            "geometry": LineString(t.rd).simplify(0.01)})
    return {naam: gpd.GeoDataFrame(rijen, geometry="geometry", crs=28992) for naam, rijen in sorted(groepen.items())}


LEESMIJ = """Tracés uit tekening {bron}
Coördinatenstelsel: RD New (EPSG:28992). Gemaakt met de georeferentie-tool.

Shapefiles (één per gekozen laag, genoemd naar de legenda van de tekening):
{lijst}

Kolommen
  status      nieuw / vervallen / verwijderen / volgeschuimd / bestaand (uit de AutoCAD-laagnaam)
  soort       drinkwater / DWA / HWA / GWA / drainage / transportriool / persleiding,
              of bij kabels en leidingen van anderen het thema uit de laagnaam (gas, et, data, ...)
  functie     leiding / huisaansluiting / kolkaansluiting / mantelbuis
  type        leiding of mantelbuis;  doel  'huisaansluiting' bij huis- en perceelaansluitingen
  aanleg      open, of de boortechniek uit de tekst bij de lijn (boogzinker, gestuurde boring, ...)
  materiaal, diameter (mm)  uit de laagnaam, of uit het label als de laagnaam ze niet noemt
  bron_mat    'laagnaam' of 'label' (leeg = onbekend)
  label       teksten bij de lijn die materiaal, diameter, soort of een boring noemen
  lengte_lab  lengte volgens het label (m);  lengte_geo  gemeten lengte (m)
  bob_begin, bob_eind, bob_ref  BOB-hoogtes bij de uiteinden (alleen riolering), NAP of MV
  laag        AutoCAD-laagnaam

Alleen de lagen die in de tool zijn aangevinkt, uit het kaartvenster waarin de paspunten liggen.
Standaard staan aangevinkt: de nieuwe en vervallen/te verwijderen leidingen van de aanvraag
(vervallen huisaansluitingen alleen als de tekening zegt dat de aansluiting verwijderd wordt).

Controleer de uitkomst altijd tegen de tekening: labels en BOB-hoogtes zijn gezocht op afstand
tot de lijn en kunnen bij drukke plekken bij de verkeerde lijn terechtkomen.
"""


def shapefile_zip(traces: list[Trace], stam: str, bron: str = "") -> bytes:
    """Zip met per soort een shapefile (.shp/.shx/.dbf/.prj/.cpg) en een LEESMIJ."""
    import tempfile
    from pathlib import Path
    gdfs = naar_geodataframes(traces, bron)
    z = io.BytesIO()
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        regels = []
        for naam, g in gdfs.items():
            pad = Path(td) / f"{naam}.shp"
            g.to_file(pad, driver="ESRI Shapefile", encoding="UTF-8")
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                f = pad.with_suffix(ext)
                if f.exists():
                    zf.write(f, f"{stam}_traces/{naam}{ext}")
            regels.append(f"  {naam}.shp  {len(g)} lijn(en), {g.length.sum():.0f} m")
        zf.writestr(f"{stam}_traces/LEESMIJ.txt", LEESMIJ.format(bron=bron or stam, lijst="\n".join(regels) or "  (geen)"))
    return z.getvalue()


def samenvatting(traces: list[Trace]) -> list[dict]:
    rij = defaultdict(lambda: {"lijnen": 0, "lengte (m)": 0.0, "materiaal/diameter": set(), "boring/mantelbuis": 0})
    for t in traces:
        r = rij[t.shapefile]
        r["lijnen"] += 1; r["lengte (m)"] += t.lengte_m
        if t.materiaal or t.diameter:
            r["materiaal/diameter"].add(f"{t.materiaal or '?'} {t.diameter:g}" if t.diameter else f"{t.materiaal}")
        r["boring/mantelbuis"] += t.aanleg != "open"
    return [{"shapefile": k, "lijnen": v["lijnen"], "lengte (m)": round(v["lengte (m)"], 1),
             "materiaal/diameter": ", ".join(sorted(v["materiaal/diameter"])), "boring/mantelbuis": v["boring/mantelbuis"]}
            for k, v in sorted(rij.items())]
