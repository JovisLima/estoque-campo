"""melhorias sistemicas de operacao e observabilidade

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _alterar_tipos_financeiros_upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "contas_financeiras",
            "valor",
            existing_type=sa.Float(),
            type_=sa.Numeric(14, 2),
            existing_nullable=False,
            postgresql_using="round(valor::numeric, 2)",
        )
        op.alter_column(
            "contas_financeiras",
            "vencimento",
            existing_type=sa.String(),
            type_=sa.Date(),
            existing_nullable=False,
            postgresql_using="vencimento::date",
        )
        op.alter_column(
            "contas_financeiras",
            "data_pagamento",
            existing_type=sa.String(),
            type_=sa.Date(),
            existing_nullable=True,
            postgresql_using="NULLIF(data_pagamento, '')::date",
        )
        op.alter_column(
            "materiais",
            "custo_unitario",
            existing_type=sa.Float(),
            type_=sa.Numeric(14, 4),
            existing_nullable=True,
            postgresql_using="round(custo_unitario::numeric, 4)",
        )
        return

    # O batch do SQLite gera CAST(texto AS DATE), que reduz uma data ISO ao
    # ano. As colunas auxiliares preservam o texto durante a recriacao.
    op.add_column(
        "contas_financeiras",
        sa.Column("_vencimento_iso_0002", sa.String(), nullable=True),
    )
    op.add_column(
        "contas_financeiras",
        sa.Column("_pagamento_iso_0002", sa.String(), nullable=True),
    )
    op.execute(sa.text(
        "UPDATE contas_financeiras SET "
        "_vencimento_iso_0002 = vencimento, "
        "_pagamento_iso_0002 = data_pagamento"
    ))
    with op.batch_alter_table("contas_financeiras") as batch_op:
        batch_op.alter_column(
            "valor",
            existing_type=sa.Float(),
            type_=sa.Numeric(14, 2),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "vencimento",
            existing_type=sa.String(),
            type_=sa.Date(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "data_pagamento",
            existing_type=sa.String(),
            type_=sa.Date(),
            existing_nullable=True,
        )
    op.execute(sa.text(
        "UPDATE contas_financeiras SET "
        "vencimento = _vencimento_iso_0002, "
        "data_pagamento = _pagamento_iso_0002"
    ))
    with op.batch_alter_table("contas_financeiras") as batch_op:
        batch_op.drop_column("_pagamento_iso_0002")
        batch_op.drop_column("_vencimento_iso_0002")
    with op.batch_alter_table("materiais") as batch_op:
        batch_op.alter_column(
            "custo_unitario",
            existing_type=sa.Float(),
            type_=sa.Numeric(14, 4),
            existing_nullable=True,
        )


def _alterar_tipos_financeiros_downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "materiais",
            "custo_unitario",
            existing_type=sa.Numeric(14, 4),
            type_=sa.Float(),
            existing_nullable=True,
            postgresql_using="custo_unitario::double precision",
        )
        op.alter_column(
            "contas_financeiras",
            "data_pagamento",
            existing_type=sa.Date(),
            type_=sa.String(),
            existing_nullable=True,
            postgresql_using="to_char(data_pagamento, 'YYYY-MM-DD')",
        )
        op.alter_column(
            "contas_financeiras",
            "vencimento",
            existing_type=sa.Date(),
            type_=sa.String(),
            existing_nullable=False,
            postgresql_using="to_char(vencimento, 'YYYY-MM-DD')",
        )
        op.alter_column(
            "contas_financeiras",
            "valor",
            existing_type=sa.Numeric(14, 2),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using="valor::double precision",
        )
        return

    with op.batch_alter_table("materiais") as batch_op:
        batch_op.alter_column(
            "custo_unitario",
            existing_type=sa.Numeric(14, 4),
            type_=sa.Float(),
            existing_nullable=True,
        )
    with op.batch_alter_table("contas_financeiras") as batch_op:
        batch_op.alter_column(
            "data_pagamento",
            existing_type=sa.Date(),
            type_=sa.String(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "vencimento",
            existing_type=sa.Date(),
            type_=sa.String(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "valor",
            existing_type=sa.Numeric(14, 2),
            type_=sa.Float(),
            existing_nullable=False,
        )


def upgrade() -> None:
    _alterar_tipos_financeiros_upgrade()

    with op.batch_alter_table("monitor_links") as batch_op:
        batch_op.add_column(sa.Column("probe_tipo", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("probe_host", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("probe_porta", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_monitor_links_probe_host",
            ["probe_host"],
        )

    with op.batch_alter_table("monitor_ocorrencias") as batch_op:
        batch_op.add_column(
            sa.Column("ultima_ocorrencia_em", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("causa_provavel", sa.String(80), nullable=True)
        )
    op.execute(
        sa.text(
            "UPDATE monitor_ocorrencias "
            "SET ultima_ocorrencia_em = inicio, "
            "causa_provavel = 'INDETERMINADA'"
        )
    )
    with op.batch_alter_table("monitor_ocorrencias") as batch_op:
        batch_op.alter_column(
            "ultima_ocorrencia_em",
            existing_type=sa.DateTime(),
            nullable=False,
        )
        batch_op.alter_column(
            "causa_provavel",
            existing_type=sa.String(80),
            nullable=False,
        )

    op.create_table(
        "monitor_agentes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(64), nullable=False),
        sa.Column("nome", sa.String(160), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_rotacionado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_contato_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultima_versao_config", sa.String(64), nullable=True),
        sa.Column("ultimo_status", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
    )
    op.create_table(
        "monitor_configuracoes_versoes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("versao", sa.String(64), nullable=False),
        sa.Column("conteudo", sa.Text(), nullable=False),
        sa.Column("ativa", sa.Boolean(), nullable=False),
        sa.Column("motivo", sa.String(240), nullable=False),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("criada_por_admin_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["criada_por_admin_id"],
            ["admin_usuarios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitor_configuracoes_versoes_ativa",
        "monitor_configuracoes_versoes",
        ["ativa"],
    )
    op.create_index(
        "ix_monitor_configuracoes_versoes_versao",
        "monitor_configuracoes_versoes",
        ["versao"],
    )
    op.create_table(
        "monitor_janelas_manutencao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_cliente_id", sa.Integer(), nullable=True),
        sa.Column("unidade_id", sa.Integer(), nullable=True),
        sa.Column("dispositivo_id", sa.Integer(), nullable=True),
        sa.Column("link_id", sa.Integer(), nullable=True),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motivo", sa.String(500), nullable=False),
        sa.Column("criado_por_admin_id", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelada_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["monitor_cliente_id"], ["monitor_clientes.id"]),
        sa.ForeignKeyConstraint(["unidade_id"], ["monitor_unidades.id"]),
        sa.ForeignKeyConstraint(["dispositivo_id"], ["monitor_dispositivos.id"]),
        sa.ForeignKeyConstraint(["link_id"], ["monitor_links.id"]),
        sa.ForeignKeyConstraint(["criado_por_admin_id"], ["admin_usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitor_janela_periodo",
        "monitor_janelas_manutencao",
        ["inicio", "fim"],
    )
    op.create_table(
        "auditoria_eventos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ator_tipo", sa.String(32), nullable=False),
        sa.Column("ator_id", sa.Integer(), nullable=True),
        sa.Column("ator_codigo", sa.String(160), nullable=True),
        sa.Column("acao", sa.String(120), nullable=False),
        sa.Column("entidade_tipo", sa.String(120), nullable=False),
        sa.Column("entidade_id", sa.String(120), nullable=True),
        sa.Column("antes", sa.Text(), nullable=True),
        sa.Column("depois", sa.Text(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auditoria_eventos_criado_em",
        "auditoria_eventos",
        ["criado_em"],
    )
    op.create_table(
        "monitor_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agente_id", sa.Integer(), nullable=False),
        sa.Column("recebido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("versao_config", sa.String(64), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["agente_id"], ["monitor_agentes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitor_heartbeats_recebido_em",
        "monitor_heartbeats",
        ["recebido_em"],
    )
    op.create_table(
        "monitor_eventos_ocorrencia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ocorrencia_id", sa.Integer(), nullable=False),
        sa.Column("dispositivo_id", sa.Integer(), nullable=False),
        sa.Column("link_id", sa.Integer(), nullable=True),
        sa.Column("chave_evento", sa.String(160), nullable=False),
        sa.Column("tipo", sa.String(32), nullable=False),
        sa.Column("inicio", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ocorrencia_id"], ["monitor_ocorrencias.id"]),
        sa.ForeignKeyConstraint(["dispositivo_id"], ["monitor_dispositivos.id"]),
        sa.ForeignKeyConstraint(["link_id"], ["monitor_links.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chave_evento"),
    )


def downgrade() -> None:
    op.drop_table("monitor_eventos_ocorrencia")
    op.drop_index(
        "ix_monitor_heartbeats_recebido_em",
        table_name="monitor_heartbeats",
    )
    op.drop_table("monitor_heartbeats")
    op.drop_index(
        "ix_auditoria_eventos_criado_em",
        table_name="auditoria_eventos",
    )
    op.drop_table("auditoria_eventos")
    op.drop_index(
        "ix_monitor_janela_periodo",
        table_name="monitor_janelas_manutencao",
    )
    op.drop_table("monitor_janelas_manutencao")
    op.drop_index(
        "ix_monitor_configuracoes_versoes_versao",
        table_name="monitor_configuracoes_versoes",
    )
    op.drop_index(
        "ix_monitor_configuracoes_versoes_ativa",
        table_name="monitor_configuracoes_versoes",
    )
    op.drop_table("monitor_configuracoes_versoes")
    op.drop_table("monitor_agentes")

    with op.batch_alter_table("monitor_ocorrencias") as batch_op:
        batch_op.drop_column("causa_provavel")
        batch_op.drop_column("ultima_ocorrencia_em")
    with op.batch_alter_table("monitor_links") as batch_op:
        batch_op.drop_constraint(
            "uq_monitor_links_probe_host",
            type_="unique",
        )
        batch_op.drop_column("probe_porta")
        batch_op.drop_column("probe_host")
        batch_op.drop_column("probe_tipo")

    _alterar_tipos_financeiros_downgrade()
