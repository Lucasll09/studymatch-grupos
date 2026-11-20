import os
import httpx
from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from datetime import date

# Importamos la configuración de DB y los modelos
from database import get_db
import db_models
import models

# Cargar las URLs desde las variables de entorno (.env / Railway)
MENSAJERIA_URL = os.getenv("MENSAJERIA_URL")
MATERIAS_URL = os.getenv("MATERIAS_URL")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://178.18.252.176:8000").rstrip("/")

app = FastAPI(
    title="Microservicio de Grupos y Disponibilidad",
    version="3.5",
    description="API con BD, Integración HTTP (Mensajería, Materias y Catálogo), Gateway y Frontend embebido"
)

# =================================================================
# CORS Y MIDDLEWARE DE SEGURIDAD PARA EL FRONTEND (iframe)
# =================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # Permite incrustar el módulo tanto en localhost:4200 como en el dominio desplegado del Frontend
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# =================================================================
# RUTA PARA ENTREGAR LA INTERFAZ VISUAL AL FRONTEND
# =================================================================
@app.get("/", response_class=HTMLResponse)
async def servir_interfaz():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Error: Crea el archivo index.html en la raíz del proyecto</h1>",
            status_code=404
        )


# =================================================================
# CATÁLOGO (USUARIOS Y MATERIAS DESDE EL GATEWAY)
# =================================================================
@app.get("/api/v1/catalogo")
async def obtener_catalogo_gateway(authorization: str = Header(None)):
    headers = {"Authorization": authorization} if authorization else {}
    usuarios_map = {}
    materias_map = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Consultar lista de estudiantes en el Gateway
        try:
            resp_u = await client.get(f"{GATEWAY_URL}/api/v1/usuarios", headers=headers)
            if resp_u.status_code == 200:
                datos_u = resp_u.json()
                lista_u = (
                    datos_u
                    if isinstance(datos_u, list)
                    else datos_u.get("usuarios", datos_u.get("data", datos_u.get("items", [])))
                )
                for u in lista_u:
                    if isinstance(u, dict):
                        uid = u.get("usuario_id") if u.get("usuario_id") is not None else u.get("id")
                        if uid is not None:
                            usuarios_map[str(uid)] = {
                                "usuario_id": uid,
                                "nombre": u.get("nombre") or f"Usuario #{uid}",
                                "correo": u.get("correo") or u.get("email") or ""
                            }
        except Exception as e:
            print(f"Advertencia catalogo usuarios: {e}")

        # 2. Consultar lista de materias en el Gateway
        try:
            resp_m = await client.get(f"{GATEWAY_URL}/api/v1/materias", headers=headers)
            if resp_m.status_code == 200:
                datos_m = resp_m.json()
                lista_m = (
                    datos_m
                    if isinstance(datos_m, list)
                    else datos_m.get("materias", datos_m.get("data", datos_m.get("items", [])))
                )
                for m in lista_m:
                    if isinstance(m, dict):
                        mid = m.get("materia_id") if m.get("materia_id") is not None else m.get("id")
                        if mid is not None:
                            materias_map[str(mid)] = {
                                "materia_id": mid,
                                "nombre": m.get("nombre") or f"Materia #{mid}"
                            }
        except Exception as e:
            print(f"Advertencia catalogo materias: {e}")

    return {
        "usuarios": usuarios_map,
        "materias": materias_map
    }


# =================================================================
# RUTAS DE LA API (BACKEND)
# =================================================================
@app.get("/api/v1/disponibilidad/{usuario_id}")
def consultar_disponibilidad(usuario_id: int, db: Session = Depends(get_db)):
    horarios_db = db.query(db_models.DisponibilidadDB).filter(
        db_models.DisponibilidadDB.usuario_id == usuario_id
    ).all()

    if not horarios_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado o sin horarios registrados")

    horarios_formateados = []
    for h in horarios_db:
        horarios_formateados.append({
            "dia_semana": h.dia_semana,
            "dia": h.dia_semana,
            "hora_inicio": h.hora_inicio.strftime("%H:%M") if h.hora_inicio else "",
            "hora_fin": h.hora_fin.strftime("%H:%M") if h.hora_fin else "",
            "modalidad": getattr(h, "modalidad", None)
        })

    return {
        "usuario_id": usuario_id,
        "horarios": horarios_formateados,
        "disponibilidad": horarios_formateados
    }


