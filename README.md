# Estoque de Campo

Sistema de controle de estoque com baixa automática, dividido em 3 partes
que conversam com um único backend central (por isso tudo fica sincronizado
sozinho — não existe lógica separada de "enviar dado de um app pro outro",
todos leem e escrevem no mesmo banco de dados através da mesma API):

```
                    ┌─────────────────────┐
                    │   backend/ (API)     │   ← roda no seu VPS
                    │  banco de dados      │
                    └──────────┬──────────┘
                 ┌─────────────┼─────────────┐
                 │              │              │
        android-tecnico/   desktop-admin/   (o navegador também
        app Android         app Windows      funciona, se quiser)
        do técnico          Estoque + Admin
```

- **`backend/`**: a API (não muda pra quem usa — só o "cérebro" do sistema).
- **`android-tecnico/`**: projeto que vira um app Android instalável no
  celular do técnico (empacota a interface `frontend/`, veja o README
  dentro da pasta).
- **`desktop-admin/`**: programa Windows (`.exe`) com abas Estoque e
  Ordens/Admin — você usa pra cadastrar técnicos, atribuir OS e acompanhar
  o estoque.
- **`frontend/`**: a versão web pura do app do técnico (base usada pelo
  projeto Android, também pode ser usada direto no navegador se quiser).

## Papéis de acesso no painel admin

O painel agora tem login individual por usuário (não é mais uma senha
única compartilhada). Dois papéis:

- **Gerência**: acesso total — Estoque, Transferências, Solicitações,
  Avisos, Ordens de Serviço, Técnicos, Financeiro, e a tela de Usuários
  do painel (onde cria outras contas e define o papel de cada uma).
- **Almoxarifado**: só Estoque, Transferências, Solicitações e Avisos —
  sem acesso a Ordens de Serviço, Técnicos, Financeiro ou gestão de
  usuários do painel.

O primeiro usuário (`admin`, papel gerência) é criado pelo `seed.py`. A
partir dele, crie os outros pela aba "Usuários do painel".

## Como funciona o fluxo

1. **Você (admin)** cadastra o técnico no app desktop (aba Técnicos) — ele
   fica **pendente de aprovação** até você clicar em "Aprovar". Só depois
   disso ele consegue logar no app dele.
2. **Você envia itens pro técnico** (aba Transferências): materiais
   (consumíveis) ou ferramentas/EPIs. O estoque central já é debitado nesse
   momento.
3. **O técnico confirma o recebimento** no app — só depois disso o material
   entra no **estoque pessoal dele**, e a ferramenta/EPI passa a constar
   como "com ele".
4. **Você atribui uma OS** a ele (aba Ordens de Serviço) — ela aparece no
   app do técnico como pendente, ele toca em "Iniciar".
5. Ele vai adicionando os materiais usados — a baixa acontece no **estoque
   pessoal dele** (não mexe no estoque central, que já foi debitado na
   transferência). Isso já aparece pra você no app desktop.
6. **Ferramentas e EPIs não têm baixa pelo técnico** — ele só pode
   confirmar recebimento ou notificar um problema (quebrou, gastou). Só
   você decide, no app desktop, se dá baixa definitiva, manda pra
   manutenção ou mantém em uso.
7. Técnico fecha a OS ao terminar.
8. **Funciona offline**: sem sinal no celular, tudo fica numa fila local e
   sincroniza sozinho assim que a conexão voltar.

O técnico também pode abrir uma OS avulsa (não atribuída por você), pra
atendimentos não planejados — o fluxo funciona igual, só que sem passar
pela etapa de atribuição.

## Rodando localmente (teste rápido)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python seed.py          # cria técnico de teste (tecnico1 / PIN 1234) e materiais de exemplo
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Em outro terminal, sirva o frontend:

```bash
cd frontend
python3 -m http.server 8080
```

Acesse `http://SEU_IP:8080` pelo celular (mesma rede). Antes de usar em
campo de verdade, edite a constante `API_URL` no topo de `frontend/app.js`
para apontar pro endereço do seu VPS.

## Deploy no VPS (produção)

**Backend:**
- Use PostgreSQL em vez de SQLite: defina a variável de ambiente
  `DATABASE_URL=postgresql://usuario:senha@localhost/estoque_campo`
- A senha do primeiro usuário admin (login `admin`, papel gerência) é
  definida por `ADMIN_SENHA` (padrão `admin123` — **troque isso antes de
  rodar `seed.py` em produção**). Depois do primeiro login, use a aba
  "Usuários do painel" (só gerência vê essa aba) pra criar outras contas
  com login/senha próprios e o papel adequado (gerência ou almoxarifado).
- Rode com um processo gerenciado (recomendo `systemd` + `gunicorn` com
  workers uvicorn, do mesmo jeito que você já faz com o Hermes):
  ```bash
  pip install gunicorn
  gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
  ```
- Coloque atrás de um Nginx com HTTPS (Let's Encrypt) — o navegador só deixa
  instalar PWA e usar `serviceWorker` em HTTPS (exceto `localhost`).

**Frontend:**
- É só HTML/JS estático — sirva com Nginx direto, ou junto do backend.
- Depois de publicado, no celular do técnico: abrir o link no Chrome →
  menu → "Adicionar à tela inicial". Vira um app normal.

## Próximos passos sugeridos

- Alertas de estoque baixo no Telegram, reaproveitando o bot que você já
  tem no Hermes (o endpoint `/materiais/baixo-estoque` já está pronto pra
  isso — é só o Hermes consultar periodicamente).
- Cadastro de materiais/categorias direto pelo app desktop (hoje dá pra
  registrar entrada de estoque, mas criar um material novo do zero ainda
  é só via `/materiais` na documentação da API em `/docs`).
- Trocar o login por PIN por algo mais forte se o número de técnicos crescer.

## Estrutura

```
backend/
  main.py         → API (FastAPI) — inclui rotas /admin/* pro painel
  models.py       → Tabelas do banco
  database.py     → Conexão (SQLite local / Postgres em produção)
  seed.py         → Dados iniciais de teste
frontend/
  index.html      → Tela do técnico (versão web, base do app Android)
  app.js          → Lógica + fila offline + OS atribuídas pelo admin
  manifest.json   → Config do PWA
  sw.js           → Cache offline do app
android-tecnico/
  www/            → cópia do frontend/, empacotada como app Android
  capacitor.config.ts
  README.md       → passo a passo pra gerar o .apk
desktop-admin/
  main.js         → ponto de entrada do Electron
  src/            → interface (abas Estoque / Ordens / Técnicos)
  README.md       → passo a passo pra rodar/gerar o .exe
```
