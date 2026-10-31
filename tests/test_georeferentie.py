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
