import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient


RAIZ = Path(__file__).resolve().parents[1]
TEMPORARIO = tempfile.TemporaryDirectory(dir=RAIZ)
BANCO = Path(TEMPORARIO.name) / "monitoramento.db"

os.environ["DATABASE_URL"] = f"sqlite:///{BANCO.as_posix()}"
os.environ["AVEN_MONITOR_API_TOKEN"] = "token-monitor-teste"
os.environ["JWT_SECRET_KEY"] = "jwt-teste-com-tamanho-suficiente"
sys.path.insert(0, str(RAIZ / "backend"))

import main
import models
from database import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    admin = models.AdminUsuario(
        nome="Gerencia Teste",
        login="gerencia",
        senha_hash=bcrypt.hashpw(
            b"senha-segura",
            bcrypt.gensalt(),
        ).decode(),
        papel=models.PapelAdmin.gerencia,
        ativo=True,
    )
    cliente = models.Cliente(
        nome="Usina Santa Cruz",
        endereco="Americo Brasiliense - SP",
    )
    db.add_all([admin, cliente])
    db.commit()
    db.close()

    yield


@pytest.fixture
def cliente_http():
    return TestClient(main.app)


def autenticar_gerencia(cliente_http):
    resposta = cliente_http.post(
        "/admin/login",
        json={
            "login": "gerencia",
            "senha": "senha-segura",
        },
    )
    assert resposta.status_code == 200
    return {
        "Authorization": f"Bearer {resposta.json()['access_token']}"
    }


