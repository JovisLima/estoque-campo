# Deploy seguro — Estoque de Campo

Este procedimento considera uma VPS KVM com Ubuntu 24.04 LTS, IPv4 dedicado,
DNS apontando para a VPS e o código instalado em `/opt/estoque-campo`.

O primeiro deploy deve ser feito em etapas. Não publique a porta 8000, não
copie ambientes virtuais e não use SQLite em produção.

## 1. Inspecionar e preparar a VPS

Antes de instalar a aplicação, confirme região, IP, sistema e recursos:

```bash
hostnamectl
cat /etc/os-release
ip -brief address
df -h
free -h
```

Atualize o sistema e instale os pacotes necessários:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git nginx postgresql postgresql-client python3-venv \
  certbot python3-certbot-nginx ufw
```

Crie o usuário de serviço caso ele ainda não exista:

```bash
sudo adduser lima
sudo usermod -aG sudo lima
```

Mantenha a sessão SSH atual aberta enquanto configura o firewall.

## 2. Instalar o código e o ambiente Python

```bash
sudo install -d -o lima -g lima /opt/estoque-campo
sudo -u lima git clone https://github.com/JovisLima/estoque-campo.git /opt/estoque-campo
sudo -u lima python3 -m venv /opt/estoque-campo/backend/venv
sudo -u lima /opt/estoque-campo/backend/venv/bin/pip install --upgrade pip
sudo -u lima /opt/estoque-campo/backend/venv/bin/pip install \
  -r /opt/estoque-campo/backend/requirements.txt
```

Fixe a versão/commit implantado e registre-o no controle operacional. Não faça
`git pull` automático no `systemd`.

## 3. Criar o PostgreSQL

Gere uma senha longa, guarde-a no gerenciador de segredos e não a cole em
logs ou tickets:

```bash
openssl rand -hex 32
```

Entre no PostgreSQL:

```bash
sudo -u postgres psql
```

Execute, substituindo a senha:

```sql
CREATE USER estoque_user WITH PASSWORD 'SENHA_FORTE_AQUI';
CREATE DATABASE estoque_campo OWNER estoque_user;
\connect estoque_campo
GRANT ALL ON SCHEMA public TO estoque_user;
\quit
```

O PostgreSQL deve continuar acessível apenas localmente, salvo se houver uma
necessidade e uma rede privada explicitamente projetadas para isso.

## 4. Configurar o ambiente de produção

Crie um diretório central para configurações:

```bash
sudo install -d -m 0750 -o root -g lima /etc/aven
sudo install -m 0640 -o root -g lima \
  /opt/estoque-campo/deploy/.env.example /etc/aven/estoque-campo.env
sudo nano /etc/aven/estoque-campo.env
```

Preencha no mínimo:

- `DATABASE_URL` com a senha do banco;
- `JWT_SECRET_KEY` e `AVEN_MONITOR_API_TOKEN` com valores independentes
  gerados por `openssl rand -hex 32`;
- `CORS_ALLOWED_ORIGINS` com as origens HTTPS realmente utilizadas;
- `ALLOWED_HOSTS` com o domínio público;
- `ADMIN_SENHA` com uma senha inicial forte e exclusiva.

Produção rejeita SQLite, curingas de CORS/hosts, segredos fracos e senhas de
bootstrap conhecidas. A documentação `/docs` permanece desativada por padrão.

## 5. Migrar o banco e criar o primeiro administrador

O schema é controlado pelo Alembic; a aplicação não cria tabelas
automaticamente em produção:

```bash
sudo systemd-run --wait --pipe --collect \
  -p User=lima -p Group=lima \
  -p WorkingDirectory=/opt/estoque-campo/backend \
  -p EnvironmentFile=/etc/aven/estoque-campo.env \
  /opt/estoque-campo/backend/venv/bin/alembic \
  -c /opt/estoque-campo/backend/alembic.ini upgrade head

sudo systemd-run --wait --pipe --collect \
  -p User=lima -p Group=lima \
  -p WorkingDirectory=/opt/estoque-campo/backend \
  -p EnvironmentFile=/etc/aven/estoque-campo.env \
  /opt/estoque-campo/backend/venv/bin/python \
  /opt/estoque-campo/backend/seed.py
