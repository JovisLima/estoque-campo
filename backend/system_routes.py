import json
import re
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

import models
from audit import agora_utc, registrar_auditoria
from database import get_db
from system_services import (
    gerar_token_agente,
    hash_token,
    normalizar_utc,
    registrar_heartbeat_amostrado,
    serializar_janela,
)


CODIGO_AGENTE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,63}$")


class AgenteCreate(BaseModel):
    codigo: str
    nome: str = Field(min_length=2, max_length=160)

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, valor: str) -> str:
        codigo = valor.strip().upper()
        if not CODIGO_AGENTE_RE.fullmatch(codigo):
            raise ValueError("codigo de agente invalido")
        return codigo


class AgenteAtivoUpdate(BaseModel):
    ativo: bool


class JanelaCreate(BaseModel):
    escopo_tipo: Literal["CLIENTE", "UNIDADE", "DISPOSITIVO", "LINK"]
    escopo_id: int = Field(gt=0)
    inicio: datetime
    fim: datetime
    motivo: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validar_periodo(self):
        if self.inicio.tzinfo is None or self.fim.tzinfo is None:
            raise ValueError("inicio e fim devem incluir fuso horario")
        if normalizar_utc(self.fim) <= normalizar_utc(self.inicio):
            raise ValueError("fim deve ser posterior ao inicio")
        if normalizar_utc(self.fim) <= agora_utc():
            raise ValueError("fim da manutencao deve estar no futuro")
        return self


