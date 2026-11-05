"""Gestión de usuarios, roles y autenticación de ACTIVE SPORT S.A."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = Path(os.environ.get("ACTIVE_SPORT_DATA_DIR", BASE_DIR))
USUARIOS_FILE = DATA_DIR / "usuarios.json"

ROLES = {
    "admin": {
        "id": "admin",
        "nombre": "Administrador",
        "descripcion": "Acceso completo, reportes y gestión de usuarios.",
    },
    "trabajador": {
        "id": "trabajador",
        "nombre": "Trabajador",
        "descripcion": "Consulta de stock y registro de ventas e ingresos.",
    },
}
ROLES_VALIDOS = set(ROLES)

_LOCK = threading.RLock()
_PATRON_USUARIO = re.compile(r"^[a-z0-9][a-z0-9._-]{2,29}$")

USUARIOS_INICIALES = (
    {
        "nombre": "Administrador",
        "usuario": "admin",
        "rol": "admin",
        "password": "Admin123!",
    },
    {
        "nombre": "Trabajador",
        "usuario": "trabajador",
        "rol": "trabajador",
        "password": "Trabajador123!",
    },
)


class UsuarioError(ValueError):
    """Error controlado de usuarios y autenticación."""


def _leer_json(ruta: Path, valor_por_defecto: Any) -> Any:
    if not ruta.exists():
        return valor_por_defecto
    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except (json.JSONDecodeError, OSError) as exc:
        raise UsuarioError(
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
        raise UsuarioError(f"No se pudo guardar {ruta.name}.") from exc
    finally:
        if temporal.exists():
            temporal.unlink(missing_ok=True)


def _entero(valor: Any, campo: str) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError) as exc:
        raise UsuarioError(f"El campo '{campo}' debe ser un número entero.") from exc


def _normalizar_usuario(valor: Any) -> str:
    return str(valor or "").strip().lower()


def _validar_nombre(valor: Any) -> str:
    nombre = str(valor or "").strip()
    if len(nombre) < 3:
        raise UsuarioError("El nombre debe tener al menos 3 caracteres.")
    if len(nombre) > 80:
        raise UsuarioError("El nombre no puede superar los 80 caracteres.")
    return nombre


def _validar_nombre_usuario(valor: Any) -> str:
    usuario = _normalizar_usuario(valor)
    if not _PATRON_USUARIO.match(usuario):
        raise UsuarioError(
            "El usuario debe tener entre 3 y 30 caracteres y usar solo letras, "
            "números, puntos, guiones o guiones bajos."
        )
    return usuario


def _validar_rol(valor: Any) -> str:
    rol = _normalizar_usuario(valor)
    if rol not in ROLES_VALIDOS:
        raise UsuarioError("El rol debe ser Administrador o Trabajador.")
    return rol


def _validar_password(valor: Any) -> str:
    password = str(valor or "")
    if len(password) < 8:
        raise UsuarioError("La contraseña debe tener al menos 8 caracteres.")
    if len(password) > 128:
        raise UsuarioError("La contraseña no puede superar los 128 caracteres.")
    return password


def _convertir_activo(valor: Any) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in {"1", "true", "si", "sí", "on"}
    return bool(valor)


def _validar_registro(registro: Any, indice: int) -> dict[str, Any]:
    if not isinstance(registro, dict):
        raise UsuarioError(f"El usuario en la posición {indice} no es válido.")

    usuario = _normalizar_usuario(registro.get("usuario"))
    nombre = str(registro.get("nombre", "")).strip()
    rol = _normalizar_usuario(registro.get("rol"))
    password_hash = str(registro.get("password_hash", "")).strip()

    if not usuario or not nombre or rol not in ROLES_VALIDOS or not password_hash:
        raise UsuarioError(f"El usuario en la posición {indice} tiene datos incompletos.")

    return {
        "id": _entero(registro.get("id", indice + 1), "id"),
        "nombre": nombre,
        "usuario": usuario,
        "rol": rol,
        "activo": _convertir_activo(registro.get("activo", True)),
        "password_hash": password_hash,
        "creado": str(registro.get("creado", "")),
        "ultimo_acceso": registro.get("ultimo_acceso"),
    }


def _registros_iniciales() -> list[dict[str, Any]]:
    ahora = datetime.now().isoformat(timespec="seconds")
    return [
        {
            "id": indice,
            "nombre": datos["nombre"],
            "usuario": datos["usuario"],
            "rol": datos["rol"],
            "activo": True,
            "password_hash": generate_password_hash(datos["password"]),
            "creado": ahora,
            "ultimo_acceso": None,
        }
        for indice, datos in enumerate(USUARIOS_INICIALES, start=1)
    ]


def cargar_usuarios() -> list[dict[str, Any]]:
    with _LOCK:
        if not USUARIOS_FILE.exists():
            _escribir_json(USUARIOS_FILE, _registros_iniciales())
        usuarios = _leer_json(USUARIOS_FILE, [])

    if not isinstance(usuarios, list):
        raise UsuarioError("El archivo usuarios.json debe contener una lista de usuarios.")

    validados = [
        _validar_registro(registro, indice)
        for indice, registro in enumerate(usuarios)
    ]
    vistos: set[str] = set()
    for usuario in validados:
        if usuario["usuario"] in vistos:
            raise UsuarioError("El archivo usuarios.json contiene usuarios duplicados.")
        vistos.add(usuario["usuario"])
    return validados


def publico(usuario: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": usuario["id"],
        "nombre": usuario["nombre"],
        "usuario": usuario["usuario"],
        "rol": usuario["rol"],
        "rol_nombre": ROLES[usuario["rol"]]["nombre"],
        "activo": usuario["activo"],
        "creado": usuario.get("creado", ""),
        "ultimo_acceso": usuario.get("ultimo_acceso"),
    }


def listar_usuarios() -> list[dict[str, Any]]:
    usuarios = [publico(usuario) for usuario in cargar_usuarios()]
    usuarios.sort(
        key=lambda usuario: (
            0 if usuario["rol"] == "admin" else 1,
            0 if usuario["activo"] else 1,
            usuario["nombre"].lower(),
        )
    )
    return usuarios


def obtener_usuario_por_id(usuario_id: Any) -> dict[str, Any] | None:
    try:
        identificador = _entero(usuario_id, "id")
    except UsuarioError:
        return None
    return next(
        (usuario for usuario in cargar_usuarios() if usuario["id"] == identificador),
        None,
    )


def obtener_usuario_por_nombre(nombre_usuario: Any) -> dict[str, Any] | None:
    usuario = _normalizar_usuario(nombre_usuario)
    return next(
        (registro for registro in cargar_usuarios() if registro["usuario"] == usuario),
        None,
    )


def autenticar(nombre_usuario: Any, password: Any) -> dict[str, Any] | None:
    usuario = obtener_usuario_por_nombre(nombre_usuario)
    if usuario is None or not usuario["activo"]:
        return None
    if not check_password_hash(usuario["password_hash"], str(password or "")):
        return None
    return usuario


def registrar_acceso(usuario_id: Any) -> None:
    with _LOCK:
        usuarios = cargar_usuarios()
        for usuario in usuarios:
            if usuario["id"] == _entero(usuario_id, "id"):
                usuario["ultimo_acceso"] = datetime.now().isoformat(timespec="seconds")
                _escribir_json(USUARIOS_FILE, usuarios)
                return


def _comprobar_ultimo_admin(
    usuarios: list[dict[str, Any]], usuario: dict[str, Any], nuevo_rol: str, nuevo_estado: bool
) -> None:
    era_admin_activo = usuario["rol"] == "admin" and usuario["activo"]
    sera_admin_activo = nuevo_rol == "admin" and nuevo_estado
    if not era_admin_activo or sera_admin_activo:
        return
    otros_admins = [
        registro
        for registro in usuarios
        if registro["id"] != usuario["id"]
        and registro["rol"] == "admin"
        and registro["activo"]
    ]
    if not otros_admins:
        raise UsuarioError("Debe existir al menos un administrador activo.")


def crear_usuario(
    nombre: str, usuario: str, rol: str, password: str
) -> dict[str, Any]:
    nombre = _validar_nombre(nombre)
    usuario = _validar_nombre_usuario(usuario)
    rol = _validar_rol(rol)
    password = _validar_password(password)

    with _LOCK:
        usuarios = cargar_usuarios()
        if any(registro["usuario"] == usuario for registro in usuarios):
            raise UsuarioError(f"Ya existe un usuario con el nombre '{usuario}'.")

        nuevo = {
            "id": max((registro["id"] for registro in usuarios), default=0) + 1,
            "nombre": nombre,
            "usuario": usuario,
            "rol": rol,
            "activo": True,
            "password_hash": generate_password_hash(password),
            "creado": datetime.now().isoformat(timespec="seconds"),
            "ultimo_acceso": None,
        }
        usuarios.append(nuevo)
        _escribir_json(USUARIOS_FILE, usuarios)
    return publico(nuevo)


def actualizar_usuario(
    usuario_id: Any,
    nombre: str,
    rol: str,
    password: str | None = None,
    actor_id: Any = None,
) -> dict[str, Any]:
    identificador = _entero(usuario_id, "id")
    nombre = _validar_nombre(nombre)
    rol = _validar_rol(rol)
    password = str(password or "")

    with _LOCK:
        usuarios = cargar_usuarios()
        usuario = next(
            (registro for registro in usuarios if registro["id"] == identificador),
            None,
        )
        if usuario is None:
            raise UsuarioError("El usuario solicitado no existe.")

        if actor_id is not None and _entero(actor_id, "id") == identificador and rol != "admin":
            raise UsuarioError("No puede quitarse a sí mismo el rol de administrador.")

        _comprobar_ultimo_admin(usuarios, usuario, rol, usuario["activo"])

        if password:
            password = _validar_password(password)
            usuario["password_hash"] = generate_password_hash(password)

        usuario["nombre"] = nombre
        usuario["rol"] = rol
        _escribir_json(USUARIOS_FILE, usuarios)
    return publico(usuario)


def cambiar_estado(
    usuario_id: Any, activo: bool, actor_id: Any = None
) -> dict[str, Any]:
    identificador = _entero(usuario_id, "id")
    nuevo_estado = bool(activo)

    with _LOCK:
        usuarios = cargar_usuarios()
        usuario = next(
            (registro for registro in usuarios if registro["id"] == identificador),
            None,
        )
        if usuario is None:
            raise UsuarioError("El usuario solicitado no existe.")

        if (
            actor_id is not None
            and _entero(actor_id, "id") == identificador
            and not nuevo_estado
        ):
            raise UsuarioError("No puede desactivar su propio usuario.")

        _comprobar_ultimo_admin(usuarios, usuario, usuario["rol"], nuevo_estado)
        usuario["activo"] = nuevo_estado
        _escribir_json(USUARIOS_FILE, usuarios)
    return publico(usuario)
