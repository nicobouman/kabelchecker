"""Losse proef-app voor de georeferentie-module.

Starten:  streamlit run georeferentie_app.py
"""
import streamlit as st

from georeferentie.ui import georeferentie_paneel

st.set_page_config(page_title="Georeferentie tekening", layout="wide")

# online (Streamlit Cloud) hetzelfde wachtwoord als de Kabelchecker, uit st.secrets; lokaal geen wachtwoord
try:
    _juist = st.secrets.get("wachtwoord")
except Exception:
    _juist = None
if _juist and not st.session_state.get("ingelogd"):
    st.title("Tekening georefereren")
    with st.form("login"):
        _w = st.text_input("Wachtwoord", type="password")
        if st.form_submit_button("Inloggen", type="primary"):
            if _w == _juist:
                st.session_state["ingelogd"] = True
                st.rerun()
            st.error("Onjuist wachtwoord.")
    st.stop()
st.title("Tekening georefereren")
st.caption("Versie 0.6 — zelf kiezen welke lagen uit de tekening mee gaan in de download")
st.caption("Zet punt 1 op de tekening (links), dan hetzelfde punt op de kaart (rechts), dan punt 2, enz. "
           "Scrollen is in- en uitzoomen, slepen is verschuiven. Een punt kun je achteraf verslepen.")
tr = georeferentie_paneel(key="georef")
