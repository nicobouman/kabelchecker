"""Kabelchecker v4 - toetst tracés aan de Waterschapsverordening AGV met regeltemplate v4.

Starten:  streamlit run kabelchecker_app_v4.py
"""
from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pydeck as pdk
import streamlit as st

import kabelchecker_v4_engine as K

APP_VERSION = "4.1"
HIER = Path(__file__).resolve().parent
STANDAARD_TEMPLATE = HIER / "regeltemplate_v4_AGV.xlsx"
_KANDIDATEN = [HIER.parent / "Kaartlezer" / "data_AGV", HIER.parent.parent / "Kaartlezer" / "data_AGV",
               HIER.parent / "data_AGV", HIER / "data_AGV"]
STANDAARD_DATA_AGV = next((p for p in _KANDIDATEN if p.exists()), _KANDIDATEN[0])

OORDEEL_TEKST = {
    "vergunning": "Vergunningplichtig",
    "maatwerk": "Maatwerk nodig",
    "onvolledig": "Onvolledig: gegevens ontbreken",
    "aandacht": "Aandachtspunt voor vergunningverlener",
    "voorschriften": "Toegestaan met voorschriften",
    "geen_specifieke_regels": "Geen specifieke regels van toepassing",
    "buiten_beperkingengebied": "Buiten het beperkingengebied",
}
OORDEEL_KLEUR = {
    "vergunning": [200, 30, 30, 255],
    "maatwerk": [230, 120, 0, 255],
    "onvolledig": [150, 90, 200, 255],
    "aandacht": [220, 180, 0, 255],
    "voorschriften": [40, 150, 60, 255],
    "geen_specifieke_regels": [90, 90, 90, 255],
    "buiten_beperkingengebied": [120, 120, 120, 255],
}
ZONE_KLEUR = {
    "WK-KZ": [252, 141, 89, 110], "WK-BZ": [254, 224, 139, 90], "WK-BBZ": [230, 245, 152, 70],
    "HV-KZ": [145, 207, 96, 110], "HV-BZ": [217, 240, 163, 90], "HV-BBZ": [240, 250, 200, 70],
    "VH-KZ": [102, 189, 99, 110], "VH-BZ": [199, 233, 192, 90], "VH-BBZ": [229, 245, 224, 70],
}


# ------------------------------------------------------------------ inlezen
@st.cache_resource(show_spinner="Leggerlagen AGV laden...")
def geolagen(pad: str):
    return K.laad_geolagen(Path(pad))


def lees_traces(uploads) -> gpd.GeoDataFrame:
    frames = []
    shp_bundel: dict[str, bytes] = {}
    for up in uploads:
        naam, data = up.name, up.getvalue()
        ext = Path(naam).suffix.lower()
        if ext in (".geojson", ".json"):
            with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
                f.write(data)
            g = gpd.read_file(f.name)
            g["__bestand__"] = Path(naam).stem
            frames.append(g)
        elif ext in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
            shp_bundel[naam] = data
        elif ext == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for m in zf.namelist():
                    if Path(m).suffix.lower() in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
                        shp_bundel[Path(m).name] = zf.read(m)
    for shp in [n for n in shp_bundel if n.lower().endswith(".shp")]:
        stam = Path(shp).stem
        with tempfile.TemporaryDirectory() as td:
            for n, raw in shp_bundel.items():
                if Path(n).stem == stam:
                    (Path(td) / n).write_bytes(raw)
            g = gpd.read_file(Path(td) / shp)
        g["__bestand__"] = stam
        frames.append(g)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=28992)
    uit = []
    for g in frames:
        if g.crs is None or (g.total_bounds[0] > 1000 and g.crs.to_epsg() != 28992 and g.crs.is_geographic):
            g = g.set_crs(28992, allow_override=True)
        uit.append(g.to_crs(28992))
    gdf = gpd.GeoDataFrame(pd.concat(uit, ignore_index=True), crs=28992)
    gdf = gdf[gdf.geometry.notna() & gdf.geom_type.isin(["LineString", "MultiLineString"])].reset_index(drop=True)
    gdf["trace"] = [f"{b}#{i + 1}" for i, b in enumerate(gdf["__bestand__"])]
    return gdf


# ------------------------------------------------------------------ attributen uit Kaartlezer-shapefiles
MEDIUM_UIT_SOORT = {"water": "drinkwater", "dw": "drinkwater", "drinkwater": "drinkwater", "hwa": "hwa", "rwa": "hwa",
                    "dwa": "dwa", "vwa": "dwa", "gwa": "dwa", "pers": "dwa", "gas": "gas", "g": "gas"}


