from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from database import engine
from settings import settings
from storage import armazenamento


def verificar_migracao() -> None:
    arquivo_ini = Path(__file__).resolve().parent / "alembic.ini"
    config = Config(str(arquivo_ini))
    scripts = ScriptDirectory.from_config(config)
    esperado = scripts.get_current_head()

    with engine.connect() as conexao:
        conexao.execute(text("SELECT 1"))
        atual = MigrationContext.configure(conexao).get_current_revision()

    if atual != esperado:
        raise RuntimeError(
            f"Banco fora da versao esperada: atual={atual!r}, esperado={esperado!r}"
        )


def verificar_diretorio_dados() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    teste = settings.data_dir / ".preflight-write-test"
    teste.write_text("ok", encoding="utf-8")
    teste.unlink()


def executar() -> None:
    if not settings.producao:
        raise RuntimeError("preflight deve executar com APP_ENV=production")
    verificar_migracao()
    verificar_diretorio_dados()
    armazenamento.verificar_acesso()
    print("Preflight do backend concluido.")


if __name__ == "__main__":
    executar()
