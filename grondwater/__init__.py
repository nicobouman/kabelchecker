"""Grondwater: indicatie van bemaling (debiet, waterbezwaar) en melding/vergunning bij het waterschap."""
from .kern import BODEMTYPEN, SCHEIDENDE_LAAG, Sleuf, bereken, totaal  # noqa: F401
from .regels import WATERSCHAPPEN, toets  # noqa: F401
