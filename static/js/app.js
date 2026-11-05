(function () {
  "use strict";

  const body = document.body;
  const botonAbrir = document.querySelector("[data-abrir-menu]");
  const cerrarMenu = document.querySelector("[data-cerrar-menu]");

  function alternarMenu(abierto) {
    body.classList.toggle("sidebar-abierta", abierto);
    if (botonAbrir) {
      botonAbrir.setAttribute("aria-expanded", String(abierto));
    }
  }

  if (botonAbrir) {
    botonAbrir.addEventListener("click", function () {
      alternarMenu(!body.classList.contains("sidebar-abierta"));
    });
  }

  if (cerrarMenu) {
    cerrarMenu.addEventListener("click", function () {
      alternarMenu(false);
    });
  }

  document.querySelectorAll(".sidebar .nav-enlace").forEach(function (enlace) {
    enlace.addEventListener("click", function () {
      alternarMenu(false);
    });
  });

  window.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape") {
      alternarMenu(false);
    }
  });

  document.querySelectorAll("[data-cerrar-mensaje]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      const toast = boton.closest(".toast");
      if (toast) {
        toast.remove();
      }
    });
  });

  document.querySelectorAll(".toast.success").forEach(function (toast) {
    window.setTimeout(function () {
      toast.classList.add("saliendo");
      window.setTimeout(function () {
        toast.remove();
      }, 250);
    }, 5000);
  });

  document.querySelectorAll("[data-imprimir]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      window.print();
    });
  });
})();
