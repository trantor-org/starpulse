// mockup: opens the dialog a ?s= state names and fills it through the page's own inputs, as a person would
(() => {
  const s = new URLSearchParams(location.search).get("s");
  const Y = window.__SCHEMES__ || {};
  const until = (find) => new Promise((done) => {
    const hit = find();
    if (hit) return done(hit);
    const mo = new MutationObserver(() => { const h = find(); if (h) { mo.disconnect(); done(h); } });
    mo.observe(document.documentElement, { subtree: true, childList: true, attributes: true });
  });
  const $ = (sel) => () => document.querySelector(sel);
  const byText = (sel, text) => () => [...document.querySelectorAll(sel)].find((e) => e.textContent.trim().startsWith(text));
  const type = (el, value) => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const paste = { "import-preview": "onedark", "import-warn": "kanagawa", "import-refused": "twilight" };
  const run = async () => {
    if (s && s.startsWith("import")) {
      (await until(byText("#admin .tile.add", "+Import scheme"))).click();
      const box = await until($('#kbm textarea[aria-label="Scheme YAML"]'));
      if (paste[s]) type(box, Y[paste[s]]);
      if (s === "import-invalid") type(box, "scheme: \"Half a scheme\"\nbase00: \"1d1f21\"\nbase01: \"282a2e\"\nbase08: \"cc66\"");
    } else if (s === "rename" || s === "delete") {
      (await until(byText("#admin .acts button", s === "rename" ? "Rename" : "Delete"))).click();
    } else if (s === "bg-color" || s === "bg-refused") {
      (await until(byText("#admin .tile.add", "+Add background"))).click();
      if (s === "bg-refused") type(await until($('#kbm input[aria-label="Surface hex"]')), "#5a6b8c");
    }
  };
  if (s) run();
})();
