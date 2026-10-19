# BoxCheck Structural — template demand research

Date: 2026-10-03 · Status: **research only** — no template, formula engine, API, UI or production code was written; nothing committed.
Companion documents: `docs/structural-research.md` (extraction), `docs/structural-spec.md` (four-PDF analysis).

**Evidence labels used throughout**

| Label | Meaning |
|---|---|
| **OBSERVED** | Found in a cited public source, or in this repository. A source being *cited* does not mean its claim is reliable — see the reliability grade. |
| **INFERENCE** | A conclusion drawn from OBSERVED items by reasoning that is stated. |
| **HYPOTHESIS** | A guess that the available data cannot confirm or refute. |
| **UNKNOWN** | Not determinable from collected evidence. |

**Source reliability grades** (shown as `[Sn·grade]`): **A** standards body / trade association · **B** manufacturer or retailer catalogue · **C** vendor marketing page or blog (SEO content) · **D** market-research aggregator snippet (figures unverified, often internally inconsistent).

**Method limits you must know before reading further**

1. Direct page fetching was blocked by the environment's network policy for almost every site tried (pacdora.com, diecuttemplates.com, fefco.org, boxshot.com, kitepackaging.co.uk, pakfactory.com and others). Everything below that is not from this repository comes from **search-result summaries of those pages**, not from reading the pages. Where a summary seemed inconsistent I say so.
2. **No reliable search-volume data was obtainable.** No figure in this document is a search volume, except one clearly flagged Etsy-keyword number (§2.3) that is not Google data. Nothing was estimated or invented.
3. The official FEFCO and ECMA catalogues could not be opened. Code-to-structure statements come from commercial summaries of them.

---

## 1. Research question

Before building the structural engine: **which packaging structures are people most likely to need a dieline for** — to search, request, generate, customise — so that the template library is driven by practical demand and not by "the largest possible list"?

Sub-questions:
1. What kinds of evidence of demand exist, and how strong is each? (§2)
2. Which packaging families and structures are candidates? (§3–§4)
3. For each candidate, what is the observable evidence of demand, the custom-size relevance, and the implementation/validation cost? (§5–§7)
4. Does one geometry engine serve all material families, or do families need separate engines? (§8)
5. Which templates belong in Phase 1, 2, 3 under a measurable (not subjective) framework? (§9–§11)
6. Should the four-PDF structure we already analysed stay the technical research template if market data points elsewhere for the first commercial template? (§12)

Corrugated packaging is **not** assumed to be the focus. The corpus below is deliberately broader: corrugated, folding carton, rigid, paper bags, inserts, food service.

---

## 2. Market evidence

### 2.1 Market size and segment reports (reliability D — treat as context, not as a ranking)

| Observation | Source |
|---|---|
| Corrugated + folding carton combined: USD 288.8 B (2024), CAGR 5.2 % (2025–2034); folding cartons "over 70 %" of the combined figure. | [S15·D] |
| Folding carton alone: USD 141.09 B (2024) → 191.61 B (2032), CAGR 3.9 %. | [S16·D] |
| US corrugated shipments reached 381 billion sq ft in 2024 (reported in a search summary of the FBA annual report; the report itself was not opened). | [S18·A] |
| Mailer packaging: USD 39.39 B (2026) → 64.87 B (2034), CAGR 6.43 %; a separate source gives a US-only CAGR of 15.1 %. | [S17·D] |
| Mailer closure split 2023: self-adhesive strip ≈ 38.4 % share; tuck-top and lock-bottom named as other segments. | [S17·D] |
| Folding-carton end markets: food & beverage 26.9 % of the market (2024) in one source; "more than 50 %" in another; healthcare "more than 9 % of volume demand"; cosmetic & personal care fastest-growing (≈ 7.5 % CAGR). | [S15·D] [S36·D] |

**Reliability problems found in these reports (OBSERVED):**
- One snippet says "Regular Slotted Cartons dominated the folding carton packaging market (39 %)" — an RSC is a *corrugated* style, so that sentence mislabels segments. [S16·D]
- Food & beverage share of folding cartons: 26.9 % vs ">50 %" vs 40.9 % (ASEAN) — three sources, three numbers.
- "Mailer packaging" in these reports includes poly mailers and padded envelopes, so it is **not** a measure of die-cut mailer-box demand.

**INFERENCE:** the reports agree on one thing only — both corrugated and folding-carton are very large, and e-commerce/mailer formats are growing. They cannot rank *structures*, and they should not be used to.

### 2.2 Search-demand evidence

**UNKNOWN — not available.** Attempts: searches for keyword-volume data for "mailer box template", "tuck end box template", "pizza box template", "dieline" (Semrush/Ahrefs/Google-Trends style). No source published such numbers. See Appendix B for a seed keyword list to pull from Google Keyword Planner / Trends / Semrush yourself.

### 2.3 The only keyword number found (not Google, not decisive)

"display box template": **210 searches per month globally** according to RankHero, a keyword tool oriented to **Etsy** search. [S33·C] This is one keyword, from an Etsy-oriented tool, for a structure (display box) of unknown relevance — it must **not** be generalised.

### 2.4 Dieline-generator and template-library evidence (what incumbents choose to build)

| Library / tool | What was observed (via search summaries) | Source |
|---|---|---|
| Die Cut Templates | "over 35,000 vector packaging templates" — named structures: tuck end, snap lock, tuck top auto bottom, standard boxes, four-corner tray, fruit and vegetable boxes, gift boxes; also carton bags/pillows, tray boxes, covered solid board boxes (rigid), special boxes. Offers a custom dieline generator. | [S1·C] [S7·B] |
| DesignNBuy | "2,500+ FEFCO standardized ready die-line templates", dimension-driven generation (vendor claim). | [S1·C] |
| Pacdora | Template types: tuck end, gable, mailer, milk carton, cardboard boxes; cereal boxes, gift boxes; dimension + paper-thickness inputs; exports DXF/AI/PNG/JPG; separate pages for mailer dielines and a "bottom lock box" tool. | [S3·C] [S4·C] [S5·C] [S6·C] |
| Boxshot / Origami | "supports most common ECMA and FEFCO dielines" (FEFCO pages seen: 0214, 0216, 0403, 0426, 0471, 0713; ECMA A20.20.01.03, A10.20.03.03 style pages); the Boxshot product states its built-in set is "limited and basic". | [S8·C] |
| GoVisually | Free generators for RSC (0201-style), full overlap (0203), CSSC; length/width/height input. | [S9·C] |
| PackMyMan | Browser generator, FEFCO/ECMA structures, L/W/D input, SVG/DXF/PDF export. | [S10·C] |
| Boxes.py | Open-source laser-cut box generator with groups: Boxes, Boxes with flex, Trays and Drawer Inserts, Shelves, Parts, Misc — a *different paradigm* (finger-jointed sheet material), not folding dielines. | [S11·C] |
| Custom Box Makers | Free dielines "for every box style": mailer, tuck end, luxury rigid and others; also candle-box pages. | [S12·C] |
| Esko ArtiosCAD | One parametric tool with "US, ECMA, FEFCO and display standards"; ECMA library "completed"; FEFCO 12th-edition library with eCommerce designs and about 100 new codes. | [S32·C] |

