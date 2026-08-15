from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from database import Base


class TipoOS(str, enum.Enum):
    instalacao = "instalacao"
    manutencao = "manutencao"
    preventiva = "preventiva"  # gerada automaticamente por falhas repetidas


class StatusOS(str, enum.Enum):
    pendente = "pendente"          # atribuída/criada, aguardando o técnico sair pra atender
    deslocamento = "deslocamento"  # técnico a caminho do local
    em_andamento = "em_andamento"  # técnico chegou e está executando o serviço
    fechada = "fechada"


class TipoMovimentacao(str, enum.Enum):
    saida = "saida"       # usado em campo (baixa do estoque PESSOAL do técnico)
    entrada = "entrada"   # reposição de estoque CENTRAL
    ajuste = "ajuste"     # correção manual (inventário)


class CategoriaFerramenta(str, enum.Enum):
    ferramenta = "ferramenta"
    epi = "epi"


class StatusFerramenta(str, enum.Enum):
    disponivel = "disponivel"      # no estoque central, livre pra transferir
    em_transito = "em_transito"    # admin enviou, aguardando o técnico confirmar
    com_tecnico = "com_tecnico"    # confirmado, está com o técnico
    manutencao = "manutencao"      # em manutenção (fora de uso temporariamente)
    baixada = "baixada"            # quebrada/gasta, retirada de circulação


class TipoTransferencia(str, enum.Enum):
    material = "material"
    ferramenta = "ferramenta"


class StatusTransferencia(str, enum.Enum):
    pendente = "pendente"
    confirmada = "confirmada"
    recusada = "recusada"


class StatusAviso(str, enum.Enum):
    aberto = "aberto"
    resolvido = "resolvido"


class StatusSolicitacao(str, enum.Enum):
    pendente = "pendente"
    aprovada = "aprovada"
    rejeitada = "rejeitada"


class PapelAdmin(str, enum.Enum):
    gerencia = "gerencia"        # acesso total
    almoxarifado = "almoxarifado"  # só estoque, transferências, solicitações e avisos


