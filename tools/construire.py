#!/usr/bin/env python3
"""Construit la page autonome (un seul fichier HTML, sans serveur).

    python3 tools/construire.py [version] [sortie]
"""
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from app.serveur import injecter  # noqa: E402
from app.index import sets_hors_ligne  # noqa: E402
from app.normalise import themes_disponibles  # noqa: E402
from app.qualite import pour_la_page  # noqa: E402

version = sys.argv[1] if len(sys.argv) > 1 else "dev"
sortie = Path(sys.argv[2] if len(sys.argv) > 2 else RACINE / "dist" / "carnet-briques.html")
meta = json.loads((RACINE / "data" / "meta.json").read_text("utf-8"))
page = injecter((RACINE / "web" / "index.html").read_text("utf-8"),
                {"sets": sets_hors_ligne(), "themes": themes_disponibles(), "sources": []},
                {"serveur": False, "version": version, "catalogue_du": meta["releve_du"], "qualite": pour_la_page()}, "x")
page = re.sub(r'<script nonce="x">', "<script>", page)
sortie.parent.mkdir(parents=True, exist_ok=True)
sortie.write_text(page, "utf-8")
print(sortie)
