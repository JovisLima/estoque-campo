"""
Cria dados iniciais: um técnico de teste e alguns materiais comuns de ISP.
Rode uma vez com: python seed.py
"""
import bcrypt
from database import Base, engine, SessionLocal
import models

Base.metadata.create_all(bind=engine)
db = SessionLocal()

"""
Cria dados iniciais: um técnico de teste, um admin de gerência,
e alguns materiais comuns de ISP.
Rode uma vez com: python seed.py
"""
import os
import bcrypt
from database import Base, engine, SessionLocal
import models

Base.metadata.create_all(bind=engine)
db = SessionLocal()

ADMIN_SENHA_INICIAL = os.getenv("ADMIN_SENHA", "admin123")

if not db.query(models.AdminUsuario).first():
    admin = models.AdminUsuario(
        nome="Administrador",
        login="admin",
        senha_hash=bcrypt.hashpw(ADMIN_SENHA_INICIAL.encode(), bcrypt.gensalt()).decode(),
        papel=models.PapelAdmin.gerencia,
    )
    db.add(admin)

if not db.query(models.Tecnico).first():
    tecnico = models.Tecnico(
        nome="Técnico Teste",
        login="tecnico1",
        pin_hash=bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode(),  # troque o PIN em produção
        aprovado=True,  # técnico de teste já aprovado, pra facilitar
        is_adm=True,  # técnico de teste como ADM, pra poder testar OS avulsa
    )
    db.add(tecnico)

materiais_exemplo = [
    ("Cabo drop 1FO", "cabo", "m", 500, 100),
    ("Conector SC/APC pré-conectorizado", "conector", "un", 100, 20),
    ("ONU GPON", "equipamento", "un", 30, 5),
    ("Cordão óptico 1m", "cabo", "un", 50, 10),
    ("Roseta óptica", "acessorio", "un", 80, 15),
    ("Abraçadeira de nylon", "fixacao", "un", 500, 100),
]
for nome, cat, unidade, qtd, minimo in materiais_exemplo:
    if not db.query(models.Material).filter_by(nome=nome).first():
        db.add(models.Material(
            nome=nome, categoria=cat, unidade=unidade,
            qtd_atual=qtd, qtd_minima=minimo,
        ))

ferramentas_exemplo = [
    ("Fusora de fibra", "FUS-001", "ferramenta"),
    ("Power meter", "PWM-001", "ferramenta"),
    ("Cinto de segurança tipo paraquedista", "EPI-001", "epi"),
    ("Luva isolante", "EPI-002", "epi"),
]
for nome, codigo, categoria in ferramentas_exemplo:
    if not db.query(models.Ferramenta).filter_by(codigo_patrimonio=codigo).first():
        db.add(models.Ferramenta(nome=nome, codigo_patrimonio=codigo, categoria=categoria))

db.commit()
print("Dados iniciais criados.")
print("Login ADMIN DESKTOP -> usuário: admin / senha:", ADMIN_SENHA_INICIAL, "(papel: gerência)")
print("Login TÉCNICO (app) -> usuário: tecnico1 / PIN: 1234")
