"""Cria somente o administrador inicial; dados de demonstracao sao opt-in."""

import os

import bcrypt

import models
from database import SessionLocal
from settings import settings, validar_senha_bootstrap


def habilitado(nome: str) -> bool:
    return os.getenv(nome, "false").strip().lower() in {"1", "true", "sim", "yes"}


def criar_admin(db) -> bool:
    if db.query(models.AdminUsuario).first():
        return False

    senha = validar_senha_bootstrap(os.getenv("ADMIN_SENHA", ""))
    db.add(models.AdminUsuario(
        nome="Administrador",
        login=os.getenv("ADMIN_LOGIN", "admin").strip(),
        senha_hash=bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode(),
        papel=models.PapelAdmin.gerencia,
        ativo=True,
    ))
    return True


def criar_dados_demonstracao(db) -> None:
    if settings.producao:
        raise RuntimeError("SEED_DEMO_DATA nao e permitido em producao")

    if not db.query(models.Tecnico).first():
        db.add(models.Tecnico(
            nome="Tecnico Teste",
            login="tecnico1",
            pin_hash=bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode(),
            aprovado=True,
            is_adm=True,
        ))

    materiais = [
        ("Cabo drop 1FO", "cabo", "m", 500, 100),
        ("Conector SC/APC pre-conectorizado", "conector", "un", 100, 20),
        ("ONU GPON", "equipamento", "un", 30, 5),
    ]
    for nome, categoria, unidade, quantidade, minimo in materiais:
        if not db.query(models.Material).filter_by(nome=nome).first():
            db.add(models.Material(
                nome=nome,
                categoria=categoria,
                unidade=unidade,
                qtd_atual=quantidade,
                qtd_minima=minimo,
            ))


def executar() -> None:
    db = SessionLocal()
    try:
        admin_criado = criar_admin(db)
        if habilitado("SEED_DEMO_DATA"):
            criar_dados_demonstracao(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("Bootstrap concluido.")
    print("Administrador inicial criado." if admin_criado else "Administrador ja existente.")
    print("A senha nao e exibida nos logs.")


if __name__ == "__main__":
    executar()
