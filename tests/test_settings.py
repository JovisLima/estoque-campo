import os
import subprocess
import sys
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]

VARIAVEIS = {
    "APP_ENV",
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "JWT_EXPIRE_HOURS",
    "AVEN_MONITOR_API_TOKEN",
    "CORS_ALLOWED_ORIGINS",
    "ALLOWED_HOSTS",
    "APP_DATA_DIR",
}


def importar_settings(valores):
    ambiente = {
        chave: valor
        for chave, valor in os.environ.items()
        if chave not in VARIAVEIS
    }
    ambiente.update(valores)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'backend'); import settings; print(settings.settings.ambiente)",
        ],
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
    )


def test_producao_rejeita_segredos_padrao():
    resultado = importar_settings({
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://usuario:senha@localhost/estoque",
        "JWT_SECRET_KEY": "aven-local-development-change-in-vps",
        "AVEN_MONITOR_API_TOKEN": "token-curto",
        "CORS_ALLOWED_ORIGINS": "https://estoque.exemplo.com",
        "ALLOWED_HOSTS": "estoque.exemplo.com",
    })

    assert resultado.returncode != 0
    assert "JWT_SECRET_KEY" in resultado.stderr


def test_producao_aceita_configuracao_explicita():
    resultado = importar_settings({
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://usuario:senha@localhost/estoque",
        "JWT_SECRET_KEY": "j" * 48,
        "AVEN_MONITOR_API_TOKEN": "m" * 48,
        "CORS_ALLOWED_ORIGINS": "https://estoque.exemplo.com,http://localhost,null",
        "ALLOWED_HOSTS": "estoque.exemplo.com",
        "APP_DATA_DIR": "/var/lib/estoque-campo",
    })

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "production"


def test_producao_rejeita_senha_de_banco_do_exemplo():
    resultado = importar_settings({
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://usuario:SENHA_FORTE_AQUI@localhost/estoque",
        "JWT_SECRET_KEY": "j" * 48,
        "AVEN_MONITOR_API_TOKEN": "m" * 48,
        "CORS_ALLOWED_ORIGINS": "https://estoque.exemplo.com",
        "ALLOWED_HOSTS": "estoque.exemplo.com",
    })

    assert resultado.returncode != 0
    assert "DATABASE_URL" in resultado.stderr
