# Moteur de recherche — architecture (v3)

État au 20/11/2026 : en service depuis la v3.0.0. Remplace le catalogue figé de 34 sets par un index de tous les sets pour adultes vendus en France, tenu à jour sans intervention.

## Objectif

L'onglet principal devient un moteur de recherche : saisie libre et filtres toujours visibles sur les sets LEGO officiel et des marques alternatives de qualité, avec le meilleur prix du jour (port compris), la fraîcheur de chaque prix et les autres offres. Tout fonctionne sans Claude : synchronisation automatique, nouveaux sets ajoutés seuls, thèmes et types déduits par règles.

## Principe : un index local nourri par des connecteurs

Interroger chaque site à chaque frappe serait lent, fragile et impoli. Le service tient un **index local** (un fichier JSON par source dans le dossier de données) que des **connecteurs** remplissent chaque jour et à la demande. Le navigateur reçoit tout l'index, compressé, et filtre lui-même : saisie et filtres instantanés. Ouvrir une fiche relit ses offres en direct.

| Connecteur | Sources | Apport | Charge pour la source |
|---|---|---|---|
| Shopify, catalogue JSON public `/products.json` | KBS (euros, Allemagne), Bausteinreich (euros, Allemagne), boutique officielle Mould King (euros avec le marché France, expédition depuis la Chine) | marques alternatives : nom, prix, stock, précommande, photos, étiquettes, référence | 2 à 7 pages par boutique et par nuit |
| Fiches produit KBS | kbs-shop.com | dimensions (absentes du catalogue JSON) | une fois par produit, gardé ensuite |
| Rebrickable, export CSV public | rebrickable.com | catalogue LEGO officiel : numéro, nom, thème, pièces, année, photo | 2 fichiers par nuit |
| BricksValue, fiches publiques | bricksvalue.com/fr | prix LEGO.com France et offres des revendeurs français, retrait | voir ci-dessous |

**BricksValue** : ses conditions interdisent la collecte automatisée sans son accord écrit ; BricksValue l'a donné par courriel le 20/11/2026 pour cet usage non commercial et raisonnable (« API et JSON »), sans documentation d'API. Aucune API publique de données n'existe (constat du 20/11) : le connecteur lit la réponse de données de chaque fiche (format React Server Components, `?_rsc` avec l'en-tête `RSC: 1`, 58 Ko contre 675 Ko pour la page), qui porte le JSON-LD des offres, toutes les photos et la série quotidienne des prix par revendeur ; la page HTML sert de secours. Le jour du dernier relevé de chaque revendeur dans cette série devient la date du prix affichée (Amazon n'y figure pas : date non donnée). Le connecteur se limite aux sets pour adultes (16 ans et plus, ou 2000 pièces et plus, d'après Rebrickable) et les relit en continu, une fiche à la fois, la plus ancienne d'abord : chacune au moins toutes les 40 heures, celles de la sélection toutes les 22 heures ; « Relire les prix » dans une fiche la relit aussitôt, une seule fois pour toutes ses offres. Désactivé par défaut dans le dépôt public, activé par `.env`.

Reportés : Lumibricks et Pantasy (prix en dollars, expédition internationale : conversion et douane à traiter), Cobi et BlueBrixx (pas de catalogue JSON, microdonnées à lire), boutiques officielles CaDA (conditions interdisant la collecte) et Reobrix (rien de lisible). Écartés : LEGO.com (refuse les robots), Reddit (robots.txt), API Amazon et AliExpress (conditions d'accès), Idealo et LeDénicheur (pas d'API).

## Normalisation (`app/normalise.py`)

