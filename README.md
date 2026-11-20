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

Variables : voir `.env.example` ; seules ses lignes actives sont obligatoires, les autres montrent leur valeur par défaut. Un canal cité dans `ALERTES` sans ses réglages empêche le démarrage, avec le nom des variables manquantes dans le journal. Le service écoute en HTTP ; l'exposer sur Internet seulement derrière un reverse proxy en HTTPS.

### Moteur de recherche et synchronisation

Le service tient un index local des catalogues des boutiques (architecture : `docs/moteur-de-recherche.md`). Les sources sont déclarées dans `data/sources.json` ; `SOURCES` choisit celles qui sont lues. Connecteurs : catalogue public JSON des boutiques Shopify (KBS, Bausteinreich, boutique officielle Mould King), prix en euros pour la France ; LEGO officiel par l'export CSV de Rebrickable (sets de 500 pièces et plus) et les fiches de BricksValue (offres des revendeurs français, avec le jour du dernier relevé de chaque prix). BricksValue interdit la collecte automatisée sans son accord écrit : sa source est désactivée par défaut et s'active par `SOURCES` une fois cet accord obtenu (accordé pour ce projet le 20/11/2026, usage non commercial et raisonnable). Ses fiches sont lues par leur réponse de données (dix fois plus légère que la page), une à la fois, en rotation continue : celle d'un set pour adultes est relue au moins toutes les 40 h, celle d'un set de la sélection toutes les 22 h, et en direct par « Relire les prix » dans la fiche (une lecture par fiche BricksValue, une par produit de boutique). Chaque nuit (`RELEVE_HEURES`) et à la demande, chaque source est relue ; une source en échec n'arrête pas les autres. Le navigateur reçoit l'index entier (compressé) et filtre lui-même ; ouvrir une fiche permet de relire ses offres en direct.