def voorinvullen(rij: pd.Series, velden: list[str]) -> dict:
    """Haalt wat kan uit de attributen van een tracé (Kaartlezer-uitvoer of eigen GeoJSON)."""
    attr = {str(k).lower(): v for k, v in rij.items() if k not in ("geometry",)}
    uit = {v: attr.get(v) for v in velden if attr.get(v) not in (None, "")}
    soort = str(attr.get("soort") or "").strip().lower()
    if "type" not in uit or str(uit.get("type")).lower() not in ("kabel", "leiding", "mantelbuis"):
        uit.pop("type", None)
        if "mantel" in soort:
            uit["type"] = "mantelbuis"
        elif any(k in soort for k in ("kabel", "elec", "ls", "ms", "telecom", "glas")):
            uit["type"] = "kabel"
        elif soort:
            uit["type"] = "leiding"
    if "medium" not in uit and soort:
        for k, m in MEDIUM_UIT_SOORT.items():
            if soort == k or soort.startswith(k):
                uit["medium"] = m
                break
    mat = str(attr.get("materiaal") or "")
    if mat:
        eerste = mat.split()[0].upper()
        uit["materiaal"] = {"PE": "PE", "PVC": "PVC", "PP": "PP", "GN": "staal", "GGIJ": "staal", "STAAL": "staal",
                            "AC": "AC", "BETON": "beton", "GRES": "gres", "KOPER": "koper", "GVK": "GVK"}.get(eerste, eerste)
        m = re.search(r"SDR\s*(\d+)", mat, re.I)
        if m:
            uit["sdr"] = int(m.group(1))
    if "diameter_mm" not in uit and attr.get("diameter") not in (None, ""):
        try:
            uit["diameter_mm"] = float(attr["diameter"])
        except (TypeError, ValueError):
            pass
    status = str(attr.get("status") or "").lower()
    if "werkwijze" not in uit and status:
        if "schuim" in status:
            uit["werkwijze"] = "volschuimen"
        elif "nieuw" in status:
            uit["werkwijze"] = "nieuw"
        elif any(k in status for k in ("vervallen", "verwijder")):
            uit["werkwijze"] = "verwijderen"
    if soort == "pers" and "druk_bar" not in uit:
        pass  # persleiding: druk vraagt de app (afspraak: persleiding > 1 bar), niet aannemen
    return {k: v for k, v in uit.items() if v not in (None, "")}


# ------------------------------------------------------------------ kaart
def kaart(traces: gpd.GeoDataFrame, uitkomsten: dict, lagen):
    if traces.empty:
        return
    wgs = traces.to_crs(4326)
    b = traces.total_bounds
    zones = lagen.zones.cx[b[0] - 150:b[2] + 150, b[1] - 150:b[3] + 150]
    layers = []
    for code in ["WK-BBZ", "HV-BBZ", "VH-BBZ", "WK-BZ", "HV-BZ", "VH-BZ", "WK-KZ", "HV-KZ", "VH-KZ"]:
        z = zones[zones["zonecode"] == code]
        if z.empty:
            continue
        z = z[["code", "zonecode", "geometry"]].to_crs(4326)
        layers.append(pdk.Layer("GeoJsonLayer", data=json.loads(z.to_json()), filled=True, stroked=True,
                                get_fill_color=ZONE_KLEUR[code], get_line_color=[110, 110, 110, 200],
                                line_width_min_pixels=1, pickable=True))
    feats = []
    for naam, (_, delen) in uitkomsten.items():
        for d, r in delen:
            g = gpd.GeoSeries([d["geometry"]], crs=28992).to_crs(4326).iloc[0]
            feats.append({"type": "Feature", "geometry": json.loads(gpd.GeoSeries([g]).to_json())["features"][0]["geometry"],
                          "properties": {"trace": naam, "zonecode": ", ".join(r.zones) or "-",
                                         "code": OORDEEL_TEKST[r.oordeel], "kleur": OORDEEL_KLEUR[r.oordeel]}})
    layers.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, stroked=True,
                            filled=False, get_line_color="properties.kleur", line_width_min_pixels=4, pickable=True))
    labels, geplaatst = [], []
    for _, r in traces.iterrows():
        g = r.geometry
        mp = g.interpolate(0.5, normalized=True) if g.geom_type == "LineString" else g.representative_point()
        # labels van tracés die dicht bij elkaar liggen onder elkaar zetten
        buren = sum(1 for q in geplaatst if q.distance(mp) < 15)
        geplaatst.append(mp)
        m = gpd.GeoSeries([mp], crs=28992).to_crs(4326).iloc[0]
        labels.append({"pos": [m.x, m.y], "tekst": "#" + str(r["trace"]).split("#")[-1], "offset": [0, 24 * buren]})
    layers.append(pdk.Layer("TextLayer", data=labels, get_position="pos", get_text="tekst", get_size=18,
                            get_pixel_offset="offset",
                            get_color=[0, 0, 0, 255], background=True, get_background_color=[255, 255, 255, 230],
                            get_text_anchor="'middle'", get_alignment_baseline="'center'", font_weight=700))
    c = wgs.union_all().centroid
    st.pydeck_chart(pdk.Deck(map_provider="carto", map_style=pdk.map_styles.CARTO_LIGHT,
                             initial_view_state=pdk.ViewState(latitude=c.y, longitude=c.x, zoom=17),
                             layers=layers, tooltip={"text": "{trace}\n{zonecode}\n{code}"}),
                    use_container_width=True, height=600)


