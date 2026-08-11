import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Por padrão usa SQLite (arquivo local, zero configuração).
# Para produção no VPS, defina a variável de ambiente DATABASE_URL, ex:
#   postgresql://usuario:senha@localhost/estoque_campo
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./estoque_campo.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
