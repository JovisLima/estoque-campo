#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

: "${DATABASE_URL:?DATABASE_URL nao definida}"
: "${APP_DATA_DIR:?APP_DATA_DIR nao definido}"
: "${BACKUP_ROOT:?BACKUP_ROOT nao definido}"

if [[ ! -d "$APP_DATA_DIR" ]]; then
  echo "Diretorio de dados nao encontrado: $APP_DATA_DIR" >&2
  exit 1
fi

mkdir -p "$BACKUP_ROOT"
timestamp=$(date --utc +%Y%m%dT%H%M%SZ)
destino="$BACKUP_ROOT/$timestamp"

if [[ -e "$destino" ]]; then
  echo "Backup ja existe: $destino" >&2
  exit 1
fi

temporario=$(mktemp -d "$BACKUP_ROOT/.${timestamp}.XXXXXX")
limpar_temporario() {
  if [[ -n "${temporario:-}" && -d "$temporario" ]]; then
    rm -rf -- "$temporario"
  fi
}
trap limpar_temporario EXIT

PGDATABASE="$DATABASE_URL"
if [[ "$PGDATABASE" == postgresql+psycopg2://* ]]; then
  PGDATABASE="postgresql://${PGDATABASE#postgresql+psycopg2://}"
fi
export PGDATABASE

pg_dump --format=custom --no-owner --file="$temporario/database.dump"
tar --create --gzip --one-file-system \
  --file="$temporario/arquivos.tar.gz" \
  --directory="$APP_DATA_DIR" .

(
  cd "$temporario"
  sha256sum database.dump arquivos.tar.gz > SHA256SUMS
)

mv -- "$temporario" "$destino"
temporario=""
echo "Backup concluido: $destino"
