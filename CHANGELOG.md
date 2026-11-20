# v3.x — Moteur de recherche : catalogues des boutiques et LEGO officiel tenus à jour en continu, meilleur prix, filtres toujours visibles.

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
