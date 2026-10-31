# Kabelchecker 4.0

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
- huisaansluitingen (label met "aansluit", of PE/koper tot 63 mm en korter dan 30 m) horen bij het sub-tracé waar ze aan vastzitten.

Online staat de app achter een wachtwoord. Dat wachtwoord staat in de Secrets van Streamlit Cloud (`wachtwoord = "..."`), niet in deze repository.
