"""Streamlit-paneel: indicatie grondwateronttrekking voor een kabel- of leidingtracé."""
from __future__ import annotations

import io
import re

import pandas as pd
import streamlit as st

from .kern import BODEMTYPEN, OPSTARTFACTOR, SCHEIDENDE_LAAG, Sleuf, bereken, totaal
from .regels import WATERSCHAPPEN, Drempels, toets

BOORPATROON = re.compile(r"boring|boogzinker|hdd|persing|nano.?drill|raket|mantelbuis|gestuurd", re.I)

OORDEEL = {
    "geen": ("Geen bemaling nodig", "#2e7d32"),
    "melding": ("Melding bij het waterschap", "#b58900"),
    "vergunning": ("Vergunning nodig bij het waterschap", "#c62828"),
}


def _getal(x, standaard=None):
    try:
        if x in (None, "") or (isinstance(x, float) and pd.isna(x)):
            return standaard
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return standaard


def _nl(x: float, dec: int = 0) -> str:
    return f"{x:,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _in_kering(geom, zones) -> bool:
    if zones is None or geom is None:
        return False
    zk = zones[zones["zonecode"].astype(str).str.endswith(("-KZ", "-BZ"))]
    idx = list(zk.sindex.query(geom, predicate="intersects"))
    return bool(idx)


def _boring(rij) -> bool:
    tekst = " ".join(str(v) for k, v in rij.items() if k != "geometry" and isinstance(v, str))
    return bool(BOORPATROON.search(tekst))


def _bob(rij):
    for k in rij.index:
        if str(k).lower() in ("bob", "bob_begin", "bob1"):
            return _getal(rij[k])
    return None


def startregels(lijnen, zones) -> pd.DataFrame:
    if lijnen is None or len(lijnen) == 0:
        return pd.DataFrame([{"meenemen": True, "deeltracé": "Tracé 1", "lengte (m)": 500.0, "boring": False,
                              "in kering": False, "maaiveld (m NAP)": None, "BOB (m NAP)": None,
                              "sleufdiepte (m -mv)": None, "GHG (m -mv)": None, "bodemtype": None}])
    # één rij per bestand (open ontgraving) en één rij voor de boringen/mantelbuizen in dat bestand:
    # de lijnen uit een tekening zijn vaak losse stukjes van dezelfde sleuf.
    groepen: dict = {}
    for _, r in lijnen.iterrows():
        boring = _boring(r)
        bestand = str(r.get("__bestand__") or r.get("trace") or "tracé")
        g = groepen.setdefault((bestand, boring), {"lengte": 0.0, "kering": False, "bob": []})
        g["lengte"] += r.geometry.length
        g["kering"] |= _in_kering(r.geometry, zones)
        if _bob(r) is not None:
            g["bob"].append(_bob(r))
    rijen = []
    for (bestand, boring), g in groepen.items():
        rijen.append({"meenemen": not boring, "deeltracé": bestand + (" (boringen)" if boring else ""),
                      "lengte (m)": round(g["lengte"], 1), "boring": boring, "in kering": g["kering"],
                      "maaiveld (m NAP)": None, "BOB (m NAP)": min(g["bob"]) if g["bob"] else None,
                      "sleufdiepte (m -mv)": None, "GHG (m -mv)": None, "bodemtype": None})
    return pd.DataFrame(rijen)