**OBSERVED:** the structure families that recur across almost every generator are **tuck-end cartons, mailer boxes, auto-lock/snap-lock bottoms, slotted corrugated (0201-type), trays, gift boxes**. Rigid and bags appear in the largest catalogue only.
**INFERENCE:** a library is a statement of what vendors believe users need, not measured demand; counts such as "35,000" are catalogue size (including dimension variants), not user counts.

### 2.5 Manufacturer / retailer assortment (reliability B)

| Seller | Range observed | Source |
|---|---|---|
| Packlane | printed mailer boxes, shipping boxes, product boxes; stock mailer sizes 4×4×2 in to 14×10×4 in. | [S14·C] |
| Packhelp | two product-box types (classic, two-piece), four mailer-box types, shipping boxes, plain variants. | [S13·C] |
| Arka | mailer, shipping and product boxes. | [S14·C] |
| UK/EU retailers (lilpackaging, renubox, labelprint24, maxpack) | 0201 in many stock sizes (e.g. 180×120×100 … 580×380×380 mm); 0427 "pizza-style postal box" in many sizes (27×14×2.5 … 62×17×7 cm). | [S20·B] [S21·B] |
| Food-service distributors | one-piece auto-lock cake/bakery boxes with window in stock sizes 4½×4½×4½ … 19×14×4 in; takeout boxes, clamshells, pails. | [S25·B] [S26·B] |
| Wine/bottle packaging | 6-bottle corrugated boxes with dividers (e.g. 270×180×245 mm), bottle carriers. | [S30·B] |

### 2.6 E-commerce / DTC trend evidence

- "The 0201 and 0427 are the two most commonly used boxes in eCommerce" — stated by several UK/EU vendors. [S20·C] **Vendor claim, no statistic given.**
- Subscription/DTC brands use mailer boxes as brand carriers; small brands moving to custom-sized, low-minimum-order mailers (weak source). [S35·C]
- Custom-dimension demand is visible as services: freelancers selling "custom mailer box dieline from dimensions". [S34·C]

### 2.7 BoxCheck's own signal (OBSERVED, internal)

In the existing product, "Packaging" setup offers: **Folding carton, Pouch / flexible bag, Paper bag, Sleeve**; the print-method label "Cardboard packaging" carries a hint of typical board 0.3–0.8 mm (folding-carton range). There is **no corrugated entry** in the current taxonomy. (`boxcheck-web/src/lib/labelsPackagingFlow.ts`, `printMethods.ts`; `PROGRESS.md`.) [S37]
**INFERENCE:** BoxCheck's current user model is a *print-artwork* customer (carton/bag/sleeve), not a corrugated converter. Analytics (self-hosted Umami) do record custom events — `boxcheck-web/src/lib/analytics.ts` defines `trackEvent` with 15 call sites (e.g. `file_selected`, `check_started`, `check_completed`, `report_downloaded`) — but **none records the product or packaging type**, so real selection counts by structure are not available.

### 2.8 Evidence-quality summary

| Evidence type | Strength for ranking structures |
|---|---|
| Standards (FEFCO/ECMA classification) | Shows structures exist; says nothing about demand. |
| Generator/template libraries | Shows what vendors supply; family-level only. |
| Manufacturer assortments and stock-size listings | Shows what is sold in standard sizes; one of the better demand proxies. |
| Market reports | Context only; internally inconsistent. |
| Search volume | **Missing.** |
| User requests (forums, services) | Anecdotal. |
| BoxCheck analytics | Events exist, but none records product/packaging type — no per-structure signal. |

---

## 3. Packaging families

| Family | Typical material | Typical caliper | Construction paradigm | Dieline needs (observed) | Fits BoxCheck's current taxonomy? |
|---|---|---|---|---|---|
| **A. Corrugated slotted** (FEFCO 02xx) | Corrugated, E/B/C flute | E 1.3–1.6 mm, B 2.6–3.0 mm, C 3.6–4.2 mm [S31·C] | Single sheet, slotted flaps, joint | Scoring allowance tied to caliper; "corrugated will fold at its midpoint" [S31·C] | No |
| **B. Corrugated telescope / slide** (03xx, 05xx) | Corrugated | same | Several parts (lid + body, sleeve + tray) | Multi-sheet output; clearance between parts | No |
| **C. Corrugated folder / mailer** (04xx incl. 0426, 0427) | Corrugated (also paperboard mailers) | same | Single sheet, hinged walls, tabs/slots | Ear-lock fit depends on caliper | Partly (e-commerce mailers) |
| **D. Folding carton — tuck-end** (STE, RTE) | SBS/paperboard | ≈ 0.3–0.8 mm (BoxCheck hint) | Single sheet, glued seam, tuck flaps | Glue flap, thickness offset [S24·C] | **Yes — "Folding carton"** |
| **E. Folding carton — auto-lock / snap-lock bottoms** | paperboard | same | Single sheet, pre-glued, fold-kinematic bottom | Offset panels, angled creases [S6·C] | Yes |
| **F. Folding carton — trays, sleeves, gable, pillow** | paperboard | same | Single/two sheet; some curved | Sleeve + tray = two sheets | Sleeve: yes |
| **G. Rigid / set-up boxes** | 2–3 mm chipboard wrapped in paper [S27·C] | 2–3 mm | **Assembly**: board pieces + wrap sheet | Wrap allowances; "no universal clearance" for magnetic boxes [S27·C] | No |
| **H. Paper bags / envelopes** | paper | thin | Tube + gusset + glued base | Width/gusset/height; handle holes [S29·C] | **Yes — "Paper bag"** |
| **I. Inserts / dividers / carriers** | corrugated or paperboard | varies | Interlocking or die-cut pieces | Often product-specific | No |
| **J. Food service** (takeout, clamshell, pail, cake box) | SBS with barrier coat | ≈ 0.3–0.5 mm | Various one-piece folds | Standard-size SKUs | Partly |
| **K. Flexible pouches** | film | thin | Heat seal, no fold/crease | — | Yes — "Pouch" (out of dieline scope) |

---

## 4. Candidate structures

### 4.1 Technical prioritization framework (measurable inputs, no "best/worst")

Each candidate is described with **observable inputs**. Phase assignment follows **explicit gates** applied to those inputs; thresholds are mine and can be changed — the table lets you apply other thresholds.

