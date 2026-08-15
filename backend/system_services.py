import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import models
from audit import agora_utc


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def gerar_token_agente() -> str:
    return secrets.token_urlsafe(48)


def normalizar_utc(valor: datetime) -> datetime:
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc)


def serializar_janela(janela: models.MonitorJanelaManutencao) -> dict:
    return {
        "id": janela.id,
        "cliente_codigo": (
            janela.monitor_cliente.codigo
            if janela.monitor_cliente
            else None
        ),
        "unidade_codigo": janela.unidade.codigo if janela.unidade else None,
        "dispositivo_codigo": (
            janela.dispositivo.codigo
            if janela.dispositivo
            else None
        ),
        "link_codigo": janela.link.codigo if janela.link else None,
        "inicio": normalizar_utc(janela.inicio).isoformat(),
        "fim": normalizar_utc(janela.fim).isoformat(),
        "motivo": janela.motivo,
        "cancelada": janela.cancelada_em is not None,
    }


def janelas_publicaveis(db) -> list[dict]:
    limite = agora_utc() - timedelta(days=1)
    janelas = db.query(models.MonitorJanelaManutencao).filter(
        models.MonitorJanelaManutencao.cancelada_em.is_(None),
        models.MonitorJanelaManutencao.fim >= limite,
    ).order_by(models.MonitorJanelaManutencao.inicio).all()
    return [serializar_janela(janela) for janela in janelas]


def janela_ativa_para_origem(db, origem) -> models.MonitorJanelaManutencao | None:
    if not origem:
        return None

    agora = agora_utc()
    janelas = db.query(models.MonitorJanelaManutencao).filter(
        models.MonitorJanelaManutencao.cancelada_em.is_(None),
        models.MonitorJanelaManutencao.inicio <= agora,
        models.MonitorJanelaManutencao.fim > agora,
    ).order_by(models.MonitorJanelaManutencao.inicio.desc()).all()

    for janela in janelas:
        if janela.link_id and origem.get("link"):
            if janela.link_id == origem["link"].id:
                return janela
            continue
        if janela.dispositivo_id:
            if janela.dispositivo_id == origem["dispositivo"].id:
                return janela
            continue
        if janela.unidade_id:
            if janela.unidade_id == origem["unidade"].id:
                return janela
            continue
        if janela.monitor_cliente_id == origem["monitor_cliente"].id:
            return janela

    return None


def calcular_versao_configuracao(conteudo: dict) -> str:
    canonico = json.dumps(
        conteudo,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def publicar_configuracao(
    db,
    conteudo: dict,
    *,
    admin_id: int | None,
    motivo: str,
) -> models.MonitorConfiguracaoVersao:
    versao = calcular_versao_configuracao(conteudo)
    db.query(models.MonitorConfiguracaoVersao).filter_by(
        ativa=True,
    ).update({"ativa": False})

    registro = models.MonitorConfiguracaoVersao(
        versao=versao,
        conteudo=json.dumps(
            conteudo,
            ensure_ascii=False,
            sort_keys=True,
        ),
        ativa=True,
        motivo=motivo[:240],
        criada_em=agora_utc(),
        criada_por_admin_id=admin_id,
    )
    db.add(registro)
    db.flush()
    return registro


def configuracao_publicada(db) -> tuple[dict, models.MonitorConfiguracaoVersao] | None:
    registro = db.query(models.MonitorConfiguracaoVersao).filter_by(
        ativa=True,
    ).order_by(models.MonitorConfiguracaoVersao.id.desc()).first()
    if not registro:
        return None
    return json.loads(registro.conteudo), registro


def registrar_heartbeat_amostrado(db, agente, status: dict, versao: str | None) -> None:
    agora = agora_utc()
    ultimo = db.query(models.MonitorHeartbeat).filter_by(
        agente_id=agente.id,
    ).order_by(models.MonitorHeartbeat.recebido_em.desc()).first()

    agente.ultimo_contato_em = agora
    agente.ultima_versao_config = versao
    agente.ultimo_status = json.dumps(
        status,
        ensure_ascii=False,
        sort_keys=True,
    )

    if not ultimo or normalizar_utc(ultimo.recebido_em) <= agora - timedelta(minutes=5):
        db.add(models.MonitorHeartbeat(
            agente_id=agente.id,
            recebido_em=agora,
            versao_config=versao,
            status=json.dumps(status, ensure_ascii=False, sort_keys=True),
        ))
