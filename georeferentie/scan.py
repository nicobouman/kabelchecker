"""Tekening scannen op RD-coordinaatlabels ("X=123027.817" / "Y=484070.892").

Bij Waternet-tekeningen staat zo'n label op een onderstreping met een
verwijslijn naar het punt. Het punt is het uiteinde van die verwijslijn.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

_X = re.compile(r"^X\s*[=:]\s*(\d{5,6}(?:[.,]\d+)?)$")
_Y = re.compile(r"^Y\s*[=:]\s*(\d{6}(?:[.,]\d+)?)$")
RD_X = (0, 300000)
RD_Y = (289000, 629000)


@dataclass
class GevondenCoordinaat:
    tekening: tuple[float, float]    # pt, y naar beneden
    rd: tuple[float, float]
    label: tuple[float, float, float, float]  # kader van het label (pt)
    zeker: bool                      # verwijslijn gevonden


def _woorden(page):
    """X= en Y= labels; ook als 'X=' en het getal losse woorden zijn."""
    ws = page.get_text("words")
    uit = []
    for i, w in enumerate(ws):
        t = w[4]
        if t in ("X=", "Y=", "X", "Y") and i + 1 < len(ws):
            n = ws[i + 1]
            if abs(n[1] - w[1]) < 3:
                t = t.rstrip("=") + "=" + n[4].lstrip("=")
                w = (w[0], min(w[1], n[1]), n[2], max(w[3], n[3]), t)
        uit.append((w[0], w[1], w[2], w[3], t))
    return uit


def _segmenten(page):
    """Alle rechte lijnstukken: array (n, 4) met ax, ay, bx, by en een array met laagnummers."""
    seg, lagen, nummer = [], [], {}
    for d in page.get_cdrawings():                  # sneller dan get_drawings()
        laag = nummer.setdefault(d.get("layer") or "", len(nummer))
        for it in d["items"]:
            if it[0] == "l":
                seg.append((*it[1], *it[2])); lagen.append(laag)
            elif it[0] == "re":                       # rechthoek: vier zijden
                x0, y0, x1, y1 = it[1]
                for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                             ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
                    seg.append((*a, *b)); lagen.append(laag)
    namen = sorted(nummer, key=nummer.get)
    return np.array(seg, float).reshape(-1, 4), np.array(lagen, int), namen


def _verwijspunt(segs: np.ndarray, kader, lagen=None, laagnamen=None, max_afstand: float = 200.0):
    """Het punt is het losse uiteinde van de verwijslijn aan de onderstreping."""
    x0, y0, x1, y1 = kader
    hoogte = y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    A, B = segs[:, :2], segs[:, 2:4]
    lengte = np.hypot(*(B - A).T)
    # onderstreping: (bijna) horizontaal, net onder het label, minstens half zo breed
    horiz = np.abs(A[:, 1] - B[:, 1]) < 0.1 * hoogte + 0.3
    ymid = (A[:, 1] + B[:, 1]) / 2
    onder = (ymid > y1 - 0.3 * hoogte) & (ymid < y1 + 0.6 * hoogte)
    overlap = np.minimum(np.maximum(A[:, 0], B[:, 0]), x1) - np.maximum(np.minimum(A[:, 0], B[:, 0]), x0)
    kand = np.where(horiz & onder & (overlap > 0.5 * (x1 - x0)))[0]
    if not len(kand):
        return None
    if laagnamen is not None and lagen is not None:
        coord = [i for i in kand if "COORD" in laagnamen[lagen[i]].upper()]
        if coord:
            kand = np.array(coord)
    o = kand[np.argmin(np.abs(ymid[kand] - y1) - 0.001 * lengte[kand])]   # direct onder het label
    houden = (lagen == lagen[o]) if lagen is not None else np.ones(len(segs), bool)
    # lijnen volgen vanaf de onderstreping
    tol = 0.6
    bezocht = {int(o)}
    rand = [tuple(A[o]), tuple(B[o])]
    while rand:
        p = np.array(rand.pop())
        d1 = np.hypot(*(A - p).T); d2 = np.hypot(*(B - p).T)
        for i in np.where(((d1 < tol) | (d2 < tol)) & houden)[0]:
            if int(i) in bezocht:
                continue
            bezocht.add(int(i))
            for q in (A[i], B[i]):
                if math.hypot(q[0] - cx, q[1] - cy) < max_afstand:
                    rand.append(tuple(q))
    verwijs = [i for i in bezocht if i != o]
    if not verwijs:
        return None
    eind = np.array([q for i in verwijs for q in (A[i], B[i])])
    alle_eind = np.array([q for i in bezocht for q in (A[i], B[i])])
    graad = (np.hypot(*(alle_eind[:, None, :] - eind[None, :, :]).transpose(2, 0, 1)) < tol).sum(0)
    los = eind[graad == 1]
    if not len(los):
        return None
    # het losse uiteinde dat het verst van de onderstreping ligt
    ya = (A[o, 1] + B[o, 1]) / 2
    xa0, xa1 = sorted((A[o, 0], B[o, 0]))
    afst = np.hypot(np.clip(los[:, 0], xa0, xa1) - los[:, 0], los[:, 1] - ya)
    return tuple(los[np.argmax(afst)])


def scan_pagina(page) -> list[GevondenCoordinaat]:
    ws = _woorden(page)
    xs = [(w, _X.match(w[4])) for w in ws]
    ys = [(w, _Y.match(w[4])) for w in ws]
    xs = [(w, float(m.group(1).replace(",", "."))) for w, m in xs if m]
    ys = [(w, float(m.group(1).replace(",", "."))) for w, m in ys if m]
    if not xs or not ys:
        return []
    alle, lagen, laagnamen = _segmenten(page)
    mid = (alle[:, :2] + alle[:, 2:]) / 2
    uit, gezien = [], set()
    for wx, X in xs:
        # Y-label direct onder (of naast) het X-label
        wy, Y = min(ys, key=lambda t: abs(t[0][0] - wx[0]) + abs(t[0][1] - wx[3]))
        if abs(wy[0] - wx[0]) > 30 or abs(wy[1] - wx[3]) > 2 * (wx[3] - wx[1]) + 2:
            continue
        if not (RD_X[0] < X < RD_X[1] and RD_Y[0] < Y < RD_Y[1]):
            continue
        kader = (min(wx[0], wy[0]), wx[1], max(wx[2], wy[2]), wy[3])
        # minuscule kopie (bv. in een situatiekaartje) overslaan
        if kader[3] - kader[1] < 2:
            continue
        sleutel = (round(X, 2), round(Y, 2))
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        cx, cy = (kader[0] + kader[2]) / 2, (kader[1] + kader[3]) / 2
        dichtbij = np.hypot(mid[:, 0] - cx, mid[:, 1] - cy) < 250
        p = _verwijspunt(alle[dichtbij], kader, lagen[dichtbij], laagnamen) if dichtbij.any() else None
        zeker = p is not None
        if p is None:   # terugval: linksonder het label
            p = (kader[0], kader[3])
        uit.append(GevondenCoordinaat((float(p[0]), float(p[1])), (X, Y), kader, zeker))
    return uit


def scan(data: bytes, pagina: int = 0) -> list[GevondenCoordinaat]:
    import fitz
    with fitz.open(stream=data, filetype="pdf") as doc:
        page = doc[pagina]
        gevonden = scan_pagina(page)
        # weergegeven pagina kan gedraaid zijn
        if page.rotation:
            m = page.rotation_matrix
            for g in gevonden:
                q = fitz.Point(*g.tekening) * m
                g.tekening = (q.x, q.y)
    return gevonden


def betrouwbare_set(gevonden: list[GevondenCoordinaat], grens_m: float = 0.5):
    """Kies de gevonden coordinaten die onderling kloppen.

    Met 3 of meer punten wordt een gelijkvormige transformatie berekend en
    wordt steeds het slechtste punt weggelaten tot alles binnen grens_m past.
    Geeft (gebruikte punten, afgewezen punten). Met 1 of 2 punten is er geen
    controle mogelijk; die worden gewoon teruggegeven."""
    from .kern import Paspunt, bereken
    goed = [g for g in gevonden if g.zeker]
    afgewezen = [g for g in gevonden if not g.zeker]
    while len(goed) >= 3:
        tr = bereken([Paspunt(i + 1, g.tekening, g.rd) for i, g in enumerate(goed)])
        slechtste = int(np.argmax(tr.restfouten_m))
        if tr.restfouten_m[slechtste] <= grens_m:
            break
        if len(goed) == 3:          # geen meerderheid meer: niets automatisch gebruiken
            afgewezen += goed
            goed = []
            break
        afgewezen.append(goed.pop(slechtste))
    if len(goed) == 2:
        # schaal moet aannemelijk zijn (1:50 tot 1:5000)
        (a, b) = goed
        d_pt = math.dist(a.tekening, b.tekening); d_m = math.dist(a.rd, b.rd)
        schaal = d_m / (d_pt * 0.0254 / 72) if d_pt else 0
        if not 50 <= schaal <= 5000:
            afgewezen += goed
            goed = []
    return goed, afgewezen