| ID | Criterion | How it is measured (observable) |
|---|---|---|
| **D1** | Demand evidence breadth | Count (0–4) of structure-level evidence types confirmed in collected sources: **E1** appears in ≥ 1 dieline generator/library · **E2** offered by ≥ 1 manufacturer/retailer · **E3** classified in a public standard (FEFCO/ECMA) · **E4** sold in listed standard sizes. `●` = confirmed (counts), `◐` = family-level/indirect (does not count). |
| **F5/F6** | Family-level context | E5 market-report mention; E6 BoxCheck taxonomy entry (shown separately because they apply to whole families and would inflate counts). |
| **D2** | Breadth of use cases | Number of distinct product categories named for the structure in the collected sources. |
| **D3** | Custom-size relevance | `Y` if sources show custom-dimension generation/ordering for it; `S` if only stock sizes seen. |
| **K** | Construction class (parameterisation) | **C0** rectangles, slots, cut-outs only, no interlocks · **C1** C0 + static tabs/slots, dust flaps, relief notches, rounded corners · **C2** fold-kinematics-dependent geometry (angled creases, corner locks, gussets) or tapered/curved developments · **C3** multi-part assembly, wrap allowances, or non-developable surfaces. |
| **V** | Validation class | **V0** closed-form relations checkable against published drawings · **V1** needs ≥ 3–4 CAD reference exports (as we have for one structure) · **V2** needs physical sample or folding simulation (locks must engage) · **V3** depends on production process (wrap, grain, machine). |
| **P** | Production-ready dieline needs | **P0** cut/crease/glue only · **P1** + caliper-driven scoring/crease offsets · **P2** + multi-part, wrap allowance, grain, tolerance data. |
| **M** | Material applicability | Materials seen in sources. |
| **S** | Single-sheet dieline? | Y/N. |

**Gates (provisional):**
- **Phase 1 eligibility:** D1 ≥ 3 · D3 = Y · K ≤ C1 · V ≤ V1 · S = Y · P ≤ P1.
- **Phase 2 eligibility:** not Phase 1, and D1 ≥ 2, K ≤ C2, V ≤ V2 (or Phase-1-eligible parts waiting on a sibling template, see §9).
- **Phase 3:** everything else (K = C3, V = V3, multi-part, or D1 < 2).

The gates give **eligibility**, not an order within a phase. The order inside a phase needs the missing demand data (§13).

### 4.2 Candidate register

Codes in brackets are the public code when one exists; a code is **never** claimed unless a source states it.

| # | Structure | Code | Material(s) | Typical use (sources) | Custom-size relevance |
|---|---|---|---|---|---|
| S01 | Regular slotted container (RSC) | FEFCO 0201 | corrugated (E/B/BC/EB) | general shipping/storage [S22·B] | Y — generators take L/W/D [S9]; stock sizes also sold [S20] |
| S02 | Full overlap / overlap slotted | FEFCO 0203 / 0204 | corrugated | heavier or sensitive items [S2·C] | Y — generator [S9] |
| S03 | Insertable-base carton | FEFCO 0215 | corrugated | heavier technical items [S2·C] | S |
| S04 | Hinged-lid mailer / postal / "pizza-style" box (ear-lock) | FEFCO 0427 | corrugated (E/B); paperboard mailers | e-commerce, subscription, pizza [S20] [S21] | Y — freelance custom dielines [S34]; stock sizes [S20] |
| S05 | Folder with lid and extended side flaps | FEFCO 0426 | corrugated | shelf-ready/e-commerce [S20] | S |
| S06 | Folder with tuck-in (double side walls) | FEFCO 0421 / 0422 | corrugated | light shipping; open sides noted [S20] | S |
| S07 | Bottle/wine carrier with crossed dividers | no code asserted | corrugated | 6-bottle carriers [S30] | S (stock sizes) |
| S08 | Inserts / dividers (generic) | FEFCO 09xx series (interior fitments) [S19] | corrugated, paperboard | protection, partitioning | Often product-specific (HYPOTHESIS) |
| S09 | Straight tuck end (STE) | ECMA A20.20.03.01 (per one commercial summary) | SBS paperboard | cosmetics, retail, cereal, candles [S23] [S4] | Y — generators [S3] |
| S10 | Reverse tuck end (RTE) | ECMA A20.20.03.02 (same summary) | SBS paperboard | cosmetics, skincare, perfume, candles, pharma [S23] | Y |
| S11 | Auto-lock / crash-lock bottom (tuck-top auto bottom) | not asserted | paperboard | heavier carton products; cake boxes [S23] [S25] | Y — generator [S6] |
| S12 | Snap-lock / 1-2-3 bottom | not asserted | paperboard | heavier objects [S23] | S |
| S13 | Sleeve (and tray + sleeve / slide) | FEFCO 05xx for corrugated slide boxes [S19] | paperboard / corrugated | candle, gift, drawer packs [S28] | S |
| S14 | Four-corner tray | not asserted | paperboard | cake/bakery trays [S25] | S |
| S15 | One-piece bakery/cake box with window (auto-lock + tuck lid) | not asserted | SBS | cakes, donuts, cookies [S25] | S (stock sizes) |
| S16 | Hinged takeout / clamshell | not asserted | SBS, kraft, bagasse | burgers, sandwiches [S26] | S |
| S17 | Oyster pail / takeout box / barn | not asserted | coated SBS | Asian takeout, heavy meals [S26] | S |
| S18 | Gable box | not asserted | paperboard | food, gifts [S4] | S |
| S19 | Pillow box | not asserted | paperboard | jewellery, small gifts [S27] | S |
| S20 | Rigid lid-and-base | FEFCO 06xx (rigid) [S19] | chipboard + wrap | luxury, premium [S27] | Y (bespoke) |
| S21 | Rigid magnetic / book / shoulder-neck | not asserted | chipboard + wrap | luxury gifts [S27] | Y (bespoke) |
| S22 | Gusseted paper bag (incl. SOS) | not asserted | paper | retail, gifts [S29] | Y — parametric a/b/c templates [S29] |
| S23 | Envelope-style bag | not asserted | paper | mailing | S |
| S24 | Counter display box | not asserted | paperboard | retail display [S33] | unknown |
| S25 | Pouch / flexible bag | — | film | — | out of scope (no folds/creases) |

---

## 5. Demand evidence by structure

`●` confirmed (counts toward D1) · `◐` family-level/indirect · `○` not observed. E1 generator/library · E2 manufacturer/retailer · E3 public standard · E4 stock-size listing. **F5** market report mention, **F6** BoxCheck taxonomy are family-level and *not* counted.

