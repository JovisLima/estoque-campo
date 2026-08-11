# Deploy em Produção — Aven Connect / Estoque de Campo

Este guia assume um VPS com **Ubuntu 22.04 ou 24.04** (ajuste os comandos
se for outra distro) e que você já tem um **domínio ou subdomínio**
apontando pro IP do VPS (ex: `estoque.suaempresa.com.br` → registro DNS
tipo A pro IP do servidor). Sem domínio, não dá pra gerar HTTPS de verdade
com Let's Encrypt — é pré-requisito.

---

## 1. Preparar o VPS

Conecte via SSH e atualize o sistema:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip postgresql postgresql-contrib nginx git
```

## 2. Criar o banco de dados PostgreSQL

```bash
sudo -u postgres psql
```
Dentro do `psql`:
```sql
CREATE DATABASE estoque_campo;
CREATE USER estoque_user WITH PASSWORD 'SENHA_FORTE_AQUI';
GRANT ALL PRIVILEGES ON DATABASE estoque_campo TO estoque_user;
\q
```

## 3. Enviar o código pro VPS

Envie a pasta `backend/` do projeto pro servidor (via `scp`, `git clone` do
seu próprio repositório, ou até um client SFTP como FileZilla). Recomendo
colocar em `/opt/estoque-campo/backend`:
```bash
sudo mkdir -p /opt/estoque-campo
sudo chown $USER:$USER /opt/estoque-campo
# depois de copiar os arquivos pra lá:
cd /opt/estoque-campo/backend
```

## 4. Ambiente virtual e dependências

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
No Linux o `psycopg2-binary` instala sem o problema que deu no Windows.

## 5. Configurar as variáveis de ambiente

```bash
cp ../deploy/.env.example .env
nano .env
```
Preencha a senha real do Postgres (a mesma do passo 2) e escolha uma senha
forte pro `ADMIN_SENHA` — essa é a senha do PRIMEIRO usuário admin (login
`admin`, papel gerência), criado pelo `seed.py`. Depois do primeiro login,
crie os outros usuários (gerência/almoxarifado) pela própria aba "Usuários
do painel" — não precisa mexer mais em variável de ambiente pra isso.

## 6. Criar as tabelas e testar manualmente uma vez

```bash
python seed.py
```
Isso cria o técnico de teste (`tecnico1`/`1234`) — depois de validar que
tudo funciona, **apague ou desative esse técnico de teste** pelo painel
admin (ou direto no banco), já que a senha dele é pública/conhecida.

Teste rápido antes de virar serviço:
```bash
source .env  # carrega as variáveis nesse terminal
uvicorn main:app --host 127.0.0.1 --port 8000
```
Se subir sem erro, `Ctrl+C` e siga pro próximo passo.

## 7. Rodar como serviço permanente (systemd)

```bash
sudo cp ../deploy/estoque-campo.service /etc/systemd/system/
```
Edite `/etc/systemd/system/estoque-campo.service` se o caminho do projeto
não for exatamente `/opt/estoque-campo/backend`. Depois:
```bash
sudo systemctl daemon-reload
sudo systemctl enable estoque-campo
sudo systemctl start estoque-campo
sudo systemctl status estoque-campo
```
Deve aparecer "active (running)" em verde. A partir de agora, o backend
sobe sozinho até quando o VPS reiniciar.

Ver os logs se algo der errado:
```bash
sudo journalctl -u estoque-campo -f
```

## 8. Nginx + HTTPS (Let's Encrypt)

```bash
sudo cp ../deploy/nginx-estoque-campo.conf /etc/nginx/sites-available/estoque-campo
sudo nano /etc/nginx/sites-available/estoque-campo
```
Troque `estoque.suaempresa.com.br` pelo seu domínio real. Depois:
```bash
sudo ln -s /etc/nginx/sites-available/estoque-campo /etc/nginx/sites-enabled/
sudo nginx -t   # testa se a configuração está válida
sudo systemctl reload nginx
```

Agora gere o certificado HTTPS automaticamente:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d estoque.suaempresa.com.br
```
Siga as perguntas (email, aceitar termos). O certbot já ajusta o Nginx
sozinho pra usar HTTPS e redirecionar HTTP → HTTPS. Ele também configura
renovação automática do certificado.

Teste no navegador: `https://estoque.suaempresa.com.br/docs` deve abrir a
documentação da API com o cadeado verde.

## 9. Firewall

```bash
sudo ufw allow 22    # SSH — não esqueça, senão você se tranca pra fora
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```
A porta 8000 **não precisa** ficar aberta pro mundo — só o Nginx (local)
fala com ela.

## 10. Backup

Configure um backup periódico (cron) pelo menos do banco de dados e das
pastas de fotos/PDFs — se o VPS tiver algum problema, é isso que evita
perder o histórico de tudo:
```bash
sudo -u postgres pg_dump estoque_campo > backup_$(date +%Y%m%d).sql
```
As pastas `backend/relatorios/`, `backend/fotos_perfil/` e
`backend/fotos_os/` guardam os arquivos gerados — inclua elas num backup
regular também (rsync pra outro servidor, ou um serviço de backup em nuvem).

---

## 11. Apontar os apps pro servidor de produção

Agora que o backend está em HTTPS de verdade, **os workarounds que usamos
pra testar no emulador não são mais necessários** — dá pra usar a
configuração mais segura e simples.

**App do técnico** (`android-tecnico/www/app.js`):
```js
const API_URL = "https://estoque.suaempresa.com.br";
```

**Reverta o `capacitor.config.json`** pra versão sem os workarounds de HTTP:
```json
{
  "appId": "com.estoquecampo.tecnico",
  "appName": "Aven Connect",
  "webDir": "www"
}
```
(remove o bloco `"server": { "androidScheme": "http", "cleartext": true }`
inteiro — não precisa mais, já que agora é tudo HTTPS)

Depois:
```powershell
npx cap sync android
```
E gere o APK final de novo (Build → Build Bundle(s)/APK(s) → Build APK(s)).

**App desktop** (`desktop-admin/src/app.js`):
```js
const API_URL = "https://estoque.suaempresa.com.br";
```
Depois gere o instalador final:
```powershell
cd desktop-admin
npm run build-win
```

## Checklist final antes de distribuir pros técnicos

- [ ] `ADMIN_SENHA` (senha do primeiro usuário `admin`) trocada pra algo forte (não `admin123`)
- [ ] Técnico de teste (`tecnico1`) apagado ou com PIN trocado
- [ ] HTTPS funcionando (cadeado verde no navegador)
- [ ] Backend rodando como serviço (`systemctl status estoque-campo` = active)
- [ ] Firewall configurado (só 22/80/443 abertas)
- [ ] Backup do banco configurado
- [ ] `API_URL` nos dois apps apontando pro domínio real, não IP local
- [ ] APK final gerado e testado num celular de verdade (não só emulador)
- [ ] Instalador do desktop gerado e testado
