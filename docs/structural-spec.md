# BoxCheck Structural — research specification (крок 2)

Статус: **research-only**. Немає production-коду, API, UI. Закомічено 03.10.2026 (див. `PROGRESS.md`); каталог `reference/` (нормалізовані дані з вхідних PDF) **свідомо не в репозиторії** — його зберігання й походження ще не вирішені, тому відтворення скриптів потребує вхідних PDF і локально згенерованого `reference/`.
Дата: 2026-10-03. Попередній крок і сира екстракція: `docs/structural-research.md`.

Відтворення (всі таблиці з маркерами `GEN` перезаписуються скриптом):

```
python scripts/extract_reference.py --sample <pdf> ×4      # → reference/normalized/*.json
python scripts/analyze_landmarks.py                         # → reference/analysis/*.json + блоки GEN нижче
```

Позначки: **OBSERVED** — прочитано з PDF · **DERIVED** — пораховано з OBSERVED ·
**PROVISIONAL / SAMPLE-DERIVED** — рівняння, що відтворює 4 зразки в межах допуску, але не доведене ·
**HYPOTHESIS** — інтерпретація · **UNKNOWN** — з наявних даних не визначається.

## 0. Межі, система координат, обмеження даних

**Походження даних (IP).** Усі числа тут простежуються до `reference/normalized/*.json`, тобто до геометрії 4 PDF.
Жодна формула, параметр чи значення з ARD не використані. Примітка про процес: ARD-файли були додані до сесії
й один раз відображені під час першого аудиту; ця специфікація від них не залежить, і це варто знати рецензенту
при юридичній перевірці. FEFCO/ECMA-порівняння (розділ H) спирається лише на публічні комерційні описи.

**Система координат.** `x_c` — від осі дзеркальної симетрії (центр bbox), `y_b` — від нижнього краю.
Дзеркальна симетрія лівий/правий: максимальна похибка ≤ 0.001 мм в усіх чотирьох зразках (**OBSERVED**),
тому `x_c` — справжня вісь симетрії, і достатньо будувати половину та віддзеркалювати.
Одиниця `u = 0.79375 мм` — символ (див. розділ F: незалежна оцінка 0.7938 ± 0.0005 мм).

**Мітки L/W/D.** Беруться з імен файлів (**UNVERIFIED**). Відносні різниці міток відтворюються геометрією лінійних орієнтирів
з точністю ≤ 0.013 мм; абсолютні значення міток геометрією не перевіряються.

**Структурне обмеження вибірки (важливо).** База — зразок `200×150×40`; кожен інший відрізняється від неї
**одним** параметром: D → `200×150×30`, W → `200×180×40`, L → `160×150×40`. Наслідки:
(1) кожен параметр має лише **два значення** — кривизну, насичення, східці (staircase) перевірити не можна;
(2) жоден зразок не змінює два параметри разом — **перехресні члени** (W·D, L·W, ...) невидимі;
(3) для кожного орієнтира 4 значення проти 4 невідомих (x0, a, b, c): вільна підгонка дала б нульову
надлишковість, тому коефіцієнти тут **не підганяються вільно**, а перевіряються на сітці кратних 0.25
(допуск 0.1 мм на пару) з єдиним вільним параметром — вільним членом; решта 3 ступені свободи — це перевірка
(залишок ≤ 0.05 мм, чисті підгонки дають ≈ 0.01 мм).

## A. Landmark dependency analysis

33 орієнтири (точки/рівні) та 23 похідні відстані. Кожен орієнтир — конкретна точка конкретного примітива,
однакового в усіх зразках (топологія ідентична, примітиви вирівняні за індексом).
Колонка «dependency» показує, від яких параметрів залежить; `none` означає зміну менше за допуск.
`unclean` — коефіцієнт не лежить на сітці або залишок > 0.05 мм: лінійність **не перевіряється** (не «доведено
нелінійно» — просто недостатньо точок). Усі такі рядки належать дугам (розділ E).

