# Mécanique ou LLM : qui fait quoi

État de la v3.20.0 (23/11/2026). Ce document est tenu à jour à chaque version : un contrôle automatique du dépôt échoue si un fichier de données n'y est pas classé, ou si la version ci-dessus n'est pas celle du dépôt.

**Le service n'appelle aucun LLM** (aucune clé, aucun appel vers un service d'intelligence artificielle). Tout ce qu'il calcule, il le calcule par script : sur les mêmes données lues, le même calcul. Les LLM sont intervenus en amont, hors du service, pour produire une partie des données qu'il applique. Ces données sont figées : elles ne changent qu'à une nouvelle passe, faite à la demande dans une conversation.

| Origine | Qui | Quand | Fiabilité |
|---|---|---|---|
| **Mécanique** | le service ou la page, par script | en continu (chaque heure, chaque jour, à la demande) | celle de la source lue et de la règle ; les règles du service sont vérifiées par les tests du dépôt |
| **LLM** | Claude (Sonnet ou Opus selon la passe), une fois Perplexity, dans une conversation avec Romain | une fois, à une date donnée | celle du modèle : erreurs possibles, contrôlées par échantillon |
| **Écrit à la main** | Romain (compte administrateur), ou Claude pour quelques règles et valeurs | quand c'est décidé | fait foi tant que ce n'est pas revu |

Dates, modèles et contrôles des passes LLM : relevés du projet (CHANGELOG, notes en tête des fichiers, document de contexte du projet).

## Mécanique : fait par script, sans LLM

| Fonction | Comment |
|---|---|
| Catalogues des boutiques (KBS, Bausteinreich, Mould King officiel) | lecture de leur catalogue public, chaque jour à 6 h ; pages inchangées non retéléchargées |
| Offres LEGO officiel | référence Rebrickable ; prix des revendeurs français lus sur BricksValue après chaque mise à jour du site (source activée par le `.env` ; sans elle, seul le prix relevé le 19/11 est servi) |
| Prix de la sélection | relus sur la boutique chaque heure, avant les alertes |
| Regroupement des offres d'un même set | marque et numéro extraits du nom par des règles écrites (`app/normalise.py`) |
| Thèmes et univers | étiquettes des boutiques, mots-clés du nom et correspondance des thèmes Rebrickable (`data/themes.json`) ; un set sans sujet reconnu reçoit un thème estimé, marqué comme tel : celui de son univers, sinon le plus fréquent de sa série, sinon de sa marque |
| Complétude du catalogue | comptée par champ (thème, univers, type, dimensions, avis, port, délai ; mesuré, estimé, absent) à chaque synchronisation ; une baisse nette est signalée à l'administrateur |
| Type de briques (Technic ou classique) | de la preuve la plus forte à la plus faible : choix de l'administrateur, corrections, étalon photo, règle par série (calculée sur les types connus), signaux des boutiques |
| Dimensions, pièces, âge | lus dans les descriptions et les pages produits des boutiques, et dans la description de LEGO officiel reprise par les fiches BricksValue, par des règles écrites (`app/normalise.py` : trois cotes, ou cotes écrites une à une, en centimètres, millimètres ou pouces, en anglais, allemand et français) ; chaque cote garde sa source |
| Dimension estimée d'un set sans cote publiée | plus grande cote estimée par une règle étalonnée à chaque reconstruction sur les sets mesurés (nombre de pièces, type de briques, thème), marquée « estimée » avec sa méthode, servie à part des cotes mesurées |
| Noms allemands | traduits mot à mot par `data/glossaire.json` |
| Disponibilité | lue chez la boutique à chaque lecture |
| Port et délai | relevés une fois (plus bas) ; pages de livraison relues chaque semaine, un montant disparu est signalé à l'administrateur ; port de KBS lu sur sa ligne « France » |
| Historique des prix, plus bas sur 30 jours, remise douteuse | calculés sur les prix relevés chaque jour |
| Verdict de qualité d'une marque (page Marques : « Favorable », « Partagé »…) | chaque site compte pour une voix, quel que soit son nombre d'articles, à la majorité de ses jugements sur le plastique depuis 2023 ; les défauts précis sont comptés à part et ne votent pas (`app/qualite.py`). Les constats, eux, viennent d'une passe LLM (plus bas). LEGO officiel est fixé en « Référence » |
| Prix de la pièce comparé au LEGO officiel, boutiques d'une marque | calculés par la page sur l'index |
| Liens de tests (vidéos, articles) | titre qui nomme la marque et le numéro, dans les flux des chaînes et blogs suivis, sans verdict ; contrôlé à la main sur 93 liens : 1 erreur |
| Photos et logos | vérifiés et récupérés par le service, revérifiés périodiquement ; photos gardées en cache sur le serveur (vignette de 400 px pour toutes, grande de 1200 px à la première demande), à la taille donnée par le site de la photo |
| Boutiques : pays, devise, livraison en France, port, délai, avis, douane, fiabilité | relus chaque semaine (`app/boutiques.py`) : `meta.json` des boutiques Shopify, API publique de Trusted Shops, avis affichés sur la page d'accueil, page de livraison (port, seuil de gratuité), mentions légales des boutiques hors Shopify (pays du numéro de TVA ou du code postal) ; douane, délai à défaut de lecture, boîte d'origine et fiabilité calculés par des règles écrites, l'origine de chaque champ (lu, estimé, règle) est rendue avec lui |
| Occasion des sets LEGO officiel | catalogues publics de deux boutiques d'occasion, chaque jour (état lu dans l'option de la variante ou l'attribut du produit, numéro dans le titre ou la référence) ; avec les clés du `.env`, guide des prix BrickLink chaque semaine et annonces eBay à l'ouverture d'une fiche ; annonce eBay retenue si son titre porte « LEGO » et le numéro, sans mot d'exclusion (notice ou boîte seule, autocollants, incomplet, compatible…) |
| Alertes (courriel, Signal) et surveillance du service | comparaison de l'état du jour à l'état connu |

