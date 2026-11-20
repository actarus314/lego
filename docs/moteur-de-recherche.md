# Moteur de recherche — architecture (v3)

État au 20/11/2026 : en service depuis la v3.0.0. Remplace le catalogue figé de 34 sets par un index de tous les sets pour adultes vendus en France, tenu à jour sans intervention.

## Objectif

L'onglet principal devient un moteur de recherche : saisie libre et filtres toujours visibles sur les sets LEGO officiel et des marques alternatives de qualité, avec le meilleur prix du jour (port compris), la fraîcheur de chaque prix et les autres offres. Tout fonctionne sans Claude : synchronisation automatique, nouveaux sets ajoutés seuls, thèmes et types déduits par règles.

## Principe : un index local nourri par des connecteurs

Interroger chaque site à chaque frappe serait lent, fragile et impoli. Le service tient un **index local** (un fichier JSON par source dans le dossier de données) que des **connecteurs** remplissent chaque jour et à la demande. Le navigateur reçoit tout l'index, compressé, et filtre lui-même : saisie et curseurs instantanés. Ouvrir une fiche relit ses offres en direct.

| Connecteur | Sources | Apport | Charge pour la source |
|---|---|---|---|
| Shopify, catalogue JSON public `/products.json` | KBS (euros, Allemagne), Bausteinreich (euros, Allemagne), boutique officielle Mould King (euros avec le marché France, expédition depuis la Chine) | marques alternatives : nom, prix, stock, précommande, photos, étiquettes, référence | 2 à 7 pages par boutique et par nuit |
| Fiches produit KBS | kbs-shop.com | dimensions (absentes du catalogue JSON) | une fois par produit, gardé ensuite |
| Rebrickable, export CSV public | rebrickable.com | catalogue LEGO officiel : numéro, nom, thème, pièces, année, photo | 2 fichiers par nuit |
| BricksValue, fiches publiques | bricksvalue.com/fr | prix LEGO.com France et offres des revendeurs français, retrait | voir ci-dessous |

**BricksValue** : ses conditions interdisent la collecte automatisée sans son accord écrit ; Romain a choisi de l'utiliser pour cet usage personnel, et une demande d'accord est proposée. Une fiche pèse environ 500 Ko et presque toutes changent chaque jour : relire les 864 fiches chaque nuit coûterait 430 Mo par jour à ce site. Le connecteur se limite donc aux sets pour adultes (16 ans et plus, ou 2000 pièces et plus, d'après Rebrickable) et les relit en continu, une fiche à la fois, la plus ancienne d'abord : chacune au moins toutes les 40 heures, celles de la sélection toutes les 22 heures ; une fiche ouverte est relue aussitôt. Désactivé par défaut dans le dépôt public, activé par `.env` ; jamais `/api/`, exclu par robots.txt.

Reportés : Lumibricks et Pantasy (prix en dollars, expédition internationale : conversion et douane à traiter), Cobi et BlueBrixx (pas de catalogue JSON, microdonnées à lire), boutiques officielles CaDA (conditions interdisant la collecte) et Reobrix (rien de lisible). Écartés : LEGO.com (refuse les robots), Reddit (robots.txt), API Amazon et AliExpress (conditions d'accès), Idealo et LeDénicheur (pas d'API).

## Normalisation (`app/normalise.py`)

- **Prix** : euros seulement ; une offre dont la devise est inconnue n'est pas indexée. Port vers la France et délai par boutique (`data/sources.json`) ; le meilleur prix compte le port.
- **Un set, plusieurs offres** : même marque (table d'alias) et même numéro (préfixes de boutique retirés). Quand une seule boutique vend un set, l'interface le dit.
- **Disponibilité** : en vente, précommande (étiquettes « vorbestellung », « pre-order »), épuisé. Un set est épuisé seulement si toutes ses offres le sont. Par défaut : en vente ; précommande en option ; épuisés masqués.
- **Thèmes** : plusieurs par set, depuis les étiquettes des boutiques, les thèmes LEGO et des mots-clés en français, anglais et allemand (`data/themes.json`, éditable) : Aérospatial (aviation et espace, réel et fiction), Marine (réel et fiction), Voitures, Engins et camions, Architecture, Trains, Militaire, Mécanique. Les mots-clés servent aussi de dictionnaire : chercher « bateau » trouve « Schiff ».
- **Type de briques** : Technic, classique, ou inconnu.
- **Pièces** : catalogue, description ou titre. **Dimensions** : description ou fiche ; inconnues sinon, jamais estimées ; le curseur de taille dit combien de sets n'en ont pas.
- **Périmètre** : marques de la liste, prix positif, 500 pièces au moins (ou 50 € si le nombre est inconnu), lots, pièces détachées, éclairages et vitrines exclus.

## Couche éditoriale

Les tests indépendants et verdicts des 32 sets restent attachés à leur set. Les autres portent un lien « Chercher des tests » (recherche YouTube préremplie). Sélection partagée, ajout par lien et achats masqués inchangés.

## Interface de l'onglet principal

- Plus de titre : la saisie libre en tête (nom, numéro, marque, thème en français).
- Filtres toujours visibles au défilement (colonne fixe sur ordinateur, barre fixe dépliable sur téléphone) : thèmes ; marques par leur logo ; type de briques par une icône (brique ou poutre Technic) ; curseur de prix plafond ; curseur de taille (plus grande dimension) ; disponibilité.
- Résultat : photo, logo, nom, pièces, taille, meilleur prix port compris, nombre de boutiques, fraîcheur ; fiche : offres relues en direct, tests, achat.
- Logos : icônes des sites des marques récupérées par le service dans son dossier de données (rien dans le dépôt) ; pastille aux initiales sinon.

## Suivi et santé

La vue « Relevé des prix » devient « Synchronisation » : une ligne par source (dernier passage, produits lus, nouveaux, disparus, erreurs) et le suivi en direct. Le conteneur passe « unhealthy » seulement si la synchronisation programmée est arrêtée ou si toutes les sources échouent : une source en panne ne bloque pas les autres.

## Versions

Construit de la v3.0.0 à la v3.4 (connecteurs, index, onglet de recherche, synchronisation, LEGO officiel, dimensions, logos, prix du jour dans la sélection) ; le détail de chaque version est dans le CHANGELOG.