| # | Structure | E1 | E2 | E3 | E4 | **D1** | F5 | F6 | D2 (categories named) | D3 |
|---|---|---|---|---|---|---|---|---|---|---|
| S01 | RSC 0201 | ● [S9][S10] | ● [S20][S13] | ● [S19] | ● [S20] | **4** | ● [S22] | ○ | 3 (e-commerce, electronics, industrial) | Y |
| S02 | 0203 / 0204 | ● [S9] | ◐ [S2] | ● [S19] | ◐ | **2** | ○ | ○ | 1 (heavier items) | Y |
| S03 | 0215 | ○ | ◐ [S2] | ● [S19] | ○ | **1** | ○ | ○ | 1 | S |
| S04 | 0427 mailer/postal/pizza-style | ◐ [S5] | ● [S20][S21][S13][S14] | ● [S19] | ● [S20][S14] | **3** | ◐ [S17] | ○ | 4+ (e-commerce, subscription, gift, pizza, candle shipping) | Y |
| S05 | 0426 | ● [S8] | ● (retailer datasheets) | ● [S19] | ◐ | **3** | ○ | ○ | 1–2 | S |
| S06 | 0421 / 0422 | ○ | ● [S20] | ● [S19] | ○ | **2** | ○ | ○ | 1 | S |
| S07 | Bottle carrier | ◐ [S30] | ● [S30] | ◐ | ● [S30] | **2** | ○ | ○ | 2 (wine, beer) | S |
| S08 | Inserts/dividers | ○ | ● [S30] | ● [S19] | ○ | **2** | ○ | ○ | 2 | product-specific |
| S09 | STE | ● [S3][S7] | ● [S23][S12] | ● ¹ | ○ | **3** | ● | ● | 5 (cosmetics, tubes, candles, cereal, retail shelf) | Y |
| S10 | RTE | ● [S4][S7] | ● [S23] | ● ¹ | ◐ | **3** | ● | ● | 6 (cosmetics, skincare, perfume, candles, pharma, promotional) | Y |
| S11 | Auto-lock / crash-lock | ● [S6][S7] | ● [S23] | ◐ | ● [S25] | **3** | ● | ● | 3 (cake/bakery, heavy retail, e-commerce) | Y |
| S12 | Snap-lock / 1-2-3 | ● [S7] | ● [S23] | ○ | ○ | **2** | ● | ● | 1–2 | S |
| S13 | Sleeve / tray + sleeve | ◐ [S7] | ● [S28] | ● (FEFCO 05xx, corrugated only) | ○ | **2** | ○ | ● | 2 (candles, gifts) | S |
| S14 | Four-corner tray | ● [S7] | ● [S25] | ○ | ● [S25] | **3** | ● | ○ | 2 | S |
| S15 | Bakery window box | ◐ | ● [S25] | ○ | ● [S25] | **2** | ● | ○ | 1 (bakery) | S |
| S16 | Hinged takeout / clamshell | ○ | ● [S26] | ○ | ◐ | **1** | ○ | ○ | 1 | S |
| S17 | Oyster pail / takeout box | ○ | ● [S26] | ○ | ◐ | **1** | ○ | ○ | 1 | S |
| S18 | Gable box | ● [S4] | ● | ○ | ○ | **2** | ○ | ○ | 2 (food, gifts) | S |
| S19 | Pillow box | ○ | ● [S27] | ○ | ○ | **1** | ○ | ○ | 1 | S |
| S20 | Rigid lid-and-base | ● [S7] | ● [S27] | ● (06xx) | ○ | **3** | ○ | ○ | 3+ (luxury, gifts, candles) | Y |
| S21 | Rigid magnetic/book/shoulder | ◐ | ● [S27] | ○ | ○ | **1** | ○ | ○ | 2 | Y |
| S22 | Paper bag | ● [S7][S29] | ● | ○ | ○ | **2** | ○ | ● | 2 (retail, gifts) | Y |
| S23 | Envelope-style bag | ◐ | ◐ | ○ | ○ | **0** | ○ | ○ | 1 | S |
| S24 | Display box | ◐ | ◐ | ○ | ○ | **0** | ○ | ○ | 1 | unknown |

¹ ECMA classification of tuck-end cartons is supported by several summaries (group A, "20" = tuck-in closure); the **exact code numbers** (A20.20.03.01 = STE, A20.20.03.02 = RTE) rest on one commercial summary [S38·C], while other results described A20.20.03.01 only as "folding box with tuck-in flap". Treat the code numbers as **unverified**.

**Coverage matrix — product categories named in collected sources (OBSERVED), and which structures serve them:**

| Category | Structures named in sources |
|---|---|
| e-commerce shipping | S01, S04, S05, paperboard mailers |
| subscription / DTC gifting | S04, S13, S20/S21 |
| cosmetics / skincare / perfume | S10, S09, S20, S13 |
| candles | S09, S10, S13, S20, S04 (shipping jars) |
| pharma / healthcare | S10, S09 |
| bakery / cake | S15, S14, S11 |
| pizza | S04 (pizza-style) |
| takeout / food service | S16, S17, lidded trays |
| bottles / wine | S07, S08, S22 |
| retail shopping | S22 |
| luxury gifts | S20, S21 |
| small gifts / favours | S19, S18 |

---

## 6. Parameterization difficulty

Measurable descriptors. "Free parameters" = independent size inputs a generator exposes in the sources, not hidden constants.

| # | Structure | Size inputs (sources) | Style/extra parameters (sources) | Interlocks / tabs | Curves / taper | Caliper-sensitive | **K** |
|---|---|---|---|---|---|---|---|
| S01 | RSC | L, W, D | joint width | none | none | scoring allowance (corrugated) [S31] | **C0** |
| S02 | 0203/0204 | L, W, D | overlap | none | none | scoring allowance | **C0** |
| S03 | 0215 | L, W, D | — | insertable base | none | scoring allowance | **C1** (HYPOTHESIS — details unseen) |
| S04 | 0427 | L, W, D | lid depth, ear-lock tabs | ear locks (static) | possible | ear-lock fit | **C1** |
| S05 | 0426 | L, W, D | side-flap extension | tabs/flaps | none | scoring allowance | **C1** |
| S06 | 0421/0422 | L, W, D | double side walls | tuck | none | scoring | **C1** |
| S07 | Bottle carrier | L, W, D, cell count | divider layout, handle | interlocking cross dividers | handle slot | scoring | **C2** |
| S08 | Inserts | product-dependent | cavities | slots | arbitrary | — | **C2/C3** (HYPOTHESIS) |
| S09 | STE | L, W, D | glue flap, tuck length, dust flaps, bleed [S24] | tuck slits/locks | rounded corners | thickness offset for glue [S24] | **C1** |
| S10 | RTE | L, W, D | same + flap swap | same | same | same | **C1** |
| S11 | Crash-lock | L, W, D | bottom-lock allowance, locking tabs [S6] | angled creases, triangular flaps | none | high (offset panels) | **C2** |
| S12 | Snap-lock | L, W, D | flap geometry | locking flaps | none | medium | **C2** |
| S13 | Sleeve (+tray) | L, W, D | tray/sleeve clearance | none | none | clearance | **C0** (single) / two sheets |
| S14 | Four-corner tray | L, W, D | corner lock | corner locks | none | medium | **C2** |
| S15 | Bakery window box | L, W, D | window size | auto-lock + corner locks | none | medium | **C2** |
| S16 | Clamshell | L, W, D | hinge | locking tab | none | low | **C1/C2** |
| S17 | Oyster pail | volume sizes | handle | interlocking flaps | taper | low | **C2** |
| S18 | Gable | L, W, D | gable angle, handle | top lock | angled panels | low | **C2** |
| S19 | Pillow | L, W, D | curve | tuck | non-developable curves | low | **C3** |
| S20 | Rigid lid-and-base | L, W, D | lid depth, board thickness, wrap | none | wrapped corners | very high (clearances) | **C3** |
| S21 | Rigid magnetic/book | L, W, D | spine, magnets | magnet pockets | rounded spine | very high ("no universal clearance") [S27] | **C3** |
| S22 | Paper bag | width, gusset, height [S29] | handle holes, top fold | glued base | triangular folds | low | **C2** |
| S23 | Envelope-style | W, H | flap | glue | none | low | **C1** |
| S24 | Display box | L, W, D | easel/shelf | locks | cut-outs | low | **C2** |

