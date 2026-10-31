"""Streamlit-onderdeel: tekening links, kaart (BGT of luchtfoto) rechts, paspunten om en om zetten.

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

from . import kern, scan, tekening, traces

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


@st.cache_data(show_spinner="Tracés uit de tekening halen...", max_entries=4)
def _traces(data: bytes, pagina: int, tr_json: str, alleen: str | None, stam: str, bron: str):
    import fitz
    tr = kern.Transformatie.van_json(tr_json)
    with fitz.open(stream=data, filetype="pdf") as doc:
        lijst, info = traces.maak_traces(doc[pagina], tr, alleen=alleen)
    zip_bytes = traces.shapefile_zip(lijst, stam, bron) if lijst else None
    return traces.samenvatting(lijst), zip_bytes, sorted(info.get("overgeslagen", ())), info.get("venster") is not None


def _traces_paneel(data: bytes, naam: str, pagina: int, tr: kern.Transformatie, key: str, stam: str):
    """Leidingen uit de PDF-lagen als shapefiles per soort."""
    st.subheader("Tracés als shapefile")
    discipline = traces.discipline_uit_naam(naam)
    keuzes = {"DW": "alleen drinkwater", "AW": "alleen riolering", None: "alles"}
    opties = [discipline, None] if discipline else [None]
    alleen = st.radio("Welke leidingen", opties, format_func=lambda k: keuzes[k], horizontal=True,
                      key=key + "_alleen",
                      help="Uit de bestandsnaam (DW of AW). Een drinkwatertekening toont soms ook nieuw riool "
                           "van een ander team; dat hoort niet bij deze aanvraag.")
    samenv, zip_bytes, overgeslagen, venster = _traces(data, pagina, tr.naar_json(), alleen, stam,
                                                        f"{naam}, pagina {pagina + 1}")
    if not venster:
        st.info("Geen nieuwe of vervallen leidingen gevonden in het kaartvenster. Werkt alleen bij PDF's uit AutoCAD "
                "met de lagen erin (NLCS-laagnamen).")
        return
    st.caption("Alleen nieuwe en vervallen/te verwijderen leidingen uit het kaartvenster waarin de paspunten liggen. "
               "Bestaande leidingen, kabels en leidingen van anderen, legenda en details gaan niet mee. "
               "Huis- en kolkaansluitingen zitten in de shapefile van hun leiding.")
    if samenv:
        st.dataframe(pd.DataFrame(samenv), hide_index=True, width="stretch")
    if overgeslagen:
        st.caption("Niet meegenomen omdat ze niet bij deze tekening horen: " + ", ".join(overgeslagen) + ".")
    if zip_bytes:
        st.download_button("Download tracés (shapefiles)", zip_bytes, file_name=f"{stam}_traces.zip",
                           mime="application/zip", key=key + "_traces_dl",
                           help="Eén shapefile per soort, in RD. Kan direct in de Kabelchecker.")


@st.cache_data(show_spinner="Tekening scannen op coördinaten...", max_entries=4)
def _scan(data: bytes, pagina: int):
    return scan.scan(data, pagina)


def _startpunten(data: bytes, pagina: int, w: tekening.Weergave):
    """Coördinaten uit de tekening als eerste paspunten. Geeft (punten, uitleg, kaartcentrum)."""
    try:
        gevonden = _scan(data, pagina)
    except Exception as e:  # scannen mag de rest nooit blokkeren
        return [], f"Scannen op coördinaten lukte niet ({e}).", None
    if not gevonden:
        return [], None, None
    goed, af = scan.betrouwbare_set(gevonden)
    punten = [{"nr": i + 1, "tek": [g.tekening[0] / w.pixel_in_pt, g.tekening[1] / w.pixel_in_pt],
               "rd": list(g.rd), "bron": "tekening"} for i, g in enumerate(goed)]
    eerste = (goed or gevonden)[0]
    centrum = {"x": eerste.rd[0], "y": eerste.rd[1], "zoom": 14,
               "tekst": f"Coördinaat uit tekening: {eerste.rd[0]:.2f}, {eerste.rd[1]:.2f}"}
    n = len(goed)
    if n >= 3:
        uitleg = f"{n} coördinaten uit de tekening gebruikt. Je kunt een extra punt toevoegen ter controle."
    elif n:
        uitleg = (f"{n} coördinaat{'en' if n > 1 else ''} uit de tekening gebruikt. "
                  f"Zet nog {3 - n} punt{'en' if 3 - n > 1 else ''} met de hand.")
    else:
        uitleg = "Coördinaten gevonden op de tekening, maar ze zijn niet betrouwbaar te koppelen. Zet de punten met de hand."
    if af and n:
        uitleg += f" {len(af)} gevonden coördinaat/coördinaten niet gebruikt omdat ze niet bij de rest passen."
    return punten, uitleg, centrum


def georeferentie_paneel(key: str = "georef", hoogte: int = 620, minimum: int = 3) -> kern.Transformatie | None:
    """Toont het volledige georeferentie-onderdeel en geeft de transformatie terug
    (of None zolang er te weinig punten zijn)."""
    s = st.session_state.setdefault(key + "_staat", {"centrum": None, "centrum_nr": 0, "reset": 0})

    c1, c3 = st.columns([3, 2])
    with c1:
        up = st.file_uploader("Tekening (PDF, PNG of JPG)", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"],
                              key=key + "_upload")
    with c3:
        soort = st.radio("Transformatie", ["gelijkvormig", "affien"], key=key + "_soort", horizontal=True,
                         help="Gelijkvormig: schuiven, draaien en één schaal. Aanbevolen.\n\n"
                              "Affien: ook scheefstand en aparte schalen in x en y. Werkt pas vanaf 4 punten, "
                              "want met 3 punten gaat affien altijd exact door de punten en valt een fout niet op.")

    if up is None:
        st.info("Upload een tekening. Staan er RD-coördinaten op, dan worden die automatisch gebruikt.")
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
    gevonden_info = None
    if sessie not in punten_staat:
        punten_staat[sessie] = []
        if up.name.lower().endswith(".pdf"):
            punten_staat[sessie], gevonden_info, centrum = _startpunten(data, pagina, w)
            if centrum:
                s["centrum_nr"] += 1
                s["centrum"] = dict(centrum, id=s["centrum_nr"])
            st.session_state[key + "_scan_" + sessie] = gevonden_info
    gevonden_info = st.session_state.get(key + "_scan_" + sessie)
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
    if gevonden_info:
        st.caption(gevonden_info)
    if fout:
        st.error(fout)
    if tr is None:
        if s["centrum"] is None:
            st.caption("Tip: typ boven de kaart de straat en het huisnummer, dan springt de kaart naar het werkgebied.")
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
    b1.toggle("Tekening over kaart", value=True, key=key + "_toon_overlay")
    stam = Path(up.name).stem.removesuffix(".pdf")
    tr_json = tr.naar_json()
    b2.download_button("Download GeoTIFF + transformatie", lambda: _export_zip(w, w_id, tr_json, stam),
                       file_name=f"{stam}_georeferentie.zip", mime="application/zip")
    if b3.button("Opnieuw beginnen", key=key + "_reset"):
        s["reset"] += 1
        st.rerun()
    if up.name.lower().endswith(".pdf"):
        _traces_paneel(data, up.name, pagina, tr, key, stam)
    return tr