Le bouton « Rechercher des tests sur le web » de la fiche ouvre une recherche DuckDuckGo dans le navigateur : ce n'est pas un appel du service.

## LLM : relevé une fois, appliqué par script

| Donnée | Fichier | Passe | Contrôle |
|---|---|---|---|
| Type de briques sur photos (l'étalon) | `data/types_photos.json` | 21/11/2026 : 833 sets lus sur vignettes par cinq lectures en parallèle, seconde lecture Opus sur 84 sets ; 812 typés, 21 laissés sans type | 110 litiges relus sur photos de détail, 17 changés de classique à technic ; les règles de repli (série, signaux des boutiques), mesurées contre l'étalon : 581 justes, 22 faux, 163 sans type |
| Type de sets mixtes ou ambigus | `data/corrections.json` (en partie) | 20 et 21/11/2026, Claude sur photos | cas nets seulement ; les autres restent « À classer » pour l'administrateur |
| Constats sur la qualité des briques : source, critère, sens, résumé ; remarque par marque | `data/qualite.json` | 21/11/2026 : 360 constats sur 20 marques, quatre recherches Opus ; fils Reddit relus par Perplexity (texte parfois reformulé) | lien, date et rang de chaque source ; 64 constats Reddit relus dans leur fil : 51 confirmés, 12 corrigés, 1 retiré. Résumés et remarques : texte rédigé par le LLM ; liens non relus par le service |
| Avis des testeurs sur 32 sets (Favorable, Mitigé, Déconseillé) et leurs tests | `data/catalogue.json` | 19/11/2026, synthèse de Claude à partir des tests lus | « Déconseillé » seulement si un testeur le dit ; chaque test avec lien et date. Cet avis porte sur un set, à ne pas confondre avec le verdict de qualité d'une marque |
| Nom français, thème, pièces, dimensions, étiquettes et prix LEGO officiel de ces 34 sets | `data/catalogue.json`, date dans `data/meta.json` | 19/11/2026, Claude | le nom et le thème priment sur ceux des boutiques ; prix remplacé par BricksValue quand la source est active |
| Fiche des boutiques affichée par la page : fiabilité de 1 à 3, délai, douane, points notables | `web/index.html` (`BOUTIQUES`) | 19 et 20/11/2026, synthèse de Claude | règle de la fiabilité écrite dans la page ; les montants et notes des points notables (avis Trusted Shops, port, prix cités) ne sont pas mis à jour ; remplacée par le relevé mécanique (`/api/boutiques`) quand la page l'affichera |
| Liste des boutiques et adresses où lire leurs champs | `data/boutiques.json` | 23/11/2026, reprise par Claude du tableau `BOUTIQUES` ; identifiant Trusted Shops lu dans la page de KBS | aucune valeur relevée dans le fichier : tout est lu par le service |
| Spécialité, note et « où acheter » de chaque marque | `web/index.html` (`MARQUES`) | 19 à 21/11/2026, Claude | spécialité et « où acheter » calculés sur l'index quand ils manquent ; les taux de défauts cités en note (Galaxus) ne sont pas mis à jour |
| Port et délai des boutiques lues | `data/sources.json` | 20/11/2026, pages de livraison lues par Claude | pages relues chaque semaine par le service |
| Port des revendeurs LEGO officiel | `data/livraison.json` | 20/11/2026, pages officielles lues par Claude | pages relues chaque semaine par le service |
| Listes de mots : thèmes, univers, correspondance Rebrickable, glossaire allemand | `data/themes.json`, `data/glossaire.json` | 20/11/2026, complétées le 23/11/2026 (univers, quatre thèmes), écrites par Claude | appliquées par script ; mesure du 23/11/2026 : 0 set sans thème sur le catalogue local et sur les 412 sets LEGO officiel suivis, dont une part de thèmes estimés (CHANGELOG) ; ajouts relus set par set sur le catalogue local |
| Chaînes et blogs de tests suivis | `data/tests_sources.json` | 20/11/2026, choisis par Claude | le rattachement aux sets est mécanique (plus haut) |
| Sites et logos déclarés des marques | `data/marques.json` | 19 à 21/11/2026, Claude | logo vérifié par le service (format, taille) |

Fichiers de `data/` sans part LLM : `meta.json` (date du relevé d'origine) et `tests_amorce.json` (historique des vidéos des chaînes suivies, tiré une fois par un outil de liste de vidéos, yt-dlp, hors du service).

## Écrit à la main

| Donnée | Qui, où |
|---|---|
| Type de briques imposé depuis la fiche | Romain, compte de `ADMINS` (`corrections_locales.json` du dossier de données) |
| Sélection et achats ; réglages des alertes | Romain et Julie, page Sélection ; Romain, `.env` |
| Règles du tri : liste des marques, mots qui excluent un lot ou une pièce détachée, étiquettes des boutiques | code (`app/normalise.py`), écrit par Claude, mesuré sur les étiquettes des boutiques |
| Paliers de prix et de taille (40 et 60 cm), liste des pays européens | page (`web/index.html`) |

## Développement

Le code est écrit par Claude et relu par un autre Claude en contexte neuf avant chaque version (pratique du projet, notée dans les messages de commit) ; il s'exécute ensuite sans aucun modèle. Ce qui le garantit est mécanique : la suite de tests du service, l'analyse de code de GitHub et les vérifications de la publication. La page n'a pas de tests automatiques : elle est vérifiée par capture d'écran à chaque version qui la touche.
