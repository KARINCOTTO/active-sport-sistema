"""Lógica de negocio del inventario multisede de ACTIVE SPORT S.A."""

from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = Path(os.environ.get("ACTIVE_SPORT_DATA_DIR", BASE_DIR))
PRODUCTOS_FILE = DATA_DIR / "productos.json"
MOVIMIENTOS_FILE = DATA_DIR / "movimientos.json"

SEDES = {
    "principal": {
        "id": "principal",
        "nombre": "Sede Principal",
        "corta": "Principal",
    },
    "secundaria": {
        "id": "secundaria",
        "nombre": "Sede Secundaria",
        "corta": "Secundaria",
    },
}
SEDE_PREDETERMINADA = "principal"
CAMPOS_STOCK_SEDE = {
    "principal": "stock_principal",
    "secundaria": "stock_secundario",
}

_LOCK = threading.RLock()
_TIPOS_VALIDOS = {"VENTA", "INGRESO"}
_CAMPOS_STOCK = ("stock_principal", "stock_secundario")
_CAMPOS_NUMERICOS = (*_CAMPOS_STOCK, "stock_minimo", "ventas_mes")
_PATRON_CODIGO = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,11}$")

_ORDENES = {
    "codigo": (lambda producto: producto["codigo"], False),
    "codigo_desc": (lambda producto: producto["codigo"], True),
    "nombre": (lambda producto: _normalizar_texto(producto["nombre"]), False),
    "nombre_desc": (lambda producto: _normalizar_texto(producto["nombre"]), True),
    "stock_asc": (lambda producto: (producto["stock_actual"], producto["codigo"]), False),
    "stock_desc": (lambda producto: (producto["stock_actual"], producto["codigo"]), True),
    "ventas_asc": (lambda producto: (producto["ventas_mes"], producto["codigo"]), False),
    "ventas_desc": (lambda producto: (producto["ventas_mes"], producto["codigo"]), True),
}


class InventarioError(ValueError):
    """Error controlado de las reglas de negocio del inventario."""


class ConfirmacionVentaCruzada(InventarioError):
    """La venta requiere confirmar el retiro desde la otra sede."""

    def __init__(
        self,
        codigo: str,
        nombre_producto: str,
        sede: str,
        sede_alterna: str,
        stock_sede: int,
        stock_alterno: int,
        cantidad: int,
    ) -> None:
        self.codigo = codigo
        self.nombre_producto = nombre_producto
        self.sede = sede
        self.sede_alterna = sede_alterna
        self.stock_sede = stock_sede
        self.stock_alterno = stock_alterno
        self.cantidad = cantidad

        nombre_sede_actual = SEDES[sede]["nombre"]
        nombre_sede_alterna = SEDES[sede_alterna]["nombre"]
        if stock_sede <= 0:
            mensaje = (
                f"Producto agotado en {nombre_sede_actual}, disponible en "
                f"{nombre_sede_alterna} (Stock: {stock_alterno}). ¿Desea proceder "
                "con la compra para retiro en la otra sede?"
            )
        else:
            mensaje = (
                f"Stock insuficiente en {nombre_sede_actual} (disponible: "
                f"{stock_sede}), pero hay {stock_alterno} unidades en "
                f"{nombre_sede_alterna}. ¿Desea proceder con la compra para retiro "
                "en la otra sede?"
            )

        self.mensaje = mensaje
        super().__init__(mensaje)


def _normalizar_texto(valor: Any) -> str:
    texto = str(valor or "").strip().lower()
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )


def normalizar_sede(valor: Any) -> str:
    clave = _normalizar_texto(valor)
    if not clave:
        return SEDE_PREDETERMINADA
    if clave in SEDES:
        return clave
    for sede in SEDES.values():
        if clave in {_normalizar_texto(sede["nombre"]), _normalizar_texto(sede["corta"])}:
            return sede["id"]
    raise InventarioError("La sede debe ser Sede Principal o Sede Secundaria.")


def nombre_sede(valor: Any) -> str:
    return SEDES.get(str(valor or ""), {}).get("nombre", str(valor or ""))


def _leer_json(ruta: Path, valor_por_defecto: Any) -> Any:
    if not ruta.exists():
        return valor_por_defecto
    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except (json.JSONDecodeError, OSError) as exc:
        raise InventarioError(
            f"No se pudo leer {ruta.name}. Verifique que el archivo sea JSON válido."
        ) from exc


