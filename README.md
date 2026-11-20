# Carnet de briques

Moteur de recherche de sets de briques pour adultes, LEGO officiel et marques alternatives (Mould King, Reobrix, CaDA, JIE STAR, Cobi…) : catalogue des boutiques tenu à jour chaque nuit, meilleur prix port compris, filtres par thème, marque, type de briques, prix et taille, tests indépendants, sélection de cadeaux partagée.

Deux façons de l'utiliser :

| | Page autonome | Service |
|---|---|---|
| Forme | un fichier HTML, à ouvrir dans un navigateur | conteneur Docker |
| Catalogue | 34 sets choisis, prix du jour de la version | tous les sets des boutiques synchronisées (environ 900) |
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

### Moteur de recherche et synchronisation

Le service tient un index local des catalogues des boutiques (architecture : `docs/moteur-de-recherche.md`). Les sources sont déclarées dans `data/sources.json` ; `SOURCES` choisit celles qui sont lues. Connecteurs : catalogue public JSON des boutiques Shopify (KBS, Bausteinreich, boutique officielle Mould King), prix en euros pour la France ; LEGO officiel par l'export CSV de Rebrickable (sets de 500 pièces et plus) et les fiches publiques de BricksValue (offres des revendeurs français). BricksValue interdit la collecte automatisée sans son accord écrit dans ses conditions : sa source est désactivée par défaut (`SOURCES` l'active). Ses fiches sont lues compressées, une à la fois, en rotation continue : celle d'un set pour adultes est relue au moins toutes les 48 h, celle d'un set de la sélection toutes les 24 h, et en direct à l'ouverture de la fiche. Chaque nuit (`RELEVE_HEURES`) et à la demande, chaque source est relue ; une source en échec n'arrête pas les autres. Le navigateur reçoit l'index entier (compressé) et filtre lui-même ; ouvrir une fiche permet de relire ses offres en direct.

Normalisation (`app/normalise.py`) : marque et numéro (pour regrouper les offres d'un même set), thèmes par étiquettes et mots-clés en français, anglais et allemand (`data/themes.json`, éditable), type de briques, pièces, dimensions, disponibilité. Sont exclus : les marques hors liste, les lots, pièces détachées, éclairages et vitrines, et les sets de moins de 500 pièces.

Les tests indépendants et verdicts de `data/catalogue.json` s'attachent aux sets correspondants ; les sets LEGO officiel de ce fichier gardent leur prix relevé à la main.

La synchronisation se suit dans la page (bouton en haut à droite) : avancement, résultat par source, relance des échecs, historique. `/api/sante` répond 503 quand la synchronisation programmée est arrêtée, quand toutes les sources ont échoué ou quand aucune n'a réussi depuis deux périodes : le conteneur passe alors « unhealthy ». Une page lue par lien ne peut viser qu'une adresse publique.

### Alertes sur la sélection

Chaque heure, le service compare l'état du jour de chaque produit suivi de la sélection (retrouvé dans l'index par l'adresse de l'offre choisie) au dernier état connu : baisse de prix (2 € et 2 % au moins, port compris), rupture, retour en vente, retrait annoncé, offre moins chère ailleurs. Les changements partent en un seul message par compte, aux canaux de la variable `ALERTES` : courriel, par un serveur SMTP déclaré dans le `.env`, ou Signal. Un produit « Acheté » ne déclenche rien. La vue Synchronisation montre les canaux du compte connecté et envoie un message d'essai.

#### Signal

Les messages partent d'un numéro dédié au service, par le conteneur [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) du compose (image 0.101, durcie : système de fichiers en lecture seule, aucune capacité). Il faut un numéro qui reçoit les SMS, distinct de celui des destinataires. Mise en place, une fois :

1. Dossier des clés du numéro, à l'utilisateur 1000 : `sudo mkdir -p /docker/lego/signal && sudo chown 1000:1000 /docker/lego/signal`.
2. Dans le `.env` : `COMPOSE_PROFILES=signal`, `DOSSIER_SIGNAL=/docker/lego/signal`, `SIGNAL_NUMERO=+33…` (numéro d'envoi) et le canal dans `ALERTES` (`romain=signal:+33…`, numéro du destinataire). Redéployer.
3. Captcha : ouvrir https://signalcaptchas.org/registration/generate.html dans un navigateur du même réseau, le résoudre, puis copier le lien du bouton « Open Signal » sans `signalcaptcha://`.
4. Inscription, sur l'hôte :
   `curl -X POST -H 'Content-Type: application/json' -d '{"captcha":"<valeur>"}' http://127.0.0.1:8081/v1/register/+33…`
5. Code reçu par SMS :
   `curl -X POST http://127.0.0.1:8081/v1/register/+33…/verify/<code>`
6. Nom affiché (facultatif) : `curl -X PUT -H 'Content-Type: application/json' -d '{"name":"Carnet de briques"}' http://127.0.0.1:8081/v1/profiles/+33…`
7. « Envoyer un essai » dans la vue Synchronisation. Le premier message arrive comme une demande de contact, à accepter.

Entretien : signal-cli doit suivre les changements des serveurs Signal ; mettre à jour `SIGNAL_IMAGE_TAG` au moins tous les trois mois, à chaque nouvelle version de l'image. Garder un courriel en second canal : un envoi Signal en échec n'empêche pas les autres.

### Logos des marques

Le service récupère l'icône du site officiel de chaque marque listée dans `data/marques.json` (page d'accueil : apple-touch-icon, puis la plus grande icône, puis `/favicon.ico` ; adresse directe quand le site refuse les robots), une fois par mois, et la garde dans `logos/` du dossier de données. Les images sont vérifiées par leur signature et servies sans script ni ressource externe. Une marque sans site connu garde une pastille à initiales. Le dépôt ne contient aucun logo.

### Données

Dans le dossier monté sur `/donnees` : `sources/<source>.json` (index), `synchro.json` (journal), `selection.json`, `logos/`, `dimensions_<source>.json` et `reference_lego.json` (caches).

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

Polices embarquées (`web/polices/`) : Inter, Space Grotesk et JetBrains Mono, licence SIL Open Font License 1.1 (`web/polices/LICENCES.txt`). Elles sont servies par le service : aucune requête vers Google.


GNU Affero General Public License v3.0 (`LICENSE`). Une version modifiée offerte en service doit publier son code source ; la page renvoie à ce dépôt. La licence couvre le code et les textes du dépôt ; les photos restent chez leurs sources et ne sont référencées que par leur lien.
