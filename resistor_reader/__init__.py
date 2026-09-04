"""Core package for the resistor reader project.

Submodules are deliberately *not* imported here: ``main.py`` on the appliance
imports only what it needs, and pulling OpenCV in at package-import time costs
noticeable startup on a Pi Zero.  Import stages explicitly, e.g.
``from resistor_reader import orchestrator``.
"""
