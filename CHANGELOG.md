# v3.x — Moteur de recherche : catalogues des boutiques et LEGO officiel tenus à jour en continu, meilleur prix, filtres toujours visibles, vues aux conventions communes.

## v3.19.2
- Serveur de photos de Shopify (`cdn.shopify.com`) sorti de la famille Shopify de la v3.19.1 : le 23/11/2026, il a servi 1031 photos sans un refus entre 7 h et 8 h pendant que les boutiques Shopify répondaient 429 ; sa propre file (0.5 s entre deux requêtes) remplace la file commune, et un 429 des boutiques ne suspend plus le cache des photos. Les boutiques Shopify gardent leur file et leur pause communes. Premier remplissage du cache des photos Shopify : de nouveau en un passage horaire.

## v3.19.1
- Boutiques Shopify, après des 429 sur toutes les boutiques Shopify à la fois depuis le serveur le 23/11/2026 (dernière synchronisation réussie : 22/11/2026, 6 h ; même client accepté depuis une autre adresse : c'est l'adresse du serveur que la protection de Shopify refuse) : les boutiques Shopify (sources, boutiques relevées par `meta.json`, De BrickPlaats, tout site qui répond « Powered-By: Shopify ») et `cdn.shopify.com` partagent une seule file, une requête par seconde pour toute la famille (avant : une par seconde et par boutique, cinq par seconde pour les photos), et une seule pause : un 429 de l'une arrête toute la famille ; chaque nouvel épisode de 429 double la pause (avec `Retry-After: 60` : 1, 2, 4… minutes ; une heure au plus ; les 429 des requêtes déjà parties ne la doublent pas), une réponse acceptée d'une boutique partie après le dernier 429 la remet à zéro (pas une photo du CDN, une redirection ni une erreur). La synchronisation Shopify n'attend plus une pause que si elle dure une minute au plus (deux avant). `sites_en_pause` de `/api/synchro` nomme la famille « shopify ». Coûts de la file commune : premier remplissage du cache des photos Shopify (1211 photos dans le catalogue local) en deux passages horaires au moins au lieu d'un ; tant qu'il n'est pas rempli, une vignette demandée par la page attend son tour (1 à 2 s chacune).

## v3.19.0
- Débit par site commun à tout le service (`app/lien.py`), après des 429 de KBS, Bausteinreich et Mould King officiel signalés le 23/11/2026 : chaque module avait sa pause, mais deux modules sur une même boutique s'additionnaient ; désormais une seconde au moins entre deux requêtes vers un même site, quel que soit le module (0.2 à 0.5 s pour les serveurs de photos), et un 429 met ce site en pause pour tout le service (durée de `Retry-After` bornée entre 1 minute et 1 heure, sinon 10 minutes), y compris pour les requêtes déjà en attente de leur tour, les requêtes pendant la pause échouant sans réseau ; chaque module reporte alors l'essai sans compter d'échec du site (photos retentées à la fin de la pause, boutiques une heure après, logos et pages de livraison au passage suivant ; la synchronisation Shopify n'attend la fin d'une pause que si elle dure deux minutes au plus) ; sites en pause dans `/api/synchro` (« sites_en_pause »).
- Boutiques : les boutiques protégées contre les robots sont de nouveau essayées chaque semaine (la v3.16.0 ne les essayait plus) et chaque échec garde sa cause exacte (code, protection : Cloudflare, défi anti-robot, Akamai ; page anti-robot servie à la place du contenu) ; boutiques hors Shopify lues par leurs pages : mentions légales (pays du numéro de TVA intracommunautaire, sinon préfixe de pays du code postal), page de livraison (port vers la France, seuil de gratuité, devise) ; une boutique qui ne livre pas la France a port, délai et douane « sans objet » par une règle, une place de marché « selon le vendeur » ; seuil de gratuité lu en euros (10 à 500 €) ; boutiques relues chaque semaine, une heure après si une lecture a buté sur une pause 429 ; mouldking.com retiré (domaine à vendre ; site officiel mouldkingcorp.com, déjà lu). Relevé du 23/11/2026 : LEGO (Danemark, 5.95 € sous 55 €), Galaxus (3.90 € sous 39 €), BlueBrixx (Allemagne, 9.95 € sous 99 €) passent de presque vides à complets hors avis ; 2 boutiques complètes sur 16, 7 sans autre manque que les avis ou le port ; MyGoBricks lue en partie (pas de `meta.json`) ; 6 bloquées techniquement depuis une adresse de centre de données (Cloudflare : Kaufland, YWOBB, Barweer, Chowbrick ; Akamai : maxibricks sur eBay ; AliExpress : redirections vers sa page anti-robot), à remesurer depuis le serveur. Avis Trustpilot : pages refusées aux robots (CloudFront 403), non lus. Limite connue : le numéro de TVA n'est lu que sous ses libellés précis (« VAT number », « N° TVA intracommunautaire », « USt-IdNr », « Umsatzsteuer-Identifikationsnummer »…) ; « VAT Reg No », « USt.-IdNr. », « TVA : », « BTW-nummer » ne le sont pas (une version plus large prenait téléphones et IBAN pour des numéros de TVA) ; validation par la somme de contrôle de chaque pays à venir.