class AdminUsuario(Base):
    __tablename__ = "admin_usuarios"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    login = Column(String, unique=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    papel = Column(Enum(PapelAdmin), default=PapelAdmin.almoxarifado)
    ativo = Column(Boolean, default=True)


class TipoConta(str, enum.Enum):
    pagar = "pagar"
    receber = "receber"


class StatusConta(str, enum.Enum):
    pendente = "pendente"
    pago = "pago"
    cancelado = "cancelado"


class ContaFinanceira(Base):
    """Contas a pagar (fornecedores, contas da empresa) e a receber
    (clientes). Só o papel 'gerencia' acessa esse módulo."""
    __tablename__ = "contas_financeiras"
    id = Column(Integer, primary_key=True)
    tipo = Column(Enum(TipoConta), nullable=False)
    descricao = Column(String, nullable=False)
    valor = Column(Numeric(14, 2), nullable=False)
    vencimento = Column(Date, nullable=False)
    categoria = Column(String, nullable=True)  # ex: fornecedor, cliente, salário, imposto
    status = Column(Enum(StatusConta), default=StatusConta.pendente)
    data_pagamento = Column(Date, nullable=True)
    observacoes = Column(Text, nullable=True)
    criada_em = Column(DateTime, default=datetime.utcnow)


class Cliente(Base):
    """Cadastro de cliente/local. Guarda a foto da rota do cabo, pra
    facilitar localizar falhas em campo, e serve pra agrupar o histórico
    de OS por local (detectar problemas recorrentes)."""
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    endereco = Column(String, nullable=True)
    observacoes = Column(Text, nullable=True)
    imagem_rota_cabo = Column(String, nullable=True)  # caminho do arquivo
    criado_em = Column(DateTime, default=datetime.utcnow)

    @property
    def tem_imagem_rota(self):
        return bool(self.imagem_rota_cabo)


class MonitorCliente(Base):
    """Vincula um cliente existente a um codigo estavel do AVEN Monitor."""

    __tablename__ = "monitor_clientes"

    id = Column(Integer, primary_key=True)
    cliente_id = Column(
        Integer,
        ForeignKey("clientes.id"),
        unique=True,
        nullable=False,
    )
    codigo = Column(String, unique=True, nullable=False)
    ativo = Column(Boolean, default=True, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    cliente = relationship("Cliente")
    unidades = relationship(
        "MonitorUnidade",
        back_populates="monitor_cliente",
        cascade="all, delete-orphan",
    )


class MonitorUnidade(Base):
    """Unidade fisica, usina ou filial pertencente a um cliente."""

    __tablename__ = "monitor_unidades"

    id = Column(Integer, primary_key=True)
    monitor_cliente_id = Column(
        Integer,
        ForeignKey("monitor_clientes.id"),
        nullable=False,
    )
    codigo = Column(String, unique=True, nullable=False)
    nome = Column(String, nullable=False)
    cidade = Column(String, nullable=False)
    estado = Column(String, nullable=True)
    ativo = Column(Boolean, default=True, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    monitor_cliente = relationship(
        "MonitorCliente",
        back_populates="unidades",
    )
    dispositivos = relationship(
        "MonitorDispositivo",
        back_populates="unidade",
        cascade="all, delete-orphan",
    )


class MonitorDispositivo(Base):
    """Roteador ou equipamento consultado pelo agente de monitoramento."""

    __tablename__ = "monitor_dispositivos"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(
        Integer,
        ForeignKey("monitor_unidades.id"),
        nullable=False,
    )
    codigo = Column(String, unique=True, nullable=False)
    nome = Column(String, nullable=False)
    fabricante = Column(String, nullable=False)
    ip_wireguard = Column(String, unique=True, nullable=False)
    ativo = Column(Boolean, default=False, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    unidade = relationship(
        "MonitorUnidade",
        back_populates="dispositivos",
    )
    links = relationship(
        "MonitorLink",
        back_populates="dispositivo",
        cascade="all, delete-orphan",
    )
    testes = relationship(
        "MonitorTesteConfiguracao",
        back_populates="dispositivo",
        cascade="all, delete-orphan",
    )


class MonitorLink(Base):
    """WAN monitorada de um equipamento."""

    __tablename__ = "monitor_links"

    id = Column(Integer, primary_key=True)
    dispositivo_id = Column(
        Integer,
        ForeignKey("monitor_dispositivos.id"),
        nullable=False,
    )
    codigo = Column(String, nullable=False)
    nome = Column(String, nullable=False)
    if_index = Column(Integer, nullable=False)
    operadora = Column(String, nullable=False)
    papel = Column(String, nullable=False)
    probe_tipo = Column(String, nullable=True)
    probe_host = Column(String, nullable=True)
    probe_porta = Column(Integer, nullable=True)
    ativo = Column(Boolean, default=True, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    dispositivo = relationship(
        "MonitorDispositivo",
        back_populates="links",
    )

    __table_args__ = (
        UniqueConstraint(
            "dispositivo_id",
            "codigo",
            name="uq_monitor_link_codigo_dispositivo",
        ),
        UniqueConstraint(
            "dispositivo_id",
            "if_index",
            name="uq_monitor_link_ifindex_dispositivo",
        ),
        UniqueConstraint(
            "probe_host",
            name="uq_monitor_links_probe_host",
        ),
    )


class MonitorTesteConfiguracao(Base):
    """Solicitacao de teste executada pelo agente antes da ativacao."""

    __tablename__ = "monitor_testes_configuracao"

    id = Column(Integer, primary_key=True)
    dispositivo_id = Column(
        Integer,
        ForeignKey("monitor_dispositivos.id"),
        nullable=False,
    )
    status = Column(String, default="PENDENTE", nullable=False)
    sucesso = Column(Boolean, nullable=True)
    resultado = Column(Text, nullable=True)
    solicitado_em = Column(DateTime, default=datetime.utcnow, nullable=False)
    iniciado_em = Column(DateTime, nullable=True)
    finalizado_em = Column(DateTime, nullable=True)

    dispositivo = relationship(
        "MonitorDispositivo",
        back_populates="testes",
    )


class MonitorAgente(Base):
    """Credencial individual de uma instalacao do AVEN Monitor."""

    __tablename__ = "monitor_agentes"

    id = Column(Integer, primary_key=True)
    codigo = Column(String(64), unique=True, nullable=False)
    nome = Column(String(160), nullable=False)
    token_hash = Column(String(64), nullable=False)
    ativo = Column(Boolean, default=True, nullable=False)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    token_rotacionado_em = Column(DateTime(timezone=True), nullable=False)
    ultimo_contato_em = Column(DateTime(timezone=True), nullable=True)
    ultima_versao_config = Column(String(64), nullable=True)
    ultimo_status = Column(Text, nullable=True)


class MonitorConfiguracaoVersao(Base):
    """Snapshot imutavel da configuracao entregue aos agentes."""

    __tablename__ = "monitor_configuracoes_versoes"

    id = Column(Integer, primary_key=True)
    versao = Column(String(64), nullable=False, index=True)
    conteudo = Column(Text, nullable=False)
    ativa = Column(Boolean, default=True, nullable=False, index=True)
    motivo = Column(String(240), nullable=False)
    criada_em = Column(DateTime(timezone=True), nullable=False)
    criada_por_admin_id = Column(
        Integer,
        ForeignKey("admin_usuarios.id"),
        nullable=True,
    )


class MonitorJanelaManutencao(Base):
    """Suspende alertas em um escopo e periodo definidos."""

    __tablename__ = "monitor_janelas_manutencao"

    id = Column(Integer, primary_key=True)
    monitor_cliente_id = Column(
        Integer,
        ForeignKey("monitor_clientes.id"),
        nullable=True,
    )
    unidade_id = Column(
        Integer,
        ForeignKey("monitor_unidades.id"),
        nullable=True,
    )
    dispositivo_id = Column(
        Integer,
        ForeignKey("monitor_dispositivos.id"),
        nullable=True,
    )
    link_id = Column(
        Integer,
        ForeignKey("monitor_links.id"),
        nullable=True,
    )
    inicio = Column(DateTime(timezone=True), nullable=False)
    fim = Column(DateTime(timezone=True), nullable=False)
    motivo = Column(String(500), nullable=False)
    criado_por_admin_id = Column(
        Integer,
        ForeignKey("admin_usuarios.id"),
        nullable=False,
    )
    criado_em = Column(DateTime(timezone=True), nullable=False)
    cancelada_em = Column(DateTime(timezone=True), nullable=True)

    monitor_cliente = relationship("MonitorCliente")
    unidade = relationship("MonitorUnidade")
    dispositivo = relationship("MonitorDispositivo")
    link = relationship("MonitorLink")

    __table_args__ = (
        Index("ix_monitor_janela_periodo", "inicio", "fim"),
    )


class AuditoriaEvento(Base):
    """Trilha imutavel das alteracoes administrativas e operacionais."""

    __tablename__ = "auditoria_eventos"

    id = Column(Integer, primary_key=True)
    ator_tipo = Column(String(32), nullable=False)
    ator_id = Column(Integer, nullable=True)
    ator_codigo = Column(String(160), nullable=True)
    acao = Column(String(120), nullable=False)
    entidade_tipo = Column(String(120), nullable=False)
    entidade_id = Column(String(120), nullable=True)
    antes = Column(Text, nullable=True)
    depois = Column(Text, nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, index=True)


class MonitorHeartbeat(Base):
    """Amostra operacional enviada periodicamente por um agente."""

    __tablename__ = "monitor_heartbeats"

    id = Column(Integer, primary_key=True)
    agente_id = Column(
        Integer,
        ForeignKey("monitor_agentes.id"),
        nullable=False,
    )
    recebido_em = Column(DateTime(timezone=True), nullable=False, index=True)
    versao_config = Column(String(64), nullable=True)
    status = Column(Text, nullable=False)

    agente = relationship("MonitorAgente")


class Tecnico(Base):
    __tablename__ = "tecnicos"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    login = Column(String, unique=True, nullable=False)
    pin_hash = Column(String, nullable=False)  # login simples via PIN numérico
    ativo = Column(Boolean, default=True)
    # cadastro é feito pelo pessoal do estoque, mas só pode logar depois de aprovado
    aprovado = Column(Boolean, default=False)
    # só técnicos ADM podem abrir uma OS avulsa (sem ser atribuída pelo admin)
    is_adm = Column(Boolean, default=False)
    telefone = Column(String, nullable=True)
    data_contratacao = Column(String, nullable=True)  # armazenado como texto "AAAA-MM-DD"
    foto_perfil = Column(String, nullable=True)  # caminho do arquivo em disco

    ordens = relationship("OrdemServico", back_populates="tecnico")

    @property
    def tem_foto_perfil(self):
        return bool(self.foto_perfil)


class Material(Base):
    __tablename__ = "materiais"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    categoria = Column(String, nullable=True)
    unidade = Column(String, default="un")  # un, m, cx, etc.
    qtd_atual = Column(Float, default=0)     # estoque CENTRAL (almoxarifado)
    qtd_minima = Column(Float, default=0)
    custo_unitario = Column(Numeric(14, 4), default=0)

    movimentacoes = relationship("MovimentacaoEstoque", back_populates="material")


class EstoquePessoal(Base):
    """Quanto de cada material cada técnico tem fisicamente com ele.
    É debitado quando o técnico usa material numa OS."""
    __tablename__ = "estoque_pessoal"
    id = Column(Integer, primary_key=True)
    tecnico_id = Column(Integer, ForeignKey("tecnicos.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materiais.id"), nullable=False)
    qtd_atual = Column(Float, default=0)

    tecnico = relationship("Tecnico")
    material = relationship("Material")

    __table_args__ = (UniqueConstraint("tecnico_id", "material_id", name="uq_estoque_pessoal"),)


class Ferramenta(Base):
    __tablename__ = "ferramentas"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    codigo_patrimonio = Column(String, unique=True, nullable=True)
    categoria = Column(Enum(CategoriaFerramenta), default=CategoriaFerramenta.ferramenta)
    status = Column(Enum(StatusFerramenta), default=StatusFerramenta.disponivel)
    tecnico_atual_id = Column(Integer, ForeignKey("tecnicos.id"), nullable=True)

    tecnico_atual = relationship("Tecnico")
    avisos = relationship("AvisoFerramenta", back_populates="ferramenta")


class Transferencia(Base):
    """Item enviado do estoque central pro técnico. Fica pendente até ele
    confirmar o recebimento no app (materiais, ferramentas ou EPIs)."""
    __tablename__ = "transferencias"
    id = Column(Integer, primary_key=True)
    tecnico_id = Column(Integer, ForeignKey("tecnicos.id"), nullable=False)
    tipo = Column(Enum(TipoTransferencia), nullable=False)
    material_id = Column(Integer, ForeignKey("materiais.id"), nullable=True)
    quantidade = Column(Float, nullable=True)  # só pra tipo=material
    ferramenta_id = Column(Integer, ForeignKey("ferramentas.id"), nullable=True)
    status = Column(Enum(StatusTransferencia), default=StatusTransferencia.pendente)
    data_envio = Column(DateTime, default=datetime.utcnow)
    data_confirmacao = Column(DateTime, nullable=True)

    tecnico = relationship("Tecnico")
    material = relationship("Material")
    ferramenta = relationship("Ferramenta")


class AvisoFerramenta(Base):
    """Técnico notifica que uma ferramenta/EPI quebrou, gastou ou tem algum
    problema. Só o estoque (admin) resolve — dando baixa, mandando pra
    manutenção ou descartando o aviso."""
    __tablename__ = "avisos_ferramentas"
    id = Column(Integer, primary_key=True)
    ferramenta_id = Column(Integer, ForeignKey("ferramentas.id"), nullable=False)
    tecnico_id = Column(Integer, ForeignKey("tecnicos.id"), nullable=False)
    descricao = Column(Text, nullable=False)
    status = Column(Enum(StatusAviso), default=StatusAviso.aberto)
    data_criacao = Column(DateTime, default=datetime.utcnow)
    data_resolucao = Column(DateTime, nullable=True)

    ferramenta = relationship("Ferramenta", back_populates="avisos")
    tecnico = relationship("Tecnico")


class OrdemServico(Base):
    __tablename__ = "ordens_servico"
    id = Column(Integer, primary_key=True)
    tecnico_id = Column(Integer, ForeignKey("tecnicos.id"), nullable=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    tipo = Column(Enum(TipoOS), nullable=False)
    cliente_local = Column(String, nullable=False)
    nome_cliente = Column(String, nullable=True)
    endereco = Column(String, nullable=True)
    prioridade = Column(Boolean, default=False)
    observacoes = Column(Text, nullable=True)
    status = Column(Enum(StatusOS), default=StatusOS.pendente)
    criada_por_admin = Column(Boolean, default=False)
    data_abertura = Column(DateTime, default=datetime.utcnow)
    data_deslocamento = Column(DateTime, nullable=True)
    data_inicio = Column(DateTime, nullable=True)
    data_fechamento = Column(DateTime, nullable=True)
    pdf_path = Column(String, nullable=True)  # relatório em PDF gerado ao fechar a OS
    lat_deslocamento = Column(Float, nullable=True)
    lon_deslocamento = Column(Float, nullable=True)
    lat_inicio = Column(Float, nullable=True)
    lon_inicio = Column(Float, nullable=True)
    lat_fim = Column(Float, nullable=True)
    lon_fim = Column(Float, nullable=True)
    # checklist padrão de boas práticas em fibra óptica
    checklist_limpar_conector = Column(Boolean, default=False)
    checklist_testar_sinal = Column(Boolean, default=False)
    checklist_verificar_otdr = Column(Boolean, default=False)
    # id gerado no celular (client_uuid) para permitir sincronização offline
    # sem duplicar OS se o técnico reenviar a mesma requisição
    client_uuid = Column(String, unique=True, nullable=True)

    tecnico = relationship("Tecnico", back_populates="ordens")
    cliente = relationship("Cliente")
    movimentacoes = relationship("MovimentacaoEstoque", back_populates="ordem")
    fotos = relationship("FotoOrdem", back_populates="ordem")
    monitor_ocorrencia = relationship(
        "MonitorOcorrencia",
        back_populates="ordem",
        uselist=False,
    )


class MonitorOcorrencia(Base):
    """Mantem a origem monitorada da OS sem alterar o fluxo do tecnico."""

    __tablename__ = "monitor_ocorrencias"

    id = Column(Integer, primary_key=True)
    ordem_id = Column(
        Integer,
        ForeignKey("ordens_servico.id"),
        unique=True,
        nullable=False,
    )
    unidade_id = Column(
        Integer,
        ForeignKey("monitor_unidades.id"),
        nullable=False,
    )
    dispositivo_id = Column(
        Integer,
        ForeignKey("monitor_dispositivos.id"),
        nullable=False,
    )
    link_id = Column(
        Integer,
        ForeignKey("monitor_links.id"),
        nullable=True,
    )
    tipo = Column(String, nullable=False)
    inicio = Column(DateTime, nullable=False)
    ultima_ocorrencia_em = Column(DateTime, nullable=False)
    causa_provavel = Column(String(80), nullable=False, default="INDETERMINADA")

    ordem = relationship(
        "OrdemServico",
        back_populates="monitor_ocorrencia",
    )
    unidade = relationship("MonitorUnidade")
    dispositivo = relationship("MonitorDispositivo")
    link = relationship("MonitorLink")
    eventos = relationship(
        "MonitorEventoOcorrencia",
        back_populates="ocorrencia",
        cascade="all, delete-orphan",
    )


class MonitorEventoOcorrencia(Base):
    """Sintoma deduplicado e correlacionado a uma unica OS raiz."""

    __tablename__ = "monitor_eventos_ocorrencia"

    id = Column(Integer, primary_key=True)
    ocorrencia_id = Column(
        Integer,
        ForeignKey("monitor_ocorrencias.id"),
        nullable=False,
    )
    dispositivo_id = Column(
        Integer,
        ForeignKey("monitor_dispositivos.id"),
        nullable=False,
    )
    link_id = Column(
        Integer,
        ForeignKey("monitor_links.id"),
        nullable=True,
    )
    chave_evento = Column(String(160), unique=True, nullable=False)
    tipo = Column(String(32), nullable=False)
    inicio = Column(DateTime, nullable=False)
    payload = Column(Text, nullable=False)
    criado_em = Column(DateTime(timezone=True), nullable=False)

    ocorrencia = relationship(
        "MonitorOcorrencia",
        back_populates="eventos",
    )
    dispositivo = relationship("MonitorDispositivo")
    link = relationship("MonitorLink")


class MovimentacaoEstoque(Base):
    __tablename__ = "movimentacoes_estoque"
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("materiais.id"), nullable=False)
    ordem_id = Column(Integer, ForeignKey("ordens_servico.id"), nullable=True)
    quantidade = Column(Float, nullable=False)
    tipo = Column(Enum(TipoMovimentacao), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    client_uuid = Column(String, unique=True, nullable=True)

    material = relationship("Material", back_populates="movimentacoes")
    ordem = relationship("OrdemServico", back_populates="movimentacoes")


class FotoOrdem(Base):
    """Fotos anexadas pelo técnico durante a execução da OS (ex: antes/depois
    da instalação, evidência do serviço)."""
    __tablename__ = "fotos_ordem"
    id = Column(Integer, primary_key=True)
    ordem_id = Column(Integer, ForeignKey("ordens_servico.id"), nullable=False)
    caminho = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    client_uuid = Column(String, unique=True, nullable=True)

    ordem = relationship("OrdemServico", back_populates="fotos")


class SolicitacaoMaterial(Base):
    """Técnico pede material do estoque central. Se o admin aprovar, debita
    o central e o material já entra direto no estoque pessoal do técnico
    (diferente da Transferencia, aqui quem inicia é o técnico)."""
    __tablename__ = "solicitacoes_material"
    id = Column(Integer, primary_key=True)
    tecnico_id = Column(Integer, ForeignKey("tecnicos.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materiais.id"), nullable=False)
    quantidade = Column(Float, nullable=False)
    observacao = Column(Text, nullable=True)
    status = Column(Enum(StatusSolicitacao), default=StatusSolicitacao.pendente)
    data_solicitacao = Column(DateTime, default=datetime.utcnow)
    data_resposta = Column(DateTime, nullable=True)
    client_uuid = Column(String, unique=True, nullable=True)

    tecnico = relationship("Tecnico")
    material = relationship("Material")
