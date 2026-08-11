const CACHE = "estoque-campo-v2";
const ARQUIVOS = ["./index.html", "./app.js", "./manifest.json", "./assets/logo.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ARQUIVOS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((chaves) =>
      Promise.all(chaves.filter((c) => c !== CACHE).map((c) => caches.delete(c)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Só cacheia o app em si (HTML/JS/manifest). Chamadas à API sempre vão
  // direto pra rede — a fila offline do app.js já cuida da parte de dados.
  if (event.request.url.includes("/materiais") || event.request.url.includes("/ordens") ||
      event.request.url.includes("/ferramentas") || event.request.url.includes("/movimentacoes") ||
      event.request.url.includes("/tecnicos") || event.request.url.includes("/transferencias") ||
      event.request.url.includes("/solicitacoes")) {
    return;
  }

  // Network-first: sempre tenta buscar a versão mais nova do servidor.
  // Só usa o que está salvo no cache se estiver sem internet mesmo.
  event.respondWith(
    fetch(event.request)
      .then((resposta) => {
        const copia = resposta.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copia));
        return resposta;
      })
      .catch(() => caches.match(event.request))
  );
});
