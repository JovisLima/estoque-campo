import os
from dataclasses import dataclass
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parent

PLACEHOLDERS = {
    "admin123",
    "aven-local-development-change-in-vps",
    "coloque_uma_chave_jwt_forte_aqui",
    "coloque_um_token_exclusivo_do_monitor_aqui",
    "troque-esta-senha-por-algo-forte-e-unico",
}


def _valor_booleano(nome: str, padrao: bool) -> bool:
    bruto = os.getenv(nome)
    if bruto is None:
        return padrao

    normalizado = bruto.strip().lower()
    if normalizado in {"1", "true", "sim", "yes"}:
        return True
    if normalizado in {"0", "false", "nao", "não", "no"}:
        return False

    raise RuntimeError(f"{nome} deve ser true ou false")


def _lista_ambiente(nome: str, padrao: str) -> tuple[str, ...]:
    valores = tuple(
        item.strip()
        for item in os.getenv(nome, padrao).split(",")
        if item.strip()
    )
    if not valores:
        raise RuntimeError(f"{nome} nao pode ficar vazio")
    return valores


def _validar_segredo(nome: str, valor: str, tamanho_minimo: int = 32) -> None:
    if len(valor) < tamanho_minimo:
        raise RuntimeError(
            f"{nome} deve possuir ao menos {tamanho_minimo} caracteres em producao"
        )
    if valor.strip().lower() in PLACEHOLDERS:
        raise RuntimeError(f"{nome} ainda usa um valor padrao ou placeholder")


@dataclass(frozen=True)
class Settings:
    ambiente: str
    database_url: str
    jwt_secret_key: str
    jwt_expire_hours: int
    aven_monitor_api_token: str | None
    allow_legacy_monitor_token: bool
    monitor_correlation_window_seconds: int
    cors_allowed_origins: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    data_dir: Path
    auto_create_schema: bool
    enable_api_docs: bool
    object_storage_backend: str
    s3_bucket: str | None
    s3_prefix: str
    s3_endpoint_url: str | None
    s3_region: str | None
    max_upload_bytes: int

    @property
    def producao(self) -> bool:
        return self.ambiente == "production"