def grondwater_paneel(lijnen=None, zones=None, sleutel: str = "gw"):
    st.subheader("Grondwater: indicatie bemaling")
    st.caption("Een eerste inschatting of bemaling nodig is, hoeveel grondwater er ongeveer wordt onttrokken en of "
               "dat een melding of vergunning bij het waterschap vraagt. Dit vervangt geen bemalingsadvies "
               "(BRL/protocol 12010); de definitieve berekening laat je maken.")

    # ------------------------------------------------ uitgangspunten
    with st.expander("Uitgangspunten voor alle deeltracés", expanded=True):
        k1, k2, k3 = st.columns(3)
        ws = k1.selectbox("Waterschap", list(WATERSCHAPPEN), key=f"{sleutel}_ws")
        bodem = k2.selectbox("Bodem waarin de sleuf ligt", list(BODEMTYPEN), index=list(BODEMTYPEN).index("fijn zand"),
                             key=f"{sleutel}_bodem",
                             help="Doorlatendheid (m/dag) laag/verwacht/hoog: " + "; ".join(
                                 f"{k}: {a:g}/{b:g}/{c:g}" for k, (a, b, c) in BODEMTYPEN.items()))
        laag = k3.selectbox("Laag onder het freatisch pakket", list(SCHEIDENDE_LAAG), index=3, key=f"{sleutel}_laag",
                            help="Met een slecht doorlatende laag eronder rekent de module met De Glee (kwel), "
                                 "zonder met Dupuit/Sichardt.")
        k1, k2, k3, k4 = st.columns(4)
        ghg = k1.number_input("Hoge grondwaterstand GHG (m -mv)", 0.0, 10.0, 0.8, 0.05, key=f"{sleutel}_ghg",
                              help="Maatgevend in de bemalingsadviezen. Bron: DINOloket/BRO-peilbuizen, "
                                   "grondwatertools.nl, grondwatertrappenkaart of eigen peilbuis.")
        glg = k2.number_input("Lage grondwaterstand GLG (m -mv, 0 = onbekend)", 0.0, 10.0, 0.0, 0.05, key=f"{sleutel}_glg")
        diepte = k3.number_input("Sleufdiepte (m -mv)", 0.3, 8.0, 1.2, 0.05, key=f"{sleutel}_diepte",
                                 help="Onderkant ontgraving. Met maaiveld en BOB in de tabel rekent de module per "
                                      "deeltracé: maaiveld - BOB + 0,1 m zandbed.")
        pakket = k4.number_input("Onderkant freatisch pakket (m -mv)", 0.5, 30.0, 4.0, 0.5, key=f"{sleutel}_pakket",
                                 help="Diepte waarop de slecht doorlatende laag begint (REGIS II/GeoTOP via DINOloket "
                                      "of een sondering). Zonder scheidende laag: dikte van het zandpakket.")
        k1, k2, k3, k4, k5 = st.columns(5)
        breedte = k1.number_input("Sleufbreedte (m)", 0.3, 20.0, 1.5, 0.1, key=f"{sleutel}_breedte",
                                  help="Breedte op grondwaterniveau, inclusief taluds.")
        ontw = k2.number_input("Ontwatering onder sleufbodem (m)", 0.0, 1.0, 0.3, 0.05, key=f"{sleutel}_ontw",
                               help="In de adviezen 0,3 à 0,5 m.")
        snel = k3.number_input("Aanlegsnelheid (m/dag)", 5.0, 500.0, 50.0, 5.0, key=f"{sleutel}_snel")
        voor = k4.number_input("Dagen voorbemalen", 0.0, 10.0, 1.0, 1.0, key=f"{sleutel}_voor")
        open_ = k5.number_input("Dagen open per vak", 1.0, 30.0, 1.0, 1.0, key=f"{sleutel}_open")
        c_eigen = None
        if SCHEIDENDE_LAAG[laag]:
            c_eigen = st.number_input("Weerstand c van die laag (dagen)", 10.0, 50_000.0, float(SCHEIDENDE_LAAG[laag]),
                                      50.0, key=f"{sleutel}_c_{laag}")
        st.markdown("**Opbarsten (optioneel)**")
        k1, k2, k3 = st.columns(3)
        dek = k1.number_input("Onderkant deklaag (m -mv, 0 = niet controleren)", 0.0, 40.0, 0.0, 0.5, key=f"{sleutel}_dek")
        stijg = k2.number_input("Stijghoogte watervoerend pakket (m -mv, negatief = boven mv)", -3.0, 10.0, 1.0, 0.05,
                                key=f"{sleutel}_stijg")
        gew = k3.number_input("Volumegewicht deklaag (kN/m³)", 9.0, 20.0, 15.0, 0.5, key=f"{sleutel}_gew",
                              help="Veen ca. 10-11, klei ca. 15-17.")

    d: Drempels = WATERSCHAPPEN[ws]
    if ws.startswith("Ander"):
        with st.expander("Drempels voor een vergunning (zelf invullen)", expanded=True):
            k1, k2, k3 = st.columns(3)
            d = Drempels("eigen",
                         vergunning_m3_uur=k1.number_input("m³/uur", 0.0, 10_000.0, 50.0, key=f"{sleutel}_d_uur") or None,
                         vergunning_m3_maand=k2.number_input("m³/maand", 0.0, 1e7, 15_000.0, key=f"{sleutel}_d_mnd") or None,
                         vergunning_dagen=k3.number_input("dagen", 0.0, 3650.0, 183.0, key=f"{sleutel}_d_dgn") or None,
                         bron="eigen invoer")

    # ------------------------------------------------ tabel per deeltracé
    st.markdown("**Deeltracés.** Boringen en mantelbuizen staan uit (geen open ontgraving). Lege cellen nemen de "
                "uitgangspunten hierboven over.")
    vingerafdruk = "leeg" if lijnen is None or len(lijnen) == 0 else abs(hash(tuple(
        (str(r.get("trace", "")), round(r.geometry.length, 1)) for _, r in lijnen.iterrows())))
    basis_sleutel = f"{sleutel}_tabel_{vingerafdruk}"
    if basis_sleutel not in st.session_state:
        st.session_state[basis_sleutel] = startregels(lijnen, zones)
    tabel = st.data_editor(
        st.session_state[basis_sleutel], key=f"{basis_sleutel}_ed", hide_index=True, width="stretch",
        num_rows="dynamic" if lijnen is None or len(lijnen) == 0 else "fixed",
        column_config={
            "meenemen": st.column_config.CheckboxColumn(),
            "boring": st.column_config.CheckboxColumn(disabled=True),
            "in kering": st.column_config.CheckboxColumn(help="Raakt de kernzone of beschermingszone van een kering "
                                                              "(legger AGV)."),
            "bodemtype": st.column_config.SelectboxColumn(options=list(BODEMTYPEN)),
            "lengte (m)": st.column_config.NumberColumn(format="%.0f"),
        })

    sleuven: list[Sleuf] = []
    kering = False
    for _, r in tabel.iterrows():
        if not bool(r.get("meenemen")) or not _getal(r.get("lengte (m)"), 0):
            continue
        sd = _getal(r.get("sleufdiepte (m -mv)"))
        mv, bob = _getal(r.get("maaiveld (m NAP)")), _getal(r.get("BOB (m NAP)"))
        if sd is None and mv is not None and bob is not None:
            sd = mv - bob + 0.1
        kering |= bool(r.get("in kering"))
        sleuven.append(Sleuf(
            naam=str(r.get("deeltracé") or f"Tracé {len(sleuven) + 1}"), lengte_m=_getal(r.get("lengte (m)"), 0),
            ontgravingsdiepte_mmv=sd if sd is not None else diepte,
            grondwater_mmv=_getal(r.get("GHG (m -mv)"), ghg), grondwater_laag_mmv=glg or None,
            bodemtype=r.get("bodemtype") if r.get("bodemtype") in BODEMTYPEN else bodem,
            pakket_onderkant_mmv=pakket, scheidende_laag=laag, c_dagen=c_eigen, sleufbreedte_m=breedte,
            ontwatering_m=ontw, aanlegsnelheid_m_dag=snel, dagen_voorbemalen=voor, dagen_open=open_,
            maaiveld_nap=mv, deklaag_onderkant_mmv=dek or None, stijghoogte_mmv=stijg if dek else None,
            gewicht_deklaag_kn_m3=gew))
    if not sleuven:
        st.info("Zet minstens één deeltracé met een lengte aan.")
        return None

    uit = [bereken(s) for s in sleuven]
    tot = totaal(uit, sleuven)
    nodig = any(u.bemaling_nodig for u in uit)
    t = toets(d, tot.max_m3_uur["opstart"], tot.max_m3_maand["verwacht"], tot.totaal_m3["verwacht"],
              tot.duur_dagen, kering, nodig)
    t_hoog = toets(d, tot.max_m3_uur["hoog"] * OPSTARTFACTOR, tot.max_m3_maand["hoog"], tot.totaal_m3["hoog"],
                   tot.duur_dagen, kering, nodig)

    # ------------------------------------------------ uitkomst
    tekst, kleur = OORDEEL[t.oordeel]
    st.markdown(f"<div style='border-left:6px solid {kleur};padding:8px 14px;margin:8px 0;"
                f"background:rgba(127,127,127,0.08)'><b style='font-size:1.15em'>{tekst}</b><br>"
                + "; ".join(t.redenen) + "</div>", unsafe_allow_html=True)
    if t.oordeel == "melding" and t_hoog.oordeel == "vergunning":
        st.warning("Bij de hoge doorlatendheid wordt het wel vergunningplichtig: " + "; ".join(t_hoog.redenen) + ".")
    if nodig:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Debiet (verwacht)", f"{_nl(tot.max_m3_uur['verwacht'], 1)} m³/uur",
                  help=f"Bandbreedte {_nl(tot.max_m3_uur['laag'], 1)} – {_nl(tot.max_m3_uur['hoog'], 1)} m³/uur; "
                       f"opstart ca. {_nl(tot.max_m3_uur['opstart'], 1)} m³/uur.")
        k2.metric("Grootste maand", f"{_nl(tot.max_m3_maand['verwacht'])} m³")
        k3.metric("Waterbezwaar totaal", f"{_nl(tot.totaal_m3['verwacht'])} m³",
                  help=f"Bandbreedte {_nl(tot.totaal_m3['laag'])} – {_nl(tot.totaal_m3['hoog'])} m³.")
        k4.metric("Duur bemaling", f"{_nl(tot.duur_dagen)} dagen", help="Deeltracés na elkaar aangelegd.")
        st.caption(f"Bandbreedte debiet {_nl(tot.max_m3_uur['laag'], 1)} – {_nl(tot.max_m3_uur['hoog'], 1)} m³/uur; "
                   f"bij de start ca. {_nl(tot.max_m3_uur['opstart'], 1)} m³/uur (+{(OPSTARTFACTOR - 1) * 100:.0f}%).")

    df = pd.DataFrame([{
        "deeltracé": u.naam, "bemaling": "ja" if u.bemaling_nodig else "nee",
        "verlaging (m)": round(u.verlaging_m, 2), "tegelijk bemalen (m)": round(u.gelijktijdig_m),
        "debiet laag (m³/u)": round(u.debiet_m3_uur["laag"], 1),
        "debiet verwacht (m³/u)": round(u.debiet_m3_uur["verwacht"], 1),
        "debiet hoog (m³/u)": round(u.debiet_m3_uur["hoog"], 1), "duur (dagen)": round(u.duur_dagen, 1),
        "waterbezwaar verwacht (m³)": round(u.waterbezwaar_m3["verwacht"]),
        "invloedsgebied 5 cm (m)": round(u.invloedsgebied_m),
        "bij GLG nodig": {None: "-", True: "ja", False: "nee"}[u.bij_glg_nodig],
        "opbarsten": (u.opbarsten or {}).get("status", "-"), "rekenwijze": u.methode,
    } for u in uit])
    st.dataframe(df, hide_index=True, width="stretch")

    for u in uit:
        for m in u.meldingen:
            st.warning(f"{u.naam}: {m}")
        if u.opbarsten and u.opbarsten["status"] != "veilig":
            st.error(f"{u.naam}: {u.opbarsten['tekst']}")

    with st.expander("Toelichting en bronnen"):
        st.markdown("\n".join(f"- {x}" for x in t.toelichting + [
            f"Drempels {d.naam}: {d.bron}. Controleer ze in de actuele waterschapsverordening.",
            "Getoetst met het opstartdebiet (uur), de grootste 30 dagen en het totale waterbezwaar.",
            "Lozing: op oppervlaktewater of hemelwaterriool gelden vaak ijzer < 5 mg/l en onopgeloste delen "
            "< 50 mg/l; meld de lozing apart.",
            "Rekenwijze: het gelijktijdig bemalen vak (aanlegsnelheid × (voorbemalen + open)) als langgerekte "
            "bouwput met r = (L + B)/π. Met een scheidende laag De Glee (flux over de rand), zonder Dupuit met "
            "invloedsstraal van Sichardt. Bandbreedte met lage/hoge k (en c ×2 / ÷2).",
            "Niet meegenomen: spanningsbemaling, neerslag, oppervlaktewater dichtbij, verontreinigingen, zetting en "
            "houten palen. Die staan in het definitieve bemalingsadvies.",
        ]))

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Deeltracés", index=False)
        pd.DataFrame([
            ("oordeel", tekst), ("redenen", "; ".join(t.redenen)), ("waterschap", d.naam), ("bron drempels", d.bron),
            ("debiet verwacht (m³/uur)", round(tot.max_m3_uur["verwacht"], 1)),
            ("debiet laag-hoog (m³/uur)", f"{tot.max_m3_uur['laag']:.1f} - {tot.max_m3_uur['hoog']:.1f}"),
            ("opstartdebiet (m³/uur)", round(tot.max_m3_uur["opstart"], 1)),
            ("grootste maand (m³)", round(tot.max_m3_maand["verwacht"])),
            ("waterbezwaar verwacht (m³)", round(tot.totaal_m3["verwacht"])),
            ("waterbezwaar laag-hoog (m³)", f"{tot.totaal_m3['laag']:.0f} - {tot.totaal_m3['hoog']:.0f}"),
            ("duur (dagen)", round(tot.duur_dagen, 1)), ("let op", "Indicatie, geen bemalingsadvies."),
        ], columns=["onderdeel", "waarde"]).to_excel(xw, sheet_name="Samenvatting", index=False)
    st.download_button("Download indicatie grondwater (Excel)", buf.getvalue(), "indicatie_grondwater.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{sleutel}_dl")
    return t
