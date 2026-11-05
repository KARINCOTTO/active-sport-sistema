"""Aplicación web Flask para la gestión de inventario de ACTIVE SPORT S.A."""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from functools import wraps
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from inventario import (
    CAMPOS_STOCK_SEDE,
    SEDES,
    SEDE_PREDETERMINADA,
    ConfirmacionVentaCruzada,
    InventarioError,
    actualizar_producto,
    buscar_productos,
    calcular_alertas,
    cargar_productos,
    crear_producto,
    filtrar_movimientos,
    nombre_sede,
    obtener_producto,
    obtener_reporte,
    registrar_movimiento,
    resumen_inventario,
)
from usuarios import (
    ROLES,
    UsuarioError,
    actualizar_usuario,
    autenticar,
    cambiar_estado,
    cargar_usuarios,
    crear_usuario,
    listar_usuarios,
    obtener_usuario_por_id,
    publico as usuario_publico,
    registrar_acceso,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "active-sport-clave-de-desarrollo"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

TIPOS_MOVIMIENTO = {"VENTA", "INGRESO"}


def _destino_seguro(destino: str | None) -> str | None:
    if not destino:
        return None
    destino = str(destino).strip()
    partes = urlsplit(destino)
    if partes.scheme or partes.netloc or not destino.startswith("/"):
        return None
    if destino.startswith("//") or "\\" in destino:
        return None
    return destino


def _ruta_actual() -> str:
    return request.full_path if request.query_string else request.path


def login_required(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if getattr(g, "usuario", None) is None:
            return redirect(url_for("login", next=_ruta_actual()))
        return vista(*args, **kwargs)

    return envoltura


def roles_requeridos(*roles: str):
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            usuario = getattr(g, "usuario", None)
            if usuario is None:
                return redirect(url_for("login", next=_ruta_actual()))
            if usuario["rol"] not in roles:
                return (
                    render_template(
                        "error.html",
                        titulo="Acceso restringido",
                        mensaje=(
                            "Su rol no tiene permisos para acceder a esta sección. "
                            "Solicite apoyo a un administrador."
                        ),
                    ),
                    403,
                )
            return vista(*args, **kwargs)

        return envoltura

    return decorador


@app.before_request
def cargar_usuario_actual():
    g.usuario = None
    usuario_id = session.get("usuario_id")
    if usuario_id is None:
        return
    usuario = obtener_usuario_por_id(usuario_id)
    if usuario is None or not usuario["activo"]:
        session.clear()
        return
    g.usuario = usuario_publico(usuario)


def _formulario_movimiento_vacio() -> dict[str, str]:
    return {
        "codigo": "",
        "tipo": "VENTA",
        "cantidad": "",
        "observacion": "",
        "sede": SEDE_PREDETERMINADA,
        "confirmar_cruce": "0",
    }


def _formulario_producto_vacio() -> dict[str, str]:
    return {
        "codigo": "",
        "nombre": "",
        "stock_principal": "0",
        "stock_secundario": "0",
        "stock_minimo": "0",
        "ventas_mes": "0",
    }


def _booleano_form(valor: str | None) -> bool:
    return str(valor or "").strip().lower() in {"1", "true", "on", "si", "sí"}


def _enriquecer_movimientos(
    movimientos: list[dict], productos: list[dict] | None = None
) -> list[dict]:
    if productos is None:
        productos = cargar_productos()
    nombres = {producto["codigo"]: producto["nombre"] for producto in productos}
    return [
        {**movimiento, "nombre_producto": nombres.get(movimiento.get("codigo"), "")}
        for movimiento in movimientos
    ]


def _filtros_movimientos() -> dict[str, str]:
    tipo = request.args.get("tipo", "").strip().upper()
    sede = request.args.get("sede", "").strip().lower()
    return {
        "tipo": tipo if tipo in TIPOS_MOVIMIENTO else "",
        "codigo": request.args.get("codigo", "").strip().upper(),
        "sede": sede if sede in SEDES else "",
        "consulta": request.args.get("q", "").strip(),
        "desde": request.args.get("desde", "").strip(),
        "hasta": request.args.get("hasta", "").strip(),
    }


def _respuesta_csv(nombre: str, encabezados: list[str], filas: list[list]) -> Response:
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(encabezados)
    escritor.writerows(filas)
    contenido = "\ufeff" + salida.getvalue()
    fecha = datetime.now().strftime("%Y%m%d")
    return Response(
        contenido,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}_{fecha}.csv"',
            "Cache-Control": "no-store",
        },
    )


