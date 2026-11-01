import io, math, zipfile
import numpy as np
from PIL import Image
from georeferentie import kern, tekening


def _punten(A, t, src):
    return [kern.Paspunt(i + 1, tuple(s), tuple(np.asarray(A) @ s + t)) for i, s in enumerate(np.asarray(src, float))]


def test_gelijkvormig_exact():
    th, s = math.radians(30), 200 * kern.PT_IN_M
    A = s * np.array([[math.cos(th), math.sin(th)], [math.sin(th), -math.cos(th)]])  # y naar beneden
    t = np.array([123000.0, 484000.0])
    tr = kern.bereken(_punten(A, t, [[100, 100], [2000, 300], [800, 1500]]))
    assert np.allclose(tr.A, A) and np.allclose(tr.t, t)
    assert max(tr.restfouten_m) < 1e-6
    assert abs(tr.tekeningschaal - 200) < 1e-6
    assert abs(tr.draaiing_graden - 30) < 1e-6


def test_fout_punt_valt_op():
    A = 0.07 * np.array([[1, 0], [0, -1]]); t = np.array([120000.0, 480000.0])
    pp = _punten(A, t, [[0, 0], [1000, 0], [0, 1000]])
    pp[2] = kern.Paspunt(3, pp[2].tekening, (pp[2].rd[0] + 2, pp[2].rd[1]))
    tr = kern.bereken(pp)
    assert max(tr.restfouten_m) > 0.5 and not tr.binnen_nauwkeurigheid
    assert kern.overtallig(3, "gelijkvormig") == 2 and kern.overtallig(3, "affien") == 0


def test_affien_en_json():
    A = np.array([[0.07, 0.01], [0.005, -0.065]]); t = np.array([121000.0, 485000.0])
    tr = kern.bereken(_punten(A, t, [[0, 0], [1000, 50], [100, 900], [800, 800]]), "affien")
    assert np.allclose(tr.A, A)
    tr2 = kern.Transformatie.van_json(tr.naar_json())
    assert np.allclose(tr2.naar_rd([[10, 20]]), tr.naar_rd([[10, 20]]))
    assert np.allclose(tr2.naar_tekening(tr2.naar_rd([[10, 20]])), [[10, 20]])


def test_geotiff_hoeken():
    im = Image.new("RGB", (400, 200), "white"); im.putpixel((0, 0), (255, 0, 0))
    b = io.BytesIO(); im.save(b, "PNG")
    w = tekening.Weergave(b.getvalue(), 400, 200, 0.5)
    A = 0.1 * np.array([[1, 0], [0, -1]]); t = np.array([100000.0, 450000.0])
    tr = kern.bereken(_punten(A, t, [[0, 0], [200, 0], [0, 100]]))
    uit, bounds, pm = tekening.noord_boven(w, tr)
    assert np.allclose(bounds, [100000, 450000 - 10, 100020, 450000]) and abs(pm - 0.05) < 1e-9
    assert uit.getpixel((0, 0))[:3] == (255, 0, 0)
    raw = tekening.geotiff(uit, bounds, pm)
    tags = Image.open(io.BytesIO(raw)).tag_v2
    assert tuple(tags[33922])[3:5] == (100000.0, 450000.0) and 28992 in tuple(tags[34735])


def test_scan_dso_tekening():
    import pathlib, pytest
    from georeferentie import scan
    f = pathlib.Path("/mnt/project-files/Kaartlezer/Waternet/DSO AW werktekening 1 200.pdf.pdf")
    if not f.exists():
        pytest.skip("voorbeeldtekening niet aanwezig")
    goed, af = scan.betrouwbare_set(scan.scan(f.read_bytes()))
    assert len(goed) >= 3
    tr = kern.bereken([kern.Paspunt(i + 1, g.tekening, g.rd) for i, g in enumerate(goed)])
    assert abs(tr.tekeningschaal - 200) < 1 and max(tr.restfouten_m) < 0.02