---

## 7. Geometry / validation difficulty

| # | Structure | Reference we hold | What validation needs | **V** | **P** | Single sheet |
|---|---|---|---|---|---|---|
| S01 | RSC | none | Closed-form relation; compare with a published FEFCO drawing at 3+ sizes | **V0** | P1 | Y |
| S02 | 0203/0204 | none | same | **V0** | P1 | Y |
| S03 | 0215 | none | published drawing + CAD export | **V1** | P1 | Y |
| S04 | 0427 | none directly (**our four-PDF structure is a neighbour, identity unproven — §12**) | CAD exports at ≥ 4 sizes + lock-fit check | **V1** | P1 | Y |
| S05 | 0426 | none | same | **V1** | P1 | Y |
| S06 | 0421/0422 | none | same | **V1** | P1 | Y |
| S07 | Bottle carrier | none | physical fit + interlock check | **V2** | P1 | Y |
| S08 | Inserts | none | per-product physical fit | **V2/V3** | P1 | Y |
| S09 | STE | none | CAD exports ≥ 4 sizes; glue flap offset | **V1** | P1 | Y |
| S10 | RTE | none | same | **V1** | P1 | Y |
| S11 | Crash-lock | none | folding simulation or physical sample (bottom must lock) | **V2** | P1 | Y |
| S12 | Snap-lock | none | same | **V2** | P1 | Y |
| S13 | Sleeve (+tray) | none | clearance check across two sheets | **V1** | P1/P2 | Y/N (tray+sleeve = 2) |
| S14 | Four-corner tray | none | physical sample | **V2** | P1 | Y |
| S15 | Bakery window box | none | physical sample + window rules | **V2** | P1 | Y |
| S16–S17 | Clamshell / pail | none | physical sample; tapered development | **V2** | P1 | Y |
| S18 | Gable | none | physical sample | **V2** | P1 | Y |
| S19 | Pillow | none | non-developable curves → simulation | **V3** | P1 | Y |
| S20–S21 | Rigid | none | production process (wrap, grain, spine) | **V3** | **P2** | **N** (board pieces + wrap) |
| S22 | Paper bag | none | gusset fold validation | **V2** | P1 | Y |
| S23 | Envelope | none | closed-form | **V1** | P0 | Y |

**Cross-cutting (OBSERVED + INFERENCE):**
- For **all** structures, "production-ready" means validity against *physical folding*, not just plausible 2D geometry: sources repeatedly tell users to "confirm the final die with your printer/converter" [S24·C], and design of lock bottoms "requires technical knowledge across multiple fields … closely linked to the type of material used, the production machinery" [S6·C]. Generated dielines are therefore treated as **drafts needing converter confirmation**.
- Caliper compensation is the main family-dependent rule: corrugated needs a scoring allowance related to caliper because it folds at its midpoint [S31·C]; thin paperboard is much less sensitive; rigid boxes need clearance set from board, wrap and lid geometry [S27·C].
- Our four-PDF analysis gives one useful fact for validation methodology: a reference-export pair set (one parameter changed at a time) plus a normalisation layer can reproduce a structure within ≈ 0.01 mm. That method is reusable for any V0/V1 structure, but each structure still needs its own references.

---

## 8. Proposed BoxCheck template architecture

### 8.1 Question: one engine or one per material family?

**Recommendation (INFERENCE, with evidence):** **one geometry core with pluggable template families and material profiles**, not separate engines per material.

```
                              BOXCHECK STRUCTURAL
                                     │
   ┌─────────────────────────────────┴─────────────────────────────────┐
   │  SHARED CORE                                                      │
   │   • Primitives: line / arc / Bézier / path (mm)                   │
   │   • Dieline model: layers CUT · CREASE · PERF · SLOT · GLUE       │
   │   • Panel graph: panels, folds, mirrors, double-crease strips     │
   │   • Exporters: SVG · PDF · DXF (later)                            │
   │   • Normalisation + regression harness (reference JSON)           │
   └───────────────┬───────────────────────────┬───────────────────────┘
                   │                           │
        TEMPLATE FAMILIES                MATERIAL / PROCESS PROFILES
   (code: construction rules)           (data + a compensation strategy)
   ┌────────────────────────────┐       ┌─────────────────────────────────┐
   │ slotted (0201/0203…)       │       │ corrugated: score allowance     │
   │ folder/mailer (0427/0426)  │       │ paperboard: crease offset,      │
   │ tuck-end (STE/RTE)         │       │             glue thickness      │
   │ lock-bottom (auto/snap)    │       │ rigid:      wrap + clearance    │
   │ tray / sleeve              │       │ paper bag:  gusset/fold rules   │
   │ bag (gusset)               │       └─────────────────────────────────┘
   │ ─ assembly layer ─         │
   │ rigid (multi-sheet output) │       Excluded from the engine:
   └────────────────────────────┘       3-D folding simulation, nesting,
                                        pouches (heat-seal, no folds)
```

### 8.2 What is shared vs family-specific

| Layer | Shared across families? | Evidence |
|---|---|---|
| Vector primitives, layers, export | **Yes** | Every incumbent exports the same cut/crease/glue layers (DXF/AI/SVG/PDF) across families [S3][S10][S7]. |
| Panel graph, fold semantics, mirror, double-crease strips | **Yes** | Needed for every folded structure; our four-PDF structure already needs them (mirror symmetry ≤ 0.001 mm, double creases of 1u and 2u). |
| Normalisation + regression harness | **Yes** | Method proven on our four references. |
| Template construction rules | **No — per structure** | Each structure differs (glue flap, tuck, lock geometry). |
| Compensation strategy (caliper handling) | **Interface shared, implementation per family** | Corrugated midpoint fold vs paperboard vs rigid wrap [S31][S27]. |
| Material profile (caliper, minimum feature size, tolerance) | **Same schema, different data** | See §3. |

### 8.3 Evidence that a single engine is workable