@app.template_filter("fecha_legible")
def fecha_legible(valor: str) -> str:
    try:
        return datetime.fromisoformat(valor).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return valor or "-"


@app.template_filter("fecha_corta")
def fecha_corta(valor: str) -> str:
    try:
        return datetime.fromisoformat(valor).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return valor or "-"


@app.template_filter("nombre_sede")
def filtro_nombre_sede(valor: str) -> str:
    return nombre_sede(valor)


@app.context_processor
def contexto_global() -> dict:
    try:
        resumen = resumen_inventario()
        alertas_nav = resumen["total_alertas"]
        total_productos_nav = resumen["total_productos"]
    except InventarioError:
        alertas_nav = 0
        total_productos_nav = 0

    usuario_actual = getattr(g, "usuario", None)
    return {
        "fecha_actual": datetime.now().strftime("%d/%m/%Y"),
        "alertas_nav": alertas_nav,
        "total_productos_nav": total_productos_nav,
        "sedes": SEDES,
        "sede_predeterminada": SEDE_PREDETERMINADA,
        "usuario_actual": usuario_actual,
        "es_admin": bool(usuario_actual and usuario_actual["rol"] == "admin"),
        "roles": ROLES,
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if getattr(g, "usuario", None) is not None:
        return redirect(url_for("panel"))

    destino = _destino_seguro(request.values.get("next"))
    nombre_usuario = request.form.get("usuario", "").strip().lower()
    error: str | None = None

    if request.method == "POST":
        password = request.form.get("password", "")
        usuario = autenticar(nombre_usuario, password)
        if usuario is None:
            error = "Usuario o contraseña incorrectos. Verifique sus datos e intente nuevamente."
        else:
            session.clear()
            session["usuario_id"] = usuario["id"]
            registrar_acceso(usuario["id"])
            flash(f"Bienvenido, {usuario['nombre']}.", "success")
            return redirect(destino or url_for("panel"))

    if error:
        flash(error, "error")

    return render_template(
        "login.html",
        usuario_valor=nombre_usuario,
        destino=destino or "",
    )


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("login"))


@app.route("/usuarios")
@roles_requeridos("admin")
def usuarios_lista():
    return render_template(
        "usuarios.html",
        usuarios=listar_usuarios(),
        total_usuarios=len(cargar_usuarios()),
    )


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@roles_requeridos("admin")
def usuario_nuevo():
    valores = {"nombre": "", "usuario": "", "rol": "trabajador"}
    errores: list[str] = []

    if request.method == "POST":
        valores = {
            "nombre": request.form.get("nombre", "").strip(),
            "usuario": request.form.get("usuario", "").strip().lower(),
            "rol": request.form.get("rol", "trabajador").strip().lower(),
        }
        password = request.form.get("password", "")
        confirmacion = request.form.get("confirmacion", "")

        if password != confirmacion:
            errores.append("La contraseña y su confirmación no coinciden.")
        else:
            try:
                usuario = crear_usuario(
                    nombre=valores["nombre"],
                    usuario=valores["usuario"],
                    rol=valores["rol"],
                    password=password,
                )
            except UsuarioError as exc:
                errores.append(str(exc))
            else:
                flash(
                    f"Usuario {usuario['nombre']} creado con rol "
                    f"{usuario['rol_nombre']}.",
                    "success",
                )
                return redirect(url_for("usuarios_lista"))

    return render_template(
        "usuario_form.html",
        modo="nuevo",
        usuario=None,
        valores=valores,
        errores=errores,
    )


