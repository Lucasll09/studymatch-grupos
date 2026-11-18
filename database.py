import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Cargar las variables de entorno desde el archivo .env
load_dotenv()

# 2. Obtener las credenciales
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

# 3. Construir la URL de conexión para PostgreSQL
SQLALCHEMY_DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={DB_SSLMODE}"

# 4. Crear el motor (Engine) que se conecta a Neon
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 5. Crear la fábrica de sesiones (Cada vez que alguien hace una petición, se abre una sesión)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 6. Clase base de la que heredarán nuestros modelos de tablas (db_models.py)
Base = declarative_base()

# 7. Función de dependencia para que FastAPI abra y cierre la base de datos automáticamente
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        