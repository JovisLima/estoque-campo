import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient


RAIZ = Path(__file__).resolve().parents[1]
TEMPORARIO = Path(tempfile.mkdtemp(
    prefix="estoque-campo-tests-",
    dir=RAIZ.parent,
))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "test"
os.environ["AVEN_MONITOR_API_TOKEN"] = "token-monitor-teste"
os.environ["JWT_SECRET_KEY"] = "jwt-teste-com-tamanho-suficiente"
os.environ["APP_DATA_DIR"] = str(TEMPORARIO / "data")
sys.path.insert(0, str(RAIZ / "backend"))

import main
import models
from database import Base, SessionLocal, engine
from storage import armazenamento, normalizar_chave


@pytest.fixture(autouse=True)
def banco_limpo():
    # Evita DDL entre testes enquanto o TestClient usa o pool em outra thread.
    # O schema e criado uma vez pela fixture de sessao; cada caso limpa apenas
    # os dados, preservando as tabelas e tornando a suite deterministica.
    with engine.begin() as conexao:
        for tabela in reversed(Base.metadata.sorted_tables):
            conexao.execute(tabela.delete())

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


@pytest.fixture(scope="session", autouse=True)
def preparar_banco_temporario():
    engine.dispose()
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    shutil.rmtree(TEMPORARIO, ignore_errors=True)


@pytest.fixture
def cliente_http():
    with TestClient(main.app) as cliente:
        yield cliente


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
                    "probe_tipo": "ICMP",
                    "probe_host": "1.1.1.1",
                },
                {
                    "codigo": "WAN-ALGAR",
                    "nome": "LINK ALGAR",
                    "if_index": 3,
                    "operadora": "ALGAR",
                    "papel": "BACKUP",
                    "probe_tipo": "TCP",
                    "probe_host": "8.8.8.8",
                    "probe_porta": 53,
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
                    "probe_tipo": "ICMP",
                    "probe_host": "1.1.1.1",
                }
            ],
        },
    )

    assert resposta.status_code == 409
    assert "cadastrado inativo" in resposta.json()["detail"]


def test_endpoints_de_saude(cliente_http):
    live = cliente_http.get("/health/live")
    ready = cliente_http.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "live"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}

    versionado = cliente_http.get("/api/v1/health/ready")
    assert versionado.status_code == 200
    assert versionado.headers["x-api-version"] == "v1"


def test_armazenamento_local_bloqueia_traversal_e_preserva_chave():
    chave = armazenamento.salvar_bytes(
        "fotos_os/teste.bin",
        b"conteudo",
        "application/octet-stream",
    )
    assert chave == "fotos_os/teste.bin"
    assert armazenamento.existe(chave)
    with pytest.raises(ValueError):
        normalizar_chave("fotos_os/../segredo")


def test_nao_permite_remover_a_ultima_gerencia(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    desativar = cliente_http.post(
        "/admin/usuarios/1/ativo",
        headers=headers,
        json={"ativo": False},
    )
    rebaixar = cliente_http.post(
        "/admin/usuarios/1/papel",
        headers=headers,
        json={"papel": "almoxarifado"},
    )
    assert desativar.status_code == 409
    assert rebaixar.status_code == 409


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


def test_credencial_individual_heartbeat_e_rotacao(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    criado = cliente_http.post(
        "/admin/monitoramento/agentes",
        headers=headers,
        json={"codigo": "AGENTE-VPS-1", "nome": "VPS principal"},
    )
    assert criado.status_code == 201, criado.text
    agente = criado.json()
    token_inicial = agente["token"]

    listagem = cliente_http.get(
        "/admin/monitoramento/agentes",
        headers=headers,
    ).json()
    assert listagem[0]["codigo"] == "AGENTE-VPS-1"
    assert "token" not in listagem[0]

    headers_agente = {
        "Authorization": f"Bearer {token_inicial}",
        "X-AVEN-Agent": "AGENTE-VPS-1",
    }
    heartbeat = cliente_http.post(
        "/api/v1/integracoes/aven-monitor/heartbeat",
        headers=headers_agente,
        json={
            "versao_config": "abc123",
            "status": {"dispositivos_configurados": 1},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text

    saude = cliente_http.get(
        "/admin/monitoramento/saude",
        headers=headers,
    ).json()
    assert saude["resumo"]["online"] == 1
    assert saude["agentes"][0]["ultima_versao_config"] == "abc123"

    rotacao = cliente_http.post(
        f"/admin/monitoramento/agentes/{agente['id']}/rotacionar-token",
        headers=headers,
    )
    assert rotacao.status_code == 200
    token_novo = rotacao.json()["token"]
    assert token_novo != token_inicial

    antigo = cliente_http.get(
        "/api/v1/integracoes/aven-monitor/configuracao",
        headers=headers_agente,
    )
    assert antigo.status_code == 401
    novo = cliente_http.get(
        "/api/v1/integracoes/aven-monitor/configuracao",
        headers={
            "Authorization": f"Bearer {token_novo}",
            "X-AVEN-Agent": "AGENTE-VPS-1",
        },
    )
    assert novo.status_code == 200


def _ativar_topologia(cliente_http, headers):
    dispositivo = cadastrar_topologia(cliente_http, headers)
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
    assert resposta.status_code == 200, resposta.text
    return dispositivo


def _incidente_link(codigo_link, nome_link, inicio):
    return {
        "tipo": "LINK",
        "dispositivo_id": "RB-SANTA-CRUZ-01",
        "cliente_codigo": "GRUPO-SANTA-CRUZ",
        "unidade_codigo": "USINA-SANTA-CRUZ",
        "dispositivo_codigo": "RB-SANTA-CRUZ-01",
        "link_codigo": codigo_link,
        "codigo": "RB-SANTA-CRUZ-01",
        "local": "Usina Santa Cruz",
        "cidade": "Americo Brasiliense",
        "fabricante": "MikroTik",
        "link": nome_link,
        "operadora": "VIVO" if codigo_link == "WAN-VIVO" else "ALGAR",
        "papel": "PRIMARIO" if codigo_link == "WAN-VIVO" else "BACKUP",
        "inicio": inicio.isoformat(),
    }


def test_manutencao_suprime_incidente_e_entra_na_configuracao(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    _ativar_topologia(cliente_http, headers)
    topologia = cliente_http.get(
        "/admin/monitoramento/topologia",
        headers=headers,
    ).json()
    link_id = topologia[0]["unidades"][0]["dispositivos"][0]["links"][0]["id"]
    agora = datetime.now(timezone.utc)
    janela = cliente_http.post(
        "/admin/monitoramento/manutencoes",
        headers=headers,
        json={
            "escopo_tipo": "LINK",
            "escopo_id": link_id,
            "inicio": (agora - timedelta(minutes=1)).isoformat(),
            "fim": (agora + timedelta(minutes=10)).isoformat(),
            "motivo": "Troca programada do equipamento",
        },
    )
    assert janela.status_code == 201, janela.text

    configuracao = cliente_http.get(
        "/integracoes/aven-monitor/configuracao",
        headers={"Authorization": "Bearer token-monitor-teste"},
    ).json()
    assert configuracao["manutencoes"][0]["link_codigo"] in {
        "WAN-ALGAR",
        "WAN-VIVO",
    }

    link_codigo = configuracao["manutencoes"][0]["link_codigo"]
    nome_link = "LINK VIVO" if link_codigo == "WAN-VIVO" else "LINK ALGAR"
    incidente = cliente_http.post(
        "/integracoes/aven-monitor/incidentes",
        headers={"Authorization": "Bearer token-monitor-teste"},
        json=_incidente_link(link_codigo, nome_link, datetime.now()),
    )
    assert incidente.status_code == 200, incidente.text
    assert incidente.json()["suprimido"] is True

    db = SessionLocal()
    try:
        assert db.query(models.OrdemServico).count() == 0
        assert db.query(models.AuditoriaEvento).filter_by(
            acao="SUPRIMIR_INCIDENTE_MANUTENCAO"
        ).count() == 1
    finally:
        db.close()


def test_correla_duas_wans_em_uma_os(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    _ativar_topologia(cliente_http, headers)
    headers_monitor = {"Authorization": "Bearer token-monitor-teste"}
    inicio = datetime(2026, 8, 15, 12, 0, 0)

    vivo = cliente_http.post(
        "/integracoes/aven-monitor/incidentes",
        headers=headers_monitor,
        json=_incidente_link("WAN-VIVO", "LINK VIVO", inicio),
    )
    algar = cliente_http.post(
        "/integracoes/aven-monitor/incidentes",
        headers=headers_monitor,
        json=_incidente_link(
            "WAN-ALGAR",
            "LINK ALGAR",
            inicio + timedelta(seconds=30),
        ),
    )
    assert vivo.status_code == 200, vivo.text
    assert algar.status_code == 200, algar.text
    assert vivo.json()["id"] == algar.json()["id"]

    db = SessionLocal()
    try:
        ocorrencia = db.query(models.MonitorOcorrencia).one()
        assert ocorrencia.causa_provavel == "INFRAESTRUTURA_COMUM"
        assert len(ocorrencia.eventos) == 2
    finally:
        db.close()


def test_rollback_republica_snapshot_anterior(cliente_http):
    headers = autenticar_gerencia(cliente_http)
    _ativar_topologia(cliente_http, headers)
    versoes = cliente_http.get(
        "/admin/monitoramento/configuracoes",
        headers=headers,
    ).json()
    antiga = min(versoes, key=lambda item: item["id"])
    assert antiga["ativa"] is False

    rollback = cliente_http.post(
        f"/admin/monitoramento/configuracoes/{antiga['id']}/rollback",
        headers=headers,
    )
    assert rollback.status_code == 200
    configuracao = cliente_http.get(
        "/integracoes/aven-monitor/configuracao",
        headers={"Authorization": "Bearer token-monitor-teste"},
    ).json()
    assert configuracao["dispositivos"] == {}