- **OBSERVED:** Esko ArtiosCAD runs FEFCO, ECMA and display standards in one parametric framework [S32·C]; Pacdora, Boxshot, PackMyMan, GoVisually and Die Cut Templates each serve several families from one generator [S3][S8][S9][S10][S7].
- **OBSERVED (from the user's ArtiosCAD session, brief §3–4):** the same corrugated-catalogue template (workspace 31010W) was run on a *folding-carton* board (SBS I-SBS-16). This shows the template geometry is parameterised by a caliper-like unit, not hard-wired to flute thickness.
- **OBSERVED (our PDFs):** all allowances in the reference structure are integer multiples of one unit `u ≈ 0.794 mm`, plus one metric constant (10 mm) — a *profile* concept, not a family engine.

### 8.4 When separate engines **would** be justified (decision criteria)

A separate engine/kernel is warranted only if a family breaks the shared model in one of these measurable ways:

1. **Not single-sheet:** output is several coordinated sheets (rigid boxes: board pieces + wrap). → Add an **assembly layer** on top of the core; no new kernel.
2. **Not fold/crease based:** heat-seal pouches. → **Out of scope.**
3. **Non-developable surfaces** (pillow box): needs simulation. → **Phase 3 research.**
4. **Product-specific geometry** (inserts): inputs are product shapes, not L/W/D. → Different input model; core still reusable.

**HYPOTHESIS:** none of Phase 1 or Phase 2 triggers a split. This should be tested by prototyping the core on two different families (e.g. a slotted RSC and a tuck-end carton) before committing — see §14.

### 8.5 Template definition (conceptual contract, not an implementation)

Each template family declares: **inputs** (L, W, D, board profile, style flags), **parameters** (named allowances, each tagged `VALIDATED / PROVISIONAL / UNKNOWN` as in `structural-spec.md`), **panel graph**, **construction rules**, **supported ranges** (outside the validated range the template refuses to generate), and **reference fixtures** (normalised JSON per sample). This keeps the "no assumption becomes a formula" rule from the research phase.

---

## 9. Phase 1 template candidates

Gate result (§4.1): D1 ≥ 3, D3 = Y, K ≤ C1, V ≤ V1, single sheet, P ≤ P1.

| # | Structure | D1 | D3 | K | V | Gate result | Note |
|---|---|---|---|---|---|---|---|
| S01 | RSC (0201) | 4 | Y | C0 | V0 | **Eligible** | simplest panel grammar; highest D1 |
| S04 | Hinged-lid mailer (0427) | 3 | Y | C1 | V1 | **Eligible** | family of our four-PDF structure (neighbour, identity unproven) |
| S09 | Straight tuck end | 3 | Y | C1 | V1 | **Eligible** | in BoxCheck taxonomy (Folding carton) |
| S10 | Reverse tuck end | 3 | Y | C1 | V1 | **Eligible** | differs from S09 by flap placement → same family template with a flag (INFERENCE) |
| S05 | 0426 | 3 | S | C1 | V1 | Fails D3 (custom-size not observed) | sibling of S04; add after S04 (shared panel grammar) |

**Smallest useful Phase 1 library (INFERENCE):** **3 templates** — `0201`, `0427`, `tuck-end (STE+RTE as one family with a flap-direction flag)`. Coverage against the observed product categories (§5): e-commerce shipping, subscription/DTC, cosmetics, candles, pharma, pizza = **6 of 12** categories; uncovered: bakery, takeout, bottles/wine, retail bags, luxury, small gifts.
**HYPOTHESIS:** this is the smallest set that spans both corrugated shipping and printed carton demand while staying at K ≤ C1 and V ≤ V1. Whether S01 or S04/S09 should come *first* inside Phase 1 cannot be decided without search-volume and user data (§13).

## 10. Phase 2 candidates

| # | Structure | Why not Phase 1 (measured) | Dependency |
|---|---|---|---|
| S11 | Crash-lock bottom | K = C2, V = V2 | needs folding validation; D1 = 3, family-level demand E5/E6 present |
| S12 | Snap-lock / 1-2-3 | K = C2, V = V2, D1 = 2 | shares lock-bottom grammar with S11 |
| S14 | Four-corner tray | K = C2, V = V2 | bakery/food categories |
| S15 | Bakery window box | K = C2, V = V2, D1 = 2 | combines S11/S14 + window cut-out |
| S13 | Sleeve (+ tray) | D1 = 2; tray+sleeve = two sheets | in BoxCheck taxonomy (Sleeve); low K |
| S22 | Gusseted paper bag | K = C2, V = V2, D1 = 2 | in BoxCheck taxonomy (Paper bag); paper not board |
| S02 | 0203 / 0204 | D1 = 2 | near-free extension once S01 exists (same grammar) |
| S05 | 0426 | D3 = S | near-free extension once S04 exists |
| S07 | Bottle carrier | K = C2, V = V2, D1 = 2 | interlocking dividers |

## 11. Phase 3 candidates

| # | Structure | Reason (measured) |
|---|---|---|
| S20, S21 | Rigid boxes | K = C3, V = V3, P = P2, multi-sheet assembly; clearances depend on board/wrap/magnets [S27] |
| S19 | Pillow box | K = C3 (non-developable curves), V = V3 |
| S18 | Gable box | D1 = 2, K = C2, V = V2 |
| S16, S17 | Takeout clamshell / pail | D1 = 1, tapered or locking geometry |
| S08 | Inserts / dividers | input model is product-specific |
| S03, S06 | 0215, 0421/0422 | D1 ≤ 2, K = C1 — candidates for Phase 2 if demand data supports |
| S23, S24 | Envelope bag, display box | D1 = 0; evidence too thin |
| S25 | Pouch | out of dieline scope |

---

## 12. Current four-PDF structure assessment

**What the structure is (OBSERVED, from `structural-spec.md`):** a one-piece folder-type tray — floor with four hinged walls (front, back, two ends), a cover hinged to the back wall with two rounded side flaps and a rounded tuck flap, one slot in the floor at the front fold with a matching tab-width cut on the front flap's edge, double creases, no glue flap. Per the research brief it was created in ArtiosCAD from a corrugated-catalogue template (workspace 31010W) on an SBS board.

**Public-standard comparison (§H of `structural-spec.md`, restated):** topology is **consistent with the FEFCO 04xx folder family** (neighbours 0426/0427), but public 0427 descriptions mention ear-locks at the sides ("side panels … pressed into the slots") and ours has a single front slot/tab and extended end panels. **Identity: UNKNOWN. No FEFCO/ECMA code is claimed.**

**Against the gates (INFERENCE):**

| Criterion | Value | Basis |
|---|---|---|
| D1 (exact structure) | **UNKNOWN** — cannot be counted because identity is unproven | no source names this exact structure |
| D1 (neighbour 0427) | 3 ● + 1 ◐ | §5 |
| K | **C1** with unresolved C2-like elements (taper and radius laws unknown) | `structural-spec.md` §E |
| V | **V1** — four references, laws only partially identified | `structural-spec.md` |
| P | P1 (caliper unit `u` governs allowances) | `structural-spec.md` §F |
| Single sheet | Y | — |

**Should it remain the technical research template? — Yes (INFERENCE).** Reasons, all observable:
1. It is the **only** structure for which we hold normalised vector references and a dependency analysis; a validation harness can be built and proven on it immediately.
2. It exercises most primitives later templates need: panel graph, double creases, mirror symmetry, rounded tangent arcs, relief notches, slot with stadium ends, caliper-unit allowances.
3. Its mailer-family neighbours (0427/0426) are in the Phase 1/2 candidate set, so primitive work is reusable, not throw-away.

**Should it be the first *commercial* template? — Not decided; a separate question.**
- Against: demand for **this exact** structure is not evidenced (D1 unknown); style laws (radius staircase, taper constant) are validated at two values only; it is specific to one ArtiosCAD workspace; BoxCheck's current taxonomy does not include corrugated.
- For: if a later step establishes that it equals or closely matches the 0427 mailer, then technical and commercial template **coincide** (0427 has D1 = 3 ●, stock sizes, e-commerce relevance).
- **Decision rule:** if identity with 0427 is confirmed by an official drawing or a CAD export of the 0427 standard, keep it as first commercial *and* technical template; otherwise use it only as the engine's regression fixture and obtain **new references** for the first commercial template (candidates: STE/RTE for BoxCheck's carton audience, 0201 for corrugated).