@app.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@roles_requeridos("admin")
def usuario_editar(usuario_id: int):
    registro = obtener_usuario_por_id(usuario_id)
    if registro is None:
        return (
            render_template(
                "error.html",
                titulo="Usuario no encontrado",
                mensaje="El usuario solicitado no existe.",
            ),
            404,
        )

    usuario = usuario_publico(registro)
    valores = {
        "nombre": usuario["nombre"],
        "usuario": usuario["usuario"],
        "rol": usuario["rol"],
    }
    errores: list[str] = []

    if request.method == "POST":
        valores = {
            "nombre": request.form.get("nombre", "").strip(),
            "usuario": usuario["usuario"],
            "rol": request.form.get("rol", "").strip().lower(),
        }
        password = request.form.get("password", "")
        confirmacion = request.form.get("confirmacion", "")

        if password != confirmacion:
            errores.append("La contraseña y su confirmación no coinciden.")
        else:
            try:
                actualizado = actualizar_usuario(
                    usuario_id=usuario_id,
                    nombre=valores["nombre"],
                    rol=valores["rol"],
                    password=password or None,
                    actor_id=g.usuario["id"],
                )
            except UsuarioError as exc:
                errores.append(str(exc))
            else:
                flash(
                    f"Usuario {actualizado['nombre']} actualizado correctamente.",
                    "success",
                )
                return redirect(url_for("usuarios_lista"))

    return render_template(
        "usuario_form.html",
        modo="editar",
        usuario=usuario,
        valores=valores,
        errores=errores,
    )


@app.route("/usuarios/<int:usuario_id>/estado", methods=["POST"])
@roles_requeridos("admin")
def usuario_estado(usuario_id: int):
    activo = _booleano_form(request.form.get("activo"))
    try:
        usuario = cambiar_estado(
            usuario_id=usuario_id,
            activo=activo,
            actor_id=g.usuario["id"],
        )
    except UsuarioError as exc:
        flash(str(exc), "error")
    else:
        estado = "activado" if usuario["activo"] else "desactivado"
        flash(f"Usuario {usuario['nombre']} {estado} correctamente.", "success")
    return redirect(url_for("usuarios_lista"))


@app.route("/")
@login_required
def panel():
    reporte = obtener_reporte()
    recientes_data = filtrar_movimientos(por_pagina=5)
    recientes = _enriquecer_movimientos(recientes_data["items"], reporte["productos"])
    return render_template(
        "panel.html",
        **reporte,
        recientes=recientes,
    )


@app.route("/productos")
@login_required
def catalogo():
    consulta = request.args.get("q", "").strip()
    estado = request.args.get("estado", "todos").strip()
    orden = request.args.get("orden", "codigo").strip()

    productos = buscar_productos(consulta=consulta, estado=estado, orden=orden)
    resumen = resumen_inventario()
    codigos_en_alerta = {alerta["codigo"] for alerta in resumen["alertas"]}

    return render_template(
        "catalogo.html",
        productos=productos,
        consulta=consulta,
        estado=estado,
        orden=orden,
        resumen=resumen,
        codigos_en_alerta=codigos_en_alerta,
        total_resultados=len(productos),
    )


@app.route("/productos/nuevo", methods=["GET", "POST"])
@roles_requeridos("admin")
def producto_nuevo():
    valores = _formulario_producto_vacio()
    errores: list[str] = []

    if request.method == "POST":
        valores = {
            "codigo": request.form.get("codigo", "").strip().upper(),
            "nombre": request.form.get("nombre", "").strip(),
            "stock_principal": request.form.get("stock_principal", "").strip(),
            "stock_secundario": request.form.get("stock_secundario", "").strip(),
            "stock_minimo": request.form.get("stock_minimo", "").strip(),
            "ventas_mes": request.form.get("ventas_mes", "0").strip(),
        }
        try:
            producto = crear_producto(**valores)
        except InventarioError as exc:
            errores.append(str(exc))
        else:
            flash(
                f"Producto {producto['codigo']} creado correctamente.",
                "success",
            )
            return redirect(url_for("producto_detalle", codigo=producto["codigo"]))

    return render_template(
        "producto_form.html",
        modo="nuevo",
        producto=None,
        valores=valores,
        errores=errores,
    )


@app.route("/productos/<codigo>")
@login_required
def producto_detalle(codigo: str):
    producto = obtener_producto(codigo)
    if producto is None:
        return (
            render_template(
                "error.html",
                titulo="Producto no encontrado",
                mensaje=f"No existe un producto con el código {codigo.upper()}.",
            ),
            404,
        )

    historial_data = filtrar_movimientos(codigo=producto["codigo"], por_pagina=20)
    historial = _enriquecer_movimientos(historial_data["items"], [producto])
    faltante = max(producto["stock_minimo"] - producto["stock_actual"], 0)

    return render_template(
        "producto_detalle.html",
        producto=producto,
        faltante=faltante,
        historial=historial,
        total_movimientos=historial_data["total"],
    )