def cadastrar_topologia(cliente_http, headers):
    resposta = cliente_http.post(
        "/admin/monitoramento/topologias",
        headers=headers,
        json={
            "cliente_id": 1,
            "cliente_codigo": "GRUPO-SANTA-CRUZ",
            "unidade_codigo": "USINA-SANTA-CRUZ",
            "unidade_nome": "Usina Santa Cruz",
            "cidade": "Americo Brasiliense",
            "estado": "SP",
            "dispositivo_codigo": "RB-SANTA-CRUZ-01",
            "dispositivo_nome": "MikroTik principal",
            "fabricante": "MikroTik",
            "ip_wireguard": "10.90.0.10",
            "ativo": False,
            "links": [
                {
                    "codigo": "WAN-VIVO",
                    "nome": "LINK VIVO",
                    "if_index": 2,
                    "operadora": "VIVO",
                    "papel": "PRIMARIO",
                },
                {
                    "codigo": "WAN-ALGAR",
                    "nome": "LINK ALGAR",
                    "if_index": 3,
                    "operadora": "ALGAR",
                    "papel": "BACKUP",
                },
            ],
        },
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_api_nao_permite_cadastro_ja_ativo(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    resposta = cliente_http.post(
        "/admin/monitoramento/topologias",
        headers=headers,
        json={
            "cliente_id": 1,
            "cliente_codigo": "GRUPO-SANTA-CRUZ",
            "unidade_codigo": "USINA-SANTA-CRUZ",
            "unidade_nome": "Usina Santa Cruz",
            "cidade": "Americo Brasiliense",
            "estado": "SP",
            "dispositivo_codigo": "RB-SANTA-CRUZ-01",
            "dispositivo_nome": "MikroTik principal",
            "fabricante": "MikroTik",
            "ip_wireguard": "10.90.0.10",
            "ativo": True,
            "links": [
                {
                    "codigo": "WAN-VIVO",
                    "nome": "LINK VIVO",
                    "if_index": 2,
                    "operadora": "VIVO",
                    "papel": "PRIMARIO",
                }
            ],
        },
    )

    assert resposta.status_code == 409
    assert "cadastrado inativo" in resposta.json()["detail"]


def executar_teste_com_sucesso(cliente_http, headers, dispositivo_id):
    solicitado = cliente_http.post(
        f"/admin/monitoramento/dispositivos/{dispositivo_id}/testes",
        headers=headers,
    )
    assert solicitado.status_code == 202

    headers_monitor = {
        "Authorization": "Bearer token-monitor-teste"
    }
    pendentes = cliente_http.get(
        "/integracoes/aven-monitor/testes/pendentes",
        headers=headers_monitor,
    )
    assert pendentes.status_code == 200
    teste = pendentes.json()[0]
    assert teste["configuracao"]["codigo"] == "RB-SANTA-CRUZ-01"

    resultado = cliente_http.post(
        f"/integracoes/aven-monitor/testes/{teste['id']}/resultado",
        headers=headers_monitor,
        json={
            "sucesso": True,
            "resultado": {
                "snmp": True,
                "mensagem": "WireGuard/SNMP acessiveis",
            },
        },
    )
    assert resultado.status_code == 200


def test_cadastro_so_entra_na_configuracao_depois_de_ativado(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    dispositivo = cadastrar_topologia(cliente_http, headers)

    assert dispositivo["ativo"] is False
    assert dispositivo["community_chave"] == "SNMP_COMMUNITY_RB_SANTA_CRUZ_01"

    resposta = cliente_http.get(
        "/integracoes/aven-monitor/configuracao",
        headers={"Authorization": "Bearer token-monitor-teste"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["dispositivos"] == {}

    ativacao_sem_teste = cliente_http.patch(
        f"/admin/monitoramento/dispositivos/{dispositivo['id']}/ativo",
        headers=headers,
        json={"ativo": True},
    )
    assert ativacao_sem_teste.status_code == 409

    executar_teste_com_sucesso(
        cliente_http,
        headers,
        dispositivo["id"],
    )

    resposta = cliente_http.patch(
        f"/admin/monitoramento/dispositivos/{dispositivo['id']}/ativo",
        headers=headers,
        json={"ativo": True},
    )
    assert resposta.status_code == 200

    configuracao = cliente_http.get(
        "/integracoes/aven-monitor/configuracao",
        headers={"Authorization": "Bearer token-monitor-teste"},
    ).json()

    rb = configuracao["dispositivos"]["RB-SANTA-CRUZ-01"]
    assert rb["cliente_codigo"] == "GRUPO-SANTA-CRUZ"
    assert rb["unidade_codigo"] == "USINA-SANTA-CRUZ"
    assert rb["links"]["LINK VIVO"]["codigo"] == "WAN-VIVO"


def test_incidente_monitor_vincula_cliente_e_mantem_idempotencia(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    dispositivo = cadastrar_topologia(cliente_http, headers)
    executar_teste_com_sucesso(
        cliente_http,
        headers,
        dispositivo["id"],
    )
    cliente_http.patch(
        f"/admin/monitoramento/dispositivos/{dispositivo['id']}/ativo",
        headers=headers,
        json={"ativo": True},
    )

    incidente = {
        "tipo": "LINK",
        "dispositivo_id": "RB-SANTA-CRUZ-01",
        "cliente_codigo": "GRUPO-SANTA-CRUZ",
        "unidade_codigo": "USINA-SANTA-CRUZ",
        "dispositivo_codigo": "RB-SANTA-CRUZ-01",
        "link_codigo": "WAN-VIVO",
        "codigo": "RB-SANTA-CRUZ-01",
        "local": "Usina Santa Cruz",
        "cidade": "Americo Brasiliense",
        "fabricante": "MikroTik",
        "link": "LINK VIVO",
        "operadora": "VIVO",
        "papel": "PRIMARIO",
        "inicio": datetime(2026, 8, 15, 8, 0, 0).isoformat(),
    }
    headers_monitor = {
        "Authorization": "Bearer token-monitor-teste"
    }

    primeira = cliente_http.post(
        "/integracoes/aven-monitor/incidentes",
        headers=headers_monitor,
        json=incidente,
    )
    segunda = cliente_http.post(
        "/integracoes/aven-monitor/incidentes",
        headers=headers_monitor,
        json=incidente,
    )

    assert primeira.status_code == 200, primeira.text
    assert segunda.status_code == 200, segunda.text
    assert primeira.json()["id"] == segunda.json()["id"]
    assert primeira.json()["cliente_id"] == 1

    db = SessionLocal()
    try:
        ocorrencia = db.query(models.MonitorOcorrencia).one()
        assert ocorrencia.ordem_id == primeira.json()["id"]
        assert ocorrencia.dispositivo.codigo == "RB-SANTA-CRUZ-01"
        assert ocorrencia.link.codigo == "WAN-VIVO"
    finally:
        db.close()


def test_contrato_legado_de_incidente_continua_aceito(cliente_http):
    resposta = cliente_http.post(
        "/integracoes/aven-monitor/incidentes",
        headers={"Authorization": "Bearer token-monitor-teste"},
        json={
            "tipo": "LINK",
            "dispositivo_id": "USINA-TESTE",
            "codigo": "USINA-TESTE",
            "local": "Usina Teste",
            "cidade": "LAB",
            "fabricante": "MikroTik",
            "link": "WAN-VIVO",
            "operadora": "VIVO",
            "papel": "PRIMARIO",
            "inicio": datetime(2026, 8, 15, 9, 0, 0).isoformat(),
        },
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["cliente_id"] is None

    db = SessionLocal()
    try:
        assert db.query(models.MonitorOcorrencia).count() == 0
    finally:
        db.close()
