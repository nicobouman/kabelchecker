"""Tekening inlezen (PDF of afbeelding) en gegeorefereerd wegschrijven."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .kern import Transformatie

Image.MAX_IMAGE_PIXELS = None
MAX_ZIJDE_PX = 8000             # grens voor de weergave in de browser


@dataclass
class Weergave:
    """Een tekeningpagina als afbeelding. 1 pixel = pixel_in_pt PDF-punten."""
    png: bytes
    breedte: int
    hoogte: int
    pixel_in_pt: float
    paginas: int = 1
    pagina: int = 0


def aantal_paginas(data: bytes, naam: str) -> int:
    if not naam.lower().endswith(".pdf"):
        return 1
    import fitz
    with fitz.open(stream=data, filetype="pdf") as doc:
        return doc.page_count


def laad(data: bytes, naam: str, pagina: int = 0, dpi: int = 150) -> Weergave:
    """PDF-pagina renderen of afbeelding inlezen.

    Bij een PDF zijn tekeningcoordinaten PDF-punten van de weergegeven pagina.
    Bij een afbeelding geldt 1 pixel = 1 'pt' (er is geen papiermaat bekend)."""
    if naam.lower().endswith(".pdf"):
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            page = doc[pagina]
            zoom = dpi / 72
            r = page.rect
            zoom = min(zoom, MAX_ZIJDE_PX / max(r.width, r.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return Weergave(pix.tobytes("png"), pix.width, pix.height, 1 / zoom, doc.page_count, pagina)
    im = Image.open(io.BytesIO(data)).convert("RGB")
    f = 1.0
    if max(im.size) > MAX_ZIJDE_PX:
        f = max(im.size) / MAX_ZIJDE_PX
        im = im.resize((round(im.width / f), round(im.height / f)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "PNG")
    return Weergave(b.getvalue(), im.width, im.height, f)


def wit_transparant(im: Image.Image, versterking: float = 4.0, kleur=(0, 0, 0)) -> Image.Image:
    """Wit papier doorzichtig maken, zodat de kaart eronder zichtbaar blijft.

    Lijnen worden in één kleur gezet (standaard zwart,
    voor het beste contrast op de BGT). kleur=None houdt de kleuren van de tekening."""
    a = np.asarray(im.convert("RGB")).copy()
    alpha = np.clip((255 - a.min(2).astype(float)) * versterking, 0, 255).astype(np.uint8)
    if kleur is not None:
        a[:] = kleur
    return Image.fromarray(np.dstack([a, alpha]), "RGBA")


def noord_boven(w: Weergave, tr: Transformatie, pixel_m: float | None = None,
                max_zijde: int | None = None, transparant_wit: bool = False):
    """Tekening omzetten naar een noord-boven afbeelding in RD.

    Geeft (RGBA-afbeelding, (xmin, ymin, xmax, ymax), pixelgrootte in m)."""
    im = Image.open(io.BytesIO(w.png)).convert("RGBA")
    # pixel (kolom, rij) -> pt -> RD
    A = np.asarray(tr.A) * w.pixel_in_pt
    t = np.asarray(tr.t)
    hoeken = np.array([[0, 0], [w.breedte, 0], [0, w.hoogte], [w.breedte, w.hoogte]]) @ A.T + t
    xmin, ymin = hoeken.min(0); xmax, ymax = hoeken.max(0)
    if pixel_m is None:
        pixel_m = math.sqrt(abs(np.linalg.det(A)))      # zelfde detail als de bron
    if max_zijde:
        pixel_m = max(pixel_m, max(xmax - xmin, ymax - ymin) / max_zijde)
    nb, nh = math.ceil((xmax - xmin) / pixel_m), math.ceil((ymax - ymin) / pixel_m)
    # uitvoerpixel (i, j) -> RD (xmin + (i+.5)p, ymax - (j+.5)p) -> bronpixel
    Ai = np.linalg.inv(A)
    M = Ai @ np.array([[pixel_m, 0], [0, -pixel_m]])
    o = Ai @ (np.array([xmin + 0.5 * pixel_m, ymax - 0.5 * pixel_m]) - t) - M @ [0.5, 0.5]
    uit = im.transform((nb, nh), Image.AFFINE, (M[0, 0], M[0, 1], o[0], M[1, 0], M[1, 1], o[1]),
                       resample=Image.BILINEAR, fillcolor=(255, 255, 255, 0))
    if transparant_wit:   # na het verkleinen: veel sneller
        doorzichtig = wit_transparant(uit.convert("RGB"))
        alpha = np.minimum(np.asarray(doorzichtig)[..., 3], np.asarray(uit)[..., 3])
        uit = Image.fromarray(np.dstack([np.asarray(doorzichtig)[..., :3], alpha]), "RGBA")
    return uit, (float(xmin), float(ymax - nh * pixel_m), float(xmin + nb * pixel_m), float(ymax)), pixel_m


# ------------------------------------------------------------------ GeoTIFF
def _geotiff_tags(xmin: float, ymax: float, pixel_m: float) -> dict:
    from PIL.TiffImagePlugin import ImageFileDirectory_v2
    ifd = ImageFileDirectory_v2()
    ifd[33550] = (pixel_m, pixel_m, 0.0)                     # ModelPixelScale
    ifd.tagtype[33550] = 12
    ifd[33922] = (0.0, 0.0, 0.0, xmin, ymax, 0.0)             # ModelTiepoint
    ifd.tagtype[33922] = 12
    # GeoKeyDirectory: projected, PixelIsArea, EPSG:28992, meters
    ifd[34735] = (1, 1, 0, 4, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 28992, 3076, 0, 1, 9001)
    ifd.tagtype[34735] = 3
    return ifd


def geotiff(im: Image.Image, bounds, pixel_m: float) -> bytes:
    """Noord-boven afbeelding als GeoTIFF (EPSG:28992), opent direct in QGIS."""
    b = io.BytesIO()
    im.save(b, "TIFF", tiffinfo=_geotiff_tags(bounds[0], bounds[3], pixel_m), compression="tiff_deflate")
    return b.getvalue()


def png_met_wereldbestand(im: Image.Image, bounds, pixel_m: float) -> tuple[bytes, str]:
    b = io.BytesIO(); im.save(b, "PNG", optimize=True)
    pgw = "\n".join(f"{v:.6f}" for v in (pixel_m, 0, 0, -pixel_m,
                                          bounds[0] + pixel_m / 2, bounds[3] - pixel_m / 2)) + "\n"
    return b.getvalue(), pgw


PRJ_RD = ('PROJCS["Amersfoort / RD New",GEOGCS["Amersfoort",DATUM["Amersfoort",SPHEROID["Bessel 1841",'
          '6377397.155,299.1528128],TOWGS84[565.2369,50.0087,465.658,-0.406857,0.350733,-1.87035,4.0812]],'
          'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Oblique_Stereographic"],'
          'PARAMETER["latitude_of_origin",52.1561605555556],PARAMETER["central_meridian",5.38763888888889],'
          'PARAMETER["scale_factor",0.9999079],PARAMETER["false_easting",155000],'
          'PARAMETER["false_northing",463000],UNIT["metre",1]]')
