import ipaddress
import json
import re
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from audit import registrar_auditoria
from database import get_db
from system_services import (
    calcular_versao_configuracao,
    configuracao_publicada,
    janelas_publicaveis,
    publicar_configuracao,
)


CODIGO_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,63}$")


def normalizar_codigo(valor: str, campo: str) -> str:
    codigo = valor.strip().upper()

    if not CODIGO_RE.fullmatch(codigo):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{campo} deve possuir de 2 a 64 caracteres e usar "
                "somente letras, numeros, hifen ou sublinhado"
            ),
        )

    return codigo


def chave_community(dispositivo_codigo: str) -> str:
    normalizado = "".join(
        caractere if caractere.isalnum() else "_"
        for caractere in dispositivo_codigo.upper()
    )
    return f"SNMP_COMMUNITY_{normalizado}"


class MonitorLinkCreate(BaseModel):
    codigo: str
    nome: str = Field(min_length=1, max_length=120)
    if_index: int = Field(gt=0)
    operadora: str = Field(min_length=1, max_length=120)
    papel: str
    probe_tipo: str
    probe_host: str
    probe_porta: Optional[int] = Field(default=None, ge=1, le=65535)
    ativo: bool = True

    @field_validator("papel")
    @classmethod
    def validar_papel(cls, valor: str) -> str:
        papel = valor.strip().upper()
        if papel not in {"PRIMARIO", "BACKUP"}:
            raise ValueError("papel deve ser PRIMARIO ou BACKUP")
        return papel

    @field_validator("probe_tipo")
    @classmethod
    def validar_probe_tipo(cls, valor: str) -> str:
        tipo = valor.strip().upper()
        if tipo not in {"ICMP", "TCP"}:
            raise ValueError("probe_tipo deve ser ICMP ou TCP")
        return tipo

    @field_validator("probe_host")
    @classmethod
    def validar_probe_host(cls, valor: str) -> str:
        try:
            return str(ipaddress.ip_address(valor.strip()))
        except ValueError as erro:
            raise ValueError("probe_host deve ser um endereco IP") from erro

    @model_validator(mode="after")
    def validar_probe_porta(self):
        if self.probe_tipo == "TCP" and self.probe_porta is None:
            raise ValueError("probe_porta e obrigatoria para probe TCP")
        if self.probe_tipo == "ICMP" and self.probe_porta is not None:
            raise ValueError("probe_porta nao se aplica ao probe ICMP")
        return self


class MonitorTopologiaCreate(BaseModel):
    cliente_id: int = Field(gt=0)
    cliente_codigo: str
    unidade_codigo: str
    unidade_nome: str = Field(min_length=1, max_length=160)
    cidade: str = Field(min_length=1, max_length=120)
    estado: Optional[str] = Field(default=None, max_length=2)
    dispositivo_codigo: str
    dispositivo_nome: str = Field(min_length=1, max_length=160)
    fabricante: str = Field(min_length=1, max_length=120)
    ip_wireguard: str
    ativo: bool = False
    links: List[MonitorLinkCreate] = Field(min_length=1)

    @field_validator("estado")
    @classmethod
    def normalizar_estado(cls, valor: Optional[str]) -> Optional[str]:
        return valor.strip().upper() if valor else None

    @field_validator("ip_wireguard")
    @classmethod
    def validar_ip_wireguard(cls, valor: str) -> str:
        try:
            endereco = ipaddress.ip_address(valor.strip())
        except ValueError as erro:
            raise ValueError("ip_wireguard invalido") from erro

        if not endereco.is_private:
            raise ValueError("ip_wireguard deve ser um endereco privado")

        return str(endereco)

    @model_validator(mode="after")
    def validar_links(self):
        codigos = []
        if_indexes = []
        nomes = []

        for link in self.links:
            codigos.append(link.codigo.strip().upper())
            if_indexes.append(link.if_index)
            nomes.append(link.nome.strip().upper())

        if len(codigos) != len(set(codigos)):
            raise ValueError("codigos de link duplicados")
        if len(if_indexes) != len(set(if_indexes)):
            raise ValueError("if_index duplicado no mesmo dispositivo")
        if len(nomes) != len(set(nomes)):
            raise ValueError("nomes de link duplicados")
        probes = [link.probe_host for link in self.links]
        if len(probes) != len(set(probes)):
            raise ValueError("cada WAN deve usar um probe_host diferente")
        if not any(link.papel == "PRIMARIO" for link in self.links):
            raise ValueError("informe ao menos um link PRIMARIO")

        return self