class HeartbeatCreate(BaseModel):
    versao_config: Optional[str] = Field(default=None, max_length=64)
    status: dict

    @model_validator(mode="after")
    def limitar_status(self):
        serializado = json.dumps(
            self.status,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(serializado.encode("utf-8")) > 16 * 1024:
            raise ValueError("status do heartbeat excede 16 KiB")
        return self


def _serializar_agente(agente: models.MonitorAgente) -> dict:
    ultimo_status = None
    if agente.ultimo_status:
        try:
            ultimo_status = json.loads(agente.ultimo_status)
        except json.JSONDecodeError:
            ultimo_status = {"erro": "status armazenado invalido"}

    online = False
    if agente.ultimo_contato_em:
        online = normalizar_utc(agente.ultimo_contato_em) >= (
            agora_utc() - timedelta(minutes=2)
        )

    return {
        "id": agente.id,
        "codigo": agente.codigo,
        "nome": agente.nome,
        "ativo": agente.ativo,
        "online": online,
        "ultimo_contato_em": agente.ultimo_contato_em,
        "ultima_versao_config": agente.ultima_versao_config,
        "ultimo_status": ultimo_status,
    }


def criar_router_sistemico(
    exigir_gerencia,
    exigir_agente,
    publicar_atual,
) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/monitoramento/agentes")
    def listar_agentes(
        db=Depends(get_db),
        _admin=Depends(exigir_gerencia),
    ):
        agentes = db.query(models.MonitorAgente).order_by(
            models.MonitorAgente.codigo
        ).all()
        return [_serializar_agente(agente) for agente in agentes]

    @router.post("/admin/monitoramento/agentes", status_code=201)
    def criar_agente(
        dados: AgenteCreate,
        db=Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        if db.query(models.MonitorAgente).filter_by(codigo=dados.codigo).first():
            raise HTTPException(409, "codigo de agente ja cadastrado")

        token = gerar_token_agente()
        agora = agora_utc()
        agente = models.MonitorAgente(
            codigo=dados.codigo,
            nome=dados.nome.strip(),
            token_hash=hash_token(token),
            ativo=True,
            criado_em=agora,
            token_rotacionado_em=agora,
        )
        db.add(agente)
        db.flush()
        registrar_auditoria(
            db,
            ator=admin,
            acao="CRIAR_AGENTE",
            entidade_tipo="MONITOR_AGENTE",
            entidade_id=agente.id,
            depois={"codigo": agente.codigo, "nome": agente.nome},
        )
        db.commit()
        return {
            **_serializar_agente(agente),
            "token": token,
            "aviso": "O token e exibido somente nesta resposta.",
        }

    @router.post("/admin/monitoramento/agentes/{agente_id}/rotacionar-token")
    def rotacionar_token(
        agente_id: int,
        db=Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        agente = db.get(models.MonitorAgente, agente_id)
        if not agente:
            raise HTTPException(404, "agente nao encontrado")
        token = gerar_token_agente()
        agente.token_hash = hash_token(token)
        agente.token_rotacionado_em = agora_utc()
        registrar_auditoria(
            db,
            ator=admin,
            acao="ROTACIONAR_TOKEN",
            entidade_tipo="MONITOR_AGENTE",
            entidade_id=agente.id,
            depois={"codigo": agente.codigo},
        )
        db.commit()
        return {
            "id": agente.id,
            "codigo": agente.codigo,
            "token": token,
            "aviso": "O token anterior deixou de funcionar.",
        }

    @router.patch("/admin/monitoramento/agentes/{agente_id}/ativo")
    def alterar_agente_ativo(
        agente_id: int,
        dados: AgenteAtivoUpdate,
        db=Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        agente = db.get(models.MonitorAgente, agente_id)
        if not agente:
            raise HTTPException(404, "agente nao encontrado")
        anterior = agente.ativo
        agente.ativo = dados.ativo
        registrar_auditoria(
            db,
            ator=admin,
            acao="ALTERAR_AGENTE",
            entidade_tipo="MONITOR_AGENTE",
            entidade_id=agente.id,
            antes={"ativo": anterior},
            depois={"ativo": agente.ativo},
        )
        db.commit()
        return _serializar_agente(agente)

    @router.get("/admin/monitoramento/manutencoes")
    def listar_manutencoes(
        incluir_canceladas: bool = False,
        db=Depends(get_db),
        _admin=Depends(exigir_gerencia),
    ):
        query = db.query(models.MonitorJanelaManutencao)
        if not incluir_canceladas:
            query = query.filter(
                models.MonitorJanelaManutencao.cancelada_em.is_(None)
            )
        return [
            serializar_janela(janela)
            for janela in query.order_by(
                models.MonitorJanelaManutencao.inicio.desc()
            ).limit(100).all()
        ]

    @router.post("/admin/monitoramento/manutencoes", status_code=201)
    def criar_manutencao(
        dados: JanelaCreate,
        db=Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        campos = {
            "monitor_cliente_id": None,
            "unidade_id": None,
            "dispositivo_id": None,
            "link_id": None,
        }
        modelos = {
            "CLIENTE": (models.MonitorCliente, "monitor_cliente_id"),
            "UNIDADE": (models.MonitorUnidade, "unidade_id"),
            "DISPOSITIVO": (models.MonitorDispositivo, "dispositivo_id"),
            "LINK": (models.MonitorLink, "link_id"),
        }
        modelo, campo = modelos[dados.escopo_tipo]
        if not db.get(modelo, dados.escopo_id):
            raise HTTPException(404, "escopo de manutencao nao encontrado")
        campos[campo] = dados.escopo_id

        janela = models.MonitorJanelaManutencao(
            **campos,
            inicio=normalizar_utc(dados.inicio),
            fim=normalizar_utc(dados.fim),
            motivo=dados.motivo.strip(),
            criado_por_admin_id=admin.id,
            criado_em=agora_utc(),
        )
        db.add(janela)
        db.flush()
        publicar_atual(
            db,
            admin.id,
            f"Janela de manutencao #{janela.id} criada",
        )
        registrar_auditoria(
            db,
            ator=admin,
            acao="CRIAR_MANUTENCAO",
            entidade_tipo="MONITOR_JANELA",
            entidade_id=janela.id,
            depois={
                "escopo_tipo": dados.escopo_tipo,
                "escopo_id": dados.escopo_id,
                "inicio": dados.inicio,
                "fim": dados.fim,
                "motivo": dados.motivo,
            },
        )
        db.commit()
        return serializar_janela(janela)

    @router.post("/admin/monitoramento/manutencoes/{janela_id}/cancelar")
    def cancelar_manutencao(
        janela_id: int,
        db=Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        janela = db.get(models.MonitorJanelaManutencao, janela_id)
        if not janela:
            raise HTTPException(404, "janela nao encontrada")
        if janela.cancelada_em is None:
            janela.cancelada_em = agora_utc()
            publicar_atual(
                db,
                admin.id,
                f"Janela de manutencao #{janela.id} cancelada",
            )
            registrar_auditoria(
                db,
                ator=admin,
                acao="CANCELAR_MANUTENCAO",
                entidade_tipo="MONITOR_JANELA",
                entidade_id=janela.id,
            )
            db.commit()
        return serializar_janela(janela)

    @router.get("/admin/monitoramento/configuracoes")
    def listar_configuracoes(
        db=Depends(get_db),
        _admin=Depends(exigir_gerencia),
    ):
        versoes = db.query(models.MonitorConfiguracaoVersao).order_by(
            models.MonitorConfiguracaoVersao.id.desc()
        ).limit(50).all()
        return [{
            "id": item.id,
            "versao": item.versao,
            "ativa": item.ativa,
            "motivo": item.motivo,
            "criada_em": item.criada_em,
            "criada_por_admin_id": item.criada_por_admin_id,
        } for item in versoes]

    @router.post("/admin/monitoramento/configuracoes/{versao_id}/rollback")
    def rollback_configuracao(
        versao_id: int,
        db=Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        alvo = db.get(models.MonitorConfiguracaoVersao, versao_id)
        if not alvo:
            raise HTTPException(404, "versao nao encontrada")
        anterior = db.query(models.MonitorConfiguracaoVersao).filter_by(
            ativa=True
        ).first()
        db.query(models.MonitorConfiguracaoVersao).filter_by(
            ativa=True
        ).update({"ativa": False})
        alvo.ativa = True
        registrar_auditoria(
            db,
            ator=admin,
            acao="ROLLBACK_CONFIGURACAO",
            entidade_tipo="MONITOR_CONFIGURACAO",
            entidade_id=alvo.id,
            antes={"versao": anterior.versao if anterior else None},
            depois={"versao": alvo.versao},
        )
        db.commit()
        return {"id": alvo.id, "versao": alvo.versao, "ativa": True}

    @router.post("/integracoes/aven-monitor/heartbeat")
    def receber_heartbeat(
        dados: HeartbeatCreate,
        db=Depends(get_db),
        agente=Depends(exigir_agente),
    ):
        if agente is None:
            raise HTTPException(
                409,
                "heartbeat exige credencial individual de agente",
            )
        registrar_heartbeat_amostrado(
            db,
            agente,
            dados.status,
            dados.versao_config,
        )
        db.commit()
        return {"status": "ok", "recebido_em": agora_utc()}

    @router.get("/admin/monitoramento/saude")
    def saude_operacional(
        db=Depends(get_db),
        _admin=Depends(exigir_gerencia),
    ):
        agentes = db.query(models.MonitorAgente).order_by(
            models.MonitorAgente.codigo
        ).all()
        return {
            "gerado_em": agora_utc(),
            "agentes": [_serializar_agente(agente) for agente in agentes],
            "resumo": {
                "total": len(agentes),
                "ativos": sum(1 for agente in agentes if agente.ativo),
                "online": sum(
                    1 for agente in agentes
                    if _serializar_agente(agente)["online"]
                ),
            },
        }

    @router.get("/admin/auditoria")
    def listar_auditoria(
        entidade_tipo: Optional[str] = None,
        limite: int = Query(default=100, ge=1, le=500),
        db=Depends(get_db),
        _admin=Depends(exigir_gerencia),
    ):
        query = db.query(models.AuditoriaEvento)
        if entidade_tipo:
            query = query.filter_by(entidade_tipo=entidade_tipo.upper())
        eventos = query.order_by(
            models.AuditoriaEvento.criado_em.desc()
        ).limit(limite).all()
        return [{
            "id": evento.id,
            "ator_tipo": evento.ator_tipo,
            "ator_id": evento.ator_id,
            "ator_codigo": evento.ator_codigo,
            "acao": evento.acao,
            "entidade_tipo": evento.entidade_tipo,
            "entidade_id": evento.entidade_id,
            "antes": json.loads(evento.antes) if evento.antes else None,
            "depois": json.loads(evento.depois) if evento.depois else None,
            "criado_em": evento.criado_em,
        } for evento in eventos]

    return router
