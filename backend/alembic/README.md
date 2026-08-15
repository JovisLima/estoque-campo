# Migracoes do banco

O schema de producao e alterado somente por revisoes Alembic versionadas.

```bash
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
alembic -c alembic.ini check
```

Em banco antigo criado por `create_all`, nao execute `stamp` sem comparar o
schema e criar um backup. O primeiro deploy da VPS usara banco PostgreSQL vazio.