class MonitorAtivoUpdate(BaseModel):
    ativo: bool


class MonitorTesteResultado(BaseModel):
    sucesso: bool
    resultado: dict


def serializar_link(link: models.MonitorLink) -> dict:
    return {
        "id": link.id,
        "codigo": link.codigo,
        "nome": link.nome,
        "if_index": link.if_index,
        "operadora": link.operadora,
        "papel": link.papel,
        "probe_tipo": link.probe_tipo,
        "probe_host": link.probe_host,
        "probe_porta": link.probe_porta,
        "ativo": link.ativo,
    }


def serializar_topologia(db: Session) -> list:
    clientes = db.query(models.MonitorCliente).order_by(
        models.MonitorCliente.codigo
    ).all()

    resultado = []

    for monitor_cliente in clientes:
        unidades = []
        for unidade in sorted(
            monitor_cliente.unidades,
            key=lambda item: item.codigo,
        ):
            dispositivos = []
            for dispositivo in sorted(
                unidade.dispositivos,
                key=lambda item: item.codigo,
            ):
                ultimo_teste = max(
                    dispositivo.testes,
                    key=lambda item: item.solicitado_em,
                    default=None,
                )
                teste_resumo = None

                if ultimo_teste is not None:
                    mensagem = None
                    if ultimo_teste.resultado:
                        try:
                            mensagem = json.loads(
                                ultimo_teste.resultado
                            ).get("mensagem")
                        except (json.JSONDecodeError, AttributeError):
                            mensagem = ultimo_teste.resultado

                    teste_resumo = {
                        "id": ultimo_teste.id,
                        "status": ultimo_teste.status,
                        "sucesso": ultimo_teste.sucesso,
                        "mensagem": mensagem,
                        "finalizado_em": ultimo_teste.finalizado_em,
                    }

                dispositivos.append({
                    "id": dispositivo.id,
                    "codigo": dispositivo.codigo,
                    "nome": dispositivo.nome,
                    "fabricante": dispositivo.fabricante,
                    "ip_wireguard": dispositivo.ip_wireguard,
                    "ativo": dispositivo.ativo,
                    "community_chave": chave_community(dispositivo.codigo),
                    "ultimo_teste": teste_resumo,
                    "links": [
                        serializar_link(link)
                        for link in sorted(
                            dispositivo.links,
                            key=lambda item: item.codigo,
                        )
                    ],
                })

            unidades.append({
                "id": unidade.id,
                "codigo": unidade.codigo,
                "nome": unidade.nome,
                "cidade": unidade.cidade,
                "estado": unidade.estado,
                "ativo": unidade.ativo,
                "dispositivos": dispositivos,
            })

        resultado.append({
            "id": monitor_cliente.id,
            "codigo": monitor_cliente.codigo,
            "ativo": monitor_cliente.ativo,
            "cliente": {
                "id": monitor_cliente.cliente.id,
                "nome": monitor_cliente.cliente.nome,
                "endereco": monitor_cliente.cliente.endereco,
            },
            "unidades": unidades,
        })

    return resultado


def montar_dispositivo_configuracao(
    dispositivo: models.MonitorDispositivo,
) -> Optional[dict]:
    links_ativos = [
        link
        for link in dispositivo.links
        if link.ativo
    ]
    if not links_ativos:
        return None

    unidade = dispositivo.unidade
    monitor_cliente = unidade.monitor_cliente

    return {
        "cliente_codigo": monitor_cliente.codigo,
        "unidade_codigo": unidade.codigo,
        "codigo": dispositivo.codigo,
        "nome": unidade.nome,
        "dispositivo_nome": dispositivo.nome,
        "cidade": unidade.cidade,
        "estado": unidade.estado,
        "fabricante": dispositivo.fabricante,
        "ip": dispositivo.ip_wireguard,
        "community_chave": chave_community(dispositivo.codigo),
        "links": {
            link.nome: {
                "codigo": link.codigo,
                "if_index": link.if_index,
                "operadora": link.operadora,
                "papel": link.papel,
                "probe_tipo": link.probe_tipo,
                "probe_host": link.probe_host,
                "probe_porta": link.probe_porta,
            }
            for link in sorted(
                links_ativos,
                key=lambda item: item.codigo,
            )
        },
    }