# ------------------------------------------------------------------ app
def wachtwoord_ok() -> bool:
    """Online versie: vraag het wachtwoord uit st.secrets. Lokaal (geen secrets) geen wachtwoord."""
    try:
        juist = st.secrets.get("wachtwoord")
    except Exception:
        juist = None
    if not juist or st.session_state.get("ingelogd"):
        return True
    st.title("Kabelchecker")
    with st.form("login"):
        w = st.text_input("Wachtwoord", type="password")
        if st.form_submit_button("Inloggen", type="primary"):
            if w == juist:
                st.session_state["ingelogd"] = True
                st.rerun()
            st.error("Onjuist wachtwoord.")
    return False


def main():
    st.set_page_config(page_title="Kabelchecker v4", layout="wide")
    if not wachtwoord_ok():
        st.stop()
    st.title(f"Kabelchecker {APP_VERSION}")
    st.caption("Toetsing van tracés aan de Waterschapsverordening AGV (art. 2.15 en 3.14-3.18), per tracédeel.")

    with st.sidebar:
        st.header("1. Regels en legger")
        tpl_up = st.file_uploader("Regeltemplate (leeg = standaard v4)", type=["xlsx"])
        if tpl_up:
            p = Path(tempfile.gettempdir()) / "kabelchecker_template_v4.xlsx"
            p.write_bytes(tpl_up.getvalue())
            tpl_pad = p
        else:
            tpl_pad = STANDAARD_TEMPLATE
        data_agv = st.text_input("Map data_AGV", str(STANDAARD_DATA_AGV))
        try:
            t = K.laad_template(tpl_pad)
        except Exception as e:
            st.error(f"Template niet te lezen: {e}")
            st.stop()
        st.success(f"{len(t.zorgplicht)} zorgplichtregels, {len(t.vergunning)} vergunningregels")
        st.header("2. Marges")
        t.params["HOEK_MIN"] = st.slider("Minimale hoek voor 'loodrecht' (graden)", 45, 90, int(t.params.get("HOEK_MIN", 75)))
        t.params["DWARS_AANDEEL"] = st.slider("Aandeel kernzonebreedte voor 'dwars door'", 0.5, 1.0,
                                              float(t.params.get("DWARS_AANDEEL", 0.75)), 0.05)
        st.header("3. Tracé")
        uploads = st.file_uploader("GeoJSON, shapefile-delen of zip", accept_multiple_files=True,
                                   type=["geojson", "json", "shp", "dbf", "shx", "prj", "cpg", "zip"])

    if not Path(data_agv).exists():
        st.error(f"Map data_AGV niet gevonden: {data_agv}")
        st.stop()
    if not uploads:
        st.info("Upload een tracé om te beginnen. De lijnen worden opgesplitst in sub-tracés: een knip bij een "
                "wissel van materiaal of diameter, bij een aftakking en aan begin en eind van een boring of mantelbuis. "
                "Delen buiten de zones vallen af.")
        st.stop()

    lagen = geolagen(data_agv)
    lijnen = lees_traces(uploads)
    if lijnen.empty:
        st.warning("Geen lijnen gevonden in de upload.")
        st.stop()
    # opsplitsen in sub-tracés (regels_opsplitsen.md); elk sub-tracé wordt apart getoetst
    rij_van = {r["trace"]: r for _, r in lijnen.iterrows()}
    subtraces = K.splits_traces(
        [dict(id=r["trace"], geometry=r.geometry, groep=r["__bestand__"],
              attrs={k: v for k, v in r.items() if k != "geometry"}) for _, r in lijnen.iterrows()],
        lagen, t.params)
    if not subtraces:
        st.success("Geen enkel tracé raakt een zone van de legger: buiten het beperkingengebied.")
        st.stop()
    sub_van = {d["naam"]: d for d in subtraces}
    traces = gpd.GeoDataFrame({"trace": [d["naam"] for d in subtraces]},
                              geometry=[d["geometry"] for d in subtraces], crs=28992)
    st.caption(f"{len(lijnen)} lijn(en) in de upload, opgesplitst in {len(subtraces)} sub-tracé(s) binnen de zones.")

    velden = [str(v["veld"]) for v in t.invoervelden]
    keuzes = {str(v["veld"]): [x.strip() for x in str(v.get("waarden") or "").split(";")]
              for v in t.invoervelden if str(v.get("type")) == "keuze"}

    info = {str(v["veld"]): v for v in t.invoervelden}
    traces["nr"] = [n.split("#")[-1] for n in traces["trace"]]
    basis = {d["naam"]: {**voorinvullen(rij_van[d["hoofdbron"]], velden), **d["invoer"]} for d in subtraces}
    antw = st.session_state.setdefault("antwoorden", {})  # (trace, veld) -> waarde

    def invoer_van(naam):
        rij = dict(basis[naam])
        for (tn, v), w in antw.items():
            if tn == naam and w not in (None, ""):
                rij[v] = w
        return rij

    def toets_alles():
        uit = {}
        for naam, d in sub_van.items():
            r = K.toets_deel(t, invoer_van(naam), d["toetszones"], d["geo"])
            uit[naam] = (r.oordeel, [(d, r)])
        return uit

    def invulveld(veld, label, sleutel):
        v = info.get(veld, {})
        if veld in keuzes:
            return st.selectbox(label, ["(kies)"] + keuzes[veld], key=sleutel)
        eenheid = f" ({v.get('eenheid')})" if v.get("eenheid") else ""
        return st.text_input(label + eenheid, key=sleutel, placeholder="getal, bijv. 1.2")

    def bewaar(naam, veld, waarde):
        if waarde in (None, "", "(kies)"):
            return
        if veld not in keuzes:
            try:
                waarde = float(str(waarde).replace(",", "."))
            except ValueError:
                st.error(f"'{waarde}' is geen getal ({veld}).")
                return
        antw[(naam, veld)] = waarde

    uitkomsten = toets_alles()
    vragen = sorted({(naam, v) for naam, (_, delen) in uitkomsten.items() for _, r in delen for v in r.vragen})

    st.subheader("Vragen aan de vergunningverlener")
    if vragen:
        st.caption("Deze gegevens staan niet in het bestand maar zijn nodig voor de toetsing. "
                   "Vul ze in en klik op 'Antwoorden opslaan'; daarna kunnen er nieuwe vragen volgen.")
        per_veld: dict[str, list[str]] = {}
        for naam, v in vragen:
            per_veld.setdefault(v, []).append(naam)
        with st.form("vragen"):
            invul = []
            for veld, namen in per_veld.items():
                vraag = info.get(veld, {}).get("vraag aan vergunningverlener") or veld
                nrs = ", ".join("#" + n.split("#")[-1] for n in namen)
                st.markdown(f"**{vraag}**  \n<span style='color:grey'>veld `{veld}` · tracé {nrs}</span>", unsafe_allow_html=True)
                c1, c2 = st.columns([1, 2])
                with c1:
                    alle = invulveld(veld, "Voor alle genoemde tracés", f"q_{veld}_alle")
                    invul.append((veld, namen, alle))
                if len(namen) > 1:
                    with c2:
                        with st.expander("Per tracé verschillend"):
                            for n in namen:
                                w = invulveld(veld, f"Tracé #{n.split('#')[-1]}", f"q_{veld}_{n}")
                                invul.append((veld, [n], w))
            if st.form_submit_button("Antwoorden opslaan", type="primary"):
                for veld, namen, w in invul:
                    for n in namen:
                        bewaar(n, veld, w)
                st.rerun()
    else:
        st.success("Alle gegevens die nodig zijn, zijn bekend.")

    with st.expander("Gegevens per tracé bekijken of aanpassen"):
        tabel = pd.DataFrame([{"tracé": "#" + n.split("#")[-1], **invoer_van(n)} for n in traces["trace"]],
                             columns=["tracé", *velden])
        st.dataframe(tabel, use_container_width=True, hide_index=True)
        with st.form("aanpassen"):
            c1, c2, c3 = st.columns(3)
            tn = c1.selectbox("Tracé", list(traces["trace"]), format_func=lambda n: "#" + n.split("#")[-1])
            vd = c2.selectbox("Veld", velden)
            wd = c3.text_input("Nieuwe waarde (bij keuzevelden: een van de opties)")
            if st.form_submit_button("Waarde opslaan"):
                if vd in keuzes and wd not in keuzes[vd]:
                    st.error(f"Kies een van: {', '.join(keuzes[vd])}")
                else:
                    bewaar(tn, vd, wd)
                    st.rerun()
        if antw and st.button("Alle antwoorden wissen"):
            antw.clear()
            st.rerun()

    st.subheader("Eindoordeel")
    st.dataframe(pd.DataFrame([{"tracé": "#" + n.split("#")[-1], "bestand": sub_van[n]["groep"],
                                "soort": sub_van[n]["soort"], "lengte_m": round(sub_van[n]["hoofdlijn"].length, 1),
                                "zwaarste zone": ", ".join(sorted(sub_van[n]["toetszones"])) or "-",
                                "kruising": sub_van[n]["wijze"] or "-", "eindoordeel": OORDEEL_TEKST[o],
                                "alle zones": ", ".join(sorted(sub_van[n]["zones"])) or "-"}
                               for n, (o, d) in uitkomsten.items()]), use_container_width=True, hide_index=True)
    kaart(traces, uitkomsten, lagen)

    st.subheader("Toelichting per tracé")
    rapport = []
    for naam, (oordeel, delen) in uitkomsten.items():
        with st.expander(f"{naam}: {OORDEEL_TEKST[oordeel]}", expanded=oordeel in ("vergunning", "maatwerk")):
            for nr, (d, r) in enumerate(delen, 1):
                g = d["geo"]
                hoek = "-" if g.get("hoek_met_kering") is None else f"{g['hoek_met_kering']:.0f}°"
                ha = f" + {d['huisaansluitingen']} huisaansluiting(en)" if d.get("huisaansluitingen") else ""
                st.markdown(f"**{d['soort']}** · {d['hoofdlijn'].length:.1f} m{ha} · getoetst op: {', '.join(r.zones) or 'geen'} "
                            f"(geraakt: {', '.join(sorted(d['zones']))}) · {d.get('wijze') or '-'} · "
                            f"regime: {', '.join(r.regimes) or '-'} · hoek met kering {hoek} · "
                            f"dwars-aandeel kernzone {g.get('dwars_aandeel_kernzone')} · kruin geraakt: {'ja' if g.get('raakt_kruin') else 'nee'} · "
                            f"**{OORDEEL_TEKST[r.oordeel]}**")
                if r.regels:
                    df = pd.DataFrame([{"stap": x.stap, "artikel": x.artikel, "uitkomst": x.uitkomst,
                                        "tekst": x.tekst, "ontbreekt": ", ".join(x.ontbrekend)} for x in r.regels])
                    volgorde = {"vergunning": 0, "voldoet_niet": 1, "onbekend": 2, "aandacht": 3, "voldoet": 4, "voorschrift": 5}
                    df = df.sort_values("uitkomst", key=lambda s: s.map(volgorde))
                    st.dataframe(df, use_container_width=True, hide_index=True)
                for x in r.regels:
                    rapport.append({"tracé": naam, "soort": d["soort"], "lengte_m": round(d["hoofdlijn"].length, 1),
                                    "getoetst_op": ", ".join(r.zones), "alle_zones": ", ".join(sorted(d["zones"])),
                                    "kruising": d.get("wijze") or "", "bronlijnen": ", ".join(map(str, d["bronnen"])),
                                    "oordeel": oordeel,
                                    "stap": x.stap, "artikel": x.artikel, "uitkomst": x.uitkomst, "tekst": x.tekst,
                                    "ontbreekt": ", ".join(x.ontbrekend)})
            vs = sorted({x.tekst for _, r in delen for x in r.regels if x.uitkomst in ("voldoet", "voorschrift") and x.tekst})
            if vs:
                st.markdown("**Voorschriften voor de reactie aan de aanvrager**")
                st.markdown("\n".join(f"- {v}" for v in vs))

    if rapport:
        st.download_button("Download toetsing (CSV)", pd.DataFrame(rapport).to_csv(index=False, sep=";").encode("utf-8-sig"),
                           "kabelchecker_v4_toetsing.csv", "text/csv")
    st.caption(f"Template: {tpl_pad.name} · HOEK_MIN {t.params['HOEK_MIN']:.0f}° · DWARS_AANDEEL {t.params['DWARS_AANDEEL']:.2f}")


if __name__ == "__main__":
    main()
