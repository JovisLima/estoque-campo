# App Desktop - Admin / Estoque

Programa desktop (Windows) com duas abas:
- **Estoque**: ver materiais e ferramentas, registrar entrada de estoque (compras).
- **Ordens de Serviço**: atribuir OS pros técnicos e acompanhar o andamento.
- **Técnicos**: cadastrar técnicos novos (gera o login/PIN que eles usam no app Android).

## Antes de tudo

Abra `src/app.js` e troque a primeira linha pro endereço real do seu backend
no VPS (em vez de `localhost`, que só funciona testando no mesmo computador
onde o backend está rodando):
```js
const API_URL = "http://localhost:8000";
```

Defina também uma senha forte pro primeiro usuário admin (variável de
ambiente `ADMIN_SENHA` no VPS, usada pelo `seed.py` — login `admin`,
papel gerência) — o padrão `admin123` é só pra teste local, não use em
produção. Depois do primeiro login, crie os outros usuários (com papel
gerência ou almoxarifado) direto pela aba "Usuários do painel".

## Testando localmente

```bash
npm install
npm start
```
Abre uma janela do programa. Faça login com a senha de admin.

## Gerando o instalador .exe (pra usar sem precisar do terminal)

```bash
npm run build-win
```
O instalador vai aparecer numa pasta `dist/`. É só rodar esse instalador no
seu computador (ou em qualquer outro Windows) que ele cria um atalho normal,
como qualquer programa.
