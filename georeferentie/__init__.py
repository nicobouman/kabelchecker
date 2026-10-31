"""Georeferentie van tekeningen zonder coordinaten (RD, EPSG:28992).

- kern: transformatie uit paspunten, restfouten, world file
- tekening: PDF/afbeelding inlezen, GeoTIFF wegschrijven
- pdok: adres zoeken via de PDOK Locatieserver
- traces: leidingen uit de PDF-lagen halen en als shapefiles per soort wegschrijven
- ui: het Streamlit-onderdeel met de twee vensters (importeer apart, vraagt streamlit)
"""
from .kern import Paspunt, Transformatie, bereken  # noqa: F401
