(function () {
  "use strict";

  const formulario = document.getElementById("formulario-movimiento");
  const selectorProducto = document.getElementById("codigo");
  const selectorSede = document.getElementById("sede");
  const campoCantidad = document.getElementById("cantidad");
  const campoConfirmar = document.getElementById("confirmar-cruce");
  const infoStock = document.getElementById("info-stock");
  const resumenSedeEtiqueta = document.getElementById("resumen-sede-etiqueta");
  const resumenOtraEtiqueta = document.getElementById("resumen-otra-etiqueta");
  const resumenResultadoEtiqueta = document.getElementById("resumen-resultado-etiqueta");
  const resumenStock = document.getElementById("resumen-stock");
  const resumenOtra = document.getElementById("resumen-otra");
  const resumenResultado = document.getElementById("resumen-resultado");
  const resumenMensaje = document.getElementById("resumen-mensaje");
  const avisoCruce = document.getElementById("aviso-cruce");
  const avisoCruceTexto = document.getElementById("aviso-cruce-texto");
  const dialogoCruce = document.getElementById("dialogo-cruce");
  const dialogoMensaje = document.getElementById("dialogo-cruce-mensaje");
  const radiosTipo = document.querySelectorAll('input[name="tipo"]');

  if (!selectorProducto || !infoStock) {
    return;
  }

  let requiereConfirmacion = false;
  let mensajeCruce = "";

  if (campoConfirmar) {
    campoConfirmar.value = "0";
  }

  function tipoActual() {
    const marcado = document.querySelector('input[name="tipo"]:checked');
    return marcado ? marcado.value : "VENTA";
  }

  function marcarTipoSeleccionado() {
    document.querySelectorAll(".tipo-opcion").forEach(function (opcion) {
      const radio = opcion.querySelector('input[name="tipo"]');
      opcion.classList.toggle("seleccionado", Boolean(radio && radio.checked));
    });
  }

  function opcionProducto() {
    return selectorProducto.options[selectorProducto.selectedIndex];
  }

  function claveSede() {
    return selectorSede && selectorSede.value ? selectorSede.value : "principal";
  }

  function claveAlterna(clave) {
    return clave === "secundaria" ? "principal" : "secundaria";
  }

  function nombreSede(clave) {
    if (selectorSede) {
      const opcion = Array.from(selectorSede.options).find(function (item) {
        return item.value === clave;
      });
      if (opcion && opcion.dataset.nombre) {
        return opcion.dataset.nombre;
      }
    }
    return clave === "secundaria" ? "Sede Secundaria" : "Sede Principal";
  }

  function stockDeSede(opcion, clave) {
    if (!opcion) {
      return NaN;
    }
    const dato =
      clave === "secundaria" ? opcion.dataset.stockSecundario : opcion.dataset.stockPrincipal;
    return Number(dato);
  }

  function limpiarAvisoCruce() {
    requiereConfirmacion = false;
    mensajeCruce = "";
    if (avisoCruce) {
      avisoCruce.hidden = true;
    }
    if (avisoCruceTexto) {
      avisoCruceTexto.textContent = "";
    }
  }

  function actualizar(resetearConfirmacion) {
    if (resetearConfirmacion !== false) {
      if (campoConfirmar) {
        campoConfirmar.value = "0";
      }
    }
    limpiarAvisoCruce();

    const opcion = opcionProducto();
    const tipo = tipoActual();
    const sede = claveSede();
    const sedeAlterna = claveAlterna(sede);
    const nombreActual = nombreSede(sede);
    const nombreAlterno = nombreSede(sedeAlterna);
    const stockPrincipal = stockDeSede(opcion, "principal");
    const stockSecundario = stockDeSede(opcion, "secundaria");
    const stockSede = sede === "secundaria" ? stockSecundario : stockPrincipal;
    const stockOtra = sede === "secundaria" ? stockPrincipal : stockSecundario;
    const stockTotal = stockPrincipal + stockSecundario;
    const minimo = opcion ? Number(opcion.dataset.minimo) : NaN;

    marcarTipoSeleccionado();

    if (!opcion || !opcion.value || Number.isNaN(stockSede)) {
      infoStock.textContent = "Seleccione un producto para ver su stock disponible por sede.";
      infoStock.className = "ayuda";
      if (campoCantidad) {
        campoCantidad.removeAttribute("max");
      }
      if (resumenSedeEtiqueta) resumenSedeEtiqueta.textContent = "Stock en sede";
      if (resumenOtraEtiqueta) resumenOtraEtiqueta.textContent = "Otra sede";
      if (resumenResultadoEtiqueta) resumenResultadoEtiqueta.textContent = "Stock resultante";
      if (resumenStock) resumenStock.textContent = "—";
      if (resumenOtra) resumenOtra.textContent = "—";
      if (resumenResultado) {
        resumenResultado.textContent = "—";
        resumenResultado.className = "";
      }
      if (resumenMensaje) {
        resumenMensaje.textContent = "Seleccione producto, sede y cantidad para ver el resultado.";
        resumenMensaje.className = "ayuda";
      }
      limpiarAvisoCruce();
      return;
    }

    if (resumenSedeEtiqueta) resumenSedeEtiqueta.textContent = "Stock " + nombreActual;
    if (resumenOtraEtiqueta) resumenOtraEtiqueta.textContent = "Stock " + nombreAlterno;
    if (resumenStock) resumenStock.textContent = String(stockSede);
    if (resumenOtra) resumenOtra.textContent = String(stockOtra);

    if (tipo === "VENTA") {
      infoStock.textContent =
        nombreActual +
        ": " +
        stockSede +
        " unidades. " +
        nombreAlterno +
        ": " +
        stockOtra +
        " unidades. Total: " +
        stockTotal +
        ".";
      infoStock.className = stockSede <= minimo ? "ayuda peligro" : "ayuda";
      if (campoCantidad) {
        campoCantidad.max = String(Math.max(stockSede, stockOtra));
      }
    } else {
      infoStock.textContent =
        "Stock en " +
        nombreActual +
        ": " +
        stockSede +
        " unidades. El ingreso incrementará esta sede.";
      infoStock.className = "ayuda";
      if (campoCantidad) {
        campoCantidad.removeAttribute("max");
      }
    }

    const cantidad = campoCantidad ? Number(campoCantidad.value) : NaN;
    const cantidadValida = Number.isInteger(cantidad) && cantidad > 0;

    limpiarAvisoCruce();

    if (!resumenResultado || !resumenMensaje) {
      return;
    }

    if (resumenResultadoEtiqueta) {
      resumenResultadoEtiqueta.textContent = "Stock resultante";
    }

    if (!cantidadValida) {
      resumenResultado.textContent = "—";
      resumenResultado.className = "";
      resumenMensaje.textContent = "Ingrese una cantidad entera mayor que cero.";
      resumenMensaje.className = "ayuda";
      return;
    }

    if (tipo === "VENTA") {
      if (cantidad <= stockSede) {
        resumenResultado.textContent = String(stockSede - cantidad);
        resumenResultado.className = "";
        resumenMensaje.textContent =
          "Se descontarán " +
          cantidad +
          " unidades de " +
          nombreActual +
          ". Quedarán " +
          (stockSede - cantidad) +
          " en esa sede.";
        resumenMensaje.className = "ayuda";
      } else if (cantidad <= stockOtra) {
        requiereConfirmacion = true;
        mensajeCruce =
          stockSede <= 0
            ? "Producto agotado en " +
              nombreActual +
              ", disponible en " +
              nombreAlterno +
              " (Stock: " +
              stockOtra +
              "). ¿Desea proceder con la compra para retiro en la otra sede?"
            : "Stock insuficiente en " +
              nombreActual +
              " (disponible: " +
              stockSede +
              "), pero hay " +
              stockOtra +
              " unidades en " +
              nombreAlterno +
              ". ¿Desea proceder con la compra para retiro en la otra sede?";

        if (resumenResultadoEtiqueta) {
          resumenResultadoEtiqueta.textContent = "Stock restante en " + nombreAlterno;
        }
        resumenResultado.textContent = String(stockOtra - cantidad);
        resumenResultado.className = "";
        resumenMensaje.textContent =
          "Venta cruzada: se descontarán " +
          cantidad +
          " unidades de " +
          nombreAlterno +
          ". Quedarán " +
          (stockOtra - cantidad) +
          " en esa sede.";
        resumenMensaje.className = "ayuda peligro";

        if (avisoCruce && avisoCruceTexto) {
          avisoCruceTexto.textContent = mensajeCruce;
          avisoCruce.hidden = false;
        }
      } else {
        resumenResultado.textContent = "No permitido";
        resumenResultado.className = "texto-peligro";
        resumenMensaje.textContent =
          "No hay stock suficiente en una sola sede. " +
          nombreActual +
          ": " +
          stockSede +
          " y " +
          nombreAlterno +
          ": " +
          stockOtra +
          ".";
        resumenMensaje.className = "ayuda peligro";
      }
    } else {
      resumenResultado.textContent = String(stockSede + cantidad);
      resumenResultado.className = "";
      resumenMensaje.textContent =
        "Se sumarán " +
        cantidad +
        " unidades a " +
        nombreActual +
        ". El stock quedar\u00e1 en " +
        (stockSede + cantidad) +
        ".";
      resumenMensaje.className = "ayuda";
    }
  }

  function prepararEnvio(evento) {
    actualizar(false);

    if (!requiereConfirmacion) {
      return;
    }
    if (campoConfirmar && campoConfirmar.value === "1") {
      return;
    }

    evento.preventDefault();

    if (!dialogoCruce || typeof dialogoCruce.showModal !== "function") {
      if (window.confirm(mensajeCruce)) {
        if (campoConfirmar) campoConfirmar.value = "1";
        if (formulario) formulario.submit();
      }
      return;
    }

    if (dialogoMensaje) {
      dialogoMensaje.textContent = mensajeCruce;
    }
    dialogoCruce.returnValue = "";
    dialogoCruce.showModal();
  }

  selectorProducto.addEventListener("change", actualizar);
  if (selectorSede) {
    selectorSede.addEventListener("change", actualizar);
  }
  if (campoCantidad) {
    campoCantidad.addEventListener("input", actualizar);
  }
  radiosTipo.forEach(function (radio) {
    radio.addEventListener("change", actualizar);
  });

  if (formulario) {
    formulario.addEventListener("submit", prepararEnvio);
  }

  if (dialogoCruce) {
    dialogoCruce.addEventListener("close", function () {
      if (dialogoCruce.returnValue === "confirmar") {
        if (campoConfirmar) campoConfirmar.value = "1";
        if (formulario) {
          if (typeof formulario.requestSubmit === "function") {
            formulario.requestSubmit();
          } else {
            formulario.submit();
          }
        }
      } else if (campoConfirmar) {
        campoConfirmar.value = "0";
      }
    });
  }

  actualizar();
})();
