# v3.x — Moteur de recherche : catalogues des boutiques et LEGO officiel tenus à jour en continu, meilleur prix, filtres toujours visibles.

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