def _escribir_json(ruta: Path, datos: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        with temporal.open("w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, ensure_ascii=False, indent=2)
            archivo.write("\n")
        os.replace(temporal, ruta)
    except OSError as exc:
        raise InventarioError(f"No se pudo guardar {ruta.name}.") from exc
    finally:
        if temporal.exists():
            temporal.unlink(missing_ok=True)


def _entero(valor: Any, campo: str) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError) as exc:
        raise InventarioError(f"El campo '{campo}' debe ser un número entero.") from exc


def _entero_no_negativo(valor: Any, campo: str) -> int:
    numero = _entero(valor, campo)
    if numero < 0:
        raise InventarioError(f"El campo '{campo}' no puede ser negativo.")
    return numero


def _validar_producto(producto: Any, indice: int) -> dict[str, Any]:
    if not isinstance(producto, dict):
        raise InventarioError(f"El producto en la posición {indice} no es válido.")

    codigo = str(producto.get("codigo", "")).strip().upper()
    nombre = str(producto.get("nombre", "")).strip()
    if not codigo or not nombre:
        raise InventarioError(f"El producto en la posición {indice} no tiene código o nombre.")

    if not any(campo in producto for campo in _CAMPOS_STOCK):
        producto["stock_principal"] = producto.get("stock_actual", 0)
        producto["stock_secundario"] = 0

    for campo in _CAMPOS_NUMERICOS:
        producto[campo] = _entero_no_negativo(producto.get(campo, 0), campo)

    producto["stock_actual"] = producto["stock_principal"] + producto["stock_secundario"]
    producto["codigo"] = codigo
    producto["nombre"] = nombre
    return producto


def _validar_datos_producto(
    codigo: str,
    nombre: str,
    stock_principal: Any,
    stock_secundario: Any,
    stock_minimo: Any,
    ventas_mes: Any,
) -> tuple[str, str, int, int, int, int]:
    codigo = (codigo or "").strip().upper()
    nombre = (nombre or "").strip()

    if not codigo:
        raise InventarioError("El código del producto es obligatorio.")
    if not _PATRON_CODIGO.match(codigo):
        raise InventarioError(
            "El código debe tener entre 2 y 12 caracteres y usar solo letras, números o guiones."
        )
    if len(nombre) < 3:
        raise InventarioError("El nombre del producto debe tener al menos 3 caracteres.")
    if len(nombre) > 80:
        raise InventarioError("El nombre del producto no puede superar los 80 caracteres.")

    return (
        codigo,
        nombre,
        _entero_no_negativo(stock_principal, "stock_principal"),
        _entero_no_negativo(stock_secundario, "stock_secundario"),
        _entero_no_negativo(stock_minimo, "stock_minimo"),
        _entero_no_negativo(ventas_mes, "ventas_mes"),
    )


def cargar_productos() -> list[dict[str, Any]]:
    with _LOCK:
        productos = _leer_json(PRODUCTOS_FILE, [])
    if not isinstance(productos, list):
        raise InventarioError("El archivo productos.json debe contener una lista de productos.")
    return [_validar_producto(producto, indice) for indice, producto in enumerate(productos)]


def cargar_movimientos() -> list[dict[str, Any]]:
    with _LOCK:
        movimientos = _leer_json(MOVIMIENTOS_FILE, [])
    if not isinstance(movimientos, list):
        raise InventarioError("El archivo movimientos.json debe contener una lista de movimientos.")
    return movimientos


def obtener_producto(codigo: str) -> dict[str, Any] | None:
    codigo = (codigo or "").strip().upper()
    for producto in cargar_productos():
        if producto["codigo"] == codigo:
            return producto
    return None


def buscar_productos(consulta: str = "", estado: str = "todos", orden: str = "codigo") -> list[dict[str, Any]]:
    productos = cargar_productos()
    consulta_normalizada = _normalizar_texto(consulta)

    if consulta_normalizada:
        productos = [
            producto
            for producto in productos
            if consulta_normalizada
            in _normalizar_texto(f"{producto['codigo']} {producto['nombre']}")
        ]

    if estado == "alerta":
        productos = [
            producto
            for producto in productos
            if producto["stock_actual"] <= producto["stock_minimo"]
        ]
    elif estado == "disponible":
        productos = [
            producto
            for producto in productos
            if producto["stock_actual"] > producto["stock_minimo"]
        ]
    elif estado == "agotado":
        productos = [producto for producto in productos if producto["stock_actual"] == 0]

    funcion_orden, descendente = _ORDENES.get(orden, _ORDENES["codigo"])
    productos.sort(key=funcion_orden, reverse=descendente)
    return productos


def calcular_alertas(productos: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if productos is None:
        productos = cargar_productos()
    alertas = []
    for producto in productos:
        stock_actual = _entero(producto.get("stock_actual"), "stock_actual")
        stock_minimo = _entero(producto.get("stock_minimo"), "stock_minimo")
        if stock_actual <= stock_minimo:
            alerta = dict(producto)
            alerta["faltante"] = max(stock_minimo - stock_actual, 0)
            alertas.append(alerta)
    alertas.sort(key=lambda alerta: (-alerta["faltante"], alerta["codigo"]))
    return alertas


def resumen_inventario(productos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if productos is None:
        productos = cargar_productos()

    alertas = calcular_alertas(productos)
    total_productos = len(productos)
    total_principal = sum(producto["stock_principal"] for producto in productos)
    total_secundario = sum(producto["stock_secundario"] for producto in productos)
    total_unidades = total_principal + total_secundario
    total_ventas_mes = sum(producto["ventas_mes"] for producto in productos)
    total_minimos = sum(producto["stock_minimo"] for producto in productos)
    productos_disponibles = total_productos - len(alertas)
    porcentaje_disponible = (
        round(productos_disponibles / total_productos * 100, 1) if total_productos else 100.0
    )
    cumplimiento_minimos = (
        round(total_unidades / total_minimos * 100, 1) if total_minimos else 100.0
    )

    return {
        "productos": productos,
        "alertas": alertas,
        "total_productos": total_productos,
        "total_unidades": total_unidades,
        "total_principal": total_principal,
        "total_secundario": total_secundario,
        "total_ventas_mes": total_ventas_mes,
        "total_alertas": len(alertas),
        "productos_disponibles": productos_disponibles,
        "productos_agotados": sum(
            1 for producto in productos if producto["stock_actual"] == 0
        ),
        "productos_agotados_principal": sum(
            1 for producto in productos if producto["stock_principal"] == 0
        ),
        "productos_agotados_secundario": sum(
            1 for producto in productos if producto["stock_secundario"] == 0
        ),
        "unidades_faltantes": sum(alerta["faltante"] for alerta in alertas),
        "porcentaje_disponible": porcentaje_disponible,
        "cumplimiento_minimos": cumplimiento_minimos,
        "max_stock": max(
            (producto["stock_actual"] for producto in productos), default=1
        )
        or 1,
    }


def crear_producto(
    codigo: str,
    nombre: str,
    stock_principal: Any,
    stock_secundario: Any,
    stock_minimo: Any,
    ventas_mes: Any = 0,
) -> dict[str, Any]:
    (
        codigo,
        nombre,
        stock_principal,
        stock_secundario,
        stock_minimo,
        ventas_mes,
    ) = _validar_datos_producto(
        codigo,
        nombre,
        stock_principal,
        stock_secundario,
        stock_minimo,
        ventas_mes,
    )

    with _LOCK:
        productos = cargar_productos()
        if any(producto["codigo"] == codigo for producto in productos):
            raise InventarioError(f"Ya existe un producto con el código {codigo}.")

        producto = {
            "codigo": codigo,
            "nombre": nombre,
            "stock_principal": stock_principal,
            "stock_secundario": stock_secundario,
            "stock_actual": stock_principal + stock_secundario,
            "stock_minimo": stock_minimo,
            "ventas_mes": ventas_mes,
        }
        productos.append(producto)
        _escribir_json(PRODUCTOS_FILE, productos)

    return producto


def actualizar_producto(codigo: str, nombre: str, stock_minimo: Any) -> dict[str, Any]:
    codigo = (codigo or "").strip().upper()
    nombre = (nombre or "").strip()
    stock_minimo = _entero_no_negativo(stock_minimo, "stock_minimo")

    if len(nombre) < 3:
        raise InventarioError("El nombre del producto debe tener al menos 3 caracteres.")
    if len(nombre) > 80:
        raise InventarioError("El nombre del producto no puede superar los 80 caracteres.")

    with _LOCK:
        productos = cargar_productos()
        producto = next(
            (item for item in productos if item["codigo"] == codigo),
            None,
        )
        if producto is None:
            raise InventarioError(f"El producto con código {codigo} no existe en el catálogo.")

        producto["nombre"] = nombre
        producto["stock_minimo"] = stock_minimo
        _escribir_json(PRODUCTOS_FILE, productos)

    return producto


def registrar_movimiento(
    codigo: str,
    tipo: str,
    cantidad: Any,
    observacion: str = "",
    sede: str = SEDE_PREDETERMINADA,
    confirmar_cruce: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    codigo = (codigo or "").strip().upper()
    tipo = (tipo or "").strip().upper()
    observacion = (observacion or "").strip()
    sede = normalizar_sede(sede)
    confirmar_cruce = bool(confirmar_cruce)

    if tipo not in _TIPOS_VALIDOS:
        raise InventarioError("El tipo de movimiento debe ser VENTA o INGRESO.")
    if not codigo:
        raise InventarioError("Debe seleccionar un producto.")
    if len(observacion) > 250:
        raise InventarioError("La observación no puede superar los 250 caracteres.")

    cantidad = _entero(cantidad, "cantidad")
    if cantidad <= 0:
        raise InventarioError("La cantidad debe ser un número entero mayor que cero.")

    with _LOCK:
        productos = cargar_productos()
        indice = next(
            (i for i, producto in enumerate(productos) if producto["codigo"] == codigo),
            None,
        )
        if indice is None:
            raise InventarioError(f"El producto con código {codigo} no existe en el catálogo.")

        producto = productos[indice]
        sede_afectada = sede
        venta_cruzada = False

        if tipo == "VENTA":
            stock_sede = producto[CAMPOS_STOCK_SEDE[sede]]
            sede_alterna = "secundaria" if sede == "principal" else "principal"
            stock_alterno = producto[CAMPOS_STOCK_SEDE[sede_alterna]]

            if cantidad > stock_sede:
                if cantidad > stock_alterno:
                    raise InventarioError(
                        "No hay stock suficiente para completar la venta en una sola sede. "
                        f"{SEDES[sede]['nombre']}: {stock_sede} unidades; "
                        f"{SEDES[sede_alterna]['nombre']}: {stock_alterno} unidades."
                    )
                if not confirmar_cruce:
                    raise ConfirmacionVentaCruzada(
                        codigo=codigo,
                        nombre_producto=producto["nombre"],
                        sede=sede,
                        sede_alterna=sede_alterna,
                        stock_sede=stock_sede,
                        stock_alterno=stock_alterno,
                        cantidad=cantidad,
                    )
                sede_afectada = sede_alterna
                venta_cruzada = True

            producto[CAMPOS_STOCK_SEDE[sede_afectada]] -= cantidad
            producto["ventas_mes"] += cantidad

            if venta_cruzada:
                nota = (
                    f"Retiro en {SEDES[sede_afectada]['nombre']} por venta cruzada "
                    f"desde {SEDES[sede]['nombre']}."
                )
                espacio = max(250 - len(nota) - 3, 0)
                base = observacion[:espacio].rstrip(" .;")
                observacion = f"{base} | {nota}" if base else nota
        else:
            producto[CAMPOS_STOCK_SEDE[sede]] += cantidad

        producto["stock_actual"] = (
            producto["stock_principal"] + producto["stock_secundario"]
        )

        movimientos = cargar_movimientos()
        ids = [
            _entero(movimiento.get("id"), "id")
            for movimiento in movimientos
            if isinstance(movimiento, dict)
        ]
        movimiento = {
            "id": max(ids, default=0) + 1,
            "codigo": codigo,
            "tipo": tipo,
            "cantidad": cantidad,
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "sede": sede,
            "sede_afectada": sede_afectada,
            "venta_cruzada": venta_cruzada,
            "observacion": observacion,
        }
        movimientos.append(movimiento)

        _escribir_json(PRODUCTOS_FILE, productos)
        _escribir_json(MOVIMIENTOS_FILE, movimientos)

    return movimiento, producto


def filtrar_movimientos(
    tipo: str = "",
    codigo: str = "",
    sede: str = "",
    consulta: str = "",
    desde: str = "",
    hasta: str = "",
    pagina: int = 1,
    por_pagina: int | None = 10,
) -> dict[str, Any]:
    movimientos = cargar_movimientos()
    tipo = (tipo or "").strip().upper()
    codigo = (codigo or "").strip().upper()
    sede = (sede or "").strip()
    if sede:
        try:
            sede = normalizar_sede(sede)
        except InventarioError:
            sede = ""
    consulta_normalizada = _normalizar_texto(consulta)
    desde = (desde or "").strip()
    hasta = (hasta or "").strip()

    if tipo not in _TIPOS_VALIDOS:
        tipo = ""

    filtrados = []
    for movimiento in movimientos:
        if not isinstance(movimiento, dict):
            continue
        if tipo and movimiento.get("tipo") != tipo:
            continue
        if codigo and movimiento.get("codigo") != codigo:
            continue

        sede_movimiento = (
            movimiento.get("sede_afectada")
            or movimiento.get("sede")
            or SEDE_PREDETERMINADA
        )
        if sede and sede_movimiento != sede:
            continue

        fecha = str(movimiento.get("fecha", ""))
        dia = fecha[:10]
        if desde and dia < desde:
            continue
        if hasta and dia > hasta:
            continue

        if consulta_normalizada:
            texto = _normalizar_texto(
                " ".join(
                    [
                        str(movimiento.get("codigo", "")),
                        str(movimiento.get("tipo", "")),
                        str(movimiento.get("observacion", "")),
                        str(movimiento.get("id", "")),
                        nombre_sede(sede_movimiento),
                        nombre_sede(movimiento.get("sede", "")),
                    ]
                )
            )
            if consulta_normalizada not in texto:
                continue

        filtrados.append(movimiento)

    filtrados.sort(
        key=lambda movimiento: (
            str(movimiento.get("fecha", "")),
            int(movimiento.get("id", 0) or 0),
        ),
        reverse=True,
    )

    total = len(filtrados)
    if por_pagina is None:
        items = filtrados
        pagina_actual = 1
        paginas = 1
    else:
        por_pagina = max(int(por_pagina), 1)
        paginas = max(1, ceil(total / por_pagina))
        pagina_actual = min(max(int(pagina or 1), 1), paginas)
        inicio = (pagina_actual - 1) * por_pagina
        items = filtrados[inicio : inicio + por_pagina]

    return {
        "items": items,
        "total": total,
        "pagina": pagina_actual,
        "paginas": paginas,
        "por_pagina": por_pagina or total or 1,
    }


def obtener_reporte() -> dict[str, Any]:
    productos = cargar_productos()
    resumen = resumen_inventario(productos)
    movimientos = cargar_movimientos()

    top_productos = sorted(
        productos,
        key=lambda producto: (producto["ventas_mes"], producto["codigo"]),
        reverse=True,
    )[:3]

    unidades_vendidas = sum(
        _entero(movimiento.get("cantidad"), "cantidad")
        for movimiento in movimientos
        if isinstance(movimiento, dict) and movimiento.get("tipo") == "VENTA"
    )
    unidades_ingresadas = sum(
        _entero(movimiento.get("cantidad"), "cantidad")
        for movimiento in movimientos
        if isinstance(movimiento, dict) and movimiento.get("tipo") == "INGRESO"
    )
    ventas_por_sede = {clave: 0 for clave in SEDES}
    ventas_cruzadas = 0
    for movimiento in movimientos:
        if not isinstance(movimiento, dict) or movimiento.get("tipo") != "VENTA":
            continue
        clave = (
            movimiento.get("sede_afectada")
            or movimiento.get("sede")
            or SEDE_PREDETERMINADA
        )
        if clave in ventas_por_sede:
            ventas_por_sede[clave] += _entero(movimiento.get("cantidad"), "cantidad")
        if movimiento.get("venta_cruzada"):
            ventas_cruzadas += 1

    ultimo_movimiento = max(
        (movimiento for movimiento in movimientos if isinstance(movimiento, dict)),
        key=lambda movimiento: int(movimiento.get("id", 0) or 0),
        default=None,
    )

    return {
        **resumen,
        "top_productos": top_productos,
        "total_movimientos": len(movimientos),
        "unidades_vendidas_historial": unidades_vendidas,
        "unidades_ingresadas_historial": unidades_ingresadas,
        "ventas_por_sede": ventas_por_sede,
        "ventas_cruzadas": ventas_cruzadas,
        "ultimo_movimiento": ultimo_movimiento,
    }