---

## 13. Missing evidence

| Gap | Why it matters | How to close |
|---|---|---|
| **Search volume** for template/dieline queries by structure | Primary demand signal; absent | Google Keyword Planner / Trends / Semrush on Appendix B list (user action; not obtainable here) |
| **Real usage inside generators** (most-downloaded templates, traffic by page) | Revealed demand vs vendor catalogue | Competitor traffic tools; public download counters |
| **Sales share by structure** from manufacturers | Actual market, not catalogue | Not public; interviews with 2–3 converters |
| **BoxCheck funnel/selection data** | Our users' real mix | Umami custom events exist but none records product/packaging type; adding an enum-only event (no filenames/content) fits the current analytics policy |
| **Official FEFCO/ECMA catalogue** | Authoritative code ↔ structure mapping | Obtain licensed/free PDFs outside this environment (FEFCO PDF located but not readable here [S19]) |
| **Regional split** (EU FEFCO vs US) | Demand differs by region | Region-specific keyword and distributor data |
| **Custom vs standard size ratio** per structure | Decides if parametric generation is the value | User survey; request logs from similar tools |
| **Reliable market statistics** | Aggregator snippets conflict | Primary sources (trade associations, FBA, PPC/FCA, Smithers) |
| **Physical validation resources** | Needed for V2 structures | Access to a sample table / converter |

---

## 14. Recommended next research steps

1. **Pull search data (user action, 1–2 hours):** run Appendix B through Keyword Planner/Trends; export volumes for US, UK, DE, UA; compare *within families* only.
2. **Competitor inventory from allowed access:** have someone with unrestricted browsing enumerate Pacdora / Boxshot / Die Cut Templates / PackMyMan category lists and note which structures are free vs paid — gives an "incumbent coverage" table without relying on summaries.
3. **Short user survey (10–20 respondents)** among BoxCheck's target users (small print shops, DTC brands, designers): "which structure did you last need a dieline for?" and "custom size or standard?". Cheapest direct demand evidence.
4. **Obtain the official FEFCO "Codes of Designs" PDF and ECMA catalogue** and record exact drawings for S01, S04, S05, S09, S10 — to settle code mapping and to check whether our four-PDF structure matches 0427/0426.
5. **ArtiosCAD sessions** (when available): export one-parameter-at-a-time references for the Phase 1 structures (0201, 0427/0426 standard, STE, RTE) with 1:1 export; and settle the open questions in `structural-spec.md` §J.
6. **Architecture feasibility check (research only):** specify the shared core's data model (Path, Dieline, PanelGraph, material profile, supported-range guard) on paper against two *different* families (RSC and STE) and list what does not fit. This tests §8.4's HYPOTHESIS before any implementation.
7. **Legal/IP review** of using FEFCO/ECMA structure descriptions and of the derived-from-PDF parameters, before any commercial release.

---

## Appendix A — Sources

Reliability grade after each: **A** standards/trade body · **B** manufacturer/retailer · **C** vendor marketing/blog · **D** aggregator snippet. All were consulted via **search-result summaries**; pages were not fetched (see method limits).

