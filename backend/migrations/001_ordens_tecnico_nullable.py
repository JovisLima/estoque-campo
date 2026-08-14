import sqlite3
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "estoque_campo.db"
)

TABELA = "ordens_servico"
TABELA_NOVA = "ordens_servico_nova"

COLUNAS = (
    "id",
    "tecnico_id",
    "cliente_id",
    "tipo",
    "cliente_local",
    "nome_cliente",
    "endereco",
    "prioridade",
    "observacoes",
    "status",
    "criada_por_admin",
    "data_abertura",
    "data_deslocamento",
    "data_inicio",
    "data_fechamento",
    "pdf_path",
    "lat_deslocamento",
    "lon_deslocamento",
    "lat_inicio",
    "lon_inicio",
    "lat_fim",
    "lon_fim",
    "checklist_limpar_conector",
    "checklist_testar_sinal",
    "checklist_verificar_otdr",
    "client_uuid",
)


def migrar():
    if not DB_PATH.exists():
        raise SystemExit(
            f"ERRO: banco nao encontrado: {DB_PATH}"
        )

    con = sqlite3.connect(DB_PATH)

    try:
        fk_antes = con.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if fk_antes:
            raise RuntimeError(
                "foreign_key_check ja possui erros antes da migracao"
            )

        colunas = con.execute(
            f"PRAGMA table_info({TABELA})"
        ).fetchall()

        tecnico = next(
            (
                coluna
                for coluna in colunas
                if coluna[1] == "tecnico_id"
            ),
            None,
        )

        if tecnico is None:
            raise RuntimeError(
                "coluna tecnico_id nao encontrada"
            )

        if tecnico[3] == 0:
            print(
                "Migracao ja aplicada: "
                "tecnico_id aceita NULL."
            )
            return

        tabela_nova_existe = con.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (TABELA_NOVA,),
        ).fetchone()

        if tabela_nova_existe:
            raise RuntimeError(
                f"tabela temporaria {TABELA_NOVA} ja existe"
            )

        ids_antes = [
            linha[0]
            for linha in con.execute(
                f"SELECT id FROM {TABELA} ORDER BY id"
            )
        ]

        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN IMMEDIATE")

        con.execute(
            f"""
            CREATE TABLE {TABELA_NOVA} (
                id INTEGER NOT NULL,
                tecnico_id INTEGER,
                cliente_id INTEGER,
                tipo VARCHAR(10) NOT NULL,
                cliente_local VARCHAR NOT NULL,
                nome_cliente VARCHAR,
                endereco VARCHAR,
                prioridade BOOLEAN,
                observacoes TEXT,
                status VARCHAR(12),
                criada_por_admin BOOLEAN,
                data_abertura DATETIME,
                data_deslocamento DATETIME,
                data_inicio DATETIME,
                data_fechamento DATETIME,
                pdf_path VARCHAR,
                lat_deslocamento FLOAT,
                lon_deslocamento FLOAT,
                lat_inicio FLOAT,
                lon_inicio FLOAT,
                lat_fim FLOAT,
                lon_fim FLOAT,
                checklist_limpar_conector BOOLEAN,
                checklist_testar_sinal BOOLEAN,
                checklist_verificar_otdr BOOLEAN,
                client_uuid VARCHAR,
                PRIMARY KEY (id),
                FOREIGN KEY(tecnico_id)
                    REFERENCES tecnicos (id),
                FOREIGN KEY(cliente_id)
                    REFERENCES clientes (id),
                UNIQUE (client_uuid)
            )
            """
        )

        nomes_colunas = ", ".join(COLUNAS)

        con.execute(
            f"""
            INSERT INTO {TABELA_NOVA} ({nomes_colunas})
            SELECT {nomes_colunas}
            FROM {TABELA}
            """
        )

        con.execute(f"DROP TABLE {TABELA}")
        con.execute(
            f"ALTER TABLE {TABELA_NOVA} "
            f"RENAME TO {TABELA}"
        )

        ids_depois = [
            linha[0]
            for linha in con.execute(
                f"SELECT id FROM {TABELA} ORDER BY id"
            )
        ]

        if ids_depois != ids_antes:
            raise RuntimeError(
                "IDs das ordens foram alterados"
            )

        fk_depois = con.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if fk_depois:
            raise RuntimeError(
                f"foreign_key_check falhou: {fk_depois}"
            )

        integridade = con.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integridade != "ok":
            raise RuntimeError(
                f"integrity_check falhou: {integridade}"
            )

        con.commit()
        con.execute("PRAGMA foreign_keys = ON")

        tecnico_depois = next(
            coluna
            for coluna in con.execute(
                f"PRAGMA table_info({TABELA})"
            )
            if coluna[1] == "tecnico_id"
        )

        if tecnico_depois[3] != 0:
            raise RuntimeError(
                "tecnico_id ainda esta NOT NULL"
            )

        print("Migracao concluida.")
        print(
            "tecnico_id agora aceita NULL."
        )
        print(
            f"Ordens preservadas: {len(ids_depois)}"
        )
        print("foreign_key_check: ok")
        print("integrity_check: ok")

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


if __name__ == "__main__":
    migrar()
