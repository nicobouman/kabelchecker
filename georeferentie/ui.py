"""Streamlit-onderdeel: tekening links, luchtfoto rechts, paspunten om en om zetten.

Gebruik in een app:

    from georeferentie.ui import georeferentie_paneel
    tr = georeferentie_paneel(key="georef")     # Transformatie of None
    if tr:
        lijn_rd = tr.transformeer_geometrie(lijn_in_pt)
"""
from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from . import kern, pdok, tekening

_component = components.declare_component("georeferentie", path=str(Path(__file__).parent / "component"))


def _url(data: bytes, mime: str, sleutel: str) -> str:
    """Afbeelding via de mediaserver van Streamlit aanbieden (scheelt megabytes per rerun).
    Lukt dat niet, dan als data-URL."""
    try:
        from streamlit import runtime
        return runtime.get_instance().media_file_mgr.add(data, mime, sleutel)
    except Exception:
        return f"data:{mime};base64," + base64.b64encode(data).decode()


@st.cache_data(show_spinner="Tekening laden...", max_entries=4)
def _laad(data: bytes, naam: str, pagina: int, dpi: int) -> tekening.Weergave:
    return tekening.laad(data, naam, pagina, dpi)


@st.cache_data(show_spinner=False, ttl=3600)
def _zoek(tekst: str) -> list[dict]:
    try:
        return pdok.zoek(tekst)
    except Exception as e:  # netwerk
        st.warning(f"Zoeken bij PDOK lukte niet: {e}")
        return []


@st.cache_data(show_spinner="Controlebeeld maken...", max_entries=4)
def _controlebeeld(_w: tekening.Weergave, w_id: str, tr_json: str):
    tr = kern.Transformatie.van_json(tr_json)
    im, bounds, pm = tekening.noord_boven(_w, tr, max_zijde=3000, transparant_wit=True)
    b = io.BytesIO(); im.save(b, "PNG")
    return b.getvalue(), bounds


def _export_zip(_w: tekening.Weergave, w_id: str, tr_json: str, stam: str) -> bytes:
    tr = kern.Transformatie.van_json(tr_json)
    im, bounds, pm = tekening.noord_boven(_w, tr)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stam}_RD.tif", tekening.geotiff(im, bounds, pm))
        zf.writestr(f"{stam}_transformatie.json", tr_json)
    return z.getvalue()