def criar_topologia(
    dados: MonitorTopologiaCreate,
    db: Session,
    admin=None,
) -> dict:
    if dados.ativo:
        raise HTTPException(
            409,
            "Todo dispositivo deve ser cadastrado inativo e passar pelo teste antes da ativacao",
        )

    cliente_codigo = normalizar_codigo(
        dados.cliente_codigo,
        "cliente_codigo",
    )
    unidade_codigo = normalizar_codigo(
        dados.unidade_codigo,
        "unidade_codigo",
    )
    dispositivo_codigo = normalizar_codigo(
        dados.dispositivo_codigo,
        "dispositivo_codigo",
    )

    cliente = db.get(models.Cliente, dados.cliente_id)
    if not cliente:
        raise HTTPException(404, "Cliente nao encontrado")

    monitor_cliente = db.query(models.MonitorCliente).filter(
        (models.MonitorCliente.cliente_id == dados.cliente_id)
        | (models.MonitorCliente.codigo == cliente_codigo)
    ).first()

    if monitor_cliente:
        if (
            monitor_cliente.cliente_id != dados.cliente_id
            or monitor_cliente.codigo != cliente_codigo
        ):
            raise HTTPException(
                409,
                "cliente_id ou cliente_codigo ja vinculado a outro cadastro",
            )
    else:
        monitor_cliente = models.MonitorCliente(
            cliente_id=dados.cliente_id,
            codigo=cliente_codigo,
            ativo=True,
        )
        db.add(monitor_cliente)
        db.flush()

    unidade = db.query(models.MonitorUnidade).filter_by(
        codigo=unidade_codigo
    ).first()

    if unidade:
        if unidade.monitor_cliente_id != monitor_cliente.id:
            raise HTTPException(
                409,
                "unidade_codigo ja pertence a outro cliente",
            )
    else:
        unidade = models.MonitorUnidade(
            monitor_cliente_id=monitor_cliente.id,
            codigo=unidade_codigo,
            nome=dados.unidade_nome.strip(),
            cidade=dados.cidade.strip(),
            estado=dados.estado,
            ativo=True,
        )
        db.add(unidade)
        db.flush()

    if db.query(models.MonitorDispositivo).filter(
        (models.MonitorDispositivo.codigo == dispositivo_codigo)
        | (models.MonitorDispositivo.ip_wireguard == dados.ip_wireguard)
    ).first():
        raise HTTPException(
            409,
            "codigo do dispositivo ou IP WireGuard ja cadastrado",
        )

    probes = [item.probe_host for item in dados.links]
    probe_existente = db.query(models.MonitorLink).filter(
        models.MonitorLink.probe_host.in_(probes)
    ).first()
    if probe_existente:
        raise HTTPException(
            409,
            f"probe_host {probe_existente.probe_host} ja pertence a outra WAN",
        )

    dispositivo = models.MonitorDispositivo(
        unidade_id=unidade.id,
        codigo=dispositivo_codigo,
        nome=dados.dispositivo_nome.strip(),
        fabricante=dados.fabricante.strip(),
        ip_wireguard=dados.ip_wireguard,
        ativo=dados.ativo,
    )
    db.add(dispositivo)
    db.flush()

    for item in dados.links:
        db.add(models.MonitorLink(
            dispositivo_id=dispositivo.id,
            codigo=normalizar_codigo(item.codigo, "link.codigo"),
            nome=item.nome.strip(),
            if_index=item.if_index,
            operadora=item.operadora.strip(),
            papel=item.papel,
            probe_tipo=item.probe_tipo,
            probe_host=item.probe_host,
            probe_porta=item.probe_porta,
            ativo=item.ativo,
        ))

    try:
        db.flush()
        publicar_configuracao_atual(
            db,
            admin.id if admin else None,
            f"Topologia {dispositivo.codigo} cadastrada",
        )
        registrar_auditoria(
            db,
            ator=admin,
            acao="CRIAR_TOPOLOGIA",
            entidade_tipo="MONITOR_DISPOSITIVO",
            entidade_id=dispositivo.id,
            depois={
                "codigo": dispositivo.codigo,
                "unidade": unidade.codigo,
                "links": [item.codigo for item in dados.links],
            },
        )
        db.commit()
    except IntegrityError as erro:
        db.rollback()
        raise HTTPException(
            409,
            "topologia conflitante com um cadastro existente",
        ) from erro

    db.refresh(dispositivo)

    return {
        "id": dispositivo.id,
        "codigo": dispositivo.codigo,
        "ativo": dispositivo.ativo,
        "community_chave": chave_community(dispositivo.codigo),
    }


