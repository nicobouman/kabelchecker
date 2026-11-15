"""Indicatieve bemalingsberekening voor kabel- en leidingsleuven.

Dit is een indicatie, geen bemalingsadvies volgens BRL/protocol 12010. De rekenwijze volgt wat de
bemalingsadviezen voor kabeltracés doen bij een 'globale berekening' (protocol 12010, par. 2.6):

- de sleuf schuift op met de aanlegsnelheid; tegelijk staat een vak van
  snelheid x (dagen voorbemalen + dagen open) in bemaling;
- dat vak is een langgerekte bouwput met equivalente straal r = (L + B) / pi;
- freatisch pakket met een scheidende laag eronder (kwel/lek): De Glee, met de flux over de rand van de
  bouwput, Q = 2 pi kD s * x K1(x) / K0(x), x = r / lambda, lambda = sqrt(kD c);
- freatisch pakket zonder scheidende laag: Dupuit met invloedsstraal van Sichardt,
  Q = pi k (H^2 - h^2) / ln((R + r) / r), R = 3000 s sqrt(k [m/s]);
- bandbreedte met een lage, verwachte en hoge doorlatendheid (en c x2 / c /2);
- opstartdebiet ca. 30% hoger dan het stationaire debiet;
- grove opbarstcontrole van de resterende deklaag (NEN 9997-1, belastingfactor 0,9).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------- bodemtypen
# horizontale doorlatendheid k in m/dag: (laag, verwacht, hoog). Ordegroottes uit de bemalingsadviezen
# (Arcadis 2020, Aveco de Bondt 2020, Tjaden 2025) en CROW-CUR Handboek 4:2020.
BODEMTYPEN: dict[str, tuple[float, float, float]] = {
    "grof zand / grind": (10.0, 20.0, 40.0),
    "matig grof zand": (5.0, 10.0, 20.0),
    "ophoogzand / zandbed": (5.0, 10.0, 15.0),
    "matig fijn zand": (2.0, 5.0, 10.0),
    "fijn zand": (0.5, 2.0, 5.0),
    "fijn zand met kleilagen": (0.1, 0.5, 1.0),
    "zandige klei / leem": (0.05, 0.2, 0.5),
    "veen": (0.01, 0.1, 0.5),
    "klei": (0.001, 0.01, 0.05),
}

# hydraulische weerstand c (dagen) van een scheidende laag onder het freatisch pakket
SCHEIDENDE_LAAG: dict[str, float | None] = {
    "geen (dik zandpakket)": None,
    "dunne klei- of veenlaag (c ca. 100 d)": 100.0,
    "kleilaag (c ca. 500 d)": 500.0,
    "dikke klei/veen-deklaag (c ca. 1000 d)": 1000.0,
    "zeer dikke deklaag (c ca. 3000 d)": 3000.0,
}

OPSTARTFACTOR = 1.3
GAMMA_WATER = 10.0  # kN/m3


# ---------------------------------------------------------------- Besselfuncties (Abramowitz & Stegun 9.8)
def _i0(x: float) -> float:
    t = x / 3.75
    if x <= 3.75:
        t2 = t * t
        return 1 + t2 * (3.5156229 + t2 * (3.0899424 + t2 * (1.2067492 + t2 * (0.2659732 + t2 * (0.0360768 + t2 * 0.0045813)))))
    return math.exp(x) / math.sqrt(x) * (0.39894228 + (1 / t) * (0.01328592 + (1 / t) * (0.00225319 + (1 / t) * (
        -0.00157565 + (1 / t) * (0.00916281 + (1 / t) * (-0.02057706 + (1 / t) * (0.02635537 + (1 / t) * (
            -0.01647633 + (1 / t) * 0.00392377))))))))


def _i1(x: float) -> float:
    t = x / 3.75
    if x <= 3.75:
        t2 = t * t
        return x * (0.5 + t2 * (0.87890594 + t2 * (0.51498869 + t2 * (0.15084934 + t2 * (0.02658733 + t2 * (0.00301532 + t2 * 0.00032411))))))
    return math.exp(x) / math.sqrt(x) * (0.39894228 + (1 / t) * (-0.03988024 + (1 / t) * (-0.00362018 + (1 / t) * (
        0.00163801 + (1 / t) * (-0.01031555 + (1 / t) * (0.02282967 + (1 / t) * (-0.02895312 + (1 / t) * (
            0.01787654 - (1 / t) * 0.00420059))))))))


def k0(x: float) -> float:
    if x <= 2.0:
        y = x * x / 4
        return -math.log(x / 2) * _i0(x) + (-0.57721566 + y * (0.42278420 + y * (0.23069756 + y * (0.03488590 + y * (0.00262698 + y * (0.00010750 + y * 0.0000074))))))
    y = 2 / x
    return math.exp(-x) / math.sqrt(x) * (1.25331414 + y * (-0.07832358 + y * (0.02189568 + y * (-0.01062446 + y * (0.00587872 + y * (-0.00251540 + y * 0.00053208))))))


def k1(x: float) -> float:
    if x <= 2.0:
        y = x * x / 4
        return math.log(x / 2) * _i1(x) + (1 / x) * (1 + y * (0.15443144 + y * (-0.67278579 + y * (-0.18156897 + y * (-0.01919402 + y * (-0.00110404 - y * 0.00004686))))))
    y = 2 / x
    return math.exp(-x) / math.sqrt(x) * (1.25331414 + y * (0.23498619 + y * (-0.03655620 + y * (0.01504268 + y * (-0.00780353 + y * (0.00325614 - y * 0.00068245))))))


# ---------------------------------------------------------------- formules
def debiet_de_glee(kD: float, c: float, s: float, r: float) -> float:
    """m3/dag uit een bouwput met straal r en verlaging s op de rand, pakket met lek (kwel) via c."""
    if s <= 0:
        return 0.0
    lam = math.sqrt(kD * c)
    x = r / lam
    return 2 * math.pi * kD * s * x * k1(x) / k0(x)


def invloedsstraal_sichardt(s: float, k_m_dag: float) -> float:
    return 3000 * s * math.sqrt(k_m_dag / 86400)


def debiet_dupuit(k: float, H: float, s: float, r: float) -> float:
    """m3/dag freatisch zonder lek: H = verzadigde dikte vóór bemaling, s = verlaging op de rand."""
    if s <= 0:
        return 0.0
    s = min(s, 0.95 * H)
    R = max(invloedsstraal_sichardt(s, k), 1.0)
    h = H - s
    return math.pi * k * (H * H - h * h) / math.log((R + r) / r)


def invloedsgebied_de_glee(kD: float, c: float, s: float, r: float, grens: float = 0.05) -> float:
    """Afstand vanaf de rand van de bouwput tot de 5 cm-verlagingslijn (m)."""
    if s <= grens:
        return 0.0
    lam = math.sqrt(kD * c)
    k0r = k0(r / lam)
    lo, hi = r, r + 50 * lam
    for _ in range(80):
        m = (lo + hi) / 2
        if s * k0(m / lam) / k0r > grens:
            lo = m
        else:
            hi = m
    return lo - r


def invloedsgebied_dupuit(k: float, s: float, grens: float = 0.05) -> float:
    if s <= grens:
        return 0.0
    R = invloedsstraal_sichardt(s, k)
    # logaritmisch verloop van s op de rand naar 0 op R; benadering van de 5 cm-lijn
    return R * (1 - grens / s) if R > 0 else 0.0


# ---------------------------------------------------------------- invoer en uitkomst
@dataclass
class Sleuf:
    naam: str
    lengte_m: float                    # te bemalen lengte (open ontgraving), boringen niet meetellen
    ontgravingsdiepte_mmv: float       # sleufbodem in m onder maaiveld
    grondwater_mmv: float              # maatgevende (hoge) grondwaterstand in m onder maaiveld (GHG)
    bodemtype: str = "fijn zand"       # freatisch pakket waarin de sleuf ligt
    pakket_onderkant_mmv: float = 5.0  # onderkant van het doorstroomde freatische pakket (m -mv)
    scheidende_laag: str = "dikke klei/veen-deklaag (c ca. 1000 d)"
    c_dagen: float | None = None       # overschrijft de c van de scheidende laag
    sleufbreedte_m: float = 1.5        # breedte op het niveau van de grondwaterstand (incl. taluds)
    ontwatering_m: float = 0.3         # verlagen tot zoveel onder de sleufbodem
    aanlegsnelheid_m_dag: float = 50.0
    dagen_voorbemalen: float = 1.0
    dagen_open: float = 1.0            # dagen dat een vak open ligt (sleuf graven, leggen, aanvullen)
    maaiveld_nap: float | None = None
    grondwater_laag_mmv: float | None = None  # GLG, om te zien of bemaling bij lage stand vervalt
    # opbarsten (optioneel): onderkant slecht doorlatende deklaag en stijghoogte eronder
    deklaag_onderkant_mmv: float | None = None
    stijghoogte_mmv: float | None = None      # negatief = boven maaiveld
    gewicht_deklaag_kn_m3: float = 15.0       # klei ca. 16-17, veen ca. 10-11


@dataclass
class Uitkomst:
    naam: str
    bemaling_nodig: bool
    verlaging_m: float
    methode: str
    gelijktijdig_m: float
    duur_dagen: float
    debiet_m3_dag: dict[str, float]           # laag / verwacht / hoog, stationair
    debiet_m3_uur: dict[str, float]
    opstart_m3_uur: float                     # verwacht x opstartfactor
    waterbezwaar_m3: dict[str, float]
    invloedsgebied_m: float                   # verwacht, tot 5 cm verlaging, vanaf de sleufrand
    bij_glg_nodig: bool | None
    opbarsten: dict | None
    meldingen: list[str] = field(default_factory=list)


def _c(s: Sleuf) -> float | None:
    if s.c_dagen:
        return float(s.c_dagen)
    return SCHEIDENDE_LAAG.get(s.scheidende_laag)


def bereken(s: Sleuf) -> Uitkomst:
    melding: list[str] = []
    if s.bodemtype not in BODEMTYPEN:
        raise ValueError(f"onbekend bodemtype: {s.bodemtype}")
    verlaging = s.ontgravingsdiepte_mmv + s.ontwatering_m - s.grondwater_mmv
    nodig = verlaging > 0
    L = max(s.aanlegsnelheid_m_dag * (s.dagen_voorbemalen + s.dagen_open), 1.0)
    L = min(L, s.lengte_m) if s.lengte_m > 0 else L
    duur = (s.lengte_m / s.aanlegsnelheid_m_dag + s.dagen_voorbemalen + s.dagen_open - 1) if nodig and s.lengte_m > 0 else 0.0
    r = (L + s.sleufbreedte_m) / math.pi
    H = s.pakket_onderkant_mmv - s.grondwater_mmv  # verzadigde dikte freatisch pakket
    c = _c(s)
    kl, kv, kh = BODEMTYPEN[s.bodemtype]

    if s.ontgravingsdiepte_mmv + s.ontwatering_m >= s.pakket_onderkant_mmv:
        melding.append("De bemaling reikt tot onder het freatisch pakket: de sleuf snijdt in een scheidende laag of "
                       "het watervoerend pakket. De indicatie is dan onbetrouwbaar; laat dit berekenen.")
    if H <= 0.1:
        melding.append("Het freatisch pakket is (bijna) droog bij deze grondwaterstand; controleer de invoer.")
        H = max(H, 0.1)

    debiet = {}
    if not nodig:
        debiet = {"laag": 0.0, "verwacht": 0.0, "hoog": 0.0}
        methode = "geen bemaling nodig bij deze grondwaterstand"
        invloed = 0.0
    elif c:
        methode = f"De Glee (lek via scheidende laag, c = {c:.0f} d), r = {r:.0f} m"
        for nm, k, cc in (("laag", kl, c * 2), ("verwacht", kv, c), ("hoog", kh, c / 2)):
            debiet[nm] = debiet_de_glee(k * H, cc, verlaging, r)
        invloed = invloedsgebied_de_glee(kv * H, c, verlaging, r)
    else:
        methode = f"Dupuit/Sichardt (freatisch, geen scheidende laag), r = {r:.0f} m"
        for nm, k in (("laag", kl), ("verwacht", kv), ("hoog", kh)):
            debiet[nm] = debiet_dupuit(k, H, verlaging, r)
        invloed = invloedsgebied_dupuit(kv, verlaging)

    per_uur = {k: v / 24 for k, v in debiet.items()}
    bezwaar = {k: v * duur for k, v in debiet.items()}
    if nodig:
        bezwaar = {k: v + (OPSTARTFACTOR - 1) * debiet[k] * min(s.dagen_voorbemalen, duur) for k, v in bezwaar.items()}

    bij_glg = None
    if s.grondwater_laag_mmv is not None:
        bij_glg = s.ontgravingsdiepte_mmv + s.ontwatering_m - s.grondwater_laag_mmv > 0

    return Uitkomst(
        naam=s.naam, bemaling_nodig=nodig, verlaging_m=max(verlaging, 0.0), methode=methode, gelijktijdig_m=L,
        duur_dagen=duur, debiet_m3_dag=debiet, debiet_m3_uur=per_uur,
        opstart_m3_uur=per_uur["verwacht"] * OPSTARTFACTOR, waterbezwaar_m3=bezwaar, invloedsgebied_m=invloed,
        bij_glg_nodig=bij_glg, opbarsten=opbarstcontrole(s), meldingen=melding)


def opbarstcontrole(s: Sleuf) -> dict | None:
    """Verticaal evenwicht van de deklaag onder de sleufbodem (NEN 9997-1: 0,9 x gewicht >= waterdruk)."""
    if s.deklaag_onderkant_mmv is None or s.stijghoogte_mmv is None:
        return None
    d = s.deklaag_onderkant_mmv - s.ontgravingsdiepte_mmv
    if d <= 0:
        return {"status": "doorsneden", "tekst": "De sleuf gaat door de deklaag heen tot in het watervoerend pakket: "
                "bemaling van het watervoerend pakket nodig; debiet kan veel hoger zijn dan de indicatie."}
    gewicht = 0.9 * d * s.gewicht_deklaag_kn_m3
    waterdruk = max(s.deklaag_onderkant_mmv - s.stijghoogte_mmv, 0) * GAMMA_WATER
    fs = gewicht / waterdruk if waterdruk > 0 else float("inf")
    if fs >= 1.0:
        return {"status": "veilig", "fs": fs, "tekst": f"Geen opbarstgevaar (veiligheid {fs:.2f})."}
    nodig = (waterdruk - gewicht) / GAMMA_WATER
    return {"status": "opbarsten", "fs": fs, "verlaging_m": nodig,
            "tekst": f"Opbarstgevaar (veiligheid {fs:.2f}): de stijghoogte moet ca. {nodig:.2f} m omlaag. "
                     "Spanningsbemaling valt buiten deze indicatie en geeft vaak een veel hoger debiet."}


# ---------------------------------------------------------------- planning en totalen
def dagreeks(uitkomsten: list[Uitkomst], sleuven: list[Sleuf]) -> list[float]:
    """Debiet per dag (m3/dag, verwacht) als de deeltracés na elkaar worden aangelegd."""
    reeks: list[float] = []
    for u, s in zip(uitkomsten, sleuven):
        if not u.bemaling_nodig:
            continue
        n = max(int(math.ceil(u.duur_dagen)), 1)
        q = u.debiet_m3_dag["verwacht"]
        for i in range(n):
            deel = min(u.duur_dagen - i, 1.0) if u.duur_dagen > 0 else 1.0
            reeks.append(q * deel * (OPSTARTFACTOR if i < s.dagen_voorbemalen else 1.0))
    return reeks


@dataclass
class Totaal:
    max_m3_uur: dict[str, float]
    max_m3_maand: dict[str, float]
    totaal_m3: dict[str, float]
    duur_dagen: float


def totaal(uitkomsten: list[Uitkomst], sleuven: list[Sleuf]) -> Totaal:
    nodig = [u for u in uitkomsten if u.bemaling_nodig]
    duur = sum(u.duur_dagen for u in nodig)
    max_uur = {k: max([u.debiet_m3_uur[k] for u in nodig] or [0.0]) for k in ("laag", "verwacht", "hoog")}
    max_uur["opstart"] = max([u.opstart_m3_uur for u in nodig] or [0.0])
    reeks = dagreeks(uitkomsten, sleuven)
    maand_v = max([sum(reeks[i:i + 30]) for i in range(len(reeks))] or [0.0])
    fac = {k: (sum(u.waterbezwaar_m3[k] for u in nodig) / max(sum(u.waterbezwaar_m3["verwacht"] for u in nodig), 1e-9))
           for k in ("laag", "verwacht", "hoog")}
    tot = {k: sum(u.waterbezwaar_m3[k] for u in nodig) for k in ("laag", "verwacht", "hoog")}
    return Totaal(max_m3_uur=max_uur, max_m3_maand={k: min(maand_v * f, tot[k]) for k, f in fac.items()},
                  totaal_m3={k: sum(u.waterbezwaar_m3[k] for u in nodig) for k in ("laag", "verwacht", "hoog")},
                  duur_dagen=duur)
