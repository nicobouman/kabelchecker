"""Testgevallen voor het opsplitsen van tracés in sub-tracés (regels_opsplitsen.md, scenario 1-6).

Fictieve kering (zoals in de scenario-plaatjes): kernzone 24 m, beschermingszone 2x20 m,
buitenbeschermingszone 2x30 m. De tracés zijn vereenvoudigde versies van de echte tracés.

Draaien:  python test_opsplitsen.py
"""
from __future__ import annotations

import math
import sys

import geopandas as gpd
from shapely.geometry import LineString, Polygon

import kabelchecker_v4_engine as K

PARAMS = {"HOEK_MIN": 75.0, "DWARS_AANDEEL": 0.75, "SNAP_AFSTAND_M": 0.5, "KORT_STUK_M": 5.0}


def kering(hoek_graden: float = 0.0, lengte: float = 1000.0) -> K.GeoLagen:
    """Rechte kering door (0, 0) onder de gegeven hoek, met zones als stroken evenwijdig aan de referentielijn."""
    r = math.radians(hoek_graden)
    ux, uy = math.cos(r), math.sin(r)       # langs de kering
    nx, ny = -uy, ux                        # haaks erop

    def strook(v0, v1):
        L = lengte / 2
        return Polygon([(-L * ux + v0 * nx, -L * uy + v0 * ny), (L * ux + v0 * nx, L * uy + v0 * ny),
                        (L * ux + v1 * nx, L * uy + v1 * ny), (-L * ux + v1 * nx, -L * uy + v1 * ny)])

    rijen = [("WK-KZ", strook(-12, 12))]
    for teken in (1, -1):
        rijen.append(("WK-BZ", strook(teken * 12, teken * 32)))
        rijen.append(("WK-BBZ", strook(teken * 32, teken * 62)))
    zones = gpd.GeoDataFrame({"code": ["K1"] * len(rijen), "zonecode": [z for z, _ in rijen]},
                             geometry=[g for _, g in rijen], crs=28992)
    refl = gpd.GeoDataFrame({"code": ["K1"], "dijktype": ["waterkerend"]},
                            geometry=[LineString([(-lengte / 2 * ux, -lengte / 2 * uy), (lengte / 2 * ux, lengte / 2 * uy)])],
                            crs=28992)
    return K.GeoLagen(zones, refl, None)


def lijn(i, punten, groep="nieuw", **attrs):
    return dict(id=i, geometry=LineString(punten), attrs=attrs, groep=groep)


GN = dict(materiaal="GN", diameter=100)
K54 = dict(materiaal="K", diameter=54)
HA = dict(materiaal="PE", diameter=32)


def huisaansluitingen(start, xs, lengte=8.0, richting=(0, 1), basis=100):
    """Korte stukjes PE 32 haaks op een lijn y = f(x)."""
    uit = []
    for n, (x, y) in enumerate(xs):
        uit.append(lijn(basis + n, [(x, y), (x + richting[0] * lengte, y + richting[1] * lengte)], **HA))
    return uit