## v3.18.0
- Thèmes : plus aucun set sans thème (« Autres » de la page). Correspondance des thèmes Rebrickable vers les thèmes du moteur pour LEGO officiel (Botanicals, LEGO Art, Architecture, Speed Champions…), mots-clés complétés (armes, chars, trains, animaux, bâtiments…), quatre thèmes ajoutés : Personnages et figurines, Art et mosaïques, Contes et fantastique, Objets et jeux. Un set dont aucun sujet n'est reconnu reçoit un thème estimé, marqué dans le champ `themes_estimes` du catalogue par sa méthode : thème par défaut de son univers, sinon celui de sa série (moitié au moins des sets, trois au moins), sinon le plus fréquent de sa marque. Mesure du 23/11/2026, catalogue local complet (toutes les sources, 412 fiches BricksValue lues) : 1002 sets, 0 sans thème, 24 thèmes estimés (20 LEGO officiel, 4 marques alternatives) ; sur les 412 sets LEGO officiel suivis par BricksValue (adultes ou non), 0 sans thème, 68 estimés (160 sans thème avant). 116 sets ont un univers.
- Univers (décision de Romain du 23/11/2026 : filtre à part) : nouveau champ `univers` des sets, la licence ou le monde de fiction (Star Wars, Harry Potter, Marvel, Pokémon, Pirates des Caraïbes… ; 48 univers dans `data/themes.json`), lu dans le chemin de thèmes Rebrickable et les mots du nom (noms d'engins et de personnages pour les marques alternatives, qui ne citent pas la licence : TIE Bomber, Black Pearl…) ; un set sans licence n'en a pas. Liste des univers servie par `/api/catalogue` (`univers`) ; affichage dans la page : plus tard. Thèmes et univers des offres LEGO officiel recalculés à chaque reconstruction depuis la référence Rebrickable ; un thème retiré, encore porté par une offre enregistrée, est ignoré. Apostrophes typographiques (’) ramenées à « ' » avant toute comparaison de mots.
- Retiré : le thème « Films, séries et jeux », qui mêlait licences et bateaux pirates (étiquette « movie and anime » de Mould King) ; ses sets gardent leur sujet et reçoivent leur univers. Mots retirés, devenus univers ou trop vagues : « star wars », « jedi », « eclipse », « monarch », « rover » (Aérospatial ; « AT-AT » passe à Militaire, « mars rover » et « lunar rover » remplacent « rover », qui classait le Land Rover Defender) ; « *tier » (Animaux : classait « Véhicule forestier »).
- Complétude : `/api/synchro` sert `completude`, compté à la fin de chaque synchronisation et noté dans son journal (avant le premier passage : compté sur le catalogue du moment) : `{"sets", "en_vente", "champs": {clé: {"libelle", "facultatif", "tous": {"mesure", "estime", "manque"}, "en_vente": {…}}}}`, pour les champs `theme`, `univers` (facultatif : un set sans licence n'en a pas), `type`, `dimensions`, `avis`, `port`, `delai`, sur tout le catalogue et sur les sets en vente ou en précommande. Sont comptés « estime » : un thème estimé, un type de briques donné par la règle de série (nouveau champ `type_estime` des sets, « série »), un port estimé ; les autres champs n'ont pas encore d'estimation. La surveillance prévient l'administrateur quand la part mesurée d'un champ autre que l'univers (sets en vente) baisse de 5 points ou plus par rapport à la médiane des passages précédents (deux à cinq, avec 20 sets en vente au moins), 10 sets au moins. Mesure du 23/11/2026 (catalogue local complet, 1002 sets dont 877 en vente ou en précommande), sets en vente mesurés : thème 853 + 24 estimés, univers 105, type de briques 872 + 2 estimés, dimensions 500, avis 325, port 569 + 263 estimés, délai 566, sur 877.

## v3.17.0
- Conventions d'interface (validées par Romain le 23/11/2026), Recherche, Sélection et fiche : un clic sur une ligne ouvre la fiche ; seule la fiche mène à une boutique ; même bloc de prix partout (prix port compris, prix et port, boutique et délai, pastilles) ; « Déconseillé » en rouge ; plus de « port non relevé », « délai non relevé », « non daté », « — » ni puce « Autres » (sets sans thème trouvés par la recherche) ; prix sans port connu dit « hors port » (revendeurs du LEGO officiel : 595 offres sur 2136 en local le 23/11, 309 fiches LEGO officiel lues sur 412).
- Recherche : colonnes Taille (cm et Petit, Moyen, Grand), Pièces, Prix, Avis (verdict des testeurs, sinon nombre de tests ; tri « Avis, du meilleur ») ; filtre LEGO officiel ou marques alternatives rétabli (retiré en v3.0.0) ; puces de marque à leur largeur, « LEGO officiel » en entier.
- Sélection : mêmes colonnes et même bloc de prix que la Recherche, plus le statut ; le nom n'ouvre plus le site de la boutique ; « Modifier » et « Retirer » passent dans la fiche ; un produit ajouté par lien a une fiche courte. Fiche : le meilleur prix est la première offre ; chaque offre porte le bloc de prix, le pays, le prix barré, la courbe et la date du relevé.

## v3.16.0
- Cache local des photos (lot B.3 de la refonte v4 ; décision du 23/11/2026 : vignettes et grandes photos à la demande) : vignette de 400 px de chaque photo du catalogue et de la sélection téléchargée par le passage horaire des photos (qui vaut alors vérification ; 1200 essais par passage au lieu de 400, premier remplissage en 6 h environ), grande de 1200 px à la première demande, servies par `/photo?u=…&l=…` derrière l'authentification ; taille demandée au site (Shopify, Rebrickable, Brickset), sans recodage ; plafond `PHOTOS_QUOTA_MO` (2048 Mo), grandes les moins demandées retirées d'abord ; fichiers d'une photo oubliée (30 jours hors catalogue) retirés ; une photo que le cache ne garde pas (trop lourde, format non gardé, disque plein) est vérifiée comme avant et n'est jamais écartée pour cela. Mesure : 22.6 Ko par vignette. La page charge encore les photos depuis leurs sites : elle passera par cette adresse au lot C ; état du cache dans `/api/synchro` (« photos », « cache »).
- Boutiques relevées par le service (lot B.2) : `data/boutiques.json` (identité, ce qu'il faut lire, aucune valeur ; nom et adresse des boutiques lues comme sources tirés de `data/sources.json`) ; relevé hebdomadaire de `meta.json` (Shopify), de l'API publique de Trusted Shops, de la page d'accueil et de la page de livraison, aucune requête vers les sites qui refusent les robots ; douane, délai à défaut, boîte d'origine et fiabilité par des règles écrites (`app/boutiques.py`) ; nouvelle route `/api/boutiques` (chaque champ avec son origine : lu, écrit, estimé ou règle ; sa source ; sa date ; champs manquants nommés). Relevé du 23/11/2026 : KBS et Bausteinreich complètes ; Mould King officiel (avis), CarBrick (port, avis ; ne livre que la Belgique, l'Allemagne et les Pays-Bas), AFOBrick et Joygobricks (port) à un ou deux champs près ; les 11 autres n'ont que le délai, la boîte d'origine et la fiabilité au plus (refus aux robots, ou boutique hors Shopify). Le tableau `BOUTIQUES` de la page reste affiché tant que le lot C2 ne le remplace pas.
- Occasion des sets LEGO officiel (lot B.1), dans `/api/fiche` (« occasion ») et `/api/synchro` (« occasion ») : sans clé, catalogues publics de De BrickPlaats (Shopify, Pays-Bas) et de Brickland (WooCommerce, France), lus une fois par jour au plus, port vers la France non publié par ces boutiques et dit comme tel (mesure du 23/11/2026 : 32 des 321 sets LEGO officiel pour adultes du catalogue local ont au moins une annonce, 29 disponibles ; notices, autocollants et minifigurines au numéro d'un set écartés) ; avec clés, guide des prix BrickLink chaque semaine (set inconnu noté « absent ») et annonces eBay France à l'ouverture d'une fiche, gardées 6 h au plus (licence de l'API eBay). Nouveaux réglages facultatifs `BRICKLINK_*`, `EBAY_APP_ID`, `EBAY_CERT_ID`. BrickLink et eBay écrits sans appel réel (clés absentes le 23/11/2026) : essai par `python -m app.sources.occasion essai <numéro>`. Évaluation des autres sources (anti-robot, clés, sites fermés) : `docs/moteur-de-recherche.md`.

## v3.15.2
- Fiche, « Rechercher des tests sur le web » : la recherche portait sur la marque et le numéro seul (avec sa lettre de variante, « 19014S »), restreinte aux résultats français ; elle porte désormais sur la marque, le numéro sans lettre de variante et le nom d'origine du set, sans filtre de région (essai du 22/11/2026 : deux tests vidéo en tête pour la pompe à béton Mould King 19014S).

## v3.15.1
- Documentation : `docs/mecanique-et-llm.md` dit ce que le service fait par script (tout ce qu'il calcule : il n'appelle aucun LLM) et quelles données viennent d'une passe LLM faite une fois (type sur photos, qualité des briques, verdicts des testeurs, fiches des boutiques et des marques, listes de mots), avec la date et le contrôle de chaque passe. Un test échoue si un fichier de `data/` n'y est pas classé ou si sa version n'est pas celle du dépôt.
- Page Marques : rapport au prix du LEGO officiel écrit à la main retiré de la table des marques (jamais affiché : la page le calcule sur l'index).

## v3.15.0
- Sélection relue chaque heure : les offres de boutique de chaque set suivi (pas seulement l'offre choisie) sont relues sur leur boutique juste avant la vérification des alertes, qui partent donc dans l'heure (avant : prix d'au plus 24 h). Vue Synchronisation : « Sélection relue ».
- Historique des prix (`historique_prix.json` du dossier de données) : prix, prix barré et disponibilité de chaque offre, un point par jour, 120 jours, alimenté par chaque lecture. Fiche : courbe des prix relevés, prix barré, plus bas prix relevé sur les 30 jours précédents (« sur N jours » tant que l'historique est plus court) ; un prix barré est signalé quand la boutique vendait déjà au prix du jour ou moins dans les 30 jours précédant sa remise (« déjà 150.00 € avant la remise » ; jugé seulement si l'historique remonte avant la remise). Liste : remise annoncée (« −8 % », au gris si douteuse) ou « Plus bas relevé » (7 jours d'historique au moins).
- Prix barré des boutiques Shopify lu (`compare_at_price`, mesure du 21/11/2026 : 18 offres sur 286 chez KBS, 41 sur 195 chez Bausteinreich, aucune chez Mould King officiel).
- Type de briques et thèmes des offres Shopify recalculés à chaque reconstruction depuis les signaux bruts gardés (catégorie, étiquettes, nom) : une règle changée s'applique sans attendre la synchronisation (offres enregistrées avant cette version : après la synchronisation suivante).
- LEGO officiel : la série quotidienne des prix a disparu des fiches BricksValue (constat du 21/11/2026), les offres LEGO officiel étaient « non datées » ; elles sont datées du jour de la dernière publication de BricksValue (`dateModified` de la page, le même pour toutes les fiches). Chaque fiche pour adultes est relue une fois après chaque publication (la sélection d'abord, étalées sur 6 h environ ; fiche en échec réessayée après 1 h, 6 h puis 24 h), puis une fiche par heure guette la suivante, au lieu de la rotation sur 40 h (N + 24 lectures par jour pour N fiches, contre 0.6 × N).
- Synchronisation à heure fixe (nouveau réglage `RELEVE_HEURE`, 6 h par défaut, heure locale, changements d'heure compris ; « aucune » : 24 h après la précédente, comme avant ; avec une heure, `RELEVE_HEURES` doit diviser 24 ou en être un multiple) ; un passage manqué, conteneur arrêté, est rattrapé au démarrage. Pages du catalogue des boutiques redemandées sous condition (ETag) : une page inchangée revient sans contenu (essai du 21/11/2026 : 13 pages sur 13 inchangées à une minute d'écart, 10.3 Mo évités) ; la vue Synchronisation compte les pages inchangées de chaque source.

## v3.14.0
- Type de briques corrigé : 103 sets à picots étaient classés Technic (voitures « Creative Idea » rangées par Mould King sous l'étiquette « Technic-Vehicles », trains motorisés, militaires classés « Technic set » par KBS). Étalon relevé sur les photos des produits (`data/types_photos.json`, 812 sets ; armes et horloges relues sur photos de détail), prioritaire sur les signaux des boutiques ; série comptée sur les seuls types sûrs ; signaux des boutiques mesurés contre cet étalon, les moins justes retirés (le mot « Technic » ne compte plus que dans le nom du produit ; la catégorie « Technic set » de KBS, juste à 82 %, ne vient plus qu'après la série). Les sets hors de l'étalon prennent la nouvelle règle à la synchronisation suivante ; la page autonome applique aussi l'étalon. Catalogue local : 333 Technic et 518 classiques (423 et 428 avant).
- Recherche : taille en trois boutons (Petit, moins de 40 cm ; Moyen, 40 à 59 cm ; Grand, 60 cm et plus), au lieu du curseur ; prix maximum sur une piste en dégradé, du vert au orange, poignée au bleu du site ; nouvelle couleur pour la taille.

## v3.13.0
- Recherche : disponibilité en cases à cocher (« En vente », « Précommande », « Épuisé »), chacune ajoutant ses sets (toutes décochées : la liste le dit) ; par défaut, en vente et précommande (les précommandes étaient masquées, et cliquer « Précommande » semblait n'afficher qu'elles). Une couleur par sujet de filtre (disponibilité, thème, briques, prix, taille, marque) sur le libellé, les puces actives et le curseur, perdue à la refonte du moteur de recherche (v3.1). Ligne de résultats : nombre en grand, « sur N » quand des filtres masquent des sets, « Prix du … » à droite.
- Type de briques : plus de « Non précisé » ; 29 sets Mould King mixtes tranchés sur photos (mécanisme en Technic : technic ; personnages articulés : classique, `data/corrections.json`). Un compte de `ADMINS` (nouveau réglage, vide par défaut) impose le type depuis la fiche et voit seul les sets encore « À classer » (filtre Briques, tuile de la vue Synchronisation). Synchronisation : l'historique compte des « Offres lues » (un set vendu par trois boutiques compte trois fois), plus des « Sets ».

## v3.12.0
- Page Marques, qualité des briques : verdict par vote des sites indépendants (« Favorable · 4 sites », « Partagé · 3 pour, 1 contre », « Un seul site », « Peu de sources ») à partir de 360 constats sourcés sur 20 marques (tests, forums, avis d'acheteurs, lien et date chacun ; seuls ceux de 2023 et après votent ; `data/qualite.json`, règle dans `app/qualite.py`) ; un site, une voix, quel que soit son nombre d'articles ; défauts précis comptés à part ; constats dépliables sous chaque marque, par critère (serrage, teintes, finition, décors, notice, pièces, fabricant). Constats Reddit relus dans leur fil (12 corrigés, 1 retiré).
- Retiré : les notes « qualité des briques » écrites à la main sans source (« Très bonnes », « Bonnes », « Moyennes » pour 7 marques) et les affirmations de qualité ou de fournisseur sans source sous les noms de JIE STAR, Bole Brick et BlueBrixx. LEGO officiel reste « Référence ».

## v3.11.0
- Page Marques : logos agrandis (case de 76 × 44 px au lieu d'une pastille de 18 px), noms alignés ; boutiques de « Où acheter » en liens vers la page de la marque chez chaque boutique (collection Shopify relevée par le service, la plus fournie), sinon vers le site de la boutique ; « 1 épuisé » accordé.
- Logos : l'image de la collection de la marque chez les boutiques Shopify lues (KBS, Bausteinreich) passe avant les icônes du site officiel (vrais logos de 150 à 435 px ; CaDA, Wange, Panlos, Sembo, TGL et Ausini, bloqués par leur site ou sans site connu, ont désormais le leur ; Rastar et MOYU gardaient une icône de 32 px ou moins). Bannières écartées. Les logos pris par l'ancienne règle sont relus au passage suivant. Kazi reste sans image.

## v3.10.4
- Liste des résultats : la colonne des vignettes suit leur nouvelle taille (152 px, 128 px en cartes) ; la vignette ne chevauche plus le nom du set (colonne restée à 120 px en v3.10.1). Même correctif dans la sélection en cartes.
- Colonne Prix : deux lignes stables, « port · délai » puis « boutique · nombre de boutiques », coupées seulement entre deux éléments (plus de « 12 / boutiques ») ; au téléphone, le prix passe sous la taille, sur toute la largeur de la carte.

## v3.10.3
- Photos : une photo dite absente une fois, en attente du second constat, passe derrière les autres photos du set au lieu de rester en tête une journée ; sans autre photo, elle reste montrée. Cas d'origine : Concorde (10318), photo Rebrickable en 404.

## v3.10.2
- Photos vérifiées en continu par le service (`app/photos.py`) : chaque photo du catalogue et de la sélection est essayée (4 Ko, sans référent, comme la page) ; une photo introuvable est remplacée par la suivante du set. Écartée aussitôt si son site en interdit l'affichage ailleurs ou si elle n'est pas en https ; après deux constats d'absence à un jour d'écart (404, 410, page à la place de l'image) ; après des échecs passagers trois jours différents. Refus (401, 403) : photo gardée, comptée « non vérifiable ». Site laissé jusqu'au passage suivant après trois échecs de suite ou un 429 ; passage horaire de 20 minutes au plus. Cas d'origine : Concorde (10318), dont la photo Rebrickable répond 404 (seule photo introuvable sur 2450 essayées sur un catalogue de 887 sets) ; la photo de BricksValue la remplace.
- Page : une photo qui ne s'affiche pas cède la place à la suivante de la galerie, puis à la brique ; dans la sélection, à la photo du catalogue (la photo enregistrée reste inchangée). Vue Synchronisation : « Photos trouvées ».
- Filtres de la recherche : plus de barre de défilement horizontale (la liste de tri et « Réinitialiser » élargissaient la colonne de 4 px).
- Lecture d'un lien : statuts acceptés au choix, lecture bornée, réponse de redirection sans adresse refusée au lieu de boucler.

## v3.10.1
Vignettes de la liste agrandies (128 × 96 sur ordinateur, 96 × 72 sur téléphone) et montrées entières : une photo haute ou carrée était rognée. Fiche : défilement des photos par flèches, glissement du doigt ou flèches du clavier, compteur « 2 / 3 » annoncé aux lecteurs d'écran, zone photo de hauteur constante.

## v3.10.0
- Type de briques par série (marque et deux premiers chiffres du numéro), calculé sur les données : 9 sets sur 10 au moins d'un même type dans une série d'au moins 10 sets connus ; validé à 240 justes pour 6 faux. Types relevés sur les photos pour 46 cas nets que rien d'autre ne tranchait (`data/corrections.json`). Sets sans type : 107 → 32.
- Tests indépendants : cinq chaînes ajoutées (The Brickfreaks, Brodaty Geek, Brick Me Up Scottie, Monster Brick Reviews, Noppenstein Stube ; amorce de 6276 liens au total), alias « XMORK ». Sets alternatifs avec au moins un test : 90 → 244 (Mould King 45 → 152 sur 598, Reobrix 1 → 19, CaDA 25 → 35, Cobi 13 → 19, Sembo, Guly, Panlos et Mork de 0 à 2).
- Packs de moteurs et jouets « fidget » écartés du catalogue (ce ne sont pas des sets).
- Vue Synchronisation : indicateurs alignés en grille, libellés à la même hauteur, sans débordement.

## v3.9.1
Lecture des fiches BricksValue : données structurées reconnues par leur contexte schema.org exact (alerte d'analyse de code sur un test de sous-chaîne).

## v3.9.0
Mécanisation, sans IA :
- Classement : type de briques d'après la catégorie de la boutique, les étiquettes de Mould King mesurées contre les catégories de KBS et la marque (285 sets sans type sur 851 avant, 107 après) ; six thèmes ajoutés (Fleurs et décoration, Noël, Films, séries et jeux, Répliques d'armes et de sabres, Animaux et dinosaures, Robots et mechas), mots composés allemands reconnus, étiquettes comparées par mot entier (139 sets sans thème avant, 30 après) ; dimensions écrites une à une dans le texte lues (Mould King : 253 sets avec dimensions sur 532, contre 112).
- Noms seulement en allemand traduits mot à mot (`data/glossaire.json`), nom d'origine cherchable. Corrections à la main dans `data/corrections.json` (réunir, séparer, imposer nom, type, thèmes, dimensions).
- LEGO officiel : fiches BricksValue lues par leur réponse de données (58 Ko au lieu de 675 Ko), accord de BricksValue du 20/11/2026 ; date de chaque prix = jour du dernier relevé du revendeur chez BricksValue, et non l'heure de lecture.
- Tests indépendants : liens rattachés par marque et numéro, sans verdict (Held der Steine, Merlin's Bricks, steine-kanal.de, StoneWars, Promobricks ; amorce de 2652 liens, flux relus chaque jour) ; 1437 liens sur 898 sets, aucun faux positif sur 55 contrôlés à la main.
- Fiche : « Relire les prix » en une requête (une lecture par fiche BricksValue au lieu d'une par revendeur) ; au-delà de trois offres, les autres repliées ; galerie de photos ; « Rechercher des tests sur le web » (DuckDuckGo) à la place de la recherche YouTube ; vignettes de la liste plus grandes.
- Onglet Boutiques : revendeurs vus dans l'index ajoutés à la liste écrite à la main, nombre de sets en vente par boutique.
- Surveillance (`ALERTES_SERVICE`) : message à l'administrateur quand le service se dégrade ou se rétablit, quand une source lit nettement moins que d'habitude, quand un montant de livraison disparaît de sa page (relue chaque semaine ; port de KBS relu sur sa ligne « France » et appliqué) ; points à vérifier dans la vue Synchronisation ; copie quotidienne de la sélection (14 jours).
- Logos : 12 marques ajoutées, plus grande icône mesurée dans le fichier, logo de la page en secours, nouvel essai après 1, 3, 7 puis 30 jours. Lien : chemin non ASCII encodé, port 0 refusé.

## v3.8.2
Sécurité, d'après l'analyse de code : reconnaissance des logos SVG réécrite en un seul passage (l'ancienne expression régulière prenait un temps exponentiel sur une suite de commentaires, ce qu'un site de marque aurait pu exploiter pour bloquer la mise à jour des logos) ; lecture d'un lien limitée aux ports 80 et 443 ; tout nom de fichier dérivé d'une requête (polices, logos, index des sources) vérifié dans son dossier après résolution des chemins ; reconnaissance des offres KBS par le nom d'hôte du lien.

## v3.8.1
Architecture du moteur de recherche mise à jour : en service, relecture continue des fiches LEGO officiel (40 heures, 22 pour la sélection) au lieu du rythme nocturne prévu, étapes remplacées par un renvoi au CHANGELOG.

## v3.8.0
Mots de passe : empreinte PBKDF2-SHA256 à 600 000 itérations (recommandation OWASP), les anciennes empreintes restant valables ; une connexion réussie est retenue 10 minutes en mémoire vive (empreinte HMAC, jamais le mot de passe) pour ne pas refaire le calcul à chaque requête.

## v3.7.7
README, Signal : liste des groupes lisible, un groupe par ligne (nom, identifiant).

## v3.7.6
README, Signal : commandes avec le port de PORT_SIGNAL au lieu de 8081 en dur, curl qui affiche ses erreurs.

## v3.7.5
Dossiers de l'hôte : un seul dossier par pile, un sous-dossier par service (/docker/lego/donnees, /docker/lego/signal), décrit dans .env.example et le README.

## v3.7.4
Test de cohérence des valeurs par défaut : compose, .env.example et code doivent porter la même valeur ; une variable du compose sans valeur ni exigence est refusée. Chemin interne des données renommé CHEMIN_DONNEES, pour ne plus partager le nom du dossier de l'hôte (DOSSIER_DONNEES).

## v3.7.3
Compose : UTILISATEURS exigé par Compose (la pile refuse de démarrer sans) ; valeurs recommandées écrites dans le compose (relevé 24 h, SMTP en ssl sur 465, journal, adresse de Signal) ; facultatifs vides. Courriel en ssl par défaut aussi dans le code.

## v3.7.2
Compose : réglages du service de nouveau écrits en interpolation, lisible par Dockhand (« ${VAR} » obligatoire pour UTILISATEURS, « ${VAR:-} » facultatif, la valeur par défaut restant dans le code) ; un nom seul était signalé comme variable inutilisée. Clés Signal à garder hors du dossier de données du service.

## v3.7.1
Compose : réglages du service transmis par leur seul nom, valeurs par défaut dans le code, une ligne vide du .env valant comme absente ; valeurs par défaut du compose gardées seulement quand elles fonctionnent telles quelles (volume Docker pour Signal). .env.example : obligatoire actif, facultatif en commentaire. Démarrage refusé si un canal d'ALERTES manque de ses réglages ; port SMTP 465 par défaut avec ssl.

## v3.7.0
Signal : le service est relié comme appareil secondaire du compte de son propriétaire et écrit dans un groupe (« signal:group.… ») ; un groupe cité par deux comptes ne reçoit chaque message qu'une fois. README : liaison par QR code à la place de l'inscription d'un numéro dédié.

## v3.6.1
Signal : réception des messages toutes les 6 heures, demandée par le protocole et qui garde le compte actif (pièces jointes ignorées) ; README : code PIN du numéro et ligne à garder ouverte.

## v3.6.0
Alertes par Signal : canal « signal:+33… » dans ALERTES, envoyé depuis un numéro dédié par le conteneur signal-cli-rest-api 0.101 du compose (profil signal, lecture seule, aucune capacité) ; inscription du numéro décrite dans le README. Message d'essai : la cause d'un échec s'affiche.

## v3.5.0
Alertes sur la sélection par courriel : baisse de prix, rupture, retour en vente, retrait annoncé, offre moins chère ailleurs, vérifiées chaque heure, un message par compte (variables ALERTES et SMTP_*) ; essai depuis la vue Synchronisation.

## v3.4.1
Port des revendeurs LEGO officiel relevé sur leurs pages officielles (LEGO.com 5.95 €, offert dès 55 € ; King Jouet ; Galaxus ; seuils de Rue du Commerce et Smyths ; JouéClub et La Grande Récré) ; une offre au port inconnu ne passe plus devant une offre au port connu.

## v3.4.0
Sélection : prix du jour de l'offre choisie (port compris), stock, retrait annoncé, variation depuis l'ajout et offre moins chère ailleurs ; total des retenus au prix du jour. Onglet Marques tiré de l'index : toutes les marques, sets en vente, prix médian de la pièce comparé au LEGO officiel, boutiques ; notes écrites à la main gardées.

## v3.3.0
Logos des marques : icône du site officiel de chaque marque (`data/marques.json`), récupérée par le service une fois par mois et gardée dans son dossier de données, servie isolée (aucun script) ; pastille à initiales pour les marques sans site connu. Le dépôt ne contient aucun logo.

## v3.2.0
Dimensions des sets KBS lues sur les cartes des pages de collection, puis sur la page produit pour les autres, gardées en cache (une fois par produit) : 299 sets KBS sur 299 ont une taille, contre 77 auparavant.

## v3.1.1
Recherche : un mot cherche d'abord dans les noms, le thème seulement sans résultat direct ou sur demande. Prix affiché port compris, détail du port et délai ; tri par sélecteur, aussi sur téléphone. Variantes regroupées (R55013 = 55013), noms nettoyés, thèmes « Autres » et type « Non précisé », écart de prix signalé. Polices servies par le service, plus rien chez Google. Onglet Boutiques lisible à 1400 px.

## v3.1.0
LEGO officiel automatique : catalogue Rebrickable (sets de 500 pièces et plus) et offres des revendeurs français lues sur les fiches BricksValue, source désactivée par défaut. Rotation continue : fiche d'un set pour adultes relue au moins toutes les 48 h, d'un set de la sélection toutes les 24 h, pages compressées. Date de retrait affichée.

## v3.0.0
L'onglet principal devient un moteur de recherche sur environ 900 sets de KBS, Bausteinreich et de la boutique officielle Mould King : catalogue JSON public relu chaque nuit, offres regroupées par marque et numéro, meilleur prix port compris, thèmes en trois langues dont Aérospatial et Marine, filtres fixes (thème, marque, type de briques, curseurs de prix et de taille, épuisés masqués), offres relues en direct. Vue Synchronisation par source. Port KBS vers la France corrigé (4.95 €).

# v2.x — Service Docker : relevé des prix à la source suivi dans la page, ajout par lien, sélection partagée avec achats masqués ; page autonome jointe à chaque version.

## v2.1.1
Relance des échecs fondue dans le dernier relevé complet ; panne signalée hors de la vue ; panneau d'avancement de hauteur fixe, résumé de fin à sa place, prix d'Idées mis à jour sans rechargement ; raisons d'échec en clair avec la boutique ; raison des boutons désactivés au survol ; onglets entiers à 360 px.

## v2.1.0
Relevé des prix suivi dans la page : avancement en direct, résultat de chaque set (lu, échec et raison, sauté), relance des échecs, historique des 30 derniers relevés. Sets LEGO.com sautés sans requête ; contrôle de santé en échec quand le relevé est en panne.

## v2.0.2
Code publié sous licence AGPL-3.0 : fichier LICENSE, mention dans l'image et lien vers le code source en pied de page. Outil de construction Docker épinglé par empreinte.

## v2.0.1
Lecture des pages en TLS 1.2 au minimum et test d'adresse de photo exact, suite à deux alertes de l'analyse de code.

## v2.0.0
Passage en service : page servie avec les prix relevés chaque jour et à la demande, lecture d'une page produit par lien (Shopify, JSON-LD, Open Graph) limitée aux adresses publiques, sélection partagée entre comptes avec achats masqués, image multi-architecture sur ghcr.io et page autonome jointe à la version. Python 3.15 ; publication par le fichier VERSION ; mises à jour par Renovate.

# v1.x — Page autonome : catalogue de 34 sets dont 12 LEGO officiels, photos, taille, tests indépendants, boutiques, marques, sélection dans le navigateur.

## v1.2
Accueil recomposé (taille, filtres principaux, filtres repliés) et 12 sets LEGO officiels.

## v1.1
Photos, fiches avec tests indépendants, filtres par sujet, onglet Sélection.

## v1.0
Première page autonome : idées, boutiques, marques, liste de cadeaux.
