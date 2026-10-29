// Round 46 (Liam, 2026-10-29): light and dark mode. A classic script in <head>, so the saved choice is on <html>
// before the page paints (no flash of the other theme). No choice saved: the computer's own setting
// (prefers-color-scheme, in styles.css). The choice is a per-browser convenience in localStorage; when storage is
// blocked the button still works for the visit.
(function () {
  var KEY = "cfig-theme";
  var root = document.documentElement;
  var dark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (e) { /* storage blocked: follow the computer */ }

  function current() {
    var t = root.getAttribute("data-theme");
    if (t === "light" || t === "dark") return t;
    return dark && dark.matches ? "dark" : "light";
  }
  function set(t) {
    root.setAttribute("data-theme", t);
    try { localStorage.setItem(KEY, t); } catch (e) { /* this visit only */ }
  }
  window.__theme = { current: current, set: set };

  document.addEventListener("DOMContentLoaded", function () {
    var b = document.getElementById("theme-toggle");
    if (!b) return;
    function label() {
      var isDark = current() === "dark";
      b.textContent = isDark ? "☀ Light mode" : "☾ Dark mode";
      b.setAttribute("aria-pressed", isDark ? "true" : "false");
    }
    label();
    b.addEventListener("click", function () { set(current() === "dark" ? "light" : "dark"); label(); });
    if (dark && dark.addEventListener) dark.addEventListener("change", label);
  });
})();