def op_lijn(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


# ---------------------------------------------------------------- scenario's
def scenario1():
    """Haakse kruising GN 100 met huisaansluitingen: één sub-tracé, kernzone, haaks."""
    a, b = (-20, 110), (20, -110)
    ls = [lijn(1, [(-30, 115), a, b, (35, -118)], **GN)]
    ls += huisaansluitingen(None, [op_lijn(a, b, t) for t in (0.05, 0.4, 0.45, 0.55, 0.6, 0.95)], richting=(1, 0.2))
    return ls


def scenario2():
    """Bijna evenwijdig op de grens BZ/BBZ, met een aftakking naar het noorden."""
    a, b = (-150, 35), (150, 29)
    ls = [lijn(1, [a, b], **GN),
          lijn(2, [op_lijn(a, b, 4 / 300), (-146, 55)], **GN)]           # aftakking (in BBZ)
    ls += huisaansluitingen(None, [op_lijn(a, b, t) for t in (0.2, 0.35, 0.5, 0.65, 0.8)], richting=(0, -1))
    return ls


def scenario3():
    """GN 100 -> K 54 -> GN 100 met een bocht van 90 graden; kering onder 45 graden."""
    return [lijn(1, [(0, -30), (0, 45)], **GN),
            lijn(2, [(0, 45), (2, 50), (60, 50)], **K54),
            lijn(3, [(60, 50), (100, 50)], **GN)]


def scenario4():
    """T-stuk: GN 100 evenwijdig (BZ), K 54 naar de kernzone, aanvoer GN 100 uit het westen."""
    t = (-60, 25)
    return [lijn(1, [t, (60, 30), (80, 45)], **GN),
            lijn(2, [t, (-30, 3), (-15, 8)], **K54),
            lijn(3, [(-150, 40), t], **GN)]


def scenario5():
    """Aftakking met hetzelfde materiaal: hoofdleiding in BZ/BBZ, aftakking door de kernzone."""
    a, b = (-100, 20), (200, 50)
    tpunt = op_lijn(a, b, 4 / 301.5)
    ls = [lijn(1, [a, b], **GN), lijn(2, [tpunt, (tpunt[0], 2)], **GN)]
    ls += huisaansluitingen(None, [op_lijn(a, b, t) for t in (0.15, 0.3, 0.5, 0.7, 0.9)], richting=(0.1, 1))
    return ls


def scenario6(open_rest_m=None):
    """Als scenario 1, maar de kernzone wordt gekruist met een gestuurde boring van 60 m."""
    ls = scenario1()
    a, b = (-20, 110), (20, -110)
    L = math.dist(a, b)
    # boring van v = +30 tot v = -30 (haaks op de kering y = 0)
    p1, p2 = op_lijn(a, b, (110 - 30) / 220), op_lijn(a, b, (110 + 30) / 220)
    if open_rest_m is not None:   # boring tot open_rest_m voor de zonerand (y = -62)
        p2 = op_lijn(a, b, (110 + 62 - open_rest_m) / 220)
    ls.append(lijn(50, [p1, p2], label="GN 100 gestuurde boring", **GN))
    return ls


def mantelbuizen():
    """Twee losse mantelbuizen op een haakse leiding: samen één sub-tracé."""
    ls = [lijn(1, [(0, 100), (0, -100)], **GN)]
    ls.append(lijn(60, [(0, 20), (0, 8)], groep="mantelbuis", soort="mantelbuis", diameter=200))
    ls.append(lijn(61, [(0, -8), (0, -20)], groep="mantelbuis", soort="mantelbuis", diameter=200))
    return ls


# ---------------------------------------------------------------- controle
def samenvatting(delen):
    return [(d["soort"], d["zwaarste_zone"], d["wijze"], d["materiaal"], d["huisaansluitingen"], round(d["hoofdlijn"].length, 1))
            for d in delen]


def controleer(naam, delen, verwacht: list[dict]) -> int:
    fouten = []
    if len(delen) != len(verwacht):
        fouten.append(f"{len(delen)} sub-tracés, verwacht {len(verwacht)}")
    else:
        over = list(delen)
        for v in verwacht:
            hit = next((d for d in over if all(d.get(k) == w for k, w in v.items())), None)
            if hit is None:
                fouten.append(f"geen sub-tracé met {v}")
            else:
                over.remove(hit)
    print(f"{naam}: {'OK ' if not fouten else 'XX '} {len(delen)} sub-tracé(s)")
    for d in delen:
        print(f"    #{d['nr']} {d['soort']:<10} zwaarste {d['zwaarste_zone']:<3} {str(d['wijze']):<10} "
              f"{d['materiaal'] or '-'} {d['diameter'] or ''} lengte {d['hoofdlijn'].length:6.1f} m "
              f"huisaansluitingen {d['huisaansluitingen']} zones {sorted(d['zones'])}")
    for f in fouten:
        print("    FOUT:", f)
    return len(fouten)


GEVALLEN = [
    ("Scenario 1 haaks", scenario1, 10, [dict(soort="open", zwaarste_zone="KZ", wijze="haaks", huisaansluitingen=4)]),
    ("Scenario 2 evenwijdig", scenario2, 0, [dict(soort="open", zwaarste_zone="BZ", wijze="evenwijdig", huisaansluitingen=5),
                                            dict(soort="open", zwaarste_zone="BBZ")]),
    ("Scenario 3 materiaal en richting", scenario3, 45, [dict(materiaal="GN", zwaarste_zone="KZ"),
                                                         dict(materiaal="K", zwaarste_zone="KZ"),
                                                         dict(materiaal="GN", zwaarste_zone="KZ")]),
    ("Scenario 4 aftakking", scenario4, 10, [dict(materiaal="GN", zwaarste_zone="BZ", wijze="evenwijdig"),
                                             dict(materiaal="K", zwaarste_zone="KZ"),
                                             dict(materiaal="GN", zwaarste_zone="BBZ")]),
    ("Scenario 5 aftakking zelfde materiaal", scenario5, 0, [dict(zwaarste_zone="BZ", huisaansluitingen=5),
                                                             dict(zwaarste_zone="KZ", wijze="haaks")]),
    ("Scenario 6 boring in kruising", scenario6, 10, [dict(soort="open", zwaarste_zone="BZ"),
                                                      dict(soort="boring", zwaarste_zone="KZ"),
                                                      dict(soort="open", zwaarste_zone="BZ")]),
    ("Scenario 6b open stukje van 3 m naast boring", lambda: scenario6(open_rest_m=3), 10,
     [dict(soort="open", zwaarste_zone="BZ"), dict(soort="boring", zwaarste_zone="KZ"),
      dict(soort="open", zwaarste_zone="BBZ")]),
    ("Mantelbuizen samen", mantelbuizen, 0, [dict(soort="open", zwaarste_zone="BZ"), dict(soort="mantelbuis", zwaarste_zone="KZ"),
                                             dict(soort="open", zwaarste_zone="BZ"), dict(soort="open", zwaarste_zone="KZ")]),
]


def main() -> int:
    fout = 0
    for naam, maak, hoek, verwacht in GEVALLEN:
        delen = K.splits_traces(maak(), kering(hoek), PARAMS)
        fout += controleer(naam, delen, verwacht)
    print(f"{fout} afwijking(en)")
    return fout


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
