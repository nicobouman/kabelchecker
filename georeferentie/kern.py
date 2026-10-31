"""Rekenkern van de georeferentie: paspunten -> transformatie -> RD.

Tekeningcoordinaten zijn in PDF-punten (pt) van de pagina zoals die wordt
weergegeven: x naar rechts, y naar beneden, (0, 0) linksboven.
RD-coordinaten zijn EPSG:28992 in meters: x naar oost, y naar noord.

Twee soorten transformatie:
- gelijkvormig (4 parameters): schuiven, draaien en een schaal. Met 3 punten
  blijven er 2 overbodige waarnemingen over, zodat een fout punt opvalt.
- affien (6 parameters): ook scheefstand en een aparte schaal in x en y.
  Gaat exact door 3 punten, dus pas zinvol als controle vanaf 4 punten.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict

import numpy as np

PT_IN_M = 0.0254 / 72          # 1 PDF-punt op papier, in meters
MIN_PUNTEN = {"gelijkvormig": 2, "affien": 3}
NAUWKEURIGHEID_M = 0.5          # gevraagde nauwkeurigheid (+/- 50 cm)


@dataclass
class Paspunt:
    nr: int
    tekening: tuple[float, float]   # (x, y) in pt, y naar beneden
    rd: tuple[float, float]         # (x, y) in meters RD


@dataclass
class Transformatie:
    """RD = A @ [x_pt, y_pt] + t"""
    soort: str
    A: list[list[float]]
    t: list[float]
    punten: list[Paspunt] = field(default_factory=list)
    restfouten_m: list[float] = field(default_factory=list)
    rms_m: float = float("nan")
    bron: dict = field(default_factory=dict)  # bv. bestandsnaam, pagina

    # ------------------------------------------------------------ toepassen
    def naar_rd(self, xy) -> np.ndarray:
        p = np.asarray(xy, float)
        return p @ np.asarray(self.A).T + np.asarray(self.t)

    def naar_tekening(self, xy) -> np.ndarray:
        p = np.asarray(xy, float) - np.asarray(self.t)
        return p @ np.linalg.inv(np.asarray(self.A)).T

    def transformeer_geometrie(self, geom):
        """Shapely-geometrie in tekening-pt -> dezelfde geometrie in RD."""
        from shapely import transform
        return transform(geom, lambda c: self.naar_rd(c))

    # ------------------------------------------------------------ kenmerken
    @property
    def schaal_m_per_pt(self) -> float:
        return math.sqrt(abs(np.linalg.det(np.asarray(self.A))))

    @property
    def tekeningschaal(self) -> float:
        """1:N van de tekening (bij afdruk op het originele papierformaat)."""
        return self.schaal_m_per_pt / PT_IN_M

    @property
    def draaiing_graden(self) -> float:
        """Hoek tussen tekening-x en RD-oost, tegen de klok in."""
        a = np.asarray(self.A)
        return math.degrees(math.atan2(a[1, 0], a[0, 0])) % 360

    @property
    def binnen_nauwkeurigheid(self) -> bool:
        return bool(self.restfouten_m) and max(self.restfouten_m) <= NAUWKEURIGHEID_M

    # ------------------------------------------------------------ opslaan
    def naar_dict(self) -> dict:
        d = asdict(self)
        d["tekeningschaal"] = round(self.tekeningschaal, 1)
        d["draaiing_graden"] = round(self.draaiing_graden, 3)
        d["crs"] = "EPSG:28992"
        d["eenheid_tekening"] = "pt (1/72 inch), y naar beneden"
        return d

    def naar_json(self) -> str:
        return json.dumps(self.naar_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def van_json(cls, tekst: str) -> "Transformatie":
        d = json.loads(tekst)
        pp = [Paspunt(p["nr"], tuple(p["tekening"]), tuple(p["rd"])) for p in d.get("punten", [])]
        return cls(d["soort"], d["A"], d["t"], pp, d.get("restfouten_m", []),
                   d.get("rms_m", float("nan")), d.get("bron", {}))


def _fit_gelijkvormig(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # tekening-y wijst naar beneden: spiegelen, dan is het een gewone gelijkvormigheid
    s = src * [1, -1]
    ms, md = s.mean(0), dst.mean(0)
    s0, d0 = s - ms, dst - md
    n = (s0 ** 2).sum()
    a = (s0[:, 0] * d0[:, 0] + s0[:, 1] * d0[:, 1]).sum() / n   # s*cos
    b = (s0[:, 0] * d0[:, 1] - s0[:, 1] * d0[:, 0]).sum() / n   # s*sin
    R = np.array([[a, -b], [b, a]]) @ np.diag([1, -1])
    return R, md - R @ src.mean(0)


def _fit_affien(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    M = np.c_[src, np.ones(len(src))]
    sol, *_ = np.linalg.lstsq(M, dst, rcond=None)
    return sol[:2].T, sol[2]


def bereken(punten: list[Paspunt], soort: str = "gelijkvormig", bron: dict | None = None) -> Transformatie:
    """Kleinste-kwadratenschatting van de transformatie uit paspunten."""
    if soort not in MIN_PUNTEN:
        raise ValueError(f"onbekende transformatie: {soort}")
    if len(punten) < MIN_PUNTEN[soort]:
        raise ValueError(f"{soort} vraagt minstens {MIN_PUNTEN[soort]} punten")
    src = np.array([p.tekening for p in punten], float)
    dst = np.array([p.rd for p in punten], float)
    if np.linalg.matrix_rank(src - src.mean(0)) < 2 and soort == "affien":
        raise ValueError("punten liggen op een lijn; kies punten verspreid over de tekening")
    A, t = (_fit_gelijkvormig if soort == "gelijkvormig" else _fit_affien)(src, dst)
    if abs(np.linalg.det(A)) < 1e-12:
        raise ValueError("punten vallen samen; kies punten verder uit elkaar")
    res = np.linalg.norm(src @ A.T + t - dst, axis=1)
    return Transformatie(soort, A.tolist(), list(map(float, t)), list(punten),
                         [float(r) for r in res], float(np.sqrt((res ** 2).mean())), bron or {})


def overtallig(n_punten: int, soort: str) -> int:
    """Aantal overtallige waarnemingen: 0 betekent geen controle op fouten."""
    return 2 * n_punten - (4 if soort == "gelijkvormig" else 6)


def wereldbestand(A, t, pixel_in_pt: float) -> str:
    """World file (.pgw/.jgw/.tfw) voor een afbeelding waarvan 1 pixel = pixel_in_pt pt.

    World files rekenen vanaf het midden van de linkerbovenpixel."""
    A = np.asarray(A) * pixel_in_pt
    c = np.asarray(t) + A @ [0.5, 0.5]
    return "\n".join(f"{v:.6f}" for v in (A[0, 0], A[1, 0], A[0, 1], A[1, 1], c[0], c[1])) + "\n"
