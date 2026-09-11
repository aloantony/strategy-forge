/* Strategy Forge · Wiki — interacciones mínimas, sin dependencias externas. */
(function () {
  "use strict";
  var root = document.documentElement;

  /* Tema claro/oscuro persistente */
  try { var s = localStorage.getItem("ta-wiki-theme"); if (s) root.setAttribute("data-theme", s); } catch (e) {}
  function syncThemeLabel() {
    var dark = root.getAttribute("data-theme") === "dark";
    document.querySelectorAll(".theme-toggle .label").forEach(function (el) { el.textContent = dark ? "Claro" : "Oscuro"; });
    document.querySelectorAll(".theme-toggle .ico").forEach(function (el) { el.textContent = dark ? "☀" : "☾"; });
  }
  function toggleTheme() {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("ta-wiki-theme", next); } catch (e) {}
    syncThemeLabel();
  }

  /* Marca el enlace activo según el archivo actual */
  var here = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  document.querySelectorAll(".sidebar nav a").forEach(function (a) {
    if ((a.getAttribute("href") || "").toLowerCase() === here) a.classList.add("active");
  });

  /* Navegación móvil */
  function setNav(open) { document.body.classList.toggle("nav-open", open); }
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (t.closest(".nav-toggle")) { setNav(!document.body.classList.contains("nav-open")); return; }
    if (t.closest(".nav-backdrop")) { setNav(false); return; }
    if (t.closest(".theme-toggle")) { toggleTheme(); return; }
    if (t.closest(".sidebar nav a")) { setNav(false); }
  });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") setNav(false); });

  /* Botón "copiar" en cada bloque de código */
  document.querySelectorAll("pre").forEach(function (pre) {
    var btn = document.createElement("button");
    btn.className = "copy-btn"; btn.type = "button"; btn.textContent = "Copiar";
    btn.addEventListener("click", function () {
      var code = pre.querySelector("code");
      var text = (code ? code.innerText : pre.innerText);
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = "Copiado"; btn.classList.add("done");
        setTimeout(function () { btn.textContent = "Copiar"; btn.classList.remove("done"); }, 1400);
      });
    });
    pre.appendChild(btn);
  });

  syncThemeLabel();
})();
