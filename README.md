# Kabelchecker 4.0

Toetst kabel- en leidingtracés aan de Waterschapsverordening AGV (art. 2.15 en 3.14-3.18).

- `kabelchecker_app_v4.py`: de Streamlit-app (startbestand)
- `kabelchecker_v4_engine.py`: de rekenkern; `python kabelchecker_v4_engine.py --test` draait de testgevallen
- `regeltemplate_v4_AGV.xlsx`: de regels; `bron/` bevat de bron waaruit het template wordt gebouwd
- `data_AGV/`: zones, referentielijnen en kruinen uit de legger van AGV

Online staat de app achter een wachtwoord. Dat wachtwoord staat in de Secrets van Streamlit Cloud (`wachtwoord = "..."`), niet in deze repository.
