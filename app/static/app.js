// Kleine UI-Verbesserungen: Toasts automatisch ausblenden, Theme-Umschalter, Lösch-Bestätigungen.
(function () {
  "use strict";

  // Theme (hell/dunkel) — Wahl bleibt in localStorage gespeichert
  var root = document.documentElement;
  var btn = document.querySelector(".theme-btn");
  function applyTheme(t) {
    root.setAttribute("data-theme", t);
    if (btn) btn.textContent = t === "dark" ? "☀️" : "🌙";
    if (btn) btn.title = t === "dark" ? "Helles Design" : "Dunkles Design";
  }
  var saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) { /* ignore */ }
  applyTheme(saved === "dark" ? "dark" : "light");
  if (btn) {
    btn.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
    });
  }

  // Flash-Meldungen: Klick oder nach 6 s ausblenden
  document.querySelectorAll(".flash").forEach(function (el) {
    var timer = setTimeout(function () { dismiss(el); }, 6000);
    el.addEventListener("click", function () { clearTimeout(timer); dismiss(el); });
    function dismiss(node) {
      node.classList.add("leaving");
      setTimeout(function () { node.remove(); }, 320);
    }
  });

  // Bestätigungsdialog bei data-confirm-Links (z. B. Löschen)
  document.querySelectorAll("a[data-confirm]").forEach(function (a) {
    a.addEventListener("click", function (ev) {
      if (!window.confirm(a.getAttribute("data-confirm") || "Wirklich ausführen?")) {
        ev.preventDefault();
      }
    });
  });
})();
