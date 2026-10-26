// The page tabs: Chart, Market today, News and Glossary. The open tab is remembered, so a refresh lands where you were.
window.Tabs = (() => {
  const TABS = ["chart", "market", "news", "glossary"];
  const KEY = "ma-tab";

  function show(name, remember = true) {
    if (!TABS.includes(name)) name = "chart";
    for (const t of TABS) {
      const on = t === name;
      document.getElementById(`tab-${t}`).hidden = !on;
      const btn = document.getElementById(`tab-btn-${t}`);
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-selected", on);
      btn.tabIndex = on ? 0 : -1;
    }
    if (remember) try { localStorage.setItem(KEY, name); } catch { /* private window */ }
  }

  document.querySelector(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) show(b.dataset.tab);
  });
  // left and right arrows move between tabs, as in any tab bar
  document.querySelector(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const i = TABS.findIndex((t) => !document.getElementById(`tab-${t}`).hidden);
    const next = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    show(next);
    document.getElementById(`tab-btn-${next}`).focus();
  });
  // any link or button with data-goto="news" (for example) switches tab
  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-goto]");
    if (g) { e.preventDefault(); show(g.dataset.goto); }
  });
  let first = null;
  try { first = localStorage.getItem(KEY); } catch { /* private window */ }
  show(first, false);

  return { show };
})();