def carregar_settings() -> Settings:
    ambiente = os.getenv("APP_ENV", "development").strip().lower()
    if ambiente not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV deve ser development, test ou production")

    database_url = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(CODE_DIR / 'estoque_campo.db').as_posix()}",
    ).strip()
    jwt_secret_key = os.getenv(
        "JWT_SECRET_KEY",
        "aven-local-development-change-in-vps",
    ).strip()
    monitor_token = os.getenv("AVEN_MONITOR_API_TOKEN")
    monitor_token = monitor_token.strip() if monitor_token else None
    allow_legacy_monitor_token = _valor_booleano(
        "AVEN_ALLOW_LEGACY_MONITOR_TOKEN",
        ambiente != "production",
    )

    try:
        correlation_window = int(os.getenv(
            "MONITOR_CORRELATION_WINDOW_SECONDS",
            "120",
        ))
    except ValueError as erro:
        raise RuntimeError(
            "MONITOR_CORRELATION_WINDOW_SECONDS deve ser inteiro"
        ) from erro
    if not 30 <= correlation_window <= 900:
        raise RuntimeError(
            "MONITOR_CORRELATION_WINDOW_SECONDS deve ficar entre 30 e 900"
        )

    object_storage_backend = os.getenv(
        "OBJECT_STORAGE_BACKEND",
        "local",
    ).strip().lower()
    if object_storage_backend not in {"local", "s3"}:
        raise RuntimeError("OBJECT_STORAGE_BACKEND deve ser local ou s3")
    s3_bucket = os.getenv("S3_BUCKET")
    s3_bucket = s3_bucket.strip() if s3_bucket else None
    s3_prefix = os.getenv("S3_PREFIX", "estoque-campo").strip().strip("/")
    s3_endpoint_url = os.getenv("S3_ENDPOINT_URL") or None
    s3_region = os.getenv("S3_REGION") or None
    if object_storage_backend == "s3" and not s3_bucket:
        raise RuntimeError("S3_BUCKET e obrigatorio quando o backend e s3")

    try:
        max_upload_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    except ValueError as erro:
        raise RuntimeError("MAX_UPLOAD_BYTES deve ser inteiro") from erro
    if not 1024 * 1024 <= max_upload_bytes <= 50 * 1024 * 1024:
        raise RuntimeError("MAX_UPLOAD_BYTES deve ficar entre 1 MiB e 50 MiB")

    try:
        jwt_expire_hours = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
    except ValueError as erro:
        raise RuntimeError("JWT_EXPIRE_HOURS deve ser inteiro") from erro
    if not 1 <= jwt_expire_hours <= 168:
        raise RuntimeError("JWT_EXPIRE_HOURS deve ficar entre 1 e 168")

    if ambiente == "production":
        cors_origins = _lista_ambiente("CORS_ALLOWED_ORIGINS", "")
        allowed_hosts = _lista_ambiente("ALLOWED_HOSTS", "")
        data_dir = Path(os.getenv("APP_DATA_DIR", "/var/lib/estoque-campo"))
        auto_create_schema = False
        enable_api_docs = _valor_booleano("ENABLE_API_DOCS", False)

        if not database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
            raise RuntimeError("DATABASE_URL deve apontar para PostgreSQL em producao")
        if "senha_forte_aqui" in database_url.lower():
            raise RuntimeError("DATABASE_URL ainda usa a senha de exemplo")
        _validar_segredo("JWT_SECRET_KEY", jwt_secret_key)
        if allow_legacy_monitor_token:
            if not monitor_token:
                raise RuntimeError(
                    "AVEN_MONITOR_API_TOKEN e obrigatorio enquanto o modo legado estiver ativo"
                )
            _validar_segredo("AVEN_MONITOR_API_TOKEN", monitor_token)
        elif monitor_token:
            _validar_segredo("AVEN_MONITOR_API_TOKEN", monitor_token)
        if "*" in cors_origins:
            raise RuntimeError("CORS_ALLOWED_ORIGINS nao pode usar * em producao")
        if "*" in allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS nao pode usar * em producao")
        if any("suaempresa.com.br" in origem.lower() for origem in cors_origins):
            raise RuntimeError("CORS_ALLOWED_ORIGINS ainda usa o dominio de exemplo")
        if any("suaempresa.com.br" in host.lower() for host in allowed_hosts):
            raise RuntimeError("ALLOWED_HOSTS ainda usa o dominio de exemplo")
        if not data_dir.is_absolute():
            raise RuntimeError("APP_DATA_DIR deve ser um caminho absoluto")
    else:
        cors_origins = _lista_ambiente("CORS_ALLOWED_ORIGINS", "*")
        allowed_hosts = _lista_ambiente("ALLOWED_HOSTS", "*")
        data_dir = Path(os.getenv("APP_DATA_DIR", str(CODE_DIR)))
        auto_create_schema = _valor_booleano("AUTO_CREATE_SCHEMA", True)
        enable_api_docs = _valor_booleano("ENABLE_API_DOCS", True)

    return Settings(
        ambiente=ambiente,
        database_url=database_url,
        jwt_secret_key=jwt_secret_key,
        jwt_expire_hours=jwt_expire_hours,
        aven_monitor_api_token=monitor_token,
        allow_legacy_monitor_token=allow_legacy_monitor_token,
        monitor_correlation_window_seconds=correlation_window,
        cors_allowed_origins=cors_origins,
        allowed_hosts=allowed_hosts,
        data_dir=data_dir,
        auto_create_schema=auto_create_schema,
        enable_api_docs=enable_api_docs,
        object_storage_backend=object_storage_backend,
        s3_bucket=s3_bucket,
        s3_prefix=s3_prefix,
        s3_endpoint_url=s3_endpoint_url,
        s3_region=s3_region,
        max_upload_bytes=max_upload_bytes,
    )


settings = carregar_settings()


def validar_senha_bootstrap(valor: str) -> str:
    senha = valor.strip()
    tamanho = 12 if not settings.producao else 16
    _validar_segredo("ADMIN_SENHA", senha, tamanho_minimo=tamanho)
    return senha