- **Prix** : euros seulement ; une offre dont la devise est inconnue n'est pas indexée. Port vers la France et délai par boutique (`data/sources.json`) ; le meilleur prix compte le port.
- **Un set, plusieurs offres** : même marque (table d'alias) et même numéro (préfixes de boutique retirés). Quand une seule boutique vend un set, l'interface le dit.
- **Disponibilité** : en vente, précommande (étiquettes « vorbestellung », « pre-order »), épuisé. Un set est épuisé seulement si toutes ses offres le sont. Trois cases à cocher, chacune ajoutant ses sets ; par défaut : en vente et précommande, épuisés masqués.
- **Thèmes** : plusieurs par set, depuis les étiquettes des boutiques (comparées par mot entier ; une étiquette qui mêle deux sujets, comme « Architecture And Rail » de Mould King, ne classe pas) et des mots-clés en français, anglais et allemand, mots composés allemands compris (`data/themes.json`, éditable) : Aérospatial, Marine, Voitures, Engins et camions, Architecture, Trains, Militaire, Mécanique, Fleurs et décoration, Noël, Films, séries et jeux, Répliques d'armes et de sabres, Animaux et dinosaures, Robots et mechas. Les mots-clés servent aussi de dictionnaire : chercher « bateau » trouve « Schiff ». Mesure du 20/11/2026 sur les catalogues : 30 sets sans thème sur 851 (139 avant).
- **Type de briques** : Technic ou classique, dans cet ordre de preuve : choix d'un compte administrateur depuis la fiche (`ADMINS`, `corrections_locales.json`), corrections à la main (`data/corrections.json`), étalon des photos (`data/types_photos.json`, 812 sets relevés le 21/11/2026), série (marque et deux premiers chiffres du numéro, comptée sur ces seuls types sûrs : au moins 10 sets et 90 % du même type), enfin signaux des boutiques, mesurés contre l'étalon : catégorie de produit de KBS (« Brickbuild-Set » 105 classiques sur 108 ; « Technic set » 134 Technic sur 163, gardé faute de mieux après la série), étiquettes classiques de Mould King (99 sur 100), étiquette « Construction » de Mould King (48 Technic sur 48), mots « brick build » ou « Klemmbaustein », marques qui ne font que des briques classiques, mot « Technic » dans le nom (pas dans les étiquettes). Le type des offres est calculé à la synchronisation : une règle changée ne s'applique aux sets hors de l'étalon qu'après la synchronisation suivante. Mesure du 21/11/2026, chaque set prédit sans sa propre photo : 581 justes, 22 faux, 163 sans type ; le tri de la v3.13, mesuré auparavant contre la catégorie de KBS (qui classe « Technic set » 29 sets à picots sur 163), classait Technic 103 sets à picots, surtout les voitures « Creative Idea » de l'étiquette « Technic-Vehicles » de Mould King. Un set nouveau resté sans type n'est visible, dans le filtre Briques (« À classer ») et dans la vue Synchronisation, que des administrateurs.
- **Noms** : un set vendu seulement par une boutique allemande reçoit une traduction mot à mot de son nom (`data/glossaire.json`) ; le nom d'origine reste cherchable.
- **Corrections** : `data/corrections.json` réunit ou sépare des offres et impose nom, type, thèmes ou dimensions d'un set.
- **Pièces** : catalogue, description ou titre. **Dimensions** : description (trois dimensions, ou une seule écrite en toutes lettres : « At 44 cm long », « stands 53.9 cm tall ») ou fiche ; inconnues sinon, jamais estimées ; le filtre de taille dit combien de sets n'en ont pas.
- **Port** : écrit par boutique (`data/sources.json`) et par revendeur (`data/livraison.json`) ; les pages de livraison sont relues chaque semaine, un montant disparu est signalé, le port de KBS lu sur sa ligne « France » s'applique seul.
- **Périmètre** : marques de la liste, prix positif, 500 pièces au moins (ou 50 € si le nombre est inconnu), lots, pièces détachées, éclairages et vitrines exclus.

## Couche éditoriale

Les tests indépendants et verdicts des 32 sets restent attachés à leur set. S'y ajoutent des liens de tests rattachés par script (`app/tests_auto.py`), sans verdict : vidéos et articles dont le titre nomme la marque et le numéro du set. Sources (`data/tests_sources.json`) : chaînes YouTube Held der Steine, The Brickfreaks, Noppenstein Stube (allemand), Merlin's Bricks, Brick Me Up Scottie, Monster Brick Reviews (anglais), Brodaty Geek (polonais), blogs steine-kanal.de, StoneWars et Promobricks (articles de test seulement, filtrés par leur titre). L'historique vient d'une amorce versionnée (`data/tests_amorce.json`, 6276 liens, produite avec yt-dlp, hors du service, par `tools/amorcer_tests.py`) ; le service relit chaque jour les flux publics (15 dernières vidéos, 10 à 20 derniers articles). Mesure du 20/11/2026 : Mould King 152 sets sur 598, CaDA 35 sur 53, Cobi 19 sur 37, Reobrix 19 sur 57 ; sans source : JIE STAR (vendu sous des numéros de boutique que les tests ne citent pas), Lonestar, Kazi, Bole Brick, Rastar, MOYU, TGL, iM.Master. Échantillons contrôlés à la main : 1 rattachement faux sur 93, dû au titre de la source. Chaque fiche porte aussi « Rechercher des tests sur le web » (DuckDuckGo, marque et numéro). Sélection partagée, ajout par lien et achats masqués inchangés.

## Interface de l'onglet principal

- Plus de titre : la saisie libre en tête (nom, numéro, marque, thème en français).
- Filtres toujours visibles au défilement (colonne fixe sur ordinateur, barre fixe dépliable sur téléphone) : thèmes ; marques par leur logo ; type de briques par une icône (brique ou poutre Technic) ; curseur de prix plafond (piste en dégradé) ; taille en trois boutons, par la longueur du set monté (Petit, moins de 40 cm ; Moyen, 40 à 59 cm ; Grand, 60 cm et plus) ; disponibilité en cases à cocher.
- Résultat : photo, logo, nom, pièces, taille, meilleur prix port compris, nombre de boutiques, fraîcheur ; fiche : offres relues en direct, tests, achat.
- Photos : liens vers les sources, vérifiés en continu par le service ; photo introuvable remplacée par la suivante du set (README, « Photos des sets »).
- Logos : icônes des sites des marques récupérées par le service dans son dossier de données (rien dans le dépôt) ; pastille aux initiales sinon.

## Suivi et santé

La vue « Relevé des prix » devient « Synchronisation » : une ligne par source (dernier passage, produits lus, nouveaux, disparus, erreurs), le suivi en direct et les points à vérifier. Le conteneur passe « unhealthy » seulement si la synchronisation programmée est arrêtée ou si toutes les sources échouent : une source en panne ne bloque pas les autres. Le module de surveillance (`app/surveillance.py`) envoie lui-même un message à l'administrateur (`ALERTES_SERVICE`) quand le service se dégrade ou se rétablit, quand une source lit moins de 70 % de sa médiane habituelle (sets ou dimensions : boutique qui a changé ses pages) et quand une condition de livraison change ; il garde une copie quotidienne de la sélection (14 jours).

## Versions

Construit de la v3.0.0 à la v3.4 (connecteurs, index, onglet de recherche, synchronisation, LEGO officiel, dimensions, logos, prix du jour dans la sélection) ; le détail de chaque version est dans le CHANGELOG.
