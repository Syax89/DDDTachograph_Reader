"""Accesso condiviso ai file DDD reali di esempio.

I file in ``DDD/`` contengono dati personali (nomi conducenti, numeri carta, VIN)
e sono volutamente esclusi dal versionamento (vedi ``.gitignore``). I test che li
richiedono devono **skippare** in modo pulito quando la cartella non è presente
(es. in CI), invece di fallire.
"""
import os
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")


def real_ddd_files():
    """Percorsi dei file .ddd reali presenti, lista vuota se DDD/ è assente."""
    if not os.path.isdir(DDD_DIR):
        return []
    return [os.path.join(DDD_DIR, n) for n in sorted(os.listdir(DDD_DIR))
            if n.lower().endswith(".ddd")]


HAS_REAL_FILES = bool(real_ddd_files())

requires_real_files = unittest.skipUnless(
    HAS_REAL_FILES,
    "file DDD reali assenti (DDD/ è git-ignored: contiene dati personali)")