@app.route("/productos/<codigo>/editar", methods=["GET", "POST"])
@roles_requeridos("admin")
def producto_editar(codigo: str):
    producto = obtener_producto(codigo)
    if producto is None:
        return (
            render_template(
                "error.html",
                titulo="Producto no encontrado",
                mensaje=f"No existe un producto con el código {codigo.upper()}.",
            ),
            404,
        )

    valores = {
        "codigo": producto["codigo"],
        "nombre": producto["nombre"],
        "stock_principal": producto["stock_principal"],
        "stock_secundario": producto["stock_secundario"],
        "stock_actual": producto["stock_actual"],
        "stock_minimo": producto["stock_minimo"],
        "ventas_mes": producto["ventas_mes"],
    }
    errores: list[str] = []

    if request.method == "POST":
        valores["nombre"] = request.form.get("nombre", "").strip()
        valores["stock_minimo"] = request.form.get("stock_minimo", "").strip()
        try:
            producto = actualizar_producto(
                codigo=producto["codigo"],
                nombre=valores["nombre"],
                stock_minimo=valores["stock_minimo"],
            )
        except InventarioError as exc:
            errores.append(str(exc))
        else:
            flash(
                f"Producto {producto['codigo']} actualizado correctamente.",
                "success",
            )
            return redirect(url_for("producto_detalle", codigo=producto["codigo"]))

    return render_template(
        "producto_form.html",
        modo="editar",
        producto=producto,
        valores=valores,
        errores=errores,
    )


@app.route("/movimientos", methods=["GET", "POST"])
@login_required
def movimientos():
    filtros = _filtros_movimientos()
    valores = _formulario_movimiento_vacio()
    valores["codigo"] = filtros["codigo"]
    valores["tipo"] = filtros["tipo"] or "VENTA"
    valores["sede"] = filtros["sede"] or SEDE_PREDETERMINADA
    errores: list[str] = []
    confirmacion_cruce: ConfirmacionVentaCruzada | None = None

    if request.method == "POST":
        valores = {
            "codigo": request.form.get("codigo", "").strip().upper(),
            "tipo": request.form.get("tipo", "").strip().upper(),
            "cantidad": request.form.get("cantidad", "").strip(),
            "observacion": request.form.get("observacion", "").strip(),
            "sede": request.form.get("sede", SEDE_PREDETERMINADA).strip().lower(),
            "confirmar_cruce": request.form.get("confirmar_cruce", "0"),
        }
        try:
            movimiento, producto = registrar_movimiento(
                codigo=valores["codigo"],
                tipo=valores["tipo"],
                cantidad=valores["cantidad"],
                observacion=valores["observacion"],
                sede=valores["sede"],
                confirmar_cruce=_booleano_form(valores["confirmar_cruce"]),
            )
        except ConfirmacionVentaCruzada as exc:
            confirmacion_cruce = exc
            valores["confirmar_cruce"] = "0"
        except InventarioError as exc:
            errores.append(str(exc))
            valores["confirmar_cruce"] = "0"
        else:
            sede_afectada = nombre_sede(movimiento["sede_afectada"])
            stock_afectado = producto[CAMPOS_STOCK_SEDE[movimiento["sede_afectada"]]]
            if movimiento["tipo"] == "VENTA":
                if movimiento["venta_cruzada"]:
                    mensaje = (
                        f"Venta cruzada #{movimiento['id']} registrada: "
                        f"{movimiento['cantidad']} x {producto['nombre']}. Retiro en "
                        f"{sede_afectada}. Stock restante en esa sede: {stock_afectado}."
                    )
                else:
                    mensaje = (
                        f"Venta #{movimiento['id']} registrada en {sede_afectada}: "
                        f"{movimiento['cantidad']} x {producto['nombre']}. Stock restante: "
                        f"{stock_afectado}."
                    )
            else:
                mensaje = (
                    f"Ingreso #{movimiento['id']} registrado en {sede_afectada}: "
                    f"{movimiento['cantidad']} x {producto['nombre']}. Stock actual: "
                    f"{stock_afectado}."
                )
            flash(mensaje, "success")
            return redirect(url_for("movimientos"))

    productos = cargar_productos()
    pagina = request.args.get("pagina", type=int) or 1
    paginacion = filtrar_movimientos(**filtros, pagina=pagina, por_pagina=8)
    historial = _enriquecer_movimientos(paginacion["items"], productos)
    alertas = calcular_alertas(productos)

    return render_template(
        "movimientos.html",
        productos=productos,
        alertas=alertas,
        valores=valores,
        errores=errores,
        filtros=filtros,
        paginacion=paginacion,
        historial=historial,
        confirmacion_cruce=confirmacion_cruce,
    )


