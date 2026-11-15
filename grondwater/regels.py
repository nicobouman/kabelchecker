"""Melding of vergunning voor een tijdelijke grondwateronttrekking, per waterschap.

Sinds de Omgevingswet (1-1-2024) staan deze regels in de waterschapsverordening van elk waterschap.
De drempels hieronder komen uit de bemalingsadviezen in de map Grondwater en zijn een startpunt:
controleer ze altijd in de actuele waterschapsverordening (bron per regel vermeld).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Drempels:
    naam: str
    vergunning_m3_uur: float | None = None
    vergunning_m3_maand: float | None = None
    vergunning_m3_jaar: float | None = None
    vergunning_m3_totaal: float | None = None
    vergunning_dagen: float | None = None
    vergunning_bij_kering: bool = True     # binnen kernzone/beschermingszone van een waterkering
    sleuf_uitzondering_duur: bool = False  # duurgrens geldt per locatie bij een voortschrijdende sleuf
    bron: str = ""
    toelichting: list[str] = field(default_factory=list)


WATERSCHAPPEN: dict[str, Drempels] = {
    "Amstel, Gooi en Vecht (AGV / Waternet)": Drempels(
        "Amstel, Gooi en Vecht", vergunning_m3_uur=50, vergunning_m3_maand=15_000, vergunning_dagen=183,
        bron="Bemalingsadviezen Overmeer-zuid (Aveco de Bondt, 2020) en Amstelwood (CRUX, 2023)",
        toelichting=["Onder de drempels volstaat een melding via het Omgevingsloket.",
                     "In de kernzone of beschermingszone van een waterkering is altijd een vergunning nodig "
                     "(Overmeer-zuid: 'vergunningsplichtig wegens de ligging in een waterkering')."]),
    "Hollands Noorderkwartier (HHNK)": Drempels(
        "Hollands Noorderkwartier", vergunning_m3_maand=15_000,
        bron="Bemalingsadvies Cornelis Geelvinckstraat Heemskerk (2025)",
        toelichting=["In een kwetsbaar gebied voor grondwater ligt de grens op 10.000 m³/maand.",
                     "In het beperkingengebied waterkering of beschermingszone A altijd een vergunning.",
                     "Onder de drempels: melding via het Omgevingsloket."]),
    "Rijnland": Drempels(
        "Rijnland", vergunning_m3_uur=100, vergunning_m3_maand=40_000, vergunning_m3_jaar=100_000,
        vergunning_dagen=183, sleuf_uitzondering_duur=True,
        bron="Bemalingsadvies 380 kV Krimpen a/d IJssel - Diemen (Sweco, 2025), par. 4.1",
        toelichting=["Dit zijn de grenzen voor 'gebied zonder extra risico's'; in grondwaterbeschermings- en "
                     "kwetsbare gebieden gelden strengere grenzen.",
                     "Bij een lange, voortschrijdende bemaling: met Rijnland afstemmen of de duurgrens geldt."]),
    "Noorderzijlvest": Drempels(
        "Noorderzijlvest", vergunning_m3_uur=80, vergunning_dagen=183,
        bron="Bemalingsadvies Robbenplaat-Oostpolderweg 220 kV (Arcadis, 2020), Keur 2009 - verouderd",
        toelichting=["Volgens de oude Keur: melding boven 10 m³/uur. Controleer de huidige waterschapsverordening."]),
    "Ander waterschap (zelf invullen)": Drempels("Ander waterschap", bron="eigen invoer"),
}

MER_DREMPEL_M3_JAAR = 10_000_000  # m.e.r.-plicht onttrekking (CRUX 2023)


@dataclass
class Toets:
    oordeel: str           # "geen", "melding", "vergunning"
    redenen: list[str]
    toelichting: list[str]


def toets(d: Drempels, max_m3_uur: float, max_m3_maand: float, totaal_m3: float, duur_dagen: float,
          in_kering: bool, bemaling_nodig: bool) -> Toets:
    if not bemaling_nodig:
        return Toets("geen", ["Bij de opgegeven grondwaterstand ligt de sleufbodem (met ontwatering) boven het "
                              "grondwater: geen bemaling nodig."], [])
    r = []
    if d.vergunning_m3_uur is not None and max_m3_uur > d.vergunning_m3_uur:
        r.append(f"debiet {max_m3_uur:.0f} m³/uur > {d.vergunning_m3_uur:.0f} m³/uur")
    if d.vergunning_m3_maand is not None and max_m3_maand > d.vergunning_m3_maand:
        r.append(f"{max_m3_maand:,.0f} m³/maand > {d.vergunning_m3_maand:,.0f} m³/maand".replace(",", "."))
    if d.vergunning_m3_jaar is not None and totaal_m3 > d.vergunning_m3_jaar:
        r.append(f"{totaal_m3:,.0f} m³ > {d.vergunning_m3_jaar:,.0f} m³/jaar".replace(",", "."))
    if d.vergunning_m3_totaal is not None and totaal_m3 > d.vergunning_m3_totaal:
        r.append(f"totaal {totaal_m3:,.0f} m³ > {d.vergunning_m3_totaal:,.0f} m³".replace(",", "."))
    if d.vergunning_dagen is not None and duur_dagen > d.vergunning_dagen:
        r.append(f"duur {duur_dagen:.0f} dagen > {d.vergunning_dagen:.0f} dagen"
                 + (" (per locatie korter: afstemmen met het waterschap)" if d.sleuf_uitzondering_duur else ""))
    if in_kering and d.vergunning_bij_kering:
        r.append("bemaling in de kernzone of beschermingszone van een waterkering")
    if totaal_m3 > MER_DREMPEL_M3_JAAR:
        r.append("waterbezwaar boven 10 miljoen m³: m.e.r.-plicht")
    if r:
        return Toets("vergunning", r, d.toelichting)
    return Toets("melding", ["onder alle drempels voor een vergunning"], d.toelichting)
