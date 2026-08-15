import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def executar_alembic(database_url, *argumentos):
    ambiente = os.environ.copy()
    ambiente.update({
        "APP_ENV": "test",
        "AUTO_CREATE_SCHEMA": "false",
        "DATABASE_URL": database_url,
    })
    resultado = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            *argumentos,
        ],
        cwd=RAIZ / "backend",
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr


def test_migracao_preserva_datas_financeiras_em_upgrade_e_rollback():
    with tempfile.TemporaryDirectory(
        prefix="estoque-migration-tests-",
        dir=RAIZ.parent,
    ) as temporario:
        banco = Path(temporario) / "migration.db"
        database_url = f"sqlite:///{banco.as_posix()}"
        executar_alembic(database_url, "upgrade", "0001")

        conexao = sqlite3.connect(banco)
        conexao.execute(
            "INSERT INTO contas_financeiras "
            "(tipo, descricao, valor, vencimento, status, data_pagamento) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("pagar", "Teste", 123.456, "2026-08-31", "pago", "2026-08-15"),
        )
        conexao.commit()
        conexao.close()

        executar_alembic(database_url, "upgrade", "head")
        executar_alembic(database_url, "check")
        executar_alembic(database_url, "downgrade", "0001")
        executar_alembic(database_url, "upgrade", "head")

        conexao = sqlite3.connect(banco)
        valor, vencimento, pagamento = conexao.execute(
            "SELECT valor, vencimento, data_pagamento "
            "FROM contas_financeiras"
        ).fetchone()
        conexao.close()

        assert valor == 123.456
        assert vencimento == "2026-08-31"
        assert pagamento == "2026-08-15"
