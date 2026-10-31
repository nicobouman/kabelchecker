# Kabelchecker 4.1

Toetst kabel- en leidingtracés aan de Waterschapsverordening AGV (art. 2.15 en 3.14-3.18).

- `kabelchecker_app_v4.py`: de Streamlit-app (startbestand)
- `kabelchecker_v4_engine.py`: de rekenkern; `python kabelchecker_v4_engine.py --test` draait de testgevallen
- `regeltemplate_v4_AGV.xlsx`: de regels; `bron/` bevat de bron waaruit het template wordt gebouwd
- `data_AGV/`: zones, referentielijnen en kruinen uit de legger van AGV
- `test_opsplitsen.py`: testgevallen voor het opsplitsen in sub-tracés (scenario 1-6 met een fictieve kering); `python test_opsplitsen.py`

## Opsplitsen in sub-tracés

De rekenkern (`splits_traces`) neemt alle lijnen van een upload samen en deelt ze op in sub-tracés:

- knippen alleen bij een wissel van materiaal of diameter, bij een aftakking en aan begin en eind van een boring of mantelbuis; een zonegrens of bocht is geen knip;
- delen buiten alle zones vallen af;
- elk sub-tracé wordt getoetst op de zwaarste zone die het raakt (kernzone, dan beschermingszone, dan buitenbeschermingszone) en krijgt haaks of evenwijdig als kenmerk;
- stukjes korter dan `KORT_STUK_M` (5 m) zonder andere zone gaan op in de tak waar ze aan vastzitten, behalve naast een boring of mantelbuis;
- elke boring is een eigen sub-tracé (herkend aan termen als gestuurde boring, boogzinker, nano-drill, persing, raketboring); alle mantelbuizen samen zijn één sub-tracé;
- huis-, perceel- en kolkaansluitingen (label met "aansluit", of tot 63 mm en korter dan 30 m) horen bij het sub-tracé waar ze aan vastzitten; zit een aansluiting nergens aan vast, dan bij het dichtstbijzijnde sub-tracé binnen `HA_ZOEKAFSTAND_M` (25 m);
- kruimels (lijntjes van hooguit `KRUIMEL_M`, 2 m, groot, zoals een putsymbool) zijn geen knip of aftakking.

Online staat de app achter een wachtwoord. Dat wachtwoord staat in de Secrets van Streamlit Cloud (`wachtwoord = "..."`), niet in deze repository.

## Georeferentie (in ontwikkeling)

Voor tekeningen zonder coördinaten: links de tekening, rechts een PDOK-kaart in RD (standaard BGT, luchtfoto en BRT kiesbaar). Straat zoeken vult aan tijdens het typen; huisnummer is een apart veld. Staan er RD-coördinaten op de tekening (X=... Y=...), dan worden die automatisch als paspunten gebruikt. Zet punt 1 op de tekening, dan op de luchtfoto, dan punt 2, enz. (minimaal 3). Per punt zie je de afwijking; boven 50 cm kleurt die rood.

- `georeferentie_app.py`: losse proef-app (`streamlit run georeferentie_app.py`)
- `georeferentie/`: de module. `ui.georeferentie_paneel()` is het onderdeel voor in de app en geeft een `Transformatie` terug (tekening-pt naar RD), met `naar_rd()` en `transformeer_geometrie()` voor de latere stap naar een shapefile.
- Download: GeoTIFF (EPSG:28992) en `_transformatie.json`
- Tracés als shapefile (`georeferentie/traces.py`): bij een AutoCAD-PDF met lagen haalt de tool de nieuwe en vervallen leidingen uit de laagnamen (NLCS) en maakt één shapefile per soort: `nieuw_DWA`, `nieuw_HWA`, `nieuw_drinkwater`, ..., plus `vervallen` (riolering) of `verwijderen` (drinkwater). Alleen het kaartvenster waarin de paspunten liggen; legenda, details, bestaande leidingen en kabels van anderen gaan niet mee. Huis- en kolkaansluitingen zitten in de shapefile van hun leiding. Kolommen: status, soort, functie, type, aanleg (open/boogzinker/...), materiaal, diameter, label, lengte, BOB. De zip gaat zo de Kabelchecker in.
- Tests: `python -m pytest tests`
