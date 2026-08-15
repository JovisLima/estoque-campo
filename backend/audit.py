import json
from datetime import datetime, timezone

import models


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _json(valor) -> str | None:
    if valor is None:
        return None
    return json.dumps(
        valor,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def registrar_auditoria(
    db,
    *,
    ator,
    acao: str,
    entidade_tipo: str,
    entidade_id=None,
    antes=None,
    depois=None,
) -> models.AuditoriaEvento:
    if isinstance(ator, models.AdminUsuario):
        ator_tipo = "ADMIN"
        ator_id = ator.id
        ator_codigo = ator.login
    elif isinstance(ator, models.MonitorAgente):
        ator_tipo = "AGENTE"
        ator_id = ator.id
        ator_codigo = ator.codigo
    else:
        ator_tipo = "SISTEMA"
        ator_id = None
        ator_codigo = str(ator) if ator else None

    evento = models.AuditoriaEvento(
        ator_tipo=ator_tipo,
        ator_id=ator_id,
        ator_codigo=ator_codigo,
        acao=acao,
        entidade_tipo=entidade_tipo,
        entidade_id=str(entidade_id) if entidade_id is not None else None,
        antes=_json(antes),
        depois=_json(depois),
        criado_em=agora_utc(),
    )
    db.add(evento)
    return evento