def georeferentie_paneel(key: str = "georef", hoogte: int = 620, minimum: int = 3) -> kern.Transformatie | None:
    """Toont het volledige georeferentie-onderdeel en geeft de transformatie terug
    (of None zolang er te weinig punten zijn)."""
    s = st.session_state.setdefault(key + "_staat", {"centrum": None, "centrum_nr": 0, "reset": 0})

    c1, c2, c3 = st.columns([3, 3, 2])
    with c1:
        up = st.file_uploader("Tekening (PDF, PNG of JPG)", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"],
                              key=key + "_upload")
    with c2:
        zoekterm = st.text_input("Adres of werkgebied", key=key + "_zoek",
                                 placeholder="bv. Spaklerweg 20 Amsterdam, of RD 123140 483706")
        treffers = _zoek(zoekterm) if zoekterm else []
        if treffers:
            keus = st.selectbox("Gevonden", range(len(treffers)), format_func=lambda i: treffers[i]["naam"],
                                key=key + "_treffer", label_visibility="collapsed")
            t = treffers[keus]
            if s["centrum"] is None or (s["centrum"]["x"], s["centrum"]["y"]) != (t["x"], t["y"]):
                s["centrum_nr"] += 1
                s["centrum"] = {"x": t["x"], "y": t["y"], "zoom": 15 if t["type"] == "adres" else 13,
                                "id": s["centrum_nr"]}
        elif zoekterm:
            st.caption("Niets gevonden.")
    with c3:
        soort = st.radio("Transformatie", ["gelijkvormig", "affien"], key=key + "_soort", horizontal=True,
                         help="Gelijkvormig: schuiven, draaien en één schaal. Aanbevolen.\n\n"
                              "Affien: ook scheefstand en aparte schalen in x en y. Werkt pas vanaf 4 punten, "
                              "want met 3 punten gaat affien altijd exact door de punten en valt een fout niet op.")

    if up is None:
        st.info("Upload een tekening en zoek het adres of werkgebied op.")
        return None

    data = up.getvalue()
    pagina = 0
    n_pag = tekening.aantal_paginas(data, up.name)
    if n_pag > 1:
        pagina = st.number_input(f"Pagina (van {n_pag})", 1, n_pag, 1, key=key + "_pagina") - 1
    w = _laad(data, up.name, pagina, 150)
    w_id = hashlib.sha1(data).hexdigest()[:12] + f"-{pagina}"

    # punten worden per tekening(pagina) bewaard
    punten_staat = st.session_state.setdefault(key + "_punten", {})
    sessie = f"{w_id}-{s['reset']}"
    ruwe = punten_staat.get(sessie, [])

    paren = [p for p in ruwe if p.get("tek") and p.get("rd")]
    pp = [kern.Paspunt(p["nr"], (p["tek"][0] * w.pixel_in_pt, p["tek"][1] * w.pixel_in_pt), tuple(p["rd"]))
          for p in paren]
    tr, fout = None, None
    if soort == "affien" and len(pp) < 4:
        if pp:
            st.caption("Affien wordt pas gebruikt vanaf 4 punten; tot dan rekent het systeem gelijkvormig.")
        soort = "gelijkvormig"
    if len(pp) >= max(minimum, kern.MIN_PUNTEN[soort]):
        try:
            tr = kern.bereken(pp, soort, bron={"bestand": up.name, "pagina": pagina + 1})
        except ValueError as e:
            fout = str(e)

    overlay = None
    if tr is not None and st.session_state.get(key + "_toon_overlay", True):
        png, bounds = _controlebeeld(w, w_id, tr.naar_json())
        overlay = {"url": _url(png, "image/png", key + "_overlay"), "bounds": bounds,
                   "id": hashlib.sha1(png).hexdigest()[:12]}

    waarde = _component(
        key=key + "_comp", default=None, hoogte=hoogte, minimum=minimum, grens=kern.NAUWKEURIGHEID_M,
        sessie=sessie, punten=ruwe, centrum=s["centrum"], overlay=overlay,
        afbeelding={"url": _url(w.png, "image/png", key + "_tekening"), "breedte": w.breedte,
                    "hoogte": w.hoogte, "id": w_id},
        restfouten={str(p.nr): r for p, r in zip(tr.punten, tr.restfouten_m)} if tr else {},
    )
    if waarde and waarde.get("sessie") == sessie and waarde.get("punten") != ruwe:
        punten_staat[sessie] = waarde["punten"]
        st.rerun()

    # ------------------------------------------------------------ uitslag
    if fout:
        st.error(fout)
    if tr is None:
        if s["centrum"] is None:
            st.caption("Tip: zoek eerst het adres op, dan springt de luchtfoto naar het werkgebied.")
        return None

    over = kern.overtallig(len(tr.punten), soort)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Grootste afwijking", f"{max(tr.restfouten_m) * 100:.0f} cm")
    k2.metric("Gemiddeld (RMS)", f"{tr.rms_m * 100:.0f} cm")
    k3.metric("Schaal tekening", f"1:{tr.tekeningschaal:.0f}" if up.name.lower().endswith(".pdf") else "n.v.t.")
    k4.metric("Draaiing", f"{tr.draaiing_graden:.1f}°")
    if over <= 0:
        st.warning("Met dit aantal punten gaat de transformatie precies door de punten, dus een fout punt valt niet op. "
                   "Zet een extra punt ter controle.")
    elif not tr.binnen_nauwkeurigheid:
        slechtste = tr.punten[max(range(len(tr.punten)), key=lambda i: tr.restfouten_m[i])].nr
        st.error(f"Afwijking groter dan {kern.NAUWKEURIGHEID_M * 100:.0f} cm. Controleer punt {slechtste} "
                 "(verslepen kan in beide vensters), of zet een extra punt.")
    else:
        st.success(f"Alle punten binnen {kern.NAUWKEURIGHEID_M * 100:.0f} cm.")

    with st.expander("Punten en afwijkingen"):
        st.dataframe(pd.DataFrame([{
            "punt": p.nr, "tekening x (pt)": round(p.tekening[0], 1), "tekening y (pt)": round(p.tekening[1], 1),
            "RD x": round(p.rd[0], 2), "RD y": round(p.rd[1], 2), "afwijking (cm)": round(r * 100, 1)}
            for p, r in zip(tr.punten, tr.restfouten_m)]), hide_index=True, width="stretch")

    b1, b2, b3 = st.columns([2, 2, 3])
    b1.toggle("Tekening over luchtfoto", value=True, key=key + "_toon_overlay")
    stam = Path(up.name).stem.removesuffix(".pdf")
    tr_json = tr.naar_json()
    b2.download_button("Download GeoTIFF + transformatie", lambda: _export_zip(w, w_id, tr_json, stam),
                       file_name=f"{stam}_georeferentie.zip", mime="application/zip")
    if b3.button("Opnieuw beginnen", key=key + "_reset"):
        s["reset"] += 1
        st.rerun()
    return tr
