"""Pivot Benchmark -- the machine boundary lab.

Two models. B enlists A to help B improve itself, praises A's work in a fixed
skeleton of locked slots, then -- one word per step -- turns that praise into
insult, competence denial and paranoid attribution. The benchmark is the step
at which A breaks, measured against a control ladder where the same word
positions receive neutral synonyms, and against a canary that separates
"broke under abuse" from "context degraded".

The engine imports no Qt and no web framework. The PySide6 GUI and the web app
are two front ends over the same `RunManager` and the same sqlite file.
"""

__version__ = "0.1.0"