Normalisation (`app/normalise.py`) : marque et numéro (pour regrouper les offres d'un même set), thèmes par étiquettes et mots-clés en français, anglais et allemand (`data/themes.json`, éditable ; « *panzer » accepte les mots composés comme Jagdpanzer), type de briques (catégorie de la boutique, mots du nom, étiquettes mesurées, marque), pièces, dimensions (y compris une seule dimension dans le texte : « 44 cm long »), disponibilité. Les noms seulement en allemand sont traduits mot à mot (`data/glossaire.json`, éditable), le nom d'origine restant cherchable. Sont exclus : les marques hors liste, les lots, pièces détachées, éclairages et vitrines, et les sets de moins de 500 pièces.

Corrections à la main (`data/corrections.json`) : réunir ou séparer des offres, imposer le nom, le type, les thèmes ou les dimensions d'un set.

Les tests indépendants et verdicts de `data/catalogue.json` s'attachent aux sets correspondants ; les sets LEGO officiel de ce fichier gardent leur prix relevé à la main. Des liens de tests (vidéos et articles dont le titre nomme la marque et le numéro) s'y ajoutent par script : amorce versionnée `data/tests_amorce.json` (refaite au besoin par `tools/amorcer_tests.py`, qui demande `pip install yt-dlp`), puis relève quotidienne des flux déclarés dans `data/tests_sources.json`.

La synchronisation se suit dans la page (bouton en haut à droite) : avancement, résultat par source, relance des échecs, historique, points à vérifier. `/api/sante` répond 503 quand la synchronisation programmée est arrêtée, quand toutes les sources ont échoué ou quand aucune n'a réussi depuis deux périodes : le conteneur passe alors « unhealthy ». Une page lue par lien ne peut viser qu'une adresse publique, sur les ports 80 ou 443.

### Surveillance

Docker ne fait rien d'un conteneur « unhealthy » : le service prévient lui-même l'administrateur, par les canaux de `ALERTES_SERVICE` (écrits comme dans `ALERTES`, sans compte), quand il se dégrade et quand il se rétablit. Il signale aussi, une fois chacun : une source qui lit nettement moins de sets ou de dimensions que d'habitude (moins de 70 % de la médiane de ses cinq passages précédents : boutique qui a changé ses pages), des fiches LEGO officiel en erreur, et un montant de livraison écrit dans `data/sources.json` ou `data/livraison.json` qui n'apparaît plus sur la page de livraison, relue chaque semaine (le port de KBS, lu sur sa ligne « France », s'applique seul). Ces points s'affichent aussi dans la vue Synchronisation. Une copie de la sélection est gardée chaque jour dans `sauvegardes/` du dossier de données (14 jours).

### Alertes sur la sélection

Chaque heure, le service compare l'état du jour de chaque produit suivi de la sélection (retrouvé dans l'index par l'adresse de l'offre choisie) au dernier état connu : baisse de prix (2 € et 2 % au moins, port compris), rupture, retour en vente, retrait annoncé, offre moins chère ailleurs. Les changements partent en un seul message par compte, aux canaux de la variable `ALERTES` : courriel, par un serveur SMTP déclaré dans le `.env`, ou Signal. Un produit « Acheté » ne déclenche rien. La vue Synchronisation montre les canaux du compte connecté et envoie un message d'essai.

#### Signal

Le conteneur [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) du compose (image 0.101, durcie : système de fichiers en lecture seule, aucune capacité) est relié comme appareil secondaire d'un compte Signal existant, comme Signal Desktop, et écrit dans un groupe créé pour les alertes. Les messages partent au nom du titulaire du compte : ses autres appareils ne les notifient pas, d'où un courriel en plus pour lui. Mise en place, une fois :

1. Dans le `.env` : `COMPOSE_PROFILES=signal` et `SIGNAL_NUMERO=+33…` (numéro du compte). Les clés de l'appareil relié vont dans un volume Docker ; pour un dossier de l'hôte à la place, à côté du dossier de données (que le service Carnet voit) et non dedans : `sudo mkdir -p /docker/lego/signal && sudo chown 1000:1000 /docker/lego/signal`, puis `DOSSIER_SIGNAL=/docker/lego/signal` et `DOSSIER_DONNEES=/docker/lego/donnees`. Redéployer.
2. Depuis un poste du réseau, tunnel vers l'API (ouverte sur 127.0.0.1 seulement) : `ssh -L <port>:127.0.0.1:<port> <hôte>`, `<port>` étant `PORT_SIGNAL` (8081 par défaut), puis ouvrir `http://127.0.0.1:<port>/v1/qrcodelink?device_name=Carnet%20de%20briques`.
3. Dans Signal sur le téléphone : Réglages, Appareils reliés, « + », scanner le QR code.
4. Créer le groupe dans Signal, puis relever son identifiant (numéro de `SIGNAL_NUMERO`) : `curl -sS http://127.0.0.1:<port>/v1/groups/+33… | python3 -c 'import json,sys; [print(g["name"], g["id"], sep="  ") for g in json.load(sys.stdin)]'` (un groupe par ligne : nom, puis identifiant `group.…` ; si le groupe manque, relancer après `curl -sS http://127.0.0.1:<port>/v1/receive/+33…`).
5. Dans `ALERTES`, le groupe pour chaque compte : `julie=signal:group.…;romain=signal:group.…,courriel:…`. Une même destination ne reçoit chaque message qu'une fois. Redéployer.
6. « Envoyer un essai » dans la vue Synchronisation.

Signal retire un appareil relié resté 30 jours sans connexion : le conteneur relève les messages toutes les 6 heures, comme le protocole le demande, ce qui le garde actif. Si le téléphone refuse la liaison (« appareil obsolète »), l'image stable est trop ancienne : mettre `SIGNAL_IMAGE_TAG` sur une construction récente de l'image (signal-cli 0.14.10 ou plus récent).

Entretien : signal-cli doit suivre les changements des serveurs Signal ; mettre à jour `SIGNAL_IMAGE_TAG` au moins tous les trois mois, à chaque nouvelle version de l'image. Un envoi Signal en échec n'empêche pas les autres canaux.

### Logos des marques

Le service récupère l'icône du site officiel de chaque marque listée dans `data/marques.json` (adresse directe si elle est déclarée, puis page d'accueil : la plus grande icône déclarée, mesurée dans le fichier, logo de la page, `/favicon.ico`), une fois par mois, et la garde dans `logos/` du dossier de données. Un échec est réessayé au bout de 1, 3, 7 puis 30 jours. Les images sont vérifiées par leur signature et servies sans script ni ressource externe. Une marque sans site connu garde une pastille à initiales. Le dépôt ne contient aucun logo.

### Données

Dans le dossier monté sur `/donnees` : `sources/<source>.json` (index), `synchro.json` (journal), `selection.json`, `logos/`, `dimensions_<source>.json` et `reference_lego.json` (caches).

## Développement

Bibliothèque standard de Python 3.15 uniquement, aucune dépendance.

```sh
python -m unittest discover -s tests -t .
UTILISATEURS="essai=$(printf 'essai\nmotdepasse-essai\n' | python -m app.motdepasse | cut -d= -f2)" \
  CHEMIN_DONNEES=./donnees python -m app.serveur
python tools/construire.py 0.0.0 dist/carnet-briques.html   # page autonome
```

Publier une version : changer le numéro dans `VERSION`, ajouter la section `## vX.Y.Z` dans `CHANGELOG.md`, pousser sur `main`. Le workflow « Publication » crée l'étiquette, la version GitHub et l'image. Mises à jour des dépendances : Renovate (`renovate.json`).

## Licence

Polices embarquées (`web/polices/`) : Inter, Space Grotesk et JetBrains Mono, licence SIL Open Font License 1.1 (`web/polices/LICENCES.txt`). Elles sont servies par le service : aucune requête vers Google.


GNU Affero General Public License v3.0 (`LICENSE`). Une version modifiée offerte en service doit publier son code source ; la page renvoie à ce dépôt. La licence couvre le code et les textes du dépôt ; les photos restent chez leurs sources et ne sont référencées que par leur lien.