@app.route("/reporte")
@roles_requeridos("admin")
def reporte():
    return render_template("reporte.html", **obtener_reporte())


@app.route("/exportar/productos.csv")
@roles_requeridos("admin")
def exportar_productos():
    consulta = request.args.get("q", "").strip()
    estado = request.args.get("estado", "todos").strip()
    orden = request.args.get("orden", "codigo").strip()
    productos = buscar_productos(consulta=consulta, estado=estado, orden=orden)
    filas = []
    for producto in productos:
        faltante = max(
            producto["stock_minimo"] - producto["stock_actual"],
            0,
        )
        estado_producto = (
            "REPONER" if producto["stock_actual"] <= producto["stock_minimo"] else "DISPONIBLE"
        )
        filas.append(
            [
                producto["codigo"],
                producto["nombre"],
                producto["stock_principal"],
                producto["stock_secundario"],
                producto["stock_actual"],
                producto["stock_minimo"],
                producto["ventas_mes"],
                faltante,
                estado_producto,
            ]
        )
    return _respuesta_csv(
        "catalogo_productos",
        [
            "codigo",
            "nombre",
            "stock_principal",
            "stock_secundario",
            "stock_total",
            "stock_minimo",
            "ventas_mes",
            "unidades_faltantes",
            "estado",
        ],
        filas,
    )


@app.route("/exportar/movimientos.csv")
@roles_requeridos("admin")
def exportar_movimientos():
    filtros = _filtros_movimientos()
    data = filtrar_movimientos(**filtros, por_pagina=None)
    productos = cargar_productos()
    nombres = {producto["codigo"]: producto["nombre"] for producto in productos}
    filas = [
        [
            movimiento.get("id", ""),
            movimiento.get("codigo", ""),
            nombres.get(movimiento.get("codigo"), ""),
            movimiento.get("tipo", ""),
            movimiento.get("cantidad", ""),
            nombre_sede(movimiento.get("sede", SEDE_PREDETERMINADA)),
            nombre_sede(
                movimiento.get(
                    "sede_afectada",
                    movimiento.get("sede", SEDE_PREDETERMINADA),
                )
            ),
            "SI" if movimiento.get("venta_cruzada") else "NO",
            movimiento.get("fecha", ""),
            movimiento.get("observacion", ""),
        ]
        for movimiento in data["items"]
    ]
    return _respuesta_csv(
        "movimientos",
        [
            "id",
            "codigo",
            "producto",
            "tipo",
            "cantidad",
            "sede",
            "sede_afectada",
            "venta_cruzada",
            "fecha",
            "observacion",
        ],
        filas,
    )


@app.route("/exportar/reporte.csv")
@roles_requeridos("admin")
def exportar_reporte():
    reporte_data = obtener_reporte()
    filas = []
    for producto in reporte_data["productos"]:
        faltante = max(
            producto["stock_minimo"] - producto["stock_actual"],
            0,
        )
        filas.append(
            [
                producto["codigo"],
                producto["nombre"],
                producto["stock_principal"],
                producto["stock_secundario"],
                producto["stock_actual"],
                producto["stock_minimo"],
                producto["ventas_mes"],
                faltante,
                "REPONER"
                if producto["stock_actual"] <= producto["stock_minimo"]
                else "DISPONIBLE",
            ]
        )
    return _respuesta_csv(
        "reporte_inventario",
        [
            "codigo",
            "nombre",
            "stock_principal",
            "stock_secundario",
            "stock_total",
            "stock_minimo",
            "ventas_mes",
            "unidades_faltantes",
            "estado",
        ],
        filas,
    )


@app.errorhandler(InventarioError)
def manejar_error_inventario(error: InventarioError):
    return (
        render_template(
            "error.html",
            titulo="Error de inventario",
            mensaje=str(error),
        ),
        500,
    )


@app.errorhandler(404)
def pagina_no_encontrada(_error):
    return (
        render_template(
            "error.html",
            titulo="Página no encontrada",
            mensaje="La ruta solicitada no existe en esta aplicación.",
        ),
        404,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