<!-- BEGIN GEN:landmarks -->
| ID | meaning | prim.pt | dependency | coef L / W / D | intercept (mm, in u) | max resid mm | status |
|---|---|---|---|---|---|---|---|
| Y_BOTTOM | bottom edge of front flap / lower end flaps | p09.1.0 | none | +0 / +0 / +0 | +0 (+0u) | 0.0 | PROVISIONAL / SAMPLE-DERIVED |
| Y_FLAP_FOLD_LO | front flap fold, lower line of double crease | p11.0.0 | D | +0 / +0 / +1 | -0.001 (-0u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| Y_FLAP_FOLD_HI | front flap fold, upper line of double crease | p10.0.0 | D | +0 / +0 / +1 | +1.586 (+2u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| Y_FRONT_FOLD | front wall / floor fold (also lower side of slot) | p08.0.0 | D | +0 / +0 / +2 | +2.379 (+3u) | 0.002 | PROVISIONAL / SAMPLE-DERIVED |
| Y_SLOT_TOP | upper side of slot | p16.4.0 | D | +0 / +0 / +2 | +4.76 (+6u) | 0.002 | PROVISIONAL / SAMPLE-DERIVED |
| Y_BACK_FOLD | floor / back wall fold | p00.0.0 | W+D | +0 / +1 / +2 | +4.755 (+5.99u) | 0.007 | PROVISIONAL / SAMPLE-DERIVED |
| Y_COVER_FOLD | back wall / cover fold | p03.0.0 | W+D | +0 / +1 / +3 | +5.547 (+6.99u) | 0.008 | PROVISIONAL / SAMPLE-DERIVED |
| Y_COVER_FLAP_BASE | lower cut edge of cover side flaps | p23.0.0 | W+D | +0 / +1 / +3 | +6.341 (+7.99u) | 0.008 | PROVISIONAL / SAMPLE-DERIVED |
| Y_COVER_SIDE_STRAIGHT_END | end of straight outer edge of cover side flap | p23.2.1 | unclean | raw -0 / +2.015 / +2.321 | — | — | DERIVED (not linear-fit) |
| Y_COVER_SIDE_TIP | end of rounded tip of cover side flap | p23.3.3 | unclean | raw -0 / +2.016 / +2.867 | — | — | DERIVED (not linear-fit) |
| Y_COVER_TUCK_FOLD | cover / tuck flap fold | p26.0.0 | W+D | +0 / +2 / +3 | +6.335 (+7.98u) | 0.012 | PROVISIONAL / SAMPLE-DERIVED |
| Y_TUCK_ARC_START | start of tuck-flap corner arc (straight side ends) | p25.0.1 | unclean | raw -0 / +2 / +3.446 | — | — | DERIVED (not linear-fit) |
| Y_TOP | top edge of tuck flap | p25.2.0 | W+D | +0 / +2 / +4 | +6.334 (+7.98u) | 0.013 | PROVISIONAL / SAMPLE-DERIVED |
| X_LEFT_EDGE | left outer edge | p09.0.0 | L+D | -0.5 / +0 / -1 | -1.186 (-1.49u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_FOLD_L1 | left end-wall fold, outer line of double crease | p06.0.0 | L | -0.5 / +0 / +0 | -1.187 (-1.5u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_FOLD_L2 | left end-wall fold, inner line of double crease | p14.3.0 | L | -0.5 / +0 / +0 | -0.394 (-0.5u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_FOLD_R1 | right end-wall fold, inner line of double crease | p15.1.0 | L | +0.5 / +0 / +0 | +0.393 (+0.5u) | 0.003 | PROVISIONAL / SAMPLE-DERIVED |
| X_FOLD_R2 | right end-wall fold, outer line of double crease | p15.3.0 | L | +0.5 / +0 / +0 | +1.187 (+1.5u) | 0.003 | PROVISIONAL / SAMPLE-DERIVED |
| X_RIGHT_EDGE | right outer edge | p18.0.0 | L+D | +0.5 / +0 / +1 | +1.186 (+1.49u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_COVER_SIDE_OUT_L | outer edge of left cover side flap | p27.2.0 | L+D | -0.5 / +0 / -1 | -0.392 (-0.49u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_COVER_SIDE_OUT_R | outer edge of right cover side flap | p23.2.0 | L+D | +0.5 / +0 / +1 | +0.392 (+0.49u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_COVER_TIP_L | tip of left cover side flap (end of rounded corner) | p27.3.3 | unclean | raw -0.5 / +0.013 / -0.566 | — | — | DERIVED (not linear-fit) |
| X_COVER_TIP_R | tip of right cover side flap (end of rounded corner) | p23.3.3 | unclean | raw +0.5 / -0.013 / +0.566 | — | — | DERIVED (not linear-fit) |
| X_TUCK_ARC_END_L | left end of tuck-flap straight top edge | p25.3.0 | unclean | raw -0.5 / +0 / +0.555 | — | — | DERIVED (not linear-fit) |
| X_TUCK_ARC_END_R | right end of tuck-flap straight top edge | p25.1.3 | unclean | raw +0.5 / +0 / -0.555 | — | — | DERIVED (not linear-fit) |
| X_RELIEF_BOT_L | left lower flap relief notch, at bottom edge | p09.2.0 | L | -0.5 / +0 / +0 | -2.775 (-3.5u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_RELIEF_TOP_L | left lower flap relief notch, at fold | p09.2.1 | L | -0.5 / +0 / +0 | -1.981 (-2.5u) | 0.004 | PROVISIONAL / SAMPLE-DERIVED |
| X_SLOT_OUT_L | slot outer left (arc extreme) | p16.1.3 | L | -0.25 / +0 / +0 | +14.604 (+18.4u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| X_SLOT_IN_L | slot flat part, left end | p16.0.1 | L | -0.25 / +0 / +0 | +15.795 (+19.9u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| X_SLOT_IN_R | slot flat part, right end | p16.0.0 | L | +0.25 / +0 / +0 | -15.795 (-19.9u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| X_SLOT_OUT_R | slot outer right (arc extreme) | p16.5.3 | L | +0.25 / +0 / +0 | -14.604 (-18.4u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| X_TAB_L | tab edge on bottom edge, left | p17.1.1 | L | -0.25 / +0 / +0 | +14.604 (+18.4u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| X_TAB_R | tab edge on bottom edge, right | p17.1.0 | L | +0.25 / +0 / +0 | -14.604 (-18.4u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| H_FRONT_FLAP | front flap height | Δ Y_BOTTOM → Y_FLAP_FOLD_LO | D | +0 / +0 / +1 | -0.001 (-0u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| H_FLAP_HINGE | double-crease strip above front flap | Δ Y_FLAP_FOLD_LO → Y_FLAP_FOLD_HI | none | +0 / +0 / +0 | +1.588 (+2u) | 0.0 | PROVISIONAL / SAMPLE-DERIVED |
| H_FRONT_WALL | front wall height | Δ Y_FLAP_FOLD_HI → Y_FRONT_FOLD | D | +0 / +0 / +1 | +0.792 (+1u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| H_FLOOR | floor height (Y) | Δ Y_FRONT_FOLD → Y_BACK_FOLD | W | +0 / +1 / +0 | +2.376 (+2.99u) | 0.005 | PROVISIONAL / SAMPLE-DERIVED |
| H_BACK_WALL | back wall height | Δ Y_BACK_FOLD → Y_COVER_FOLD | D | +0 / +0 / +1 | +0.793 (+1u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| H_COVER | cover panel height (fold to fold) | Δ Y_COVER_FOLD → Y_COVER_TUCK_FOLD | W | +0 / +1 / +0 | +0.788 (+0.99u) | 0.005 | PROVISIONAL / SAMPLE-DERIVED |
| H_COVER_CUT | cover side-flap height (cut base to fold) | Δ Y_COVER_FLAP_BASE → Y_COVER_TUCK_FOLD | W | +0 / +1 / +0 | -0.005 (-0.01u) | 0.005 | PROVISIONAL / SAMPLE-DERIVED |
| H_TUCK | tuck flap height | Δ Y_COVER_TUCK_FOLD → Y_TOP | D | +0 / +0 / +1 | -0.001 (-0u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| H_TOTAL | overall height | Δ Y_BOTTOM → Y_TOP | W+D | +0 / +2 / +4 | +6.334 (+7.98u) | 0.013 | PROVISIONAL / SAMPLE-DERIVED |
| W_END_WALL_L | left end wall width (edge to outer fold line) | Δ X_LEFT_EDGE → X_FOLD_L1 | D | +0 / +0 / +1 | -0.001 (-0u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| W_END_WALL_R | right end wall width | Δ X_FOLD_R2 → X_RIGHT_EDGE | D | +0 / +0 / +1 | -0.001 (-0u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| W_FLOOR_OUT | floor width between outer fold lines | Δ X_FOLD_L1 → X_FOLD_R2 | L | +1 / +0 / +0 | +2.374 (+2.99u) | 0.007 | PROVISIONAL / SAMPLE-DERIVED |
| W_FLOOR_IN | floor width between inner fold lines | Δ X_FOLD_L2 → X_FOLD_R1 | L | +1 / +0 / +0 | +0.787 (+0.99u) | 0.007 | PROVISIONAL / SAMPLE-DERIVED |
| W_TOTAL | overall width | Δ X_LEFT_EDGE → X_RIGHT_EDGE | L+D | +1 / +0 / +2 | +2.372 (+2.99u) | 0.009 | PROVISIONAL / SAMPLE-DERIVED |
| W_COVER_SIDE | cover side flap width (fold to outer edge) | Δ X_FOLD_R1 → X_COVER_SIDE_OUT_R | D | +0 / +0 / +1 | -0.001 (-0u) | 0.001 | PROVISIONAL / SAMPLE-DERIVED |
| W_TUCK_FLAT | tuck flap straight top edge length | Δ X_TUCK_ARC_END_L → X_TUCK_ARC_END_R | unclean | raw +1 / +0 / -1.111 | — | — | DERIVED (not linear-fit) |
| W_SLOT_OUT | slot overall width | Δ X_SLOT_OUT_L → X_SLOT_OUT_R | L | +0.5 / +0 / +0 | -29.209 (-36.8u) | 0.002 | PROVISIONAL / SAMPLE-DERIVED |
| W_SLOT_IN | slot flat-part width | Δ X_SLOT_IN_L → X_SLOT_IN_R | L | +0.5 / +0 / +0 | -31.59 (-39.8u) | 0.002 | PROVISIONAL / SAMPLE-DERIVED |
| W_TAB | tab width on bottom edge | Δ X_TAB_L → X_TAB_R | L | +0.5 / +0 / +0 | -29.209 (-36.8u) | 0.002 | PROVISIONAL / SAMPLE-DERIVED |
| D_SLOT_HEIGHT | slot height | Δ Y_FRONT_FOLD → Y_SLOT_TOP | none | +0 / +0 / +0 | +2.381 (+3u) | 0.0 | PROVISIONAL / SAMPLE-DERIVED |
| D_COVER_TIP_RISE | cover side flap: straight end to tip (rounded corner rise) | Δ Y_COVER_SIDE_STRAIGHT_END → Y_COVER_SIDE_TIP | unclean | raw -0 / +0.001 / +0.546 | — | — | DERIVED (not linear-fit) |
| D_COVER_TIP_DROP | cover side flap: tip to fold (taper) | Δ Y_COVER_SIDE_TIP → Y_COVER_TUCK_FOLD | unclean | raw -0 / -0.016 / +0.134 | — | — | DERIVED (not linear-fit) |
| D_TUCK_ARC_RISE | tuck flap: straight side end to top edge | Δ Y_TUCK_ARC_START → Y_TOP | unclean | raw -0 / +0 / +0.556 | — | — | DERIVED (not linear-fit) |
<!-- END GEN:landmarks -->

Висновки (DERIVED): (1) усі рівні й відстані на прямолінійній геометрії лінійні за L, W, D із коефіцієнтами з
`{0, ±¼, ±½, 1, 2, 3, 4}`; (2) вільні члени — цілі (або напівцілі) кратні `u` з точністю ≈ 0.02u (2u, 3u, 6u, 7u, 8u, 1.5u, 0.5u,
2.5u, 3.5u) — це найсильніший аргумент, що `u` є природною одиницею шаблону; **єдиний виняток — слот**
(ширина `L/2 − 36.8u`, `L/2 − 39.8u`: не кратні `u`), тобто ширина слота має інший механізм, ніж «припуски в `u`»; (3) нелінійні/незчищені — лише
бічні клапани кришки (кінець прямої, кінчик, скіс) і закруглення tuck-клапана.

## B. Linear dependencies — таблиця рівнянь

**PROVISIONAL / SAMPLE-DERIVED.** Не універсальні формули. Діють лише у тестованому діапазоні
`L ∈ {160, 200}`, `W ∈ {150, 180}`, `D ∈ {30, 40}` і лише для цього стилю (одна родина, один слот, один board).
Мм; `u = 0.79375`; максимальний залишок підгонки 0.013 мм.

Вертикальні рівні `y_b` (від нижнього краю переднього клапана):

| Орієнтир | Рівняння | Залишок |
|---|---|---|
| Y_FLAP_FOLD_LO (нижня лінія подвійного креза) | `D` | 0.001 |
| Y_FLAP_FOLD_HI (верхня лінія) | `D + 2u` | 0.001 |
| Y_FRONT_FOLD (передня стінка / дно; нижня сторона слота) | `2D + 3u` | 0.002 |
| Y_SLOT_TOP | `2D + 6u` | 0.002 |
| Y_BACK_FOLD (дно / задня стінка) | `W + 2D + 6u` | 0.007 |
| Y_COVER_FOLD (задня стінка / кришка) | `W + 3D + 7u` | 0.008 |
| Y_COVER_FLAP_BASE (низ бічних клапанів кришки) | `W + 3D + 8u` | 0.008 |
| Y_COVER_TUCK_FOLD (кришка / tuck) | `2W + 3D + 8u` | 0.012 |
| Y_TOP | `2W + 4D + 8u` | 0.013 |

Горизонтальні рівні `x_c` (праві; ліві — дзеркально зі знаком мінус):

| Орієнтир | Рівняння | Залишок |
|---|---|---|
| X_FOLD_R1 / R2 (внутрішня / зовнішня лінії згину торцевої стінки) | `L/2 + 0.5u` / `L/2 + 1.5u` | 0.003 |
| X_RIGHT_EDGE | `L/2 + D + 1.5u` | 0.004 |
| X_COVER_SIDE_OUT_R | `L/2 + D + 0.5u` | 0.004 |
| Нотч-релі нижнього клапана торця (низ / згин) | `−(L/2 + 3.5u)` / `−(L/2 + 2.5u)` | 0.004 |

Розміри панелей (відстані):

| Панель / відстань | Рівняння |
|---|---|
| Передній клапан (висота) | `D` |
| Смуга подвійного креза над клапаном | `2u` |
| Передня стінка (висота) | `D + u` |
| Дно (висота / ширина між зовнішніми згинами) | `W + 3u` / `L + 3u` |
| Дно (ширина між внутрішніми згинами) | `L + u` |
| Задня стінка (висота) | `D + u` |
| Кришка (згин до згину) / бічний клапан кришки від різу | `W + u` / `W` |
| Tuck-клапан (висота) | `D` |
| Торцева стінка (ширина), бічний клапан кришки (ширина) | `D`, `D` |
| Загальна ширина / висота | `L + 2D + 3u` / `2W + 4D + 8u` |

Слот (залежить лише від L; розділ D): зовнішні краї `x_c = ±(L/4 − 14.604)`, ширина `L/2 − 29.209`, висота `3u`.

**Чого ці рівняння не гарантують.** (a) поведінки поза тестованими значеннями; (b) перехресних членів;
(c) залежності від board/caliper (один board в усіх зразках); (d) що `u` — це саме caliper (розділ F).

## C. Directional behavior

Перевірка на **всіх** координатних точках (кінці ліній і кривих, 126 точок на зразок; контрольні точки Безьє —
окремо, бо їхній рух залежить від радіуса) з абсолютним допуском 0.4 мм для «не змінилось».

<!-- BEGIN GEN:directional -->
| pair | axis | points | unchanged (≤0.4 mm) | max unchanged Δ mm | clean moving (k histogram) | unclean | unclean paths | Bézier handles unchanged / total |
|---|---|---|---|---|---|---|---|---|
| 200x150x40->200x150x30 (D-10) | x | 126 | 84 | 0.004 | 34 (-1×17; 1×17) | 8 | p23, p25, p27 | 10 / 20 |
| 200x150x40->200x150x30 (D-10) | y | 126 | 16 | 0.0 | 98 (1×18; 2×42; 3×34; 4×4) | 12 | p23, p25, p27 | 0 / 20 |
| 200x150x40->200x180x40 (W+30) | x | 126 | 126 | 0.387 | 0 (—) | 0 | — | 20 / 20 |
| 200x150x40->200x180x40 (W+30) | y | 126 | 62 | 0.0 | 56 (1×40; 2×16) | 8 | p23, p27 | 8 / 20 |
| 200x150x40->160x150x40 (L-40) | x | 126 | 0 | 0 | 126 (-0.5×54; -0.25×9; 0.25×9; 0.5×54) | 0 | — | 0 / 20 |
| 200x150x40->160x150x40 (L-40) | y | 126 | 126 | 0.009 | 0 (—) | 0 | — | 20 / 20 |
<!-- END GEN:directional -->

| Твердження | Глобально? | Область дії (DERIVED) |
|---|---|---|
| W змінює Y, але не X | **Майже глобально** | 126/126 X-точок незмінні (≤ 0.001 мм), **крім 4 кінцевих точок скосу бічного клапана кришки** (p23.3.3, p23.4.0 і дзеркальні): ±0.387 мм; контрольні точки тих самих дуг ≤ 0.22 мм. Y: 62 незмінні, 56 рухаються на `1·ΔW` (40) або `2·ΔW` (16), 8 (p23, p27) — нелінійні. |
| L змінює X, але не Y | **Глобально** | 126/126 Y-точок незмінні (≤ 0.009 мм). Усі X-точки рухаються: 108 — на `±½·ΔL`, 18 — на `±¼·ΔL` (слот, язик, примикаючі креази). |
| D впливає на багато зсувів | **Так, на обидві осі** | X: 84 незмінні, 34 — на `±1·ΔD`, 8 нелінійні. Y: 16 незмінні, 98 — на `1,2,3,4·ΔD`, 12 нелінійні. |
| Криві клапани поводяться інакше | **Підтверджено, але локально** | Нелінійні точки — **лише** у шляхах p23, p27 (бічні клапани кришки) і p25 (tuck): 8 + 12 для D, 8 для W, 0 для L. Дуги слота й малі кутові дуги (p16, p23.1/p27.1) — константи в `u`. |

## D. Slot analysis

<!-- BEGIN GEN:slot -->
| sample | L | outer left x_c | outer right x_c | centre x_c | outer width | flat width | tab width | height | slot bottom − front fold |
|---|---|---|---|---|---|---|---|---|---|
| 200x150x40 | 200 | -35.396 | 35.396 | 0.0 | 70.792 | 68.411 | 70.792 | 2.381 | 0.0 |
| 200x150x30 | 200 | -35.394 | 35.395 | 0.0 | 70.789 | 68.408 | 70.789 | 2.381 | 0.0 |
| 200x180x40 | 200 | -35.396 | 35.396 | 0.0 | 70.792 | 68.411 | 70.792 | 2.381 | 0.0 |
| 160x150x40 | 160 | -25.397 | 25.397 | -0.0 | 50.793 | 48.412 | 50.793 | 2.381 | 0.0 |
<!-- END GEN:slot -->

**Спостереження (OBSERVED / DERIVED):**
1. **Центр** слота на осі симетрії: `|x_c| ≤ 0.001` мм у всіх зразках.
2. **Краї:** зовнішні `x_c = ±35.396` (L=200) і `±25.397` (L=160): кожен край рухається на `∓¼·ΔL`, ширина змінюється на `½·ΔL`.
   Залежності від W і D немає (зміни ≤ 0.003 мм).
3. **Ширина:** зовнішня `70.79` (L=200, у всіх зразках з L=200) і `50.79` (L=160); пласка частина `68.41` / `48.41`.
   Пласка = зовнішня − `3u` (кінці — півкола).
4. **Висота** `3u = 2.381` мм, радіус кінцевих дуг `1.5u` (чотири чверть-дуги, кожна ≈ 89.6°): константи в `u`.
5. **Положення по Y:** нижня сторона слота лежить **точно** на лінії `Y_FRONT_FOLD` (відхилення 0.000), верхня — на `3u` вище,
   тобто слот входить у дно. Креази p12/p13 закінчуються рівно на пласких кінцях слота (`X_SLOT_IN_L/R`), між ними
   проходить різ p16.0 по лінії згину.
6. **Язик (tab) на нижньому краї** (p17): ширина = зовнішній ширині слота (різниця ≤ 0.001 мм), глибина язика 0 (край прямий).
   Інтерпретація (HYPOTHESIS): відрізок p17 — контур язика нульової глибини, що ділить нижній край у точках `±(зовн. ширина слота/2)`.
7. **Залежність положення від L/W/D:** `x_c` — лише L; `y_b` — лише D (`2D+3u … 2D+6u`); W не впливає.

**Що виводиться математично:** лінійна підгонка за двома значеннями L:
`ширина_зовн = L/2 − 29.209` (`−36.8u`), `ширина_пласка = L/2 − 31.590` (`−39.8u`), краї `±(L/4 − 14.604)`.
Це **PROVISIONAL / SAMPLE-DERIVED** і має **нуль надлишковості**: дві точки визначають будь-яку лінію.
Нумерологія (не доказ): `29.209 мм = 1.1500″`, а `50.793 мм ≈ 2.000″` при L=160.

**Чи достатньо для рівняння? НІ.** Дві значення L не розрізняють: лінійну залежність, таблицю/бібліотеку з кроками,
округлення до кратних `u` чи дюйма, обмеження (clamp). Лінійний закон не може бути глобальним: при `L < 58.4 мм`
ширина стала б від'ємною. Невідомі параметри бібліотеки слота (мінімум/максимум ширини, крок, відступ від країв)
**не вигадуються**. Для POC допустимо лише захищене провізоричне правило з явним діапазоном `L ∈ [160, 200]`.

## E. Rounded flap analysis

<!-- BEGIN GEN:arcs -->
| prim | role | sample | Bézier-fit radius mm | r / u | tangent-length radius mm | sweep ° | circular? | r / (D/2) |
|---|---|---|---|---|---|---|---|---|
| p16.1 | slot end (lower-left) | 200x150x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.1 | slot end (lower-left) | 200x150x30 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0796 |
| p16.1 | slot end (lower-left) | 200x180x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.1 | slot end (lower-left) | 160x150x40 | 1.194 | 1.504 | 1.191 | 89.63 | yes | 0.0597 |
| p16.3 | slot end (upper-left) | 200x150x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.3 | slot end (upper-left) | 200x150x30 | 1.194 | 1.504 | 1.191 | 89.65 | yes | 0.0796 |
| p16.3 | slot end (upper-left) | 200x180x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.3 | slot end (upper-left) | 160x150x40 | 1.195 | 1.506 | 1.191 | 89.63 | yes | 0.0598 |
| p16.5 | slot end (upper-right) | 200x150x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.5 | slot end (upper-right) | 200x150x30 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0796 |
| p16.5 | slot end (upper-right) | 200x180x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.5 | slot end (upper-right) | 160x150x40 | 1.195 | 1.506 | 1.191 | 89.63 | yes | 0.0598 |
| p16.7 | slot end (lower-right) | 200x150x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.7 | slot end (lower-right) | 200x150x30 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0796 |
| p16.7 | slot end (lower-right) | 200x180x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p16.7 | slot end (lower-right) | 160x150x40 | 1.194 | 1.504 | 1.191 | 89.64 | yes | 0.0597 |
| p23.1 | cover side flap base corner (R) | 200x150x40 | 0.796 | 1.003 | 0.794 | 89.64 | yes | 0.0398 |
| p23.1 | cover side flap base corner (R) | 200x150x30 | 0.796 | 1.003 | 0.794 | 89.64 | yes | 0.0531 |
| p23.1 | cover side flap base corner (R) | 200x180x40 | 0.796 | 1.003 | 0.794 | 89.62 | yes | 0.0398 |
| p23.1 | cover side flap base corner (R) | 160x150x40 | 0.796 | 1.003 | 0.794 | 89.62 | yes | 0.0398 |
| p27.1 | cover side flap base corner (L) | 200x150x40 | 0.796 | 1.003 | 0.794 | 89.62 | yes | 0.0398 |
| p27.1 | cover side flap base corner (L) | 200x150x30 | 0.796 | 1.003 | 0.794 | 89.64 | yes | 0.0531 |
| p27.1 | cover side flap base corner (L) | 200x180x40 | 0.797 | 1.004 | 0.794 | 89.61 | yes | 0.0399 |
| p27.1 | cover side flap base corner (L) | 160x150x40 | 0.796 | 1.003 | 0.794 | 89.64 | yes | 0.0398 |
| p23.3 | cover side flap rounded tip (R) | 200x150x40 | 19.892 | 25.061 | — | 82.96 | yes | 0.9946 |
| p23.3 | cover side flap rounded tip (R) | 200x150x30 | 14.325 | 18.047 | — | 85.18 | yes | 0.955 |
| p23.3 | cover side flap rounded tip (R) | 200x180x40 | 19.894 | 25.063 | — | 84.07 | yes | 0.9947 |
| p23.3 | cover side flap rounded tip (R) | 160x150x40 | 19.892 | 25.061 | — | 82.96 | yes | 0.9946 |
| p27.3 | cover side flap rounded tip (L) | 200x150x40 | 19.892 | 25.061 | — | 82.96 | yes | 0.9946 |
| p27.3 | cover side flap rounded tip (L) | 200x150x30 | 14.325 | 18.047 | — | 85.18 | yes | 0.955 |
| p27.3 | cover side flap rounded tip (L) | 200x180x40 | 19.894 | 25.063 | — | 84.07 | yes | 0.9947 |
| p27.3 | cover side flap rounded tip (L) | 160x150x40 | 19.892 | 25.061 | — | 82.96 | yes | 0.9946 |
| p25.1 | tuck flap corner (R) | 200x150x40 | 19.907 | 25.08 | 19.843 | 89.63 | yes | 0.9953 |
| p25.1 | tuck flap corner (R) | 200x150x30 | 14.333 | 18.057 | 14.287 | 89.63 | yes | 0.9555 |
| p25.1 | tuck flap corner (R) | 200x180x40 | 19.907 | 25.08 | 19.843 | 89.63 | yes | 0.9953 |
| p25.1 | tuck flap corner (R) | 160x150x40 | 19.907 | 25.08 | 19.844 | 89.63 | yes | 0.9953 |
| p25.3 | tuck flap corner (L) | 200x150x40 | 19.907 | 25.08 | 19.843 | 89.63 | yes | 0.9953 |
| p25.3 | tuck flap corner (L) | 200x150x30 | 14.332 | 18.056 | 14.287 | 89.63 | yes | 0.9555 |
| p25.3 | tuck flap corner (L) | 200x180x40 | 19.907 | 25.08 | 19.843 | 89.63 | yes | 0.9953 |
| p25.3 | tuck flap corner (L) | 160x150x40 | 19.907 | 25.08 | 19.844 | 89.63 | yes | 0.9953 |

Tuck-corner radius vs D/2 (HYPOTHESIS test, 2 distinct D only):

| sample | D/2 in u | r in u | r = floor(D/2) in u | r = round(D/2) in u |
|---|---|---|---|---|
| 200x150x40 | 25.197 | 24.999 | True | True |
| 200x150x30 | 18.898 | 17.999 | True | False |
| 200x180x40 | 25.197 | 24.999 | True | True |
| 160x150x40 | 25.197 | 25.0 | True | True |

Cover side flap tip (right flap): geometry vs W, D (mm, calibrated):

| sample | L | W | D | run to fold | drop | taper ° | rise | tip arc r | sweep ° | tuck r | pred. run = D − r(1−sinα) | pred. rise = r·cosα | tanα·W | tanα·W/(D−10) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 200x150x40 | 200 | 150 | 40 | 22.502 | 2.679 | 6.79 | 19.704 | 19.892 | 82.96 | 19.843 | 22.503 | 19.704 | 17.859 | 0.5953 |
| 200x150x30 | 200 | 150 | 30 | 16.842 | 1.337 | 4.538 | 14.242 | 14.325 | 85.18 | 14.287 | 16.843 | 14.242 | 11.906 | 0.5953 |
| 200x180x40 | 200 | 180 | 40 | 22.115 | 2.194 | 5.666 | 19.746 | 19.894 | 84.07 | 19.843 | 22.116 | 19.746 | 17.859 | 0.5953 |
| 160x150x40 | 160 | 150 | 40 | 22.502 | 2.679 | 6.789 | 19.704 | 19.892 | 82.96 | 19.844 | 22.502 | 19.705 | 17.858 | 0.5953 |
<!-- END GEN:arcs -->

**Інвентар (10 кубічних кривих):** 4 кінці слота, 2 малі кутові дуги основи бічних клапанів кришки, 2 кінчики бічних
клапанів кришки (p23.3, p27.3), 2 кути tuck-клапана (p25.1, p25.3).

1. **Слот і малі кутові дуги — константи в `u`** (OBSERVED, 4/4 зразки): радіуси `1.5u` і `1.0u`, не залежать від L, W, D.
2. **Кути tuck-клапана:** радіус (довжина дотичної) `25.0u = 19.84 мм` при D=40 (три зразки, включно зі змінами L і W) та
   `18.0u = 14.29 мм` при D=30. Радіус не залежить від L і W. Порівняння з D/2: `20 → 19.84`, `15 → 14.29`
   (відхилення `0.16` і `0.71` мм — не стала різниця). Правило `r = floor((D/2)/u)·u` збігається у 4/4 зразків,
   `round` — у 3/4 (хибне при D=30). **HYPOTHESIS** (лише два значення D; інші правила з однаковим результатом
   можливі: `min(D/2 − ε, …)`). Нелінійність коефіцієнта D для tuck-орієнтирів у розділі A — це саме ефект «сходинки».
3. **Кінчик бічного клапана кришки — повністю описується побудовою (DERIVED).** Це коло радіуса `r = r_tuck`,
   дотичне до вертикального зовнішнього краю й до скошеного краю. Передбачені `run = D − r(1 − sin α)` та
   `rise = r·cos α` збігаються зі виміряними до **0.001 мм** у всіх чотирьох зразках; `sweep ≈ 90° − α` (в межах 0.25°).
4. **Скіс (кут α):** `tan α · W = 0.5953·(D − 10)` у 4/4 зразків (`0.5953` — однакове в усіх; `α = 6.79°, 4.54°, 5.67°, 6.79°` для B, A, C, D).
   Статус **PROVISIONAL / SAMPLE-DERIVED, слабкий**: дві сталі (`0.5953` і `10`) підігнані по A і B, незалежна перевірка —
   лише C (залежність `1/W`, збіг до 0.0001). Константа `10 мм` точна, не кратна `u` (`12.6u`) — схоже на метричну
   константу шаблону. Форма за D (`D − 10`) **не перевіряється** (два значення D). Взаємодія W·D за межами
   цих трьох комбінацій не перевірена.
5. **Контрольні точки Безьє:** усі криві близькі до кола (співвідношення довжини handle ≈ 1 ± 3 %), але дотичні
   мають перекіс до `0.2°` відносно осей (OBSERVED), тому радіус за хордою на `0.3 %` більший за довжину дотичної
   (напр. 19.91 проти 19.84). Для побудови береться довжина дотичної; точне відтворення handle-ів до 0.1 мм не потрібне.
6. **Що рухається:** при зміні **L** — лише паралельний перенос (форма дуг не змінюється); при зміні **W** — кінцеві точки
   й handle-и кінчика (≤ 0.39 / 0.22 мм по X, і зсув по Y); при зміні **D** — усі радіуси (сходинка) та кінчик.

**Чи достатньо 4 зразків для відновлення методу побудови?** **Частково.** Геометрична побудова (кола, дотичні, зв'язок
радіуса кінчика з радіусом tuck) — DERIVED. **UNKNOWN:** закон радіуса за D за межами 30/40, закон α за D, взаємодія W·D,
стилі `angled / rounded / no scrap / cut back` (інші варіанти клапана), та чи радіус має верхнє обмеження через W або L.

## F. Crease analysis та одиниця `u`

<!-- BEGIN GEN:unit -->
| pair parameter | n features | median unit mm | Q1–Q3 |
|---|---|---|---|
| D | 250 | 0.79352 | 0.79336–0.79367 |
| W | 76 | 0.79377 | 0.79377–0.79377 |
| L | 86 | 0.79385 | 0.79385–0.79386 |

Relative error of each pair estimate against candidate values (estimate/candidate − 1):

| candidate mm | D pair | W pair | L pair |
|---|---|---|---|
| 0.79 | +0.4460% | +0.4770% | +0.4870% |
| 0.79375 | -0.0290% | +0.0030% | +0.0130% |
| 0.794 | -0.0600% | -0.0290% | -0.0190% |
| 0.8 | -0.8100% | -0.7790% | -0.7690% |

| sample | unit gap (page mm) | smallest arc r / unit gap | slot height / u | double-crease strip / u |
|---|---|---|---|---|
| 200x150x40 | 0.7719 | 1.0 | 3.0 | 2.0 |
| 200x150x30 | 0.8006 | 0.9999 | 3.0 | 2.0 |
| 200x180x40 | 0.7719 | 1.0001 | 3.0 | 2.0 |
| 160x150x40 | 0.8078 | 1.0 | 3.0 | 2.0 |
<!-- END GEN:unit -->

**OBSERVED:** проміжок подвійного креза (одиниця) на масштабі сторінки: `0.8006 / 0.7719 / 0.7719 / 0.8078` мм (A, B, C, D) —
масштаб кожного PDF різний; у кожному зразку цей проміжок дорівнює найменшому радіусу дуги з точністю `0.0001`,
висота слота `= 3×`, смуга подвійного креза над клапаном `= 2×`. Вертикальні креази подвоєні з проміжком `1u`,
горизонтальні — одна подвійна лінія з проміжком `2u` (над переднім клапаном).

**Незалежна оцінка одиниці (DERIVED, не використовує припущення 1/32″):** для кожної пари «база ↔ зразок»
знаходимо `u`, при якому різниці координат у «проміжках» дають задані мітками ΔL, ΔW, ΔD (кратні `k = ½, 1, 2 …`):
`0.79352` (D, 250 точок), `0.79377` (W, 76), `0.79385` (L, 86) мм; розкид медіан `0.00033 мм (0.04 %)`.

**Докази за `u = 0.79375 мм = 1/32″`:**
1. Три незалежні пари збігаються з ним у межах `−0.03 % … +0.013 %`; `0.79` відхиляється на `+0.45…+0.49 %`, `0.8` — на `−0.77…−0.81 %` (виключені).
2. Усі вільні члени рівнянь розділу B — цілі кратні `u` (1, 2, 3, 6, 7, 8, 0.5, 1.5, 2.5, 3.5) з точністю 0.02u.
3. Радіуси слота й кутових дуг, висота слота, смуга креза — рівно `1u`, `1.5u`, `3u`, `2u`.
4. Радіус tuck `25u` / `18u` — цілі кратні.

**Докази проти / обмеження:**
1. Оцінка спирається на **різниці міток у назвах файлів** (UNVERIFIED); абсолютного масштабу з відомою міркою немає.
2. Розкид 0.04 % не розрізняє `0.79375` та `0.7938` або `0.794` (різниця 0.03 %).
3. Відомий публічний факт: SBS «16» зазвичай означає `16 pt = 0.016″ = 0.406 мм`, тоді як `u = 0.794 мм ≈ 2 × 0.397`.
   Отже `u` може бути **похідною величиною (два шари / припуск)**, а не сирим caliper board. Звʼязок з board **UNKNOWN**.
4. У шаблоні є **метрична** стала (`10 мм`, розділ E.4), не кратна `u`: не все масштабується з caliper.
5. Один board у всіх зразках: caliper і константи шаблону не розділяються.

**Впевненість:** `u = 0.7938 ± 0.0005 мм` — **висока** (за умови, що мітки різниць точні); `u = 1/32″ точно` — **середня**;
`u = caliper board` — **низька / невідомо**.

**Тест у ArtiosCAD, що підтвердить:** (1) експорт PDF 1:1 (без «вписати в сторінку») з відомою мітко-довжиною (напр. розмір L/W/D
з виміру в самому ArtiosCAD) — абсолютний масштаб без залежності від імен файлів; (2) прочитати caliper board у діалозі
Board Selection і порівняти з `u`; (3) той самий L/W/D при board з іншим caliper: прогноз — усі `k·u` зсуви змінюються
пропорційно, `10 мм` — ні.

## G. Topology (OBSERVED)

<!-- BEGIN GEN:topology -->
| path | sep | role | primitives | shape |
|---|---|---|---|---|
| p00 | Crease | floor/back-wall fold | 1 | H |
| p01 | Cut | left slit back wall / end-upper | 1 | V |
| p02 | Cut | left chamfer at cover base | 1 | D |
| p03 | Crease | back-wall/cover fold | 1 | H |
| p04 | Cut | right slit + chamfer back wall / end-upper | 2 | DV |
| p05 | Cut | left end-upper outline | 2 | DV |
| p06 | Crease | left end-wall fold (V) + end-wall/end-upper fold (H) | 2 | VH |
| p07 | Cut | left outer edge of end wall | 1 | V |
| p08 | Crease | left end-wall/end-lower fold | 1 | H |
| p09 | Cut | left end-lower flap outline | 4 | VHDH |
| p10 | Crease | front flap hinge, upper line | 1 | H |
| p11 | Crease | front flap hinge, lower line | 1 | H |
| p12 | Crease | front fold, right of slot | 1 | H |
| p13 | Crease | front fold, left of slot | 1 | H |
| p14 | Cut | front flap left outline + notch | 4 | VDVH |
| p15 | Cut | front flap right outline + notch | 4 | HVDV |
| p16 | Cut | slot outline | 6 | HCCHCC |
| p17 | Cut | tab edge on bottom | 1 | H |
| p18 | Cut | right end-lower flap outline | 4 | VHDH |
| p19 | Crease | right end-wall fold (V) + end-wall/end-upper fold (H) | 2 | VH |
| p20 | Cut | right outer edge of end wall | 1 | V |
| p21 | Crease | right end-wall/end-lower fold | 1 | H |
| p22 | Cut | right end-upper outline | 2 | DV |
| p23 | Cut | right cover side flap outline | 5 | HCVCD |
| p24 | Crease | right cover/cover-side fold | 1 | V |
| p25 | Cut | tuck flap outline | 5 | VCHCV |
| p26 | Crease | cover/tuck fold | 1 | H |
| p27 | Cut | left cover side flap outline | 5 | HCVCD |
| p28 | Crease | left cover/cover-side fold | 1 | V |

Crease endpoints versus Cut geometry:

| sample | on cut interior | at cut endpoint | on crease only | free |
|---|---|---|---|---|
| 200x150x40 | 0 | 30 | 0 | 0 |
| 200x150x30 | 0 | 30 | 0 | 0 |
| 200x180x40 | 0 | 30 | 0 | 0 |
| 160x150x40 | 0 | 30 | 0 | 0 |

Panels (BASE frame; x from symmetry axis, y from bottom edge):

| panel | x range | y range | w | h |
|---|---|---|---|---|
| FRONT_FLAP | -100.39 … 100.39 | 0.0 … 40.0 | 200.79 | 40.0 |
| FLAP_HINGE_STRIP | -101.19 … 101.19 | 40.0 … 41.59 | 202.38 | 1.59 |
| FRONT_WALL | -101.19 … 101.19 | 41.59 … 82.38 | 202.38 | 40.79 |
| FLOOR | -101.19 … 101.19 | 82.38 … 234.76 | 202.38 | 152.38 |
| BACK_WALL | -101.19 … 101.19 | 234.76 … 275.55 | 202.38 | 40.79 |
| COVER | -101.19 … 101.19 | 275.55 … 426.34 | 202.38 | 150.79 |
| COVER_TUCK | -100.39 … 100.39 | 426.34 … 466.34 | 200.79 | 40.0 |
| END_WALL_L | -141.19 … -101.19 | 82.38 … 234.76 | 40.0 | 152.38 |
| END_WALL_R | 101.19 … 141.19 | 82.38 … 234.76 | 40.0 | 152.38 |
| END_LOWER_L | -141.19 … -101.19 | 0.0 … 82.38 | 40.0 | 82.38 |
| END_LOWER_R | 101.19 … 141.19 | 0.0 … 82.38 | 40.0 | 82.38 |
| END_UPPER_L | -141.19 … -101.19 | 234.76 … 275.55 | 40.0 | 40.79 |
| END_UPPER_R | 101.19 … 141.19 | 234.76 … 275.55 | 40.0 | 40.79 |
| COVER_SIDE_L | -140.39 … -100.39 | 276.34 … 426.34 | 40.0 | 150.0 |
| COVER_SIDE_R | 100.39 … 140.39 | 276.34 … 426.34 | 40.0 | 150.0 |

Crease adjacency (panel on each side of the crease line):

| crease | panel A | panel B |
|---|---|---|
| p00.0 | FLOOR | BACK_WALL |
| p03.0 | BACK_WALL | COVER |
| p06.0 | END_WALL_L | FLOOR |
| p06.1 | END_WALL_L | END_UPPER_L |
| p08.0 | END_LOWER_L | END_WALL_L |
| p10.0 | FLAP_HINGE_STRIP | FRONT_WALL |
| p11.0 | FRONT_FLAP | FLAP_HINGE_STRIP |
| p12.0 | FRONT_WALL | FLOOR |
| p13.0 | FRONT_WALL | FLOOR |
| p19.0 | FLOOR | END_WALL_R |
| p19.1 | END_WALL_R | END_UPPER_R |
| p21.0 | END_LOWER_R | END_WALL_R |
| p24.0 | COVER | COVER_SIDE_R |
| p26.0 | COVER | COVER_TUCK |
| p28.0 | COVER_SIDE_L | COVER |
<!-- END GEN:topology -->

**Структура (OBSERVED):**
```
                COVER_TUCK
 COVER_SIDE_L ─ COVER ─ COVER_SIDE_R        cover (lid) на задній стінці
                BACK_WALL ── END_UPPER_L/R (прикріплені до END_WALL)
 END_WALL_L ─── FLOOR ─── END_WALL_R        4 стінки прикріплені до дна згинами
 END_LOWER_L    FRONT_WALL    END_LOWER_R   (END_LOWER — продовження торця вниз)
                FLAP_HINGE_STRIP (подвійний креаз, 2u)
                FRONT_FLAP (+ язик на нижньому краї, слот у дні біля переднього згину)
```
- 15 панелей/смуг. Центральна колонка: FRONT_FLAP – FLAP_HINGE_STRIP – FRONT_WALL – FLOOR – BACK_WALL – COVER – COVER_TUCK.
  Бічні: END_WALL_L/R (прикріплені до FLOOR), END_LOWER_L/R і END_UPPER_L/R (прикріплені до END_WALL), COVER_SIDE_L/R (прикріплені до COVER).
- Клею-клапана (glue flap) немає.
- **Креази:** 15 сегментів у 13 шляхах; усі 30 кінців креазів закінчуються **у вершинах Cut-контуру** (30/30 у всіх зразках): немає вільних кінців
  і немає Т-з'єднань у внутрішності різу (OBSERVED). Креаз у слоті розривається: p12/p13 закінчуються на кінцях пласкої частини слота.
- **Різи:** різ-щілини між передньою стінкою/клапаном і END_LOWER (p14/p15), між BACK_WALL і END_UPPER (p01/p04), нотч-релі на краях нижніх клапанів.
- **Криві різи:** слот (p16, 4 дуги), бічні клапани кришки (p23/p27: дуга `1u` біля основи + кінчик), tuck (p25: два кути).
- **Дзеркальна симетрія** лівий/правий (≤ 0.001 мм) — шаблон можна будувати наполовину.
- На лінії `Y_FRONT_FOLD` різ p16.0 лежить рівно на лінії креза, між p12 і p13 (OBSERVED, відхилення 0.000 мм).

## H. FEFCO / ECMA comparison (research only)

**Джерела й межі.** Офіційний каталог FEFCO/ECMA недоступний у цьому середовищі (egress до сторінок-каталогів заблоковано),
тому порівняння спирається лише на результати пошуку (комерційні описи). Це **слабке джерело**.

| Ознака | OBSERVED у наших PDF | PUBLIC STANDARD COMPARISON (сніпети) |
|---|---|---|
| Один шматок | так, одна заготовка | FEFCO 04xx — «folder»-тип, зазвичай один шматок |
| Дно + 4 стінки | дно з 4 стінками, прикріпленими згинами | 0427: «all four side walls … connected to the floor … creasing line» |
| Кришка | на задній стінці, 2 бічні клапани + tuck | 0427: кришка — продовження задньої панелі; бічні клапани кришки заходять у корпус, tuck знизу |
| Замок | 1 слот на дні біля переднього згину, язик на краї переднього клапана; на торцях — подовження (END_LOWER/UPPER), видимих замкових язиків немає | 0427: «side panels … pressed into the slots inside the box» (ear-lock); 0426: кришка і подовжені бічні клапани |
| Клейовий шов | відсутній | ECMA group A = коробка з поздовжнім клейовим швом — **не збігається** |

**Висновок:** топологія **узгоджується з родиною FEFCO 04xx (folder-тип, найближчі сусіди 0426/0427)**, але **точну ідентичність
не можна стверджувати**: у публічних описах 0427 замки по торцях, у наших PDF їх немає (лише один слот/язик спереду).
ECMA A20.20.xx (tuck-end з клейовим швом) — не збігається. **Ідентичність UNKNOWN**; не записувати код FEFCO як факт без
офіційного каталогу.

## I. Independent geometry specification

Конвеєр: `Inputs → parameters → landmarks → panels → creases → flaps → slot → curved sections → normalized Dieline`.
Вимога приймання: рушій має відтворити 4 референси (`reference/normalized/*.json`) у допуску **0.05 мм** по кожному примітиву.

| Етап | Зміст | Статус |
|---|---|---|
| Inputs | `L, W, D` (мм), одиниця `u` (за замовчуванням 0.79375; зв'язок з board невідомий) | **IMPLEMENTABLE NOW** |
| Parameters | вільні члени = цілі кратні `u`; метрична стала `10 мм` для скосу | **NEEDS VALIDATION** (залежність від board невідома) |
| Landmarks | рівні `Y_*`, `X_*` за розділом B | **IMPLEMENTABLE NOW** (діапазон L∈{160,200}, W∈{150,180}, D∈{30,40}); поза діапазоном — **NEEDS VALIDATION** |
| Panels | 15 прямокутників з розділу G | **IMPLEMENTABLE NOW** |
| Creases | 15 сегментів, подвійні (1u, 2u), розрив на слоті, кінці на вершинах різу | **IMPLEMENTABLE NOW** |
| Cut contour | прямі ділянки, нотч-релі, щілини p01/p04/p14/p15, 4 дуги слота | **IMPLEMENTABLE NOW** (форми нотчів потребують точних координат) |
| Flaps: front flap + язик | висота `D`, язик = ширина слота, глибина 0 | **IMPLEMENTABLE NOW** |
| Slot | стадіон `3u` заввишки, півколо `1.5u`, нижня сторона на `Y_FRONT_FOLD` | форма — **IMPLEMENTABLE NOW**; **ширина** `L/2 − 29.209` лише для L∈[160,200] — **UNKNOWN** закон; кількість/положення слотів — **UNKNOWN** |
| Curved: малі кутові дуги, кінці слота | `1u`, `1.5u` константи | **IMPLEMENTABLE NOW** |
| Curved: кути tuck | `r = floor((D/2)/u)·u` | **NEEDS VALIDATION** (2 значення D) |
| Curved: кінчик бічного клапана | коло `r_tuck`, дотичне до вертикалі й скосу | побудова **IMPLEMENTABLE NOW**; кут α (`tanα·W = 0.5953(D−10)`) — **NEEDS VALIDATION** |
| Dieline output | `Path{type: cut / crease / slot}`, мм, початок у нижньому лівому куті, шари CUT/CREASE/SLOT | **IMPLEMENTABLE NOW** |
| Інші стилі (flap detail, cover style, slot count/style) | — | **UNKNOWN** |

Рекомендація: спершу harness порівняння з референсами (нормалізація й допуски), потім рушій у межах підтвердженого діапазону;
кожну формулу з розділів E, D позначити в коді статусом і відмовлятися (`raise`), поза підтвердженим діапазоном.

## J. Next ArtiosCAD experiments (пріоритет)

| # | Експеримент | Що змінюється | Гіпотеза / що перевіряє |
|---|---|---|---|
| 1 | **Протокол експорту 1:1**: перезаписати всі 4 існуючі розміри, масштаб 100 %, без «вписати в сторінку», однакова сторінка | лише налаштування експорту | прибирає залежність від різного масштабу; прямо перевіряє `u = 0.79375` (абсолютний масштаб без міток) |
| 2 | **Той самий L/W/D (200×150×40), три board з різним caliper** (напр. ≈0.4, ≈0.8, ≈1.2 мм) | лише board | чи `u` = caliper board; які вільні члени (`k·u`) змінюються; чи `10 мм` стала лишається |
| 3 | **Серія D** (15, 20, 25, 30, 35, 40, 50, 60) при L=200, W=150 | лише D | закон радіуса tuck (`floor` vs `round` vs інше), закон α (форма `D−10`, нуль при D=10), лінійність за D |
| 4 | **Серія L** (80, 100, 120, 140, 160, 180, 200, 240, 300) при W=150, D=40 | лише L | закон ширини слота (лінія / таблиця / округлення / clamp), мінімальний L |
| 5 | **Серія W** (80, 100, 120, 150, 180, 220) при L=200, D=40 | лише W | перевірка `tanα ∝ 1/W`, лінійність висот |
| 6 | **Двофакторні комбінації**: (W=180,D=30), (L=160,W=180), (L=160,D=30) | два параметри разом | перехресні члени (особливо W·D для α і L·D для радіусів) |
| 7 | **Кількість слотів** 1, 2, 3, 4 при базі | лише slot count | положення/відступи/ширини кожного слота, чи змінюється решта геометрії |
| 8 | **Стиль слота** (cut-out / crushed / 3 sides cut) | лише slot style | топологія слота (які сторони різ/креаз) |
| 9 | **Стиль клапана**: flap height (meet in center / out to blank / user defined / cut back), flap detail (no scrap / angled / rounded / cut back), cover style (squared / angled / rounded / no scrap) — по одному | лише стиль | топологія й радіуси кутів, скос бічного клапана; які орієнтири змінюються |
| 10 | **Збурення параметрів** у діалогах (Caliper fit / Clearance / Cover / Slot-Tab / Flap values): змінити по одному значенню | один параметр | які координати рухаються — без доступу до формул, лише геометрія виходу |

Усі експерименти — один фактор за раз, 1:1 експорт, база `200×150×40`, board `I-SBS-16`, якщо не вказано інше.

## K. Final summary

### A. CONFIRMED FACTS
1. Усі 4 PDF — векторні, з каналами `/Separation /Cut` і `/Separation /Crease`; роль береться з імені каналу.
2. Топологія ідентична (38 Cut-ліній + 10 чверть-дуг + 15 Crease-ліній; порядок примітивів однаковий); 30/30 кінців креазів — у вершинах Cut-контуру.
3. Дзеркальна симетрія лівий/правий ≤ 0.001 мм; вісь симетрії = центр bbox.
4. Масштаб експорту різний у кожному PDF; радіуси й проміжок креза в кожному PDF — цілі кратні однієї одиниці.
5. Незалежна оцінка одиниці `0.7938 ± 0.0005 мм` (за умови точних різниць міток).
6. Розв'язка осей: L ↔ X (Y незмінний ≤ 0.009 мм); W ↔ Y (X незмінний ≤ 0.01 мм, крім 4 кінцевих точок скосу ≤ 0.39 мм).
7. Слот: центр на осі, висота `3u`, кінці — півкола `1.5u`, нижня сторона на лінії переднього згину, язик = ширина слота.
8. Нелінійні/незчищені координати знаходяться виключно у p23, p27 (бічні клапани кришки) і p25 (tuck).

### B. PROVISIONAL / SAMPLE-DERIVED EQUATIONS
Розділ B (рівні й розміри панелей, залишок ≤ 0.013 мм); слот `ширина_зовн = L/2 − 29.209` (лише L∈{160,200});
радіус tuck `r = floor((D/2)/u)·u`; кут скосу `tanα·W = 0.5953·(D − 10)`; кінчик: `run = D − r(1−sinα)`, `rise = r·cosα`
(останнє — DERIVED побудова). Діапазон: L∈{160,200}, W∈{150,180}, D∈{30,40}; один стиль, один board.

### C. HYPOTHESES
- `u = 1/32″` точно (середня впевненість); `u` = caliper board (низька).
- `r_tuck = floor((D/2)/u)·u` (два значення D).
- Скіс `tanα ∝ (D−10)/W` (константа `10 мм` метрична).
- Ширина слота `L/2 − 29.209` — лінійна, а не таблична.
- Родина FEFCO 04xx (сусіди 0426/0427) — слабке джерело, ідентичність не встановлена.

### D. UNKNOWN / NOT DETERMINABLE
- Абсолютний масштаб без міток; зв'язок `u` з board caliper; закони поза L∈{160,200}, W∈{150,180}, D∈{30,40}.
- Закон ширини слота й параметри бібліотеки слота; кількість/позиції слотів; стилі слота.
- Закон радіуса за D за межами 30/40; закон α за D; перехресні члени W·D, L·D, L·W (жоден зразок не змінює два параметри).
- Стилі клапана/кришки (`angled / rounded / no scrap / cut back`), точна FEFCO/ECMA-ідентичність, роль END_UPPER/END_LOWER.
- Точні координати handle-ів Безьє (перекіс до 0.2°) — несуттєво для виробництва.

### E. NEXT ARTIOSCAD EXPERIMENTS
Таблиця розділу J: (1) експорт 1:1; (2) інший board; (3) серія D; (4) серія L; (5) серія W; (6) двофакторні комбінації;
(7) кількість слотів; (8) стиль слота; (9) стилі клапана/кришки; (10) збурення параметрів.

### F. RECOMMENDED IMPLEMENTATION ORDER
1. Harness порівняння: нормалізація, допуск 0.05 мм, 4 референси як фікстури (перша перевірка — зелений на всіх чотирьох).
2. Модель Dieline (`Path`, мм, шари CUT/CREASE/SLOT) і SVG-експорт.
3. Рівні й панелі (розділ B) + креази (подвійні, розрив на слоті) — повністю у підтвердженому діапазоні.
4. Різи: щілини, нотч-релі, слот (форма константами `u`, ширина зі «стражем» діапазону).
5. Криві: малі дуги й кінці слота (константи), tuck (`floor`, статус HYPOTHESIS), кінчик (коло, α — статус PROVISIONAL).
6. Тільки після пунктів 1–5 і після експериментів 1–6 (розділ J) — зняти захисні обмеження діапазону і розширювати стилі.