| ID | Source | Used for |
|---|---|---|
| S1 | [DesignNBuy — 7 best dieline generators](https://www.designnbuy.com/blog/best-dieline-generators/) · C | library sizes, tool list |
| S2 | [DesignNBuy — top-selling FEFCO styles](https://designnbuy.com/?p=209586) · C | 0201/0204/0215/0427 |
| S3 | [Pacdora dieline generator](https://pacdora.com/tools/dieline-generator) · C | generator inputs/exports |
| S4 | [Pacdora dielines](https://www.pacdora.com/dielines) · C | template types |
| S5 | [Pacdora mailer box dielines](https://www.pacdora.com/dielines/mailer-box-dielines) · C | mailer category |
| S6 | [Pacdora bottom lock box dieline](https://www.pacdora.com/tools/bottom-lock-box-dieline) · C | lock-bottom parameters |
| S7 | [Die Cut Templates — packaging](https://www.diecuttemplates.com/help/packaging) · B | library structures |
| S8 | [Boxshot Origami dieline generator](https://boxshot.com/origami/tutorials/basic/7-dieline-generator/) · C; [FEFCO 0426 page](https://www.boxshot.com/dielines/fefco/0426/) | ECMA/FEFCO coverage |
| S9 | [GoVisually dieline tool](https://govisually.com/free-tools/dieline) · C; [RSC](https://govisually.com/free-tools/dieline/rsc-box-dieline); [full overlap](https://govisually.com/free-tools/dieline/full-overlap-box-dieline) | slotted generators |
| S10 | [PackMyMan](https://peerpush.com/p/packmyman) · C | FEFCO/ECMA generator |
| S11 | [Boxes.py review](https://hackspace.raspberrypi.com/articles/boxes-py-review) · C; [docs](https://boxes-audreyfeldroy.readthedocs.io/en/latest/README.html) | open-source generator |
| S12 | [Custom Box Makers free dielines](https://www.customboxmakers.com/free-dieline-templates/) · B; [candle boxes](https://www.customboxmakers.com/candle-boxes/) | styles, candles |
| S13 | [Packhelp — boxes for product packaging](https://packhelp.com/boxes-for-product-packaging) · B | product range |
| S14 | [Packlane review](https://www.ecommerceceo.com/reviews/packlane/) · C; [Arka resources](https://www.arka.com/pages/resources-hub) · B | range, stock sizes |
| S15 | [GMI — corrugated and folding carton market](https://gminsights.com/industry-analysis/corrugated-and-folding-carton-packaging-market/market-share) · D | market size |
| S16 | [Credence — folding carton](https://www.credenceresearch.com/report/folding-carton-packaging-market) · D; [folding-carton share analysis](https://ameliass.substack.com/p/folding-cartons-market-share-analysis) · D | segment data (and RSC mislabel) |
| S17 | [Research and Markets — mailer packaging](https://www.researchandmarkets.com/reports/6069194/mailer-packaging-global-strategic-business) · D; [Market Research Future](https://www.marketresearchfuture.com/es/reports/mailer-packaging-market-30792) · D | mailer market |
| S18 | [FBA annual report](https://members.fibrebox.org/upload/2024/Store/FBA%20Annual%20Report%20-%20Non%20Members.pdf) · A (not opened; figure from search summary) | US shipments |
| S19 | [FEFCO Codes of Designs (official PDF, unreadable here)](https://www.fefco.org/sites/default/files/documents/FEFCO_Codes_of_Designs.pdf) · A; [Model Group knowledge base](https://modelgroup.com/ch/en/packaging/knowledge-base/Verpackungstypen.html) · B; [Thimm](https://thimm.com/en/packaging/fefco) · B | code series 0100–0900 |
| S20 | [Lil Packaging — FEFCO codes](https://eu.lilpackaging.com/blogs/packaging-knowledgebase/what-are-fefco-codes-plus-the-difference-between-cardboard-boxes-postal-boxes) · B; [Renubox](https://www.renubox.com/fefco-codes) · B; [Packhelp FEFCO](https://packhelp.com/fefco-codes/) · B | 0201/0427/0421/0426, stock sizes |
| S21 | [Labelprint24 0427](https://www.labelprint24.com/en/products/hinged-lid-box-fefco-0427-230.php) · B; [Onlineprinters hinged lid boxes](https://www.onlineprinters.ie/p/hinged-lid-boxes-4) · B | 0427 construction |
| S22 | [Packmage — most common box styles](https://www.packmage.com/about/article/447-B_The_most_commonly_used_box_styles) · C; [PCA](https://www.packagingcorp.com/?p=9557) · B | RSC as most common |
| S23 | [STTARK folding carton styles](https://sttark.helpscoutdocs.com/article/201-folding-carton-styles) · B; [Meyers tuck-end](https://meyers.com/meyers-blog/tuck-end-folding-cartons-types-examples/) · B; [Vivopak RTE](https://www.vivopak.com.au/custom-boxes/styles/reverse-tuck-end-box/) · B; [CartonCraft](https://cartoncraftinc.com/folding-carton-structures/) · B; [CCL closure styles](https://cclhealthcare.com/folding-carton-closure-styles/) · B; [Packaging-warehouse crash lock](https://www.packaging-warehouse.com/en/adviser/crash-lock-base-280) · B | carton structures |
| S24 | [Pack.ly — tuck end dieline](https://www.pack.ly/en/blog/post/dieline-tuck-end-box) · C | tuck-end anatomy/parameters |
| S25 | [Imperial Dade cake box](https://www.imperialdade.com/catalog/product-detail/cake-box-14x10x4-in-white-auto-lock-bottom-1-piece-with-window-100-case?id=36312) · B; [WebstaurantStore cake box](https://www.webstaurantstore.com/10-x-10-x-5-white-window-cake-bakery-box-bundle/24510105WBBL.html) · B | bakery boxes, stock sizes |
| S26 | [Graphic Packaging — takeout](https://www.graphicpkg.com/?p=6734) · B; [Napco clamshell](https://napconational.com/takeaway-delivery/clamshell-box) · B | food service |
| S27 | [PakFactory — rigid boxes](https://pakfactory.com/blog/packaging-types-rigid-boxes) · C; [Packmojo — rigid vs magnetic](https://packmojo.com/blog/rigid-box-vs-magnetic-closure-box-luxury-brands/) · C; [Tiny Box Company](https://tinyboxcompany.co.uk/blog/post/unpacking-different-box-types-from-rigid-lid-and-base-to-pillow-boxes) · B | rigid structures, clearance note |
| S28 | [Packmojo — candle boxes](https://packmojo.com/blog/candle-packaging-boxes/) · C | candle structures |
| S29 | [Die Cut Templates — bag dieline](https://www.diecuttemplates.com/dielines/52194/carton-bags-pillows-becf-1219) · B | paper-bag parameters |
| S30 | [GWP bottle carriers](https://www.gwp.co.uk/packaging/bottle/carrier) · B; [BigDug wine boxes](https://www.bigdug.co.uk/wine-bottle-packaging-with-dividers/v/DPACD06MP_1/) · B; [Die Cut Templates special boxes](https://www.diecuttemplates.com/dielines/51297/special-boxes-becf-21e21) · B | carriers/dividers |
| S31 | [Packaging School — dieline design](https://library.packagingschool.com/blog/dieline-design) · C; [Racklify flute profiles](https://racklify.com/encyclopedia/understanding-flute-profiles/) · C | scoring allowance, flute thickness |
| S32 | [Packaging South Asia — Esko parametric standards](https://packagingsouthasia.com/supply-chain-function/end-of-line/coding-and-marking/esko-implements-new-parametric-standards-for-corrugated-boxes) · C; [Converter — Esko FEFCO 2022](https://www.converter.it/en/?p=80534) · C; [Esko Style Catalog Reference](https://docs.esko.com/docs/en-us/artioscad/22.07/adminguide/pdf/StyleCatalogReference.pdf) · B | single-tool multi-standard libraries |
| S33 | [RankHero — display box template](https://www.rankhero.com/keywords/display-box-template) · C | the single Etsy keyword figure |
| S34 | [Fiverr — custom mailer box dieline](https://fiverr.com/arch_greatness/create-custom-mailer-box-dieline-from-dimensions-subscription-box-template) · C; [Refine Packaging — box templates](https://refinepackaging.com/blog/box-templates/) · C | custom-dimension demand (anecdotal) |
| S35 | [Inquirer — custom mailer boxes](https://usa.inquirer.net/184161/custom-mailer-boxes) · C; [PCA — subscription packaging](https://www.packagingcorp.com/resource-hub/industry-insights/three-packaging-strategies-subscription-box-retailers-cant-ignore) · B | e-commerce trends |
| S36 | [GMI — folding carton packaging market](https://gminsights.com/industry-analysis/folding-carton-packaging-market) · D; [Packnode folding cartons](https://www.packnode.org/en/latest/folding-cartons-market-which-industries-and-regions-will-shape-i) · D | end-market shares |
| S37 | BoxCheck repository: `boxcheck-web/src/lib/labelsPackagingFlow.ts`, `printMethods.ts`, `boxcheck/PROGRESS.md` | internal taxonomy |
| S38 | [Labelprint24 — folding box with tuck-in flap](https://api-old.labelprint24.com/en/products/folding-box-with-tuck-in-flap-standard-opposite-flaps-208.php) · B; [Boxshot ECMA A20.20.01.03 page](https://dielines.boxshot.com/make/ecma-a20200103/) · C | ECMA STE/RTE code mapping (unverified) |

## Appendix B — Seed keyword list for the search-volume step (volumes **not** collected)

Pull for the US, UK, DE and UA markets; compare within a family:

`dieline template`, `box template`, `box dieline generator`, `mailer box template`, `mailer box dieline`, `FEFCO 0427 template`, `FEFCO 0201 template`, `RSC box dieline`, `pizza box template`, `tuck end box template`, `straight tuck end dieline`, `reverse tuck end dieline`, `crash lock box template`, `auto bottom box dieline`, `1-2-3 bottom box template`, `snap lock box template`, `sleeve box template`, `tray box template`, `hinged lid box template`, `cake box template`, `cosmetic box template`, `candle box template`, `gift box template`, `rigid box template`, `magnetic box template`, `paper bag template`, `envelope template`, `bottle carrier template`, `box insert template`, `gable box template`, `pillow box template`, `custom size box dieline`.
