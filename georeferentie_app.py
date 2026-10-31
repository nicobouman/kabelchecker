"""Losse proef-app voor de georeferentie-module.

Starten:  streamlit run georeferentie_app.py
"""
import streamlit as st

from georeferentie.ui import georeferentie_paneel

st.set_page_config(page_title="Georeferentie tekening", layout="wide")
st.title("Tekening georefereren")
st.caption("Versie 0.3 — BGT, zwarte overlay, coördinaten uit tekening, cyaan adresstip")
st.caption("Zet punt 1 op de tekening (links), dan hetzelfde punt op de kaart (rechts), dan punt 2, enz. "
           "Scrollen is in- en uitzoomen, slepen is verschuiven. Een punt kun je achteraf verslepen.")
tr = georeferentie_paneel(key="georef")