# ------------------------------------------------------------------ tracés
def test_laagnamen():
    from georeferentie.traces import ontleed_laag, shapefile_naam
    l = ontleed_laag("xref|N-OI-RI-DWA_RIOOLLEIDING_PVC_250-G")
    assert (l.status, l.soort, l.functie, l.materiaal, l.diameter) == ("nieuw", "DWA", "leiding", "PVC", 250)
    assert shapefile_naam(l) == "nieuw_DWA"
    l = ontleed_laag("N-OI-RI-HWA_KOLKAANSLUITLEIDING_PVC_125-G")
    assert l.functie == "kolkaansluiting" and shapefile_naam(l) == "nieuw_HWA"
    l = ontleed_laag("N-OI-KL-WATER_HUISAANSLUITING_LEIDING_PE_40-G")
    assert l.functie == "huisaansluiting" and shapefile_naam(l) == "nieuw_drinkwater"
    l = ontleed_laag("N-OI-RI-PERSLEIDING_PE SDR17_200-G")
    assert l.materiaal == "PE SDR17" and l.diameter == 200
    assert ontleed_laag("N-OI-RI-DWA_RIOOLLEIDING-VOLSCHUIMEN-G").status == "volgeschuimd"
    assert shapefile_naam(ontleed_laag("V-OI-KL-WATER_DISTRIBUTIE KLEIN_LEIDING-G")) == "verwijderen"
    assert shapefile_naam(ontleed_laag("V-OI-RI-HWA_RIOOLLEIDING-G")) == "vervallen"
    l = ontleed_laag("V-OI-KL-WATER_HUISAANSLUITING_LEIDING-G")
    assert (l.status, l.functie) == ("verwijderen", "huisaansluiting")
    # niet mee: bestaand, kabels van anderen, hulplagen, vervallen huisaansluitingen
    for naam in ("B-OI-RI-DWA_RIOOLLEIDING_PVC_250-G", "N-OI-KL-DATA_KABELBED-G", "V-OI-KL-WARMTENET-G",
                 "N-OI-RI-DWA_RIOOLLEIDING_STROMINGSRICHTING-G", "N-OI-RI-HWA_RIOOLLEIDING_BUITENKANT-G",
                 "N-OI-RI-DWA_RIOOLLEIDING-T18",
                 "N-WE-VH-MATERIAALGRENS-G"):
        assert ontleed_laag(naam) is None, naam


def test_rijgen_streepjes_en_versiering():
    from georeferentie.traces import rijg
    # streepjeslijn van 0 tot 100 pt: streepjes van 8, gaten van 4
    streepjes = [np.array([[x, 0.0], [x + 8, 0.0]]) for x in range(0, 96, 12)]
    # driehoekjes op de lijn (drainsymbool): voet op de lijn, top 3 pt erboven
    driehoek = [np.array([[20.0, 0], [22, 3], [24, 0]])]
    # // teken dwars over de lijn
    streep = [np.array([[50.0, -2], [52, 2]])]
    uit = rijg(streepjes + driehoek + streep, gat=16, max_uitsteeksel=6)
    lang = [u for u in uit if np.hypot(*np.diff(u, axis=0).T).sum() > 10]
    assert len(lang) == 1
    assert abs(lang[0][:, 0].min()) < 0.2 and abs(lang[0][:, 0].max() - 92) < 0.2   # raster van 0,3 pt
    assert np.allclose(lang[0][:, 1], 0)


def test_traces_uit_tekening(tmp_path):
    import pathlib, pytest, zipfile as zf
    import geopandas as gpd
    import fitz
    from georeferentie import scan, traces
    f = pathlib.Path("/mnt/project-files/Kaartlezer/Waternet/01.4668_WN_AW_TRP_PV_001_H1116_C1545_DOwijz.pdf")
    if not f.exists():
        pytest.skip("voorbeeldtekening niet aanwezig")
    goed, _ = scan.betrouwbare_set(scan.scan(f.read_bytes()))
    tr = kern.bereken([kern.Paspunt(i + 1, g.tekening, g.rd) for i, g in enumerate(goed)])
    with fitz.open(f) as doc:
        lijst, info = traces.maak_traces(doc[0], tr, alleen="AW")
    namen = {t.shapefile for t in lijst}
    assert namen == {"nieuw_HWA", "nieuw_persleiding", "vervallen"}
    # vervallen DWA GY 250 staat op de tekening als 19,95 m
    assert any(abs(t.lengte_m - 19.95) < 0.3 and "19,95m" in t.label for t in lijst)
    data = traces.shapefile_zip(lijst, "proef")
    with zf.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp_path)
    g = gpd.read_file(tmp_path / "proef_traces" / "nieuw_persleiding.shp")
    assert g.crs.to_epsg() == 28992 and set(g["materiaal"]) == {"PE SDR17", "PVC"}
    assert 122900 < g.total_bounds[0] < 123100