def montar_conteudo_configuracao_atual(db: Session) -> dict:
    dispositivos = db.query(models.MonitorDispositivo).join(
        models.MonitorUnidade
    ).join(models.MonitorCliente).filter(
        models.MonitorDispositivo.ativo.is_(True),
        models.MonitorUnidade.ativo.is_(True),
        models.MonitorCliente.ativo.is_(True),
    ).order_by(models.MonitorDispositivo.codigo).all()

    configuracao = {}

    for dispositivo in dispositivos:
        dados_dispositivo = montar_dispositivo_configuracao(
            dispositivo
        )
        if dados_dispositivo is not None:
            configuracao[dispositivo.codigo] = dados_dispositivo

    return {
        "dispositivos": configuracao,
        "manutencoes": janelas_publicaveis(db),
    }


def publicar_configuracao_atual(
    db: Session,
    admin_id: int | None,
    motivo: str,
):
    # SessionLocal usa autoflush=False; o snapshot precisa enxergar as
    # alteracoes ainda nao commitadas que motivaram a publicacao.
    db.flush()
    return publicar_configuracao(
        db,
        montar_conteudo_configuracao_atual(db),
        admin_id=admin_id,
        motivo=motivo,
    )


def montar_configuracao_monitor(db: Session) -> dict:
    publicada = configuracao_publicada(db)
    if publicada:
        conteudo, registro = publicada
        versao = registro.versao
    else:
        conteudo = montar_conteudo_configuracao_atual(db)
        versao = calcular_versao_configuracao(conteudo)

    return {
        "versao": versao,
        "gerado_em": datetime.utcnow().isoformat(timespec="seconds"),
        **conteudo,
    }


def resolver_origem_incidente(
    db: Session,
    dados,
) -> Optional[dict]:
    codigo = getattr(dados, "dispositivo_codigo", None)
    if not codigo:
        return None

    dispositivo = db.query(models.MonitorDispositivo).filter_by(
        codigo=normalizar_codigo(codigo, "dispositivo_codigo")
    ).first()
    if not dispositivo:
        raise HTTPException(409, "dispositivo monitorado nao encontrado")

    unidade = dispositivo.unidade
    monitor_cliente = unidade.monitor_cliente

    cliente_codigo = getattr(dados, "cliente_codigo", None)
    unidade_codigo = getattr(dados, "unidade_codigo", None)

    if cliente_codigo and monitor_cliente.codigo != normalizar_codigo(
        cliente_codigo,
        "cliente_codigo",
    ):
        raise HTTPException(409, "cliente do incidente nao corresponde ao cadastro")

    if unidade_codigo and unidade.codigo != normalizar_codigo(
        unidade_codigo,
        "unidade_codigo",
    ):
        raise HTTPException(409, "unidade do incidente nao corresponde ao cadastro")

    link = None
    link_codigo = getattr(dados, "link_codigo", None)
    if dados.tipo == "LINK":
        if not link_codigo:
            raise HTTPException(422, "incidente LINK exige link_codigo")
        link = db.query(models.MonitorLink).filter_by(
            dispositivo_id=dispositivo.id,
            codigo=normalizar_codigo(link_codigo, "link_codigo"),
        ).first()
        if not link:
            raise HTTPException(409, "link monitorado nao encontrado")

    return {
        "monitor_cliente": monitor_cliente,
        "unidade": unidade,
        "dispositivo": dispositivo,
        "link": link,
    }