@app.get("/api/v1/grupos/usuario/{usuario_id}")
def listar_grupos_usuario(usuario_id: int, db: Session = Depends(get_db)):
    grupos_db = (
        db.query(db_models.GrupoDB)
        .join(
            db_models.GrupoUsuarioDB,
            db_models.GrupoDB.grupo_id == db_models.GrupoUsuarioDB.grupo_id
        )
        .filter(db_models.GrupoUsuarioDB.usuario_id == usuario_id)
        .all()
    )

    grupos_lista = [
        {
            "grupo_id": g.grupo_id,
            "nombre": g.nombre,
            "materia_id": g.materia_id,
            "fecha_creacion": g.fecha_creacion.isoformat() if g.fecha_creacion else None
        }
        for g in grupos_db
    ]

    return {
        "usuario_id": usuario_id,
        "total_grupos": len(grupos_lista),
        "grupos": grupos_lista
    }


@app.post("/api/v1/grupos", status_code=status.HTTP_201_CREATED)
async def crear_grupo(
    grupo: models.GrupoCreate,
    # Recibimos el ID limpio que manda el Gateway o la interfaz
    x_user_id: int = Header(None, alias="X-User-Id"),
    db: Session = Depends(get_db)
):
    # 1. Validación de seguridad
    if not x_user_id:
        raise HTTPException(status_code=401, detail="No autorizado. Falta X-User-Id desde el Gateway")

    # 2. --- INTEGRACIÓN CON MATERIAS (Validar contra GET /api/v1/materias) ---
    if MATERIAS_URL:
        base_materias = MATERIAS_URL.rstrip("/")
        url_consulta = (
            base_materias
            if base_materias.endswith("/materias")
            else f"{base_materias}/api/v1/materias"
        )
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                resp_materia = await client.get(url_consulta)

                if resp_materia.status_code != 200:
                    raise HTTPException(
                        status_code=503,
                        detail=f"El microservicio de Materias respondió con estado {resp_materia.status_code}."
                    )

                datos_materias = resp_materia.json()
                lista_materias = (
                    datos_materias
                    if isinstance(datos_materias, list)
                    else datos_materias.get("materias", datos_materias.get("data", []))
                )

                ids_validos = {
                    m.get("materia_id") if m.get("materia_id") is not None else m.get("id")
                    for m in lista_materias
                    if isinstance(m, dict)
                }

                if grupo.materia_id not in ids_validos:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Error: La materia con ID {grupo.materia_id} no existe en el sistema."
                    )
        except HTTPException:
            raise
        except httpx.RequestError:
            raise HTTPException(
                status_code=503,
                detail="El microservicio de Materias está fuera de línea. No se pudo validar."
            )

    # 3 y 4. Insertar grupo e integrantes en una sola transacción limpia
    miembros_unicos = list(dict.fromkeys([x_user_id, *grupo.miembros]))
    try:
        nuevo_grupo = db_models.GrupoDB(
            nombre=grupo.nombre,
            materia_id=grupo.materia_id,
            fecha_creacion=date.today()
        )
        db.add(nuevo_grupo)
        db.flush()

        for estudiante_id in miembros_unicos:
            nuevo_miembro = db_models.GrupoUsuarioDB(
                grupo_id=nuevo_grupo.grupo_id,
                usuario_id=estudiante_id,
                rol="admin" if estudiante_id == x_user_id else "usuario"
            )
            db.add(nuevo_miembro)

        db.commit()
        db.refresh(nuevo_grupo)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Error de integridad al registrar el grupo o los integrantes: {str(e.orig)}"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error de base de datos al crear el grupo: {str(e)}"
        )

    # 5. --- INTEGRACIÓN CON MENSAJERÍA ---
    chat_creado = False
    if MENSAJERIA_URL:
        payload = {
            "grupo_id": nuevo_grupo.grupo_id,
            "nombre": nuevo_grupo.nombre,
            "usuario_ids": miembros_unicos,
            "materia_id": nuevo_grupo.materia_id,
            "creador_id": x_user_id
        }
        headers = {"X-Internal-Service": "servicio-grupos"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                respuesta = await client.post(MENSAJERIA_URL, json=payload, headers=headers)
                if respuesta.status_code in (200, 201):
                    chat_creado = True
        except Exception as e:
            print(f"Advertencia: Error interno al contactar a Mensajería: {e}")

    return {
        "mensaje": "Grupo creado exitosamente en PostgreSQL",
        "grupo_id": nuevo_grupo.grupo_id,
        "chat_inicializado": chat_creado
    }