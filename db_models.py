from sqlalchemy import Column, Integer, String, Time, Date
from database import Base

class DisponibilidadDB(Base):
    __tablename__ = "disponibilidad"
    
    # Mapeo exacto según la base de datos
    disponibilidad_id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, index=True)
    dia_semana = Column(String(10))
    hora_inicio = Column(Time)
    hora_fin = Column(Time)
    modalidad = Column(String(20))

class GrupoDB(Base):
    __tablename__ = "grupos"
    
    grupo_id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150))
    materia_id = Column(Integer, index=True)
    fecha_creacion = Column(Date)

class GrupoUsuarioDB(Base):
    __tablename__ = "grupo_usuario"
    
    # Esta tabla usa llaves primarias compuestas (ambas son primary_key)
    grupo_id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, primary_key=True)
    rol = Column(String(20))