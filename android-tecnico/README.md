# App Android do Técnico

Este projeto empacota o app do técnico (a mesma interface web que já testamos)
como um app Android de verdade, instalável no celular sem precisar do Chrome.

## O que você precisa instalar (uma vez só)

1. **Node.js**: [nodejs.org](https://nodejs.org) — baixe a versão LTS.
2. **Android Studio**: [developer.android.com/studio](https://developer.android.com/studio)
   — durante a instalação, deixe marcado pra instalar o "Android SDK" também
   (a instalação padrão já faz isso).

## Permissão de localização (GPS)

O app registra a localização do técnico ao iniciar e finalizar uma OS. No
Android, isso pode exigir uma permissão explícita no
`AndroidManifest.xml` (gerado pelo `npx cap add android`). Se o app pedir
localização e não funcionar, adicione essas linhas **antes** da tag
`<application>`:
```xml
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
```
Depois `npx cap sync android` e rode de novo. Isso não trava o app se o
técnico negar a permissão — a OS só fica sem a localização registrada.

## Sobre HTTP vs HTTPS (importante)

O `capacitor.config.json` já vem com `"cleartext": true`, que libera o app
pra conversar com um backend em `http://` (sem criptografia) — necessário
pra testar contra o servidor local (`10.0.2.2` no emulador, ou o IP da sua
rede num celular físico). **Antes de distribuir o app de verdade pros
técnicos**, o backend no VPS deve estar atrás de HTTPS (com Nginx +
Let's Encrypt, como descrito no README principal do projeto) — nesse caso
dá pra remover o `cleartext: true` e usar só `https://` no `API_URL`.

## Se der "Failed to fetch" no app

A causa mais comum é **Mixed Content**: o Capacitor carrega a interface do
app em `https://localhost/` por padrão, mas as chamadas pro backend vão em
`http://` (sem HTTPS configurado ainda) — o navegador bloqueia isso por
segurança, mesmo sendo tudo local. Se o `capacitor.config.json` do projeto
já não tiver, ajuste:
```json
{
  "server": {
    "androidScheme": "http",
    "cleartext": true
  }
}
```
Depois rode `npx cap sync android`, e no Android Studio: pare o app (⏹),
**Build → Clean Project**, **Build → Rebuild Project**, rode de novo (▶).

Se mesmo assim continuar, confira o resto nessa ordem:

**1. O backend está rodando?** No terminal dele, precisa aparecer
`Uvicorn running on http://0.0.0.0:8000` — repare que é `0.0.0.0`, não
`127.0.0.1`. Se você rodou só `uvicorn main:app --reload` sem o
`--host 0.0.0.0`, o backend só aceita conexão de dentro do próprio Windows,
e o emulador/celular não consegue entrar. Rode:
```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**2. O `API_URL` está certo pro seu tipo de teste?**
- Emulador do Android Studio → `http://10.0.2.2:8000`
- Celular físico (mesma rede Wi-Fi) → IP real do PC, ex: `http://192.168.1.15:8000`
- Nunca `localhost` — dentro do app, isso aponta pro próprio celular/emulador, não pro seu PC.

**3. Depois de editar `www/app.js` ou o `capacitor.config.json`, sempre
sincronize antes de rodar de novo**:
```powershell
npx cap sync android
```

**4. Ainda com o `AndroidManifest.xml`**: garanta que a tag `<application>`
tem `android:usesCleartextTraffic="true"` (às vezes precisa dos dois —
esse atributo E o `cleartext: true` no config — dependendo da versão do
Capacitor).

**5. Celular físico apenas**: confirme que o Firewall do Windows libera a
porta 8000 (PowerShell como Administrador):
```powershell
New-NetFirewallRule -DisplayName "Backend Estoque Campo" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

## Aplicando a logo da Aven Connect como ícone do app

A logo já está em `www/assets/logo.png` (aparece dentro do app). Pra ela
também virar o **ícone do aplicativo** (o que aparece na tela inicial do
celular), depois de rodar `npx cap open android`:

1. No Android Studio, clique com o botão direito na pasta `app` (painel
   esquerdo) → **New → Image Asset**.
2. Em "Icon Type", escolha **Launcher Icons (Adaptive and Legacy)**.
2. Em "Path", clique na pastinha e selecione `www/assets/logo.png`.
3. Ajuste o "Resize" se a logo ficar cortada (o Android corta os cantos em
   ícones adaptativos — deixe uma margem/respiro ao redor se for gerar uma
   versão com fundo transparente maior).
4. Clique em **Next** → **Finish**. Isso gera os ícones em todos os
   tamanhos automaticamente.

## Passo a passo

**1. Antes de tudo, ajuste o endereço do servidor.**
Abra `www/app.js` e troque a primeira linha:
```js
const API_URL = "http://localhost:8000";
```
pelo endereço real do seu backend no VPS, por exemplo:
```js
const API_URL = "https://api.suaempresa.com.br";
```
(`localhost` não funciona no celular — lá dentro do app, "localhost" seria o
próprio celular, não seu servidor.)

**2. Instale as dependências do projeto** (terminal, dentro desta pasta
`android-tecnico`):
```bash
npm install
```

**3. Adicione a plataforma Android** (só precisa rodar uma vez):
```bash
npx cap add android
```
Isso cria uma pasta `android/` — é um projeto Android Studio completo.

**4. Sempre que você editar algo em `www/` (o código do app), sincronize:**
```bash
npx cap sync android
```

**5. Abra o projeto no Android Studio:**
```bash
npx cap open android
```
Isso abre o Android Studio automaticamente com o projeto certo.

**6. Gerar o APK (arquivo instalável):**
No Android Studio, vá no menu **Build → Build Bundle(s) / APK(s) → Build APK(s)**.
Espere terminar (a barra de progresso fica embaixo). Quando acabar, vai
aparecer um link "locate" — clique nele pra achar o arquivo
`app-debug.apk`.

**7. Instalar no celular do técnico:**
- Mais simples: mande o `.apk` pelo WhatsApp/Telegram pro celular do técnico,
  ele abre o arquivo e instala (pode pedir pra habilitar "instalar de fontes
  desconhecidas" nas configurações — normal para apps fora da Play Store).
- Alternativa: conecte o celular no computador por USB com a "depuração USB"
  ativada e clique no botão verde "Run" (▶) no Android Studio — instala
  direto.

## Testando sem gerar o APK toda hora

Enquanto estiver ajustando o app, é mais rápido testar num emulador Android
(vem com o Android Studio: **Device Manager → criar dispositivo virtual**) ou
com o celular conectado por USB, clicando em "Run" (▶) direto do Android
Studio — não precisa gerar o `.apk` pra isso, só quando for distribuir de
verdade pros técnicos.

## Gerando um APK "de verdade" (assinado, pra distribuir oficialmente)

O `app-debug.apk` do passo 6 já funciona perfeitamente para uso interno
(instalar manualmente nos celulares da equipe). Se um dia você quiser algo
mais formal (assinatura própria, atualizações automáticas, etc.), o
Android Studio tem a opção **Build → Generate Signed Bundle / APK** — mas
para o seu caso (poucos técnicos, instalação manual) o debug já resolve.