def _traces_van(naam, alleen):
    import pathlib, pytest
    import fitz
    from georeferentie import traces
    f = pathlib.Path("/mnt/project-files/Kaartlezer/Waternet") / naam
    if not f.exists():
        pytest.skip("voorbeeldtekening niet aanwezig")
    s = 200 * kern.PT_IN_M
    tr = kern.Transformatie("gelijkvormig", [[s, 0], [0, -s]], [120000.0, 480000.0])
    with fitz.open(f) as doc:
        return traces.maak_traces(doc[0], tr, alleen=alleen)[0]


def test_vervallen_huisaansluiting_alleen_als_verwijderen_er_staat():
    # case 005: legenda "Verwijderen Aansluitleiding / Drinkwaterleiding" -> die gaat mee
    lijst = _traces_van("Case 005 DW A2 werktekening 1-200.pdf", "DW")
    assert lijst and {t.shapefile for t in lijst} == {"verwijderen"}
    assert all(t.laag.functie == "huisaansluiting" for t in lijst)
    # 01.4954: legenda noemt alleen "Verwijderen Drinkwaterleiding" -> vervallen huisaansluiting niet mee
    lijst = _traces_van("01.4954_WN_DW_TDP_PV_001_Uitvoeringstekening.pdf", "DW")
    assert not [t for t in lijst if t.laag.status != "nieuw" and t.laag.functie == "huisaansluiting"]


def _keuzes_van(naam, alleen):
    import pathlib, pytest
    import fitz
    from georeferentie import traces
    f = pathlib.Path("/mnt/project-files/Kaartlezer/Waternet") / naam
    if not f.exists():
        pytest.skip("voorbeeldtekening niet aanwezig")
    s = 200 * kern.PT_IN_M
    tr = kern.Transformatie("gelijkvormig", [[s, 0], [0, -s]], [120000.0, 480000.0])
    with fitz.open(f) as doc:
        lijst, info = traces.maak_traces(doc[0], tr, alleen=alleen, alle=True)
        return lijst, traces.laagkeuzes(doc[0], lijst, info)


def test_lagen_kiezen_met_legenda():
    from georeferentie import traces
    # case 005: de vervallen huisaansluiting heet in de legenda "Verwijderen Aansluitleiding / Drinkwaterleiding"
    # (de legenda gebruikt een andere laag in dezelfde kleur); bestaande leidingen staan uit
    lijst, keuzes = _keuzes_van("Case 005 DW A2 werktekening 1-200.pdf", "DW")
    aan = [k for k in keuzes if k.standaard]
    assert [k.naam for k in aan] == ["Verwijderen Aansluitleiding / Drinkwaterleiding"]
    assert aan[0].uit_legenda and aan[0].voorbeeld[:4] == b"\x89PNG"
    assert "K 35" in aan[0].eigenschappen
    assert any(k.naam.startswith("Bestaande") and not k.standaard for k in keuzes)
    # de aangevinkte tracés zijn dezelfde als zonder keuzelijst
    gekozen = traces.gekozen_traces(keuzes, {aan[0].sleutel})
    assert {t.shapefile for t in gekozen} == {"Verwijderen_Aansluitleiding_Drinkwaterleiding"}
    assert abs(sum(t.lengte_m for t in gekozen) - sum(t.lengte_m for t in _traces_van(
        "Case 005 DW A2 werktekening 1-200.pdf", "DW"))) < 0.01
    # AW-tekening: legendanaam zonder statuswoord krijgt de status erbij
    lijst, keuzes = _keuzes_van("11.0019_WN_AW_TRP_PV_001_Werktekening.pdf", "AW")
    namen = {k.naam for k in keuzes if k.standaard}
    assert {"Rioolleiding DWA (nieuw)", "Rioolleiding DWA (vervallen)"} <= namen
    assert "Rioolleiding DWA (bestaand)" in {k.naam for k in keuzes if not k.standaard}
    assert len({k.bestand for k in keuzes}) == len(keuzes)
