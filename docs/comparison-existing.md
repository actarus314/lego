# Comparison with existing services

Measured on 23/11/2026. Directory of the brick world: [actarus314/awesome-lego](https://github.com/actarus314/awesome-lego).

**Question.** Do one or two existing sites already do everything the Carnet de briques aims to do? If so, development stops.

**Standard, fixed before the measurement.** Every essential required, from one site or two combined:

| | Essential | Threshold |
|---|---|---|
| E1 | Catalogue covers the Carnet's sets | 90 % |
| E2 | Offer in stock, deliverable to France, at most 48 h old, shipping known | 80 % |
| E3 | Best delivered price at most 5 % above the Carnet's | 80 % |
| E4 | One search mixing official LEGO and alternative brands, filtered by price, size, pieces, theme and brand | yes |
| E5 | A list of sets with a price alert | yes |

**Sample.** The 879 sets for sale or pre-order in the Carnet on 23/11/2026: 709 alternative-brand sets, 170 official LEGO sets for adults.

**Results for [Brick Broker](https://brick-broker.com/) and [Brickfact](https://brickfact.com/) combined.**

| | Alternative brands | Official LEGO | Verdict |
|---|---|---|---|
| E1 | 651 / 709 (91.8 %) | 170 / 170 | passed |
| E2 | 642 / 709 (90.5 %); freshness sampled on 13 sets | 170 / 170 | passed |
| E3 | 636 / 642 (99.1 %); 544 at least 5 % cheaper, median 14.8 % cheaper | 152 / 166 (91.6 %); Brick Broker alone 77.1 %, Brickfact alone 81.3 % | passed |
| E4 | no filter by size or dimensions (dimensions shown on each Brick Broker page) | | **failed** |
| E5 | e-mail alert for each set, no account; followed list with an account | | passed |

**Conclusion.** Four essentials out of five. Strictly, the stop condition is not met: only the size filter is missing. On alternative-brand prices, Brick Broker does better than the Carnet (median of 3 merchants per set against 1).

**Only in the Carnet de briques.** Filter by size, brick type (classic or Technic), brand quality verdict with sources (360 findings), alerts on Signal, self-hosting.

**Limits.**
- Brick Broker shows shipping as free for Brickmo (wrong for France), KBS Shop and Bausteinreich (not confirmed); the measurement uses their shipping to France (Brickmo 9.95 €, 3.50 € more under 24 €; KBS Shop 4.95 €; Bausteinreich 9.95 €, estimated). Barweer was left out (stale offers).
- Mould King official prices are about 8 % lower on Brick Broker than in the Carnet (median, 415 sets), unexplained; this gap accounts for 98 of the 544 cheaper sets.
- The Carnet's reference is its best price with known shipping; the 4 official LEGO sets without known shipping are left out of E3.
- Brick Broker and Brickfact pages were read once each, 2 s apart, without any key or account. Only aggregates are published here: per-set prices of these sites stay out of this repository.
