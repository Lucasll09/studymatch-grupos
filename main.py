import os
import httpx
from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from datetime import date

# Importamos la configuración de DB y los modelos
from database import get_db
import db_models
import models

# Cargar las URLs desde el .env
MENSAJERIA_URL = os.getenv("MENSAJERIA_URL")
MATERIAS_URL = os.getenv("MATERIAS_URL") 

app = FastAPI(
    title="Microservicio de Grupos y Disponibilidad",
    version="3.1",
    description="API con BD, Integración HTTP (Mensajería y Materias), Gateway y Frontend embebido"
)

# =================================================================
# MIDDLEWARE DE SEGURIDAD PARA EL FRONTEND (Acuerdo V1)
# =================================================================
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # Permite que localhost:4200 (El Frontend Principal) incruste esta app en un iframe
        response.headers["Content-Security-Policy"] = "frame-ancestors http://localhost:4200"
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
# RUTAS DE LA API (BACKEND)
# =================================================================
@app.get("/api/v1/disponibilidad/{usuario_id}", response_model=models.DisponibilidadResponse)
def consultar_disponibilidad(usuario_id: int, db: Session = Depends(get_db)):
    horarios_db = db.query(db_models.DisponibilidadDB).filter(
        db_models.DisponibilidadDB.usuario_id == usuario_id
    ).all()
    
    if not horarios_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado o sin horarios registrados")
        
    horarios_formateados = []
    for h in horarios_db:
        horarios_formateados.append(models.Horario(
            dia=h.dia_semana,
            hora_inicio=h.hora_inicio.strftime("%H:%M") if h.hora_inicio else "",
            hora_fin=h.hora_fin.strftime("%H:%M") if h.hora_fin else ""
        ))
        
    return models.DisponibilidadResponse(usuario_id=usuario_id, horarios=horarios_formateados)


@app.post("/api/v1/grupos", status_code=status.HTTP_201_CREATED)
async def crear_grupo(
    grupo: models.GrupoCreate, 
    # Recibimos el ID limpio que manda el Gateway
    x_user_id: int = Header(None, alias="X-User-Id"), 
    db: Session = Depends(get_db)
):
    # 1. Validación de seguridad (El Gateway es el filtro)
    if not x_user_id:
        raise HTTPException(status_code=401, detail="No autorizado. Falta X-User-Id desde el Gateway")

    # 2. --- INTEGRACIÓN CON MATERIAS (Validar que exista) ---
    if MATERIAS_URL:
        # Armamos la URL de consulta, ej: http://10.8.9.31:8000/tablero/5
        url_consulta = f"{MATERIAS_URL}/{grupo.materia_id}" 
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp_materia = await client.get(url_consulta)
                
                # Si el compañero de materias devuelve un 404, bloqueamos la creación del grupo
                if resp_materia.status_code == 404:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Error: La materia con ID {grupo.materia_id} no existe en el sistema."
                    )
        except httpx.RequestError as e:
            # Si el PC del compañero está apagado o la red de la universidad falla
            raise HTTPException(
                status_code=503, 
                detail="El microservicio de Materias está fuera de línea. No se pudo validar."
            )

    # 3. Insertar en la tabla principal 'grupos'
    nuevo_grupo = db_models.GrupoDB(
        nombre=grupo.nombre,
        materia_id=grupo.materia_id,
        fecha_creacion=date.today()
    )
    db.add(nuevo_grupo)
    db.commit()             
    db.refresh(nuevo_grupo) 
    
    # 4. Insertar a los integrantes en la tabla intermedia 'grupo_usuario'
    for estudiante_id in grupo.miembros:
        nuevo_miembro = db_models.GrupoUsuarioDB(
            grupo_id=nuevo_grupo.grupo_id,
            usuario_id=estudiante_id,
            rol="estudiante" 
        )
        db.add(nuevo_miembro)
        
    db.commit() 

    # 5. --- INTEGRACIÓN CON MENSAJERÍA ---
    chat_creado = False
    if MENSAJERIA_URL:
        payload = {
            "grupo_id": nuevo_grupo.grupo_id,
            "nombre": nuevo_grupo.nombre,
            "usuario_ids": grupo.miembros,
            "materia_id": nuevo_grupo.materia_id,
            "creador_id": x_user_id # Usamos el ID de quien hace la petición
        }
        headers = {"X-Internal-Service": "servicio-grupos"}
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                respuesta = await client.post(MENSAJERIA_URL, json=payload, headers=headers)
                if respuesta.status_code == 201:
                    chat_creado = True
        except Exception as e:
            print(f"Advertencia: Error interno al contactar a Mensajería: {e}")
    
    return {
        "mensaje": "Grupo creado exitosamente en PostgreSQL", 
        "grupo_id": nuevo_grupo.grupo_id,
        "chat_inicializado": chat_creado 
    }
