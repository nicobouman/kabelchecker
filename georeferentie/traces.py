"""Tracés uit een AutoCAD-PDF halen en als shapefiles per soort wegschrijven.

Werkwijze:
1. Lijnen lezen uit de PDF-lagen (NLCS-laagnamen, bijv. N-OI-RI-DWA_RIOOLLEIDING_PVC_250-G).
   De laagnaam geeft status (N nieuw, V vervallen), soort, materiaal en diameter.
2. Alleen lijnen in het kaartvenster waarin de paspunten liggen. Legenda, titelblok,
   situatiekaartje en details vallen daarmee weg.
3. Losse lijnstukjes (ook streepjeslijnen) aan elkaar rijgen tot tracés.
4. Labels, boringen en BOB-hoogtes uit de tekst rond de lijn halen.
5. Met de georeferentie omrekenen naar RD en per soort een shapefile maken.

Regels (oefenen_traces/regels_tracés.md):
- alleen nieuw en vervallen/verwijderen; bestaand en cyaan gaan niet mee;
- één shapefile per soort voor nieuw (DWA, HWA, drinkwater, ...), één voor vervallen
  (riolering) of verwijderen (drinkwater) met soort als kolom;
- huis- en perceelaansluitingen zitten in de shapefile van de leiding waar ze aan vastzitten;
  kolkaansluitingen bij HWA; vervallen huisaansluitingen gaan niet mee;
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
    status: str          # nieuw / vervallen / verwijderen / volgeschuimd
    soort: str           # drinkwater / DWA / HWA / ...
    functie: str         # leiding / huisaansluiting / kolkaansluiting / mantelbuis
    materiaal: str | None
    diameter: float | None
    discipline: str      # DW of AW


def ontleed_laag(naam: str) -> Laag | None:
    """NLCS-laagnaam -> Laag, of None als de lijn niet mee moet."""
    kort = naam.split("|")[-1].strip()
    m = _LAAG.match(kort)
    if not m:
        return None
    st, thema, rest = m.groups()
    if st == "B":
        return None                                   # bestaand: niet mee
    delen = rest.split("_")
    if thema == "KL":
        if delen[0] != "WATER":                       # kabels en leidingen van anderen
            return None
        soort, discipline = "drinkwater", "DW"
    else:
        hoofd = delen[0].split("-")[0]
        if hoofd not in _SOORT_RI:
            return None
        soort, discipline = _SOORT_RI[hoofd], "AW"
    if any(h in rest for h in _HULPLAGEN) or not _LEIDINGWOORD.search(rest):
        return None
    if "AANSLUIT" in rest and "KOLK" not in rest:
        functie = "huisaansluiting"
    elif "KOLK" in rest:
        functie = "kolkaansluiting"
    elif "MANTELBUIS" in rest:
        functie = "mantelbuis"
    else:
        functie = "leiding"
    if _SCHUIM.search(rest):
        status = "volgeschuimd"
    elif st == "N":
        status = "nieuw"
    else:
        status = "verwijderen" if discipline == "DW" else "vervallen"
    if status != "nieuw" and functie == "huisaansluiting":
        return None                                   # vervallen huisaansluitingen: niet mee
    materiaal = diameter = None
    staart = [d for d in delen[1:] if not _SCHUIM.search(d)]
    if len(staart) >= 2 and re.fullmatch(r"\d+(?:[.,]\d+)?", staart[-1]):
        diameter = float(staart[-1].replace(",", "."))
        materiaal = staart[-2].strip() or None
    return Laag(naam, status, soort, functie, materiaal, diameter, discipline)


def shapefile_naam(laag: Laag) -> str:
    if laag.status == "nieuw":
        return f"nieuw_{laag.soort}"
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


def _draai(page):
    """Functie die PDF-coördinaten omzet naar de weergegeven (gedraaide) pagina."""
    if not page.rotation:
        return lambda a: np.asarray(a, float)
    m = page.rotation_matrix
    M = np.array([[m.a, m.c], [m.b, m.d]]); t = np.array([m.e, m.f])
    return lambda a: np.asarray(a, float) @ M.T + t


MIN_PAD_PT = 4.5     # kleinere tekenobjecten zijn versiering van de lijnstijl (1,6 mm op papier)


def lees_paden(page) -> tuple[list[_Pad], set]:
    """Alle lijnen op leidinglagen, met het venster (clip) waarin ze getekend zijn.
    Geeft ook alle vensters op de pagina terug."""
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
            lagen[naam] = ontleed_laag(naam)
        laag = lagen[naam]
        if laag is None or _is_cyaan(d.get("color")) or "DETAIL" in naam.split("|")[0].upper():
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
            uit.append(_Pad(laag, draai(pts), venster))
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
        if t.bestaand:
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

    @property
    def lengte_m(self) -> float:
        return float(np.hypot(*np.diff(self.rd, axis=0).T).sum())


GAT_M = 2.5          # streepjeslijn: gaten tot zoveel meter overbruggen
MIN_LENGTE_M = 1.2   # kleinere losse stukjes zijn letters in de lijnstijl, // tekens of putjes


def discipline_uit_naam(naam: str) -> str | None:
    """'DW' (drinkwater) of 'AW' (afvalwater) uit de bestandsnaam, anders None."""
    m = re.search(r"(?:^|[^A-Z])(DW|AW)(?:[^A-Z]|$)", naam.upper())
    return m.group(1) if m else None


def maak_traces(page, tr: Transformatie, alleen: str | None = None,
                min_lengte_m: float = MIN_LENGTE_M) -> tuple[list[Trace], dict]:
    """Tracés van één PDF-pagina, in RD. Geeft (tracés, info).

    alleen: 'DW' of 'AW' om alleen drinkwater of alleen riolering mee te nemen (een DW-tekening
    toont soms ook het nieuwe riool van een ander team)."""
    paden, vensters = lees_paden(page)
    pas = np.array([p.tekening for p in tr.punten], float) if tr.punten else None
    r = page.rect
    venster = kies_venster(paden, (r.x0, r.y0, r.x1, r.y1), pas, vensters)
    info = {"venster": venster, "lagen": {}}
    if venster is None:
        return [], info
    m_per_pt = tr.schaal_m_per_pt
    per_laag = defaultdict(list)
    info["overgeslagen"] = set()
    for p in paden:
        if p.venster != venster:
            continue
        if alleen and p.laag.discipline != alleen:
            info["overgeslagen"].add(p.laag.soort)
            continue
        per_laag[p.laag.naam].append(p)
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
            if not laag.materiaal:
                t.materiaal, t.diameter = materiaal_uit_label(t.label)
                t.bron_mat = "label" if t.materiaal else ""
            traces.append(t)
            n += 1
        info["lagen"][naam] = n
    return traces, info


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

Eén shapefile per soort:
{lijst}

Kolommen
  status      nieuw / vervallen / verwijderen / volgeschuimd (uit de AutoCAD-laagnaam)
  soort       drinkwater / DWA / HWA / GWA / drainage / transportriool / persleiding
  functie     leiding / huisaansluiting / kolkaansluiting / mantelbuis
  type        leiding of mantelbuis;  doel  'huisaansluiting' bij huis- en perceelaansluitingen
  aanleg      open, of de boortechniek uit de tekst bij de lijn (boogzinker, gestuurde boring, ...)
  materiaal, diameter (mm)  uit de laagnaam, of uit het label als de laagnaam ze niet noemt
  bron_mat    'laagnaam' of 'label' (leeg = onbekend)
  label       teksten bij de lijn die materiaal, diameter, soort of een boring noemen
  lengte_lab  lengte volgens het label (m);  lengte_geo  gemeten lengte (m)
  bob_begin, bob_eind, bob_ref  BOB-hoogtes bij de uiteinden (alleen riolering), NAP of MV
  laag        AutoCAD-laagnaam

Wat niet mee is genomen: bestaande leidingen (ook alles in cyaan), kabels en leidingen van
anderen, ondergrond, hulpstukken, putten, details, legenda en titelblok, en vervallen
huisaansluitingen. Alleen het kaartvenster waarin de paspunten liggen is gebruikt.

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
