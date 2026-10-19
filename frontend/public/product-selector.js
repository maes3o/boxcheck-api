/**
 * BoxCheck — Tier 1 product/format selector.
 *
 * Self-contained, framework-free component. Deliberately unstyled beyond a
 * few structural class names (bc-product-*) — visual design is Gemini's; this
 * only handles behavior/state and talks to the backend.
 *
 * INTEGRATION (see README_INTEGRATION.md for the full walkthrough):
 *   1. Add a GET /products endpoint on the backend returning
 *      products.products_catalog_response() (mirrors the existing GET
 *      /profiles pattern — see products.py).
 *   2. Drop a <div id="bc-product-selector"></div> somewhere before the
 *      upload zone in index.html, and include this script.
 *   3. Call BoxCheckProductSelector.init({ mountId: 'bc-product-selector' }).
 *   4. Listen for the 'boxcheck:product-selected' event (bubbles on
 *      document) to read { productId, formatId } and include them in the
 *      existing /check POST payload (e.g. as extra form fields or query
 *      params — match however print_method is currently sent).
 *   5. Language: this reads window.BoxCheckLang if it's already set by the
 *      existing UA/EN toggle (expects 'ua' or 'en'); otherwise defaults to
 *      'ua'. If the real toggle uses a different global/mechanism, swap the
 *      two lines marked LANG HOOK below to match it — everything else is
 *      independent of that.
 */