```

O `seed.py` de produção cria somente o primeiro administrador. Ele não cria o
técnico de demonstração com PIN conhecido. Depois de confirmar o login,
remova `ADMIN_SENHA` do arquivo de ambiente; ela não é necessária para o
funcionamento normal.

Antes de adotar Alembic em um banco antigo criado por `create_all`, faça backup
e compare o schema. Não execute `alembic stamp` às cegas.

## 6. Instalar e iniciar o serviço

```bash
sudo cp /opt/estoque-campo/deploy/estoque-campo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now estoque-campo.service
sudo systemctl status estoque-campo.service
sudo journalctl -u estoque-campo.service -n 100 --no-pager
```

Antes de cada inicialização, o serviço aplica as migrações e executa o
`preflight.py`, que verifica banco, revisão Alembic e diretório persistente.

Teste localmente:

```bash
curl --fail -H 'Host: estoque.suaempresa.com.br' \
  http://127.0.0.1:8000/health/live
curl --fail -H 'Host: estoque.suaempresa.com.br' \
  http://127.0.0.1:8000/health/ready
```

## 7. Nginx, DNS e HTTPS

Edite o domínio no arquivo fornecido e instale-o:

```bash
sudo cp /opt/estoque-campo/deploy/nginx-estoque-campo.conf \
  /etc/nginx/sites-available/estoque-campo
sudo nano /etc/nginx/sites-available/estoque-campo
sudo ln -s /etc/nginx/sites-available/estoque-campo \
  /etc/nginx/sites-enabled/estoque-campo
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d estoque.suaempresa.com.br
sudo certbot renew --dry-run
```

O Nginx limita tentativas de login, adiciona cabeçalhos de segurança e faz o
proxy apenas para `127.0.0.1:8000`.

## 8. Firewall e snapshot

Primeiro confirme que a regra SSH corresponde à porta realmente utilizada:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status verbose
```

Não libere as portas 8000 ou 5432 para a Internet. Após validar SSH, HTTPS e
serviços, crie um snapshot da VPS no provedor.

## 9. Backup e teste de restauração

Instale e ative o timer diário:

```bash
sudo install -d -m 0700 -o lima -g lima /var/backups/estoque-campo
sudo cp /opt/estoque-campo/deploy/estoque-campo-backup.service \
  /opt/estoque-campo/deploy/estoque-campo-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now estoque-campo-backup.timer
sudo systemctl start estoque-campo-backup.service
sudo systemctl status estoque-campo-backup.service
sudo systemctl list-timers estoque-campo-backup.timer
```

O backup inclui um `pg_dump` em formato custom, arquivos persistentes e
checksums SHA-256. Copie os arquivos de `/var/backups/estoque-campo` para um
destino externo à VPS e defina retenção nesse destino.

Um backup só é confiável depois de um ensaio de restauração em banco separado:

```bash
createdb -h 127.0.0.1 -U estoque_user estoque_restore_test
pg_restore -h 127.0.0.1 -U estoque_user -d estoque_restore_test \
  --clean --if-exists CAMINHO_DO_BACKUP.dump
```

Use credenciais e permissões adequadas ao ambiente do ensaio e apague o banco
de teste somente após validar tabelas e registros.

## 10. Publicar os clientes

Depois que o domínio HTTPS estiver estável, configure `API_URL` no Android e
no Desk com `https://estoque.suaempresa.com.br`, sincronize o Capacitor e gere
novos artefatos release. Não use `cleartext` no Android de produção.

## Checklist de liberação

- [ ] Ubuntu 24.04, IPv4 e região confirmados.
- [ ] SSH por chave, firewall e snapshot validados.
- [ ] PostgreSQL local, migrations em `head` e preflight aprovados.
- [ ] Segredos únicos e nenhum valor de exemplo no ambiente.
- [ ] Administrador inicial criado e `ADMIN_SENHA` removida do ambiente.
- [ ] HTTPS válido; portas 8000 e 5432 fechadas externamente.
- [ ] `/health/live` e `/health/ready` respondendo.
- [ ] Backup externo e restauração de teste concluídos.
- [ ] Monitor implantado somente depois de o backend estar saudável.
