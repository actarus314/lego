"""Lecture des réglages : une variable absente ou vide prend la valeur par défaut du code.

Le compose transmet les réglages du service par leur seul nom : une ligne « NOM= » vide du .env
arrive vide, et vaut donc comme absente.
"""
from __future__ import annotations

import os


def reglage(nom: str, defaut: str = "") -> str:
    return (os.environ.get(nom) or "").strip() or defaut
