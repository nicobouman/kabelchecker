# Kabelchecker 4.0

Toetst kabel- en leidingtracés aan de Waterschapsverordening AGV (art. 2.15 en 3.14-3.18).

- `kabelchecker_app_v4.py`: de Streamlit-app (startbestand)
- `kabelchecker_v4_engine.py`: de rekenkern; `python kabelchecker_v4_engine.py --test` draait de testgevallen
- `regeltemplate_v4_AGV.xlsx`: de regels; `bron/` bevat de bron waaruit het template wordt gebouwd
- `data_AGV/`: zones, referentielijnen en kruinen uit de legger van AGV

Online staat de app achter een wachtwoord. Dat wachtwoord staat in de Secrets van Streamlit Cloud (`wachtwoord = "..."`), niet in deze repository.

## Georeferentie (in ontwikkeling)

Voor tekeningen zonder coördinaten: links de tekening, rechts de PDOK-luchtfoto in RD. Zet punt 1 op de tekening, dan op de luchtfoto, dan punt 2, enz. (minimaal 3). Per punt zie je de afwijking; boven 50 cm kleurt die rood.

- `georeferentie_app.py`: losse proef-app (`streamlit run georeferentie_app.py`)
- `georeferentie/`: de module. `ui.georeferentie_paneel()` is het onderdeel voor in de app en geeft een `Transformatie` terug (tekening-pt naar RD), met `naar_rd()` en `transformeer_geometrie()` voor de latere stap naar een shapefile.
- Download: GeoTIFF (EPSG:28992) en `_transformatie.json`
- Tests: `python -m pytest tests`