def criar_router_monitoramento(
    exigir_gerencia,
    exigir_monitor,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/admin/monitoramento/topologia",
        dependencies=[Depends(exigir_gerencia)],
    )
    def listar_topologia(db: Session = Depends(get_db)):
        return serializar_topologia(db)

    @router.post(
        "/admin/monitoramento/topologias",
        status_code=201,
        dependencies=[Depends(exigir_gerencia)],
    )
    def cadastrar_topologia(
        dados: MonitorTopologiaCreate,
        db: Session = Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        return criar_topologia(dados, db, admin)

    @router.patch(
        "/admin/monitoramento/dispositivos/{dispositivo_id}/ativo",
        dependencies=[Depends(exigir_gerencia)],
    )
    def alterar_dispositivo_ativo(
        dispositivo_id: int,
        dados: MonitorAtivoUpdate,
        db: Session = Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        dispositivo = db.get(models.MonitorDispositivo, dispositivo_id)
        if not dispositivo:
            raise HTTPException(404, "Dispositivo nao encontrado")

        if dados.ativo and not any(link.ativo for link in dispositivo.links):
            raise HTTPException(
                409,
                "Nao e possivel ativar dispositivo sem link ativo",
            )

        if dados.ativo and any(
            not link.probe_host or not link.probe_tipo
            for link in dispositivo.links
            if link.ativo
        ):
            raise HTTPException(
                409,
                "Todos os links ativos precisam de probe WAN configurado",
            )

        if dados.ativo:
            limite = datetime.utcnow() - timedelta(minutes=30)
            teste_valido = db.query(
                models.MonitorTesteConfiguracao
            ).filter(
                models.MonitorTesteConfiguracao.dispositivo_id
                == dispositivo.id,
                models.MonitorTesteConfiguracao.status == "SUCESSO",
                models.MonitorTesteConfiguracao.sucesso.is_(True),
                models.MonitorTesteConfiguracao.finalizado_em >= limite,
            ).order_by(
                models.MonitorTesteConfiguracao.finalizado_em.desc()
            ).first()

            if not teste_valido:
                raise HTTPException(
                    409,
                    "Execute e aprove um teste de conectividade nos ultimos 30 minutos",
                )

        anterior = dispositivo.ativo
        dispositivo.ativo = dados.ativo
        dispositivo.atualizado_em = datetime.utcnow()
        publicar_configuracao_atual(
            db,
            admin.id,
            f"Dispositivo {dispositivo.codigo} {'ativado' if dados.ativo else 'desativado'}",
        )
        registrar_auditoria(
            db,
            ator=admin,
            acao="ALTERAR_DISPOSITIVO",
            entidade_tipo="MONITOR_DISPOSITIVO",
            entidade_id=dispositivo.id,
            antes={"ativo": anterior},
            depois={"ativo": dispositivo.ativo},
        )
        db.commit()

        return {
            "id": dispositivo.id,
            "codigo": dispositivo.codigo,
            "ativo": dispositivo.ativo,
        }

    @router.patch(
        "/admin/monitoramento/links/{link_id}/ativo",
        dependencies=[Depends(exigir_gerencia)],
    )
    def alterar_link_ativo(
        link_id: int,
        dados: MonitorAtivoUpdate,
        db: Session = Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        link = db.get(models.MonitorLink, link_id)
        if not link:
            raise HTTPException(404, "Link nao encontrado")

        if (
            not dados.ativo
            and link.dispositivo.ativo
            and not any(
                outro.ativo
                for outro in link.dispositivo.links
                if outro.id != link.id
            )
        ):
            raise HTTPException(
                409,
                "Desative o dispositivo antes de desativar o ultimo link",
            )

        anterior = link.ativo
        link.ativo = dados.ativo
        link.atualizado_em = datetime.utcnow()
        publicar_configuracao_atual(
            db,
            admin.id,
            f"Link {link.codigo} {'ativado' if dados.ativo else 'desativado'}",
        )
        registrar_auditoria(
            db,
            ator=admin,
            acao="ALTERAR_LINK",
            entidade_tipo="MONITOR_LINK",
            entidade_id=link.id,
            antes={"ativo": anterior},
            depois={"ativo": link.ativo},
        )
        db.commit()

        return serializar_link(link)

    @router.post(
        "/admin/monitoramento/dispositivos/{dispositivo_id}/testes",
        status_code=202,
        dependencies=[Depends(exigir_gerencia)],
    )
    def solicitar_teste(
        dispositivo_id: int,
        db: Session = Depends(get_db),
        admin=Depends(exigir_gerencia),
    ):
        dispositivo = db.get(models.MonitorDispositivo, dispositivo_id)
        if not dispositivo:
            raise HTTPException(404, "Dispositivo nao encontrado")

        if not any(link.ativo for link in dispositivo.links):
            raise HTTPException(409, "Dispositivo nao possui link ativo")

        existente = db.query(
            models.MonitorTesteConfiguracao
        ).filter(
            models.MonitorTesteConfiguracao.dispositivo_id
            == dispositivo.id,
            models.MonitorTesteConfiguracao.status.in_([
                "PENDENTE",
                "EM_EXECUCAO",
            ]),
        ).order_by(
            models.MonitorTesteConfiguracao.solicitado_em.desc()
        ).first()

        if existente:
            return {
                "id": existente.id,
                "status": existente.status,
            }

        teste = models.MonitorTesteConfiguracao(
            dispositivo_id=dispositivo.id,
            status="PENDENTE",
        )
        db.add(teste)
        db.flush()
        registrar_auditoria(
            db,
            ator=admin,
            acao="SOLICITAR_TESTE",
            entidade_tipo="MONITOR_TESTE",
            entidade_id=teste.id,
            depois={"dispositivo_id": dispositivo.id},
        )
        db.commit()
        db.refresh(teste)

        return {
            "id": teste.id,
            "status": teste.status,
        }

    @router.get(
        "/admin/monitoramento/testes/{teste_id}",
        dependencies=[Depends(exigir_gerencia)],
    )
    def consultar_teste(
        teste_id: int,
        db: Session = Depends(get_db),
    ):
        teste = db.get(models.MonitorTesteConfiguracao, teste_id)
        if not teste:
            raise HTTPException(404, "Teste nao encontrado")

        resultado = None
        if teste.resultado:
            try:
                resultado = json.loads(teste.resultado)
            except json.JSONDecodeError:
                resultado = {"mensagem": teste.resultado}

        return {
            "id": teste.id,
            "dispositivo_id": teste.dispositivo_id,
            "status": teste.status,
            "sucesso": teste.sucesso,
            "resultado": resultado,
            "solicitado_em": teste.solicitado_em,
            "finalizado_em": teste.finalizado_em,
        }

    @router.get(
        "/integracoes/aven-monitor/testes/pendentes",
        dependencies=[Depends(exigir_monitor)],
    )
    def testes_pendentes(db: Session = Depends(get_db)):
        limite_reprocessamento = datetime.utcnow() - timedelta(minutes=2)
        testes = db.query(models.MonitorTesteConfiguracao).filter(
            (
                models.MonitorTesteConfiguracao.status == "PENDENTE"
            )
            | (
                (models.MonitorTesteConfiguracao.status == "EM_EXECUCAO")
                & (
                    models.MonitorTesteConfiguracao.iniciado_em
                    <= limite_reprocessamento
                )
            )
        ).order_by(
            models.MonitorTesteConfiguracao.solicitado_em
        ).limit(5).all()

        resultado = []
        for teste in testes:
            configuracao = montar_dispositivo_configuracao(
                teste.dispositivo
            )
            if configuracao is None:
                teste.status = "ERRO"
                teste.sucesso = False
                teste.resultado = json.dumps({
                    "mensagem": "Dispositivo sem link ativo",
                })
                teste.finalizado_em = datetime.utcnow()
                continue

            teste.status = "EM_EXECUCAO"
            teste.iniciado_em = datetime.utcnow()
            resultado.append({
                "id": teste.id,
                "dispositivo_id": teste.dispositivo.codigo,
                "configuracao": configuracao,
            })

        db.commit()
        return resultado

    @router.post(
        "/integracoes/aven-monitor/testes/{teste_id}/resultado",
        dependencies=[Depends(exigir_monitor)],
    )
    def registrar_resultado_teste(
        teste_id: int,
        dados: MonitorTesteResultado,
        db: Session = Depends(get_db),
    ):
        teste = db.get(models.MonitorTesteConfiguracao, teste_id)
        if not teste:
            raise HTTPException(404, "Teste nao encontrado")

        if teste.status in {"SUCESSO", "ERRO"}:
            return {
                "id": teste.id,
                "status": teste.status,
            }

        teste.sucesso = dados.sucesso
        teste.status = "SUCESSO" if dados.sucesso else "ERRO"
        teste.resultado = json.dumps(
            dados.resultado,
            ensure_ascii=False,
            sort_keys=True,
        )
        teste.finalizado_em = datetime.utcnow()
        db.commit()

        return {
            "id": teste.id,
            "status": teste.status,
        }

    @router.get(
        "/integracoes/aven-monitor/configuracao",
        dependencies=[Depends(exigir_monitor)],
    )
    def configuracao_monitor(db: Session = Depends(get_db)):
        return montar_configuracao_monitor(db)

    return router
