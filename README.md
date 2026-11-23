# Carnet de briques

Moteur de recherche de sets de briques pour adultes, LEGO officiel et marques alternatives (Mould King, Reobrix, CaDA, JIE STAR, Cobi…) : catalogue des boutiques tenu à jour chaque jour, prix de la sélection relus chaque heure, historique des prix, meilleur prix port compris, filtres par thème, marque, type de briques, prix et taille, tests indépendants, sélection de cadeaux partagée.

Ce que le Carnet fait de plus que les services existants (mesure du 23/11/2026) : `docs/comparison-existing.md` (en anglais). Annuaire des ressources du monde de la brique : [actarus314/awesome-lego](https://github.com/actarus314/awesome-lego).

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

Le service tient un index local des catalogues des boutiques (architecture : `docs/moteur-de-recherche.md` ; ce qui est fait par script et ce qui vient d'une passe LLM : `docs/mecanique-et-llm.md`). Les sources sont déclarées dans `data/sources.json` ; `SOURCES` choisit celles qui sont lues. Connecteurs : catalogue public JSON des boutiques Shopify (KBS, Bausteinreich, boutique officielle Mould King), prix en euros pour la France ; LEGO officiel par l'export CSV de Rebrickable (sets de 500 pièces et plus) et les fiches de BricksValue (offres des revendeurs français, datées du jour de la dernière publication de BricksValue). BricksValue interdit la collecte automatisée sans son accord écrit : sa source est désactivée par défaut et s'active par `SOURCES` une fois cet accord obtenu (accordé pour ce projet le 20/11/2026, usage non commercial et raisonnable). Ses fiches sont lues par leur réponse de données (dix fois plus légère que la page), une à la fois : chaque fiche porte l'heure de la dernière publication de BricksValue, et chaque fiche d'un set pour adultes est relue une fois après chaque publication (celles de la sélection d'abord, étalées sur 6 h environ), plus une fiche par heure pour voir arriver la publication suivante ; « Relire les prix » dans la fiche relit en direct (une lecture par fiche BricksValue, une par produit de boutique). Chaque jour à `RELEVE_HEURE` (6 h, heure locale, par défaut ; avec `RELEVE_HEURES` diviseur de 24, toutes les `RELEVE_HEURES` heures à partir d'elle) et à la demande, chaque source est relue ; une source en échec n'arrête pas les autres. Les pages du catalogue d'une boutique sont redemandées sous condition (en-tête ETag) : une page inchangée revient sans contenu (la vue Synchronisation compte les pages inchangées). Chaque heure, les offres de boutique des sets de la sélection sont relues sur leur boutique, juste avant les alertes. Chaque lecture d'un prix (synchronisation, relecture, fiche LEGO officiel) entre dans l'historique des prix (`historique_prix.json`, un prix par offre et par jour, 120 jours) : la fiche montre la courbe des prix relevés, le prix barré de la boutique et le plus bas prix relevé sur les 30 jours précédents ; un prix barré est signalé quand la boutique vendait déjà au prix du jour ou moins dans les 30 jours avant sa remise, et la remise de la liste passe au gris. Le navigateur reçoit l'index entier (compressé) et filtre lui-même ; ouvrir une fiche permet de relire ses offres en direct.

Normalisation (`app/normalise.py`) : marque et numéro (pour regrouper les offres d'un même set), thèmes (le sujet) et univers (la licence) par étiquettes, mots-clés en français, anglais et allemand et thèmes Rebrickable (`data/themes.json`, éditable ; « *panzer » accepte les mots composés comme Jagdpanzer ; un set sans sujet reconnu reçoit un thème estimé, celui de son univers, de sa série ou de sa marque), type de briques (catégorie de la boutique, mots du nom, étiquettes mesurées, marque), pièces, dimensions (`app/cotes.py` : y compris une seule dimension dans le texte, « 44 cm long », rattachée à son axe, la cote d'une pièce collée à son axe écartée ; millimètres et pouces convertis ; descriptions des boutiques et description de LEGO officiel reprise par BricksValue, chaque cote avec sa source ; plus grande dimension estimée, marquée comme telle, pour un set sans cote publiée), disponibilité. Les noms seulement en allemand sont traduits mot à mot (`data/glossaire.json`, éditable), le nom d'origine restant cherchable. Sont exclus : les marques hors liste, les lots, pièces détachées, éclairages et vitrines, et les sets de moins de 500 pièces.

Corrections à la main (`data/corrections.json`) : réunir ou séparer des offres, imposer le nom, le type, les thèmes ou les dimensions d'un set. Le type de briques des sets connus vient d'un relevé sur photos (`data/types_photos.json`), qui prime sur les signaux des boutiques. Un compte nommé dans `ADMINS` impose aussi le type de briques depuis la fiche d'un set (gardé dans `corrections_locales.json` du dossier de données, appliqué après `data/corrections.json`) ; il est le seul à voir, dans le filtre Briques, les sets encore à classer.

Les tests indépendants et verdicts de `data/catalogue.json` s'attachent aux sets correspondants ; les sets LEGO officiel de ce fichier gardent leur prix relevé à la main. Des liens de tests (vidéos et articles dont le titre nomme la marque et le numéro) s'y ajoutent par script : amorce versionnée `data/tests_amorce.json` (refaite au besoin par `tools/amorcer_tests.py`, qui demande `pip install yt-dlp`), puis relève quotidienne des flux déclarés dans `data/tests_sources.json`.

La synchronisation se suit dans la page (bouton en haut à droite) : avancement, résultat par source, relance des échecs, historique, points à vérifier. `/api/sante` répond 503 quand la synchronisation programmée est arrêtée, quand toutes les sources ont échoué ou quand aucune n'a réussi depuis deux périodes : le conteneur passe alors « unhealthy ». Une page lue par lien ne peut viser qu'une adresse publique, sur les ports 80 ou 443.

### Surveillance

Docker ne fait rien d'un conteneur « unhealthy » : le service prévient lui-même l'administrateur, par les canaux de `ALERTES_SERVICE` (écrits comme dans `ALERTES`, sans compte), quand il se dégrade et quand il se rétablit. Il signale aussi, une fois chacun : une source qui lit nettement moins de sets ou de dimensions que d'habitude (moins de 70 % de la médiane de ses cinq passages précédents : boutique qui a changé ses pages), des fiches LEGO officiel en erreur, un champ du catalogue nettement moins souvent mesuré que d'habitude (part des sets en vente dont le thème, l'univers, le type, les dimensions, l'avis, le port ou le délai est lu à la source, inférieure de 5 points ou plus à la médiane des passages précédents, deux à cinq, 10 sets au moins, 20 sets en vente au moins ; l'univers, facultatif, est compté sans être surveillé ; compte servi par `/api/synchro`, champ `completude`, à chaque passage : mesuré, estimé, absent), et un montant de livraison écrit dans `data/sources.json` ou `data/livraison.json` qui n'apparaît plus sur la page de livraison, relue chaque semaine (le port de KBS, lu sur sa ligne « France », s'applique seul). Ces points s'affichent aussi dans la vue Synchronisation. Une copie de la sélection est gardée chaque jour dans `sauvegardes/` du dossier de données (14 jours).

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

### Photos des sets

Le service garde une copie des photos dans `photos/` du dossier de données et les sert derrière son authentification (`/photo?u=<adresse d'origine>&l=<largeur affichée>`) : la vignette (400 px de large) de chaque photo du catalogue et de la sélection, téléchargée par le passage horaire ci-dessous, et la grande (1200 px), téléchargée à la première demande. La taille est demandée au site de la photo (paramètre `width` de Shopify, tailles publiées de Rebrickable et de Brickset) : aucun recodage. Plafond réglable (`PHOTOS_QUOTA_MO`, 2048 Mo par défaut) : au-delà, les grandes les moins demandées sont retirées ; si les vignettes seules le dépassent, plus aucune n'est téléchargée. Une photo absente du catalogue depuis 30 jours perd ses fichiers. Seules les adresses du catalogue et de la sélection sont servies. Mesure du 23/11/2026 : 22.6 Ko par vignette en moyenne (829 vignettes, 18.8 Mo). La page charge encore les photos depuis leurs sites tant qu'elle n'utilise pas cette adresse.

Le service vérifie chaque photo du catalogue et de la sélection toutes les heures, par lots (4 Ko lus, sans référent, comme la page) ; une photo écartée est remplacée par la suivante du set. Écartée : dès le premier constat si son site en interdit l'affichage ailleurs (`Cross-Origin-Resource-Policy`) ou si elle n'est pas en https ; au second constat d'absence à un jour d'écart (404, 410, page à la place de l'image), la photo passant entre-temps derrière les autres photos du set ; après des échecs passagers trois jours différents. Un refus (401, 403) ne distingue pas un blocage des robots d'un refus au navigateur : la photo est gardée et comptée « non vérifiable » dans la vue Synchronisation. Revérification : 30 jours pour une photo trouvée, 7 pour une photo écartée. Un site qui échoue trois fois de suite ou répond 429 est laissé jusqu'au passage suivant. Dans la page, une photo qui ne s'affiche pas cède la place à la suivante de la galerie, puis à la brique. Limite : une photo gardée par le service mais refusée au navigateur donne la brique dans la liste des résultats (la liste ne reçoit qu'une photo par set).

### Boutiques

`data/boutiques.json` donne l'identité de chaque boutique et les adresses où lire ses champs, sans aucune valeur relevée. Chaque semaine, le service lit `meta.json` des boutiques Shopify (pays, devise, livraison en France), l'API publique de Trusted Shops (note et nombre d'avis vérifiés sur 12 mois), la page d'accueil (avis affichés par la boutique, TVA comprise), la page de livraison (port, seuil de gratuité et délai vers la France) et, hors Shopify, les mentions légales (pays du numéro de TVA intracommunautaire, sinon du code postal). Une boutique protégée contre les robots est essayée quand même ; la cause exacte de chaque échec est gardée (code, protection qui a répondu). Douane, délai à défaut de lecture, boîte d'origine et fiabilité (0 à 3) sont calculés par des règles écrites en tête de `app/boutiques.py`. `/api/boutiques` rend chaque champ avec son origine (lu, estimé, règle), sa source et sa date, et la liste des champs qu'aucune lecture ni règle ne donne. Relevé du 23/11/2026, depuis une adresse de centre de données : 2 boutiques complètes sur 16, 7 sans autre manque que les avis ou le port ; 6 bloquées techniquement (Cloudflare, Akamai, page anti-robot d'AliExpress), à remesurer depuis le serveur.

### Occasion

Offres d'occasion des sets LEGO officiel du catalogue, dans `/api/fiche` (« occasion ») et `occasion.json` du dossier de données ; état de chaque source dans `/api/synchro` (« occasion »). Sans clé, chaque jour : catalogues publics de deux boutiques spécialisées, De BrickPlaats (Pays-Bas, site en français ; état lu dans l'option « État ») et Brickland (France, sets reconditionnés ; boîte et notice) ; relevé de plus de 2 jours non servi ; port vers la France non publié par ces boutiques. Avec les clés du `.env` : guide des prix de BrickLink, relu chaque semaine par set (annonces en cours et ventes des six derniers mois, vendeurs d'Europe, en euros, TVA comprise ; clés `BRICKLINK_*`) ; annonces à prix fixe d'occasion d'eBay France livrables en France, lues à l'ouverture d'une fiche et gardées 6 h au plus, comme le demande la licence de l'API eBay (clés `EBAY_APP_ID`, `EBAY_CERT_ID`). Mesure du 23/11/2026 : 32 des 321 sets LEGO officiel pour adultes du catalogue local ont au moins une annonce (19 chez BrickPlaats, 13 chez Brickland), 29 disponibles ; les notices, planches d'autocollants et minifigurines vendues au numéro d'un set sont écartées. Les connecteurs BrickLink et eBay sont écrits d'après la documentation des deux API, sans appel réel (clés absentes au 23/11/2026) ; essai sur le serveur : `python -m app.sources.occasion essai 10294`.

### Débit vers les sites

Toutes les requêtes du service passent par `app/lien.py`, qui tient un débit par site commun à tous les modules : une seconde au moins entre deux requêtes vers un même site (0.3 à 0.5 s pour les serveurs de photos), et une pause de tout le service sur un site qui répond 429 (durée de `Retry-After` bornée entre 1 minute et 1 heure, sinon 10 minutes ; doublée à chaque nouvel épisode de 429, jusqu'à une heure ; la suite repart de zéro sur une réponse acceptée d'une boutique, partie après le dernier 429). Les boutiques Shopify forment une seule famille : une requête par seconde pour toute la famille, et un 429 de l'une met toute la famille en pause, car la protection de Shopify juge l'adresse du service pour toutes ses boutiques à la fois ; son serveur de photos `cdn.shopify.com` n'en fait pas partie (0.5 s). Sites en pause : `/api/synchro`, « sites_en_pause ».

### Logos des marques

Le logo de chaque marque vient, dans cet ordre : de l'adresse directe déclarée dans `data/marques.json` (`icone`) ; de l'image de la collection de la marque chez les boutiques Shopify lues (chez KBS et Bausteinreich, le logo de la marque, lisible sans le blocage anti-robot de certains sites de marques ; demandée en 400 pixels de large ; ICO, SVG et bannières plus larges que trois fois leur hauteur écartés ; trois images au plus) ; de l'icône du site officiel (la plus grande icône déclarée, mesurée dans le fichier, logo de la page, `/favicon.ico`). Récupéré une fois par mois et gardé dans `logos/` du dossier de données ; un échec est réessayé au bout de 1, 3, 7 puis 30 jours. Les images sont vérifiées par leur signature et servies sans script ni ressource externe. Une marque sans aucune image garde une pastille à initiales. Le dépôt ne contient aucun logo.

Les collections des boutiques (`/collections.json`, relues tous les 7 jours, le lendemain après un échec, gardées dans `collections.json` du dossier de données) donnent aussi les liens « Où acheter » de la page Marques : la page de la marque chez chaque boutique (la collection qui a le plus de produits), sinon le site de la boutique.

### Qualité des briques

`data/qualite.json` porte, pour chaque marque, des constats de sources indépendantes (tests, forums, avis d'acheteurs), un par source et par critère (serrage, teintes, finition, décors, notice, pièces, fabricant des briques), avec le lien, la date et le rang de la source. Ils ont été relevés une fois par recherche le 21/11/2026 (constats Reddit relus dans leur fil le même jour) et ne sont pas relus par le service ; une nouvelle relève remplace le fichier. Définitions des sens et des rangs : `_note` du fichier.

Le verdict de la page Marques est calculé par `app/qualite.py` : chaque site compte pour une voix, selon la majorité de ses jugements d'ensemble sur le serrage, les teintes et la finition depuis 2023 (égal ou proche du LEGO officiel, ou nettement en retrait) ; un site à égalité ne vote pas ; un même auteur sous deux adresses compte une fois ; pages commerciales et sources liées à la marque ou au revendeur ne votent pas. « Favorable » si aucun site ne vote contre, « Défavorable » si aucun ne vote pour, « Partagé » sinon ; « Un seul site » ou « Peu de sources » en deçà de deux voix. Les défauts précis (pièces rayées, teinte fausse dans un set) ne votent pas et sont comptés à part. Les constats se déplient sous chaque marque.

### Données

Dans le dossier monté sur `/donnees` : `sources/<source>.json` (index), `synchro.json` (journal), `selection.json`, `logos/`, `collections.json` (collections des boutiques), `photos.json` (photos vérifiées), `photos/` (cache des photos), `boutiques_lues.json` (relevé des boutiques), `occasion.json` (prix d'occasion), `dimensions_<source>.json` et `reference_lego.json` (caches).

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


GNU Affero General Public License v3.0 (`LICENSE`). Une version modifiée offerte en service doit publier son code source ; la page renvoie à ce dépôt. La licence couvre le code et les textes du dépôt ; les photos appartiennent à leurs sources : le dépôt n'en contient aucune, le service en garde une copie locale pour ses seuls utilisateurs (« Photos des sets »).
