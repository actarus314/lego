"""Calcule l'empreinte d'un mot de passe pour la variable UTILISATEURS.

    docker run --rm -it ghcr.io/actarus314/lego python -m app.motdepasse
"""
import getpass
import sys

from .acces import empreinte

if __name__ == "__main__":
    nom = input("Nom du compte : ").strip() if sys.stdin.isatty() else sys.stdin.readline().strip()
    mdp = getpass.getpass("Mot de passe : ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
    if not nom or "=" in nom or ";" in nom or len(mdp) < 10:
        sys.exit("Nom sans « = » ni « ; », mot de passe de 10 caractères au moins.")
    print(f"{nom}={empreinte(mdp)}")
