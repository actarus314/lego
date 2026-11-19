# v3.x — Moteur de recherche : catalogues des boutiques et LEGO officiel tenus à jour en continu, meilleur prix, filtres toujours visibles.

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
