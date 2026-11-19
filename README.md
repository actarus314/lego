# Carnet de briques

Outil de choix de sets de briques pour adultes, LEGO officiel et marques alternatives (Mould King, Reobrix, CaDA, Bole Brick…) : catalogue avec photos, taille, avis de testeurs indépendants, boutiques et marques, sélection de cadeaux.

Deux façons de l'utiliser :

| | Page autonome | Service |
|---|---|---|
| Forme | un fichier HTML, à ouvrir dans un navigateur | conteneur Docker |
| Prix | ceux du catalogue au jour de la version | relevés à la source chaque jour et à la demande |
| Sélection | gardée dans le navigateur, copier-coller pour la transmettre | partagée entre les comptes, achats masqués aux comptes choisis |
| Ajout par lien | nom deviné depuis l'adresse | nom, prix, photo et pièces lus sur la page |

La page autonome est jointe à chaque [version](https://github.com/actarus314/lego/releases).

## Service

Image : `ghcr.io/actarus314/lego` (amd64 et arm64), publiée à chaque nouvelle version.

1. Récupérer `compose.yaml` et `.env.example` (dépôt ou version), copier `.env.example` en `.env`.
2. Créer une empreinte par compte et la reporter dans `UTILISATEURS` (`nom=empreinte;nom2=empreinte2`) :
   ```sh
   docker run --rm -it ghcr.io/actarus314/lego python -m app.motdepasse
   ```
3. `docker compose up -d`, puis ouvrir `http://<hôte>:<PORT_HOTE>`.

Variables : voir `.env.example`. Le service écoute en HTTP ; l'exposer sur Internet seulement derrière un reverse proxy en HTTPS.

### Relevé des prix

Le relevé lit chaque set à la source : catalogue public des boutiques Shopify (KBS, par exemple), sinon les métadonnées de la page (JSON-LD, Open Graph). Les sites qui refusent les robots, dont LEGO.com, gardent le prix du catalogue. Une page lue par lien ne peut viser qu'une adresse publique : les adresses du réseau local, de bouclage ou réservées sont refusées, à chaque redirection.

Le relevé se suit dans la page (bouton en haut à droite) : avancement, résultat de chaque set (lu, échec et sa raison, sauté), relance des seuls échecs, historique des 30 derniers relevés. Les sites qui refusent les robots, dont LEGO.com, sont sautés sans être interrogés. `/api/sante` répond 503 quand le relevé programmé est arrêté, quand le dernier relevé complet n'a lu aucun set ou quand aucun relevé n'a réussi depuis deux périodes : le conteneur passe alors « unhealthy ». Le journal du conteneur trace chaque relevé et chaque échec.

### Données

Le catalogue est dans l'image (`data/catalogue.json`) ; les relevés et la sélection sont dans le dossier monté sur `/donnees` (`releves.json`, `selection.json`).

## Développement

Bibliothèque standard de Python 3.15 uniquement, aucune dépendance.

```sh
python -m unittest discover -s tests -t .
UTILISATEURS="essai=$(printf 'essai\nmotdepasse-essai\n' | python -m app.motdepasse | cut -d= -f2)" \
  DOSSIER_DONNEES=./donnees python -m app.serveur
python tools/construire.py 0.0.0 dist/carnet-briques.html   # page autonome
```

Publier une version : changer le numéro dans `VERSION`, ajouter la section `## vX.Y.Z` dans `CHANGELOG.md`, pousser sur `main`. Le workflow « Publication » crée l'étiquette, la version GitHub et l'image. Mises à jour des dépendances : Renovate (`renovate.json`).

## Licence

GNU Affero General Public License v3.0 (`LICENSE`). Une version modifiée offerte en service doit publier son code source ; la page renvoie à ce dépôt. La licence couvre le code et les textes du dépôt ; les photos restent chez leurs sources et ne sont référencées que par leur lien.
