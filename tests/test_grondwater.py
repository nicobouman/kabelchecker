"""Tests voor de grondwatermodule (indicatie bemaling)."""
import math

import pytest

from grondwater.kern import Sleuf, bereken, debiet_de_glee, debiet_dupuit, k0, k1, opbarstcontrole, totaal
from grondwater.regels import WATERSCHAPPEN, toets


def test_bessel_tabelwaarden():
    # Abramowitz & Stegun tabel 9.8
    assert k0(0.5) == pytest.approx(0.9244, abs=1e-3)
    assert k0(1.0) == pytest.approx(0.4210, abs=1e-3)
    assert k0(3.0) == pytest.approx(0.03474, abs=1e-4)
    assert k1(1.0) == pytest.approx(0.6019, abs=1e-3)
    assert k1(3.0) == pytest.approx(0.04016, abs=1e-4)


def test_arcadis_robbenplaat_de_glee():
    """Arcadis 2020 (220 kV Eemshaven, westzijde): k=0,5 m/d, h=4 m, c=1000 d, s=1,5 m, r=33 m
    geeft met De Glee (put) ca. 31 m3/dag per bouwkuip van 100 m."""
    kD, c, s, r = 0.5 * 4, 1000, 1.5, 33
    klassiek = 2 * math.pi * kD * s / k0(r / math.sqrt(kD * c))
    assert klassiek == pytest.approx(31, rel=0.05)
    # de randflux-variant is iets lager maar dezelfde orde
    assert 0.5 * klassiek < debiet_de_glee(kD, c, s, r) < klassiek


def test_arcadis_sleuf_in_bandbreedte():
    s = Sleuf("west", 1300, ontgravingsdiepte_mmv=2.0, grondwater_mmv=1.0, bodemtype="fijn zand met kleilagen",
              pakket_onderkant_mmv=5.2, scheidende_laag="dikke klei/veen-deklaag (c ca. 1000 d)", sleufbreedte_m=6,
              ontwatering_m=0.5, aanlegsnelheid_m_dag=100, dagen_voorbemalen=2, dagen_open=1)
    u = bereken(s)
    assert u.bemaling_nodig and u.verlaging_m == pytest.approx(1.5)
    assert u.gelijktijdig_m == 300
    # Arcadis: max 100 m3/dag (4,2 m3/uur incl. voorbemalen), totaal 1300 m3
    assert u.debiet_m3_dag["laag"] < 100 < u.debiet_m3_dag["hoog"] * 1.3
    assert u.waterbezwaar_m3["laag"] < 1300 < u.waterbezwaar_m3["hoog"] * 1.3


def test_geen_bemaling_boven_grondwater():
    u = bereken(Sleuf("droog", 200, ontgravingsdiepte_mmv=1.0, grondwater_mmv=2.0))
    assert not u.bemaling_nodig and u.debiet_m3_uur["verwacht"] == 0
    t = totaal([u], [Sleuf("droog", 200, 1.0, 2.0)])
    assert toets(WATERSCHAPPEN["Rijnland"], 0, 0, 0, 0, False, False).oordeel == "geen"
    assert t.totaal_m3["verwacht"] == 0


def test_dupuit_groeit_met_k():
    assert debiet_dupuit(20, 8, 1, 30) > debiet_dupuit(2, 8, 1, 30) > 0


def test_freatisch_zand_dupuit_gebruikt():
    u = bereken(Sleuf("zand", 500, 2.0, 1.0, bodemtype="matig grof zand", pakket_onderkant_mmv=15,
                      scheidende_laag="geen (dik zandpakket)"))
    assert u.methode.startswith("Dupuit") and u.debiet_m3_uur["verwacht"] > 5


def test_opbarsten():
    veilig = Sleuf("a", 100, 1.5, 0.5, deklaag_onderkant_mmv=6, stijghoogte_mmv=1.0)
    assert opbarstcontrole(veilig)["status"] == "veilig"
    gevaar = Sleuf("b", 100, 1.5, 0.5, deklaag_onderkant_mmv=3, stijghoogte_mmv=-0.5, gewicht_deklaag_kn_m3=11)
    o = opbarstcontrole(gevaar)
    assert o["status"] == "opbarsten" and o["verlaging_m"] > 0
    assert opbarstcontrole(Sleuf("c", 100, 3.5, 0.5, deklaag_onderkant_mmv=3, stijghoogte_mmv=0))["status"] == "doorsneden"


def test_toets_agv():
    agv = WATERSCHAPPEN["Amstel, Gooi en Vecht (AGV / Waternet)"]
    assert toets(agv, 10, 7000, 12000, 40, False, True).oordeel == "melding"
    assert toets(agv, 60, 7000, 12000, 40, False, True).oordeel == "vergunning"
    assert toets(agv, 10, 20000, 30000, 40, False, True).oordeel == "vergunning"
    # Overmeer-zuid: laag debiet, maar in de waterkering -> vergunning
    t = toets(agv, 13, 7500, 12000, 49, True, True)
    assert t.oordeel == "vergunning" and any("waterkering" in r for r in t.redenen)


def test_totaal_maand_en_duur():
    s1 = Sleuf("1", 1000, 2.0, 1.0, aanlegsnelheid_m_dag=50)
    s2 = Sleuf("2", 500, 2.0, 1.0, aanlegsnelheid_m_dag=50)
    u = [bereken(s1), bereken(s2)]
    t = totaal(u, [s1, s2])
    assert t.duur_dagen == pytest.approx(u[0].duur_dagen + u[1].duur_dagen)
    assert t.max_m3_maand["verwacht"] <= t.totaal_m3["verwacht"] + 1e-6
    assert t.max_m3_uur["opstart"] > t.max_m3_uur["verwacht"]