(function () {
  "use strict";

  const TIER1_ORDER = ["business_card", "flyer", "brochure", "poster"];

  // Fallback catalog used only if GET /products isn't wired up yet, so this
  // component is drop-in testable before the backend endpoint exists. Keep
  // in sync with products.py, or better: delete this once /products is live.
  const FALLBACK_CATALOG = {
    business_card: {
      tier: 1, name_ua: "Візитки", name_en: "Business cards",
      formats: [
        { id: "eu_90x50", label_ua: "90×50 мм (Європа)", label_en: "90×50 mm (Europe)" },
        { id: "us_3.5x2", label_ua: "3.5×2″ (США)", label_en: "3.5×2″ (US)" },
      ],
    },
    flyer: {
      tier: 1, name_ua: "Флаєри/листівки", name_en: "Flyers / postcards",
      formats: [
        { id: "a6", label_ua: "A6 (105×148 мм)", label_en: "A6 (105×148 mm)" },
        { id: "a5", label_ua: "A5 (148×210 мм)", label_en: "A5 (148×210 mm)" },
        { id: "a4", label_ua: "A4 (210×297 мм)", label_en: "A4 (210×297 mm)" },
        { id: "100x150", label_ua: "100×150 мм", label_en: "100×150 mm" },
        { id: "us_4x6", label_ua: "4×6″ (США)", label_en: "4×6″ (US)" },
      ],
    },
    brochure: {
      tier: 1, name_ua: "Буклети/брошури", name_en: "Booklets / brochures",
      formats: [
        { id: "a4", label_ua: "A4 (210×297 мм)", label_en: "A4 (210×297 mm)" },
        { id: "a5", label_ua: "A5 (148×210 мм)", label_en: "A5 (148×210 mm)" },
      ],
    },
    poster: {
      tier: 1, name_ua: "Постери/плакати", name_en: "Posters",
      formats: [
        { id: "a3", label_ua: "A3 (297×420 мм)", label_en: "A3 (297×420 mm)" },
        { id: "a2", label_ua: "A2 (420×594 мм)", label_en: "A2 (420×594 mm)" },
        { id: "a1", label_ua: "A1 (594×841 мм)", label_en: "A1 (594×841 mm)" },
        { id: "50x70cm", label_ua: "50×70 см", label_en: "50×70 cm" },
        { id: "us_18x24", label_ua: "18×24″ (США)", label_en: "18×24″ (US)" },
      ],
    },
  };

  function currentLang() {
    // LANG HOOK (1/2): read the site's real language state here.
    return window.BoxCheckLang === "en" ? "en" : "ua";
  }

  function t(labelUa, labelEn) {
    // LANG HOOK (2/2): swap for the existing translation helper if one exists.
    return currentLang() === "en" ? labelEn : labelUa;
  }

  async function loadCatalog() {
    try {
      const res = await fetch("/products");
      if (!res.ok) throw new Error("bad status " + res.status);
      const data = await res.json();
      if (data && Object.keys(data).length) return data;
    } catch (e) {
      // silently fall back — endpoint may not exist yet during rollout
    }
    return FALLBACK_CATALOG;
  }

  function emitSelection(productId, formatId) {
    document.dispatchEvent(
      new CustomEvent("boxcheck:product-selected", {
        detail: { productId, formatId },
        bubbles: true,
      })
    );
  }

  function buildUI(root, catalog) {
    const state = { productId: null, formatId: null };

    const productWrap = document.createElement("div");
    productWrap.className = "bc-product-step bc-product-step-product";

    const heading = document.createElement("div");
    heading.className = "bc-product-heading";
    heading.textContent = t("Оберіть тип виробу", "Choose a product type");
    productWrap.appendChild(heading);

    const productList = document.createElement("div");
    productList.className = "bc-product-list";
    productWrap.appendChild(productList);

    const formatWrap = document.createElement("div");
    formatWrap.className = "bc-product-step bc-product-step-format";
    formatWrap.hidden = true;

    const formatHeading = document.createElement("div");
    formatHeading.className = "bc-product-heading";
    formatHeading.textContent = t("Оберіть формат", "Choose a format");
    formatWrap.appendChild(formatHeading);

    const formatList = document.createElement("div");
    formatList.className = "bc-product-list";
    formatWrap.appendChild(formatList);

    const skipBtn = document.createElement("button");
    skipBtn.type = "button";
    skipBtn.className = "bc-product-skip";
    skipBtn.textContent = t(
      "Не знаю формат — пропустити",
      "Not sure of the format — skip"
    );
    skipBtn.addEventListener("click", () => {
      state.formatId = null;
      emitSelection(state.productId, null);
    });
    formatWrap.appendChild(skipBtn);

    TIER1_ORDER.filter((id) => catalog[id]).forEach((productId) => {
      const product = catalog[productId];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "bc-product-card";
      btn.dataset.productId = productId;
      btn.textContent = t(product.name_ua, product.name_en);
      btn.addEventListener("click", () => {
        state.productId = productId;
        state.formatId = null;

        productList
          .querySelectorAll(".bc-product-card")
          .forEach((el) => el.classList.toggle("is-active", el === btn));

        formatList.innerHTML = "";
        const formats = product.formats || [];
        if (!formats.length) {
          formatWrap.hidden = true;
          emitSelection(state.productId, null);
          return;
        }

        formats.forEach((fmt) => {
          const fbtn = document.createElement("button");
          fbtn.type = "button";
          fbtn.className = "bc-format-card";
          fbtn.dataset.formatId = fmt.id;
          fbtn.textContent = t(fmt.label_ua, fmt.label_en);
          fbtn.addEventListener("click", () => {
            state.formatId = fmt.id;
            formatList
              .querySelectorAll(".bc-format-card")
              .forEach((el) => el.classList.toggle("is-active", el === fbtn));
            emitSelection(state.productId, state.formatId);
          });
          formatList.appendChild(fbtn);
        });

        formatWrap.hidden = false;
      });
      productList.appendChild(btn);
    });

    root.appendChild(productWrap);
    root.appendChild(formatWrap);
  }

  async function init(opts) {
    const mountId = (opts && opts.mountId) || "bc-product-selector";
    const root = document.getElementById(mountId);
    if (!root) {
      console.warn("[BoxCheckProductSelector] mount point #" + mountId + " not found");
      return;
    }
    const catalog = await loadCatalog();
    buildUI(root, catalog);
  }

  window.BoxCheckProductSelector = { init };
})();
