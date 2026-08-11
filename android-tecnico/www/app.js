// ===== CONFIGURAÇÃO =====
// Troque pela URL do seu backend no VPS, ex: "https://estoque.suaempresa.com.br"
const API_URL = "http://localhost:8000";

// ===== ESTADO LOCAL (persistido no celular) =====
let tecnico = JSON.parse(localStorage.getItem("tecnico") || "null");
let osAtiva = JSON.parse(localStorage.getItem("os_ativa") || "null");
let estoquePessoalCache = JSON.parse(localStorage.getItem("estoque_pessoal_cache") || "[]");
let catalogoCentralCache = JSON.parse(localStorage.getItem("catalogo_central_cache") || "[]");
let minhasSolicitacoesCache = JSON.parse(localStorage.getItem("minhas_solicitacoes_cache") || "[]");
let fila = JSON.parse(localStorage.getItem("fila_sync") || "[]");

function uuid() {
  return crypto.randomUUID ? crypto.randomUUID() :
    'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
}

// Tenta pegar a localização atual do celular. Não trava o fluxo se demorar
// ou se o técnico negar a permissão — só segue sem coordenadas.
function obterLocalizacao() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) { resolve({ lat: null, lon: null }); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => resolve({ lat: null, lon: null }),
      { timeout: 6000, maximumAge: 30000 }
    );
  });
}

function salvarEstado() {
  localStorage.setItem("tecnico", JSON.stringify(tecnico));
  localStorage.setItem("os_ativa", JSON.stringify(osAtiva));
  localStorage.setItem("estoque_pessoal_cache", JSON.stringify(estoquePessoalCache));
  localStorage.setItem("catalogo_central_cache", JSON.stringify(catalogoCentralCache));
  localStorage.setItem("minhas_solicitacoes_cache", JSON.stringify(minhasSolicitacoesCache));
  localStorage.setItem("fila_sync", JSON.stringify(fila));
}

// ===== CONEXÃO =====
function atualizarStatusConexao() {
  const el = document.getElementById("status-conexao");
  if (navigator.onLine) {
    el.textContent = "online"; el.className = "online";
    sincronizarFila();
  } else {
    el.textContent = "offline"; el.className = "offline";
  }
}
window.addEventListener("online", atualizarStatusConexao);
window.addEventListener("offline", atualizarStatusConexao);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && tecnico) {
    carregarPendentes();
    carregarTransferencias();
  }
});

// ===== LOGIN =====
async function fazerLogin() {
  const login = document.getElementById("login-input").value.trim();
  const pin = document.getElementById("pin-input").value.trim();
  const erroEl = document.getElementById("login-erro");
  erroEl.textContent = "";

  try {
    const resp = await fetch(`${API_URL}/tecnicos/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login, pin }),
    });
    if (resp.status === 403) {
      erroEl.textContent = "Seu cadastro ainda está aguardando aprovação do estoque.";
      return;
    }
    if (!resp.ok) throw new Error("Login ou PIN inválido");
    tecnico = await resp.json();
    salvarEstado();
    await carregarTudo();
    mostrarTelaPrincipal();
  } catch (e) {
    if (!navigator.onLine) {
      erroEl.textContent = "Sem internet e sem login salvo. Conecte-se ao menos uma vez para entrar.";
    } else {
      erroEl.textContent = e.message;
    }
  }
}

function logout() {
  tecnico = null; osAtiva = null;
  salvarEstado();
  location.reload();
}

async function carregarTudo() {
  await Promise.all([
    carregarEstoquePessoal(), carregarPendentes(),
    carregarTransferencias(), carregarMinhasFerramentas(),
    carregarCatalogoCentral(), carregarMinhasSolicitacoes(),
  ]);
}

// ===== NAVEGAÇÃO ENTRE ABAS =====
function mudarTab(tab) {
  document.getElementById("tab-ordens").classList.toggle("oculto", tab !== "ordens");
  document.getElementById("tab-materiais").classList.toggle("oculto", tab !== "materiais");
  document.getElementById("tab-perfil").classList.toggle("oculto", tab !== "perfil");
  document.getElementById("btn-tab-ordens").classList.toggle("ativa", tab === "ordens");
  document.getElementById("btn-tab-materiais").classList.toggle("ativa", tab === "materiais");
  document.getElementById("btn-tab-perfil").classList.toggle("ativa", tab === "perfil");
  if (tab === "perfil") carregarPerfil();
}

// ===== PERFIL DO TÉCNICO =====
async function carregarPerfil() {
  try {
    const r = await fetch(`${API_URL}/tecnicos/${tecnico.id}/perfil`);
    const perfil = await r.json();
    localStorage.setItem("perfil_cache", JSON.stringify(perfil));
    renderizarPerfil(perfil);
  } catch (e) {
    const cache = JSON.parse(localStorage.getItem("perfil_cache") || "null");
    if (cache) renderizarPerfil(cache);
  }
}

function renderizarPerfil(perfil) {
  document.getElementById("perfil-nome").textContent = perfil.nome;
  document.getElementById("perfil-adm").textContent = perfil.is_adm ? "⭐ Técnico ADM" : "";
  document.getElementById("perfil-login").textContent = perfil.login;
  document.getElementById("perfil-telefone").textContent = perfil.telefone || "não informado";
  document.getElementById("perfil-data").textContent = perfil.data_contratacao
    ? new Date(perfil.data_contratacao + "T00:00:00").toLocaleDateString("pt-BR")
    : "não informado";

  const img = document.getElementById("perfil-foto");
  const semFoto = document.getElementById("perfil-sem-foto");
  if (perfil.tem_foto_perfil) {
    img.src = `${API_URL}/tecnicos/${tecnico.id}/foto-perfil?t=${Date.now()}`;
    img.classList.remove("oculto");
    semFoto.classList.add("oculto");
  } else {
    img.classList.add("oculto");
    semFoto.classList.remove("oculto");
  }
}

// ===== ESTOQUE PESSOAL (o que o técnico tem fisicamente com ele) =====
async function carregarEstoquePessoal() {
  try {
    const r = await fetch(`${API_URL}/tecnicos/${tecnico.id}/estoque-pessoal`);
    estoquePessoalCache = await r.json();
    salvarEstado();
  } catch (e) {
    // offline: segue com o cache salvo da última vez online
  }
  preencherSelectMaterial();
  renderizarMeuSaldo();
}

function renderizarMeuSaldo() {
  const div = document.getElementById("lista-meu-saldo");
  if (!div) return;
  div.innerHTML = estoquePessoalCache.length
    ? estoquePessoalCache.map(m => `
        <div class="item-lista"><span>${m.nome}</span><strong>${m.qtd_atual} ${m.unidade}</strong></div>
      `).join("")
    : "<p style='color:#64748b;font-size:13px;'>Você ainda não tem materiais com você.</p>";
}

function preencherSelectMaterial() {
  const sel = document.getElementById("select-material");
  if (estoquePessoalCache.length === 0) {
    sel.innerHTML = `<option value="">Você não tem materiais no seu estoque pessoal</option>`;
    return;
  }
  sel.innerHTML = estoquePessoalCache.map(m =>
    `<option value="${m.material_id}">${m.nome} (${m.qtd_atual} ${m.unidade} com você)</option>`
  ).join("");
}

// ===== OS ATRIBUÍDAS PELO ADMIN =====
let pendentesCache = JSON.parse(localStorage.getItem("pendentes_cache") || "[]");

async function carregarPendentes() {
  try {
    const r = await fetch(`${API_URL}/tecnicos/${tecnico.id}/ordens-pendentes`);
    pendentesCache = await r.json();
    localStorage.setItem("pendentes_cache", JSON.stringify(pendentesCache));
  } catch (e) {
    // offline: mantém o que já tinha em cache da última vez online
  }
  renderizarPendentes();
}

function renderizarPendentes() {
  const card = document.getElementById("card-pendentes");
  const div = document.getElementById("lista-pendentes");
  if (pendentesCache.length === 0) { card.classList.add("oculto"); return; }
  card.classList.remove("oculto");
  div.innerHTML = pendentesCache.map(o => `
    <div class="item-lista" style="flex-direction:column; align-items:flex-start; gap:6px; ${o.prioridade ? 'border-left:3px solid #dc2626; padding-left:8px;' : ''}">
      <div>${o.prioridade ? '🔴 <strong>PRIORIDADE</strong> — ' : ''}${o.tipo === 'preventiva' ? '🛠️ <strong>PREVENTIVA</strong> — ' : ''}<strong>${o.cliente_local}</strong> — ${o.tipo}</div>
      ${o.nome_cliente ? `<div style="color:#94a3b8; font-size:12px;">👤 ${o.nome_cliente}</div>` : ""}
      ${o.endereco ? `<div style="color:#94a3b8; font-size:12px;">📍 ${o.endereco}</div>` : ""}
      ${o.observacoes ? `<div style="color:#94a3b8; font-size:12px;">${o.observacoes}</div>` : ""}
      <button style="margin-top:4px;" onclick="iniciarDeslocamento(${o.id})">🚗 Iniciar deslocamento</button>
    </div>
  `).join("");
}

async function iniciarDeslocamento(ordemId) {
  const ordem = pendentesCache.find(o => o.id === ordemId);
  if (!ordem) return;
  if (osAtiva) { alert("Finalize a OS em andamento antes de iniciar outra."); return; }

  osAtiva = {
    id_servidor: ordemId, client_uuid: null, tipo: ordem.tipo,
    cliente_local: ordem.cliente_local, cliente_id: ordem.cliente_id,
    nome_cliente: ordem.nome_cliente, endereco: ordem.endereco,
    prioridade: ordem.prioridade, fase: "deslocamento", materiais: [],
  };
  pendentesCache = pendentesCache.filter(o => o.id !== ordemId);
  localStorage.setItem("pendentes_cache", JSON.stringify(pendentesCache));
  salvarEstado();
  renderizarPendentes();
  mostrarOsAtiva();

  const { lat, lon } = await obterLocalizacao();
  enfileirar({ tipo: "deslocamento", payload: { ordem_id: ordemId, lat, lon } });
  sincronizarFila();
}

async function chegouNoLocal() {
  const idServidor = osAtiva.id_servidor, clientUuid = osAtiva.client_uuid;
  osAtiva.fase = "em_andamento";
  salvarEstado();
  mostrarOsAtiva();

  const { lat, lon } = await obterLocalizacao();
  enfileirar({
    tipo: "iniciar_ordem",
    payload: { ordem_id: idServidor, ordem_client_uuid: clientUuid, lat, lon },
  });
  sincronizarFila();
}

// ===== TRANSFERÊNCIAS PENDENTES (materiais/ferramentas enviados pelo estoque) =====
let transferenciasCache = JSON.parse(localStorage.getItem("transferencias_cache") || "[]");

async function carregarTransferencias() {
  try {
    const r = await fetch(`${API_URL}/tecnicos/${tecnico.id}/transferencias-pendentes`);
    transferenciasCache = await r.json();
    localStorage.setItem("transferencias_cache", JSON.stringify(transferenciasCache));
  } catch (e) {
    // offline: mantém cache
  }
  renderizarTransferencias();
}

function renderizarTransferencias() {
  const card = document.getElementById("card-transferencias");
  const div = document.getElementById("lista-transferencias");
  if (transferenciasCache.length === 0) { card.classList.add("oculto"); return; }
  card.classList.remove("oculto");
  div.innerHTML = transferenciasCache.map(t => `
    <div class="item-lista" style="flex-direction:column; align-items:flex-start; gap:6px;">
      <div><strong>${t.item}</strong> ${t.tipo === "material" ? `— ${t.quantidade} ${t.unidade || ""}` : `(${t.categoria_ferramenta})`}</div>
      <div style="display:flex; gap:8px; width:100%;">
        <button style="margin-top:4px;" onclick="confirmarTransferencia(${t.id})">✅ Confirmar recebimento</button>
        <button class="secundario" style="margin-top:4px;" onclick="recusarTransferencia(${t.id})">Recusar</button>
      </div>
    </div>
  `).join("");
}

async function confirmarTransferencia(id) {
  transferenciasCache = transferenciasCache.filter(t => t.id !== id);
  localStorage.setItem("transferencias_cache", JSON.stringify(transferenciasCache));
  renderizarTransferencias();
  try {
    await fetch(`${API_URL}/transferencias/${id}/confirmar`, { method: "POST" });
    await Promise.all([carregarEstoquePessoal(), carregarMinhasFerramentas()]);
  } catch (e) {
    // sem internet agora: enfileira pra tentar depois
    enfileirar({ tipo: "confirmar_transferencia", payload: { id } });
  }
}

async function recusarTransferencia(id) {
  if (!confirm("Tem certeza que quer recusar o recebimento deste item?")) return;
  transferenciasCache = transferenciasCache.filter(t => t.id !== id);
  localStorage.setItem("transferencias_cache", JSON.stringify(transferenciasCache));
  renderizarTransferencias();
  try {
    await fetch(`${API_URL}/transferencias/${id}/recusar`, { method: "POST" });
  } catch (e) {
    enfileirar({ tipo: "recusar_transferencia", payload: { id } });
  }
}

// ===== MINHAS FERRAMENTAS / EPIs (só leitura + avisar problema) =====
let minhasFerramentasCache = JSON.parse(localStorage.getItem("minhas_ferramentas_cache") || "[]");

async function carregarMinhasFerramentas() {
  try {
    const r = await fetch(`${API_URL}/tecnicos/${tecnico.id}/ferramentas`);
    minhasFerramentasCache = await r.json();
    localStorage.setItem("minhas_ferramentas_cache", JSON.stringify(minhasFerramentasCache));
  } catch (e) {
    // offline: mantém cache
  }
  renderizarMinhasFerramentas();
}

function renderizarMinhasFerramentas() {
  const card = document.getElementById("card-minhas-ferramentas");
  const div = document.getElementById("lista-minhas-ferramentas");
  if (minhasFerramentasCache.length === 0) { card.classList.add("oculto"); return; }
  card.classList.remove("oculto");
  div.innerHTML = minhasFerramentasCache.map(f => `
    <div class="item-lista">
      <span>${f.categoria === "epi" ? "🦺" : "🔧"} ${f.nome}</span>
      <button class="secundario" style="width:auto; margin:0; padding:8px 12px; font-size:13px;"
        onclick="notificarProblema(${f.id}, '${f.nome.replace(/'/g, "")}')">Notificar problema</button>
    </div>
  `).join("");
}

async function notificarProblema(ferramentaId, nome) {
  const descricao = prompt(`Descreva o problema com "${nome}" (ex: quebrou, gastou, parou de funcionar):`);
  if (!descricao) return;
  const payload = { ferramenta_id: ferramentaId, tecnico_id: tecnico.id, descricao };
  try {
    await fetch(`${API_URL}/ferramentas/avisos`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    alert("Aviso enviado pro estoque!");
  } catch (e) {
    enfileirar({ tipo: "notificar_problema", payload });
    alert("Sem internet agora — o aviso vai ser enviado assim que sincronizar.");
  }
}

// ===== SOLICITAR MATERIAL AO ESTOQUE CENTRAL =====
async function carregarCatalogoCentral() {
  try {
    const r = await fetch(`${API_URL}/materiais`);
    catalogoCentralCache = await r.json();
    salvarEstado();
  } catch (e) {
    // offline: mantém cache
  }
  const sel = document.getElementById("solic-material");
  sel.innerHTML = catalogoCentralCache.map(m =>
    `<option value="${m.id}">${m.nome} (${m.qtd_atual} ${m.unidade} no central)</option>`
  ).join("");
}

async function solicitarMaterial() {
  const material_id = parseInt(document.getElementById("solic-material").value);
  const quantidade = parseFloat(document.getElementById("solic-qtd").value);
  const observacao = document.getElementById("solic-obs").value.trim();
  const msg = document.getElementById("solic-msg");
  if (!material_id || !quantidade || quantidade <= 0) { alert("Escolha o material e uma quantidade válida"); return; }

  const client_uuid = uuid();
  const payload = { tecnico_id: tecnico.id, material_id, quantidade, observacao, client_uuid };

  try {
    await fetch(`${API_URL}/solicitacoes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    msg.style.color = "#86efac";
    msg.textContent = "Solicitação enviada! Aguardando aprovação do estoque.";
  } catch (e) {
    enfileirar({ tipo: "criar_solicitacao", payload });
    msg.style.color = "#fdba74";
    msg.textContent = "Sem internet agora — vai enviar assim que sincronizar.";
  }
  document.getElementById("solic-qtd").value = "";
  document.getElementById("solic-obs").value = "";
  await carregarMinhasSolicitacoes();
}

async function carregarMinhasSolicitacoes() {
  try {
    const r = await fetch(`${API_URL}/tecnicos/${tecnico.id}/solicitacoes`);
    minhasSolicitacoesCache = await r.json();
    salvarEstado();
  } catch (e) {
    // offline: mantém cache
  }
  renderizarMinhasSolicitacoes();
}

function renderizarMinhasSolicitacoes() {
  const div = document.getElementById("lista-minhas-solicitacoes");
  const iconeStatus = { pendente: "⏳", aprovada: "✅", rejeitada: "❌" };
  div.innerHTML = minhasSolicitacoesCache.length
    ? minhasSolicitacoesCache.map(s => `
        <div class="item-lista"><span>${s.material} — ${s.quantidade}</span>
          <span style="font-size:12px;">${iconeStatus[s.status] || ""} ${s.status}</span></div>
      `).join("")
    : "";
}

// ===== ORDEM DE SERVIÇO =====
async function abrirOrdem() {
  const tipo = document.getElementById("os-tipo").value;
  const local = document.getElementById("os-local").value.trim();
  const nome_cliente = document.getElementById("os-nome-cliente").value.trim();
  const endereco = document.getElementById("os-endereco").value.trim();
  const prioridade = document.getElementById("os-prioridade").checked;
  const obs = document.getElementById("os-obs").value.trim();
  if (!local) { alert("Informe o cliente/local"); return; }

  const client_uuid = uuid();
  const { lat, lon } = await obterLocalizacao();
  const payload = {
    tecnico_id: tecnico.id, tipo, cliente_local: local,
    nome_cliente: nome_cliente || null, endereco: endereco || null,
    prioridade, observacoes: obs, lat, lon, client_uuid,
  };

  osAtiva = {
    id_servidor: null, client_uuid, tipo, cliente_local: local,
    nome_cliente: nome_cliente || null, endereco: endereco || null,
    prioridade, fase: "deslocamento", materiais: [],
  };

  enfileirar({ tipo: "criar_ordem", payload });
  salvarEstado();
  document.getElementById("os-nome-cliente").value = "";
  document.getElementById("os-endereco").value = "";
  document.getElementById("os-prioridade").checked = false;
  mostrarOsAtiva();
  await sincronizarFila();
}

function mostrarOsAtiva() {
  document.getElementById("card-os-ativa").classList.remove("oculto");
  document.getElementById("os-ativa-local").textContent =
    (osAtiva.prioridade ? "🔴 " : "") + (osAtiva.tipo === "preventiva" ? "🛠️ " : "") + osAtiva.cliente_local;

  const emDeslocamento = osAtiva.fase === "deslocamento";
  document.getElementById("fase-deslocamento").classList.toggle("oculto", !emDeslocamento);
  document.getElementById("fase-em-andamento").classList.toggle("oculto", emDeslocamento);
  document.getElementById("os-ativa-status").textContent =
    emDeslocamento ? "🚗 A caminho do local" : "🔧 Atendimento em andamento";

  // checklist só faz sentido pra manutenção (instalação nova não tem "conector antigo" pra limpar)
  document.getElementById("checklist-area").classList.toggle("oculto", osAtiva.tipo === "instalacao");

  // mostra o botão de ver a rota do cabo se esse cliente tiver uma cadastrada
  const areaRota = document.getElementById("rota-cabo-area");
  if (osAtiva.cliente_id) {
    fetch(`${API_URL}/clientes/${osAtiva.cliente_id}`).then(r => r.json()).then(c => {
      areaRota.classList.toggle("oculto", !c.tem_imagem_rota);
    }).catch(() => areaRota.classList.add("oculto"));
  } else {
    areaRota.classList.add("oculto");
  }

  if (!emDeslocamento) renderizarItensOs();
}

function mostrarRotaCabo() {
  const img = document.getElementById("rota-cabo-imagem");
  if (img.classList.contains("oculto")) {
    img.src = `${API_URL}/clientes/${osAtiva.cliente_id}/rota-cabo`;
    img.classList.remove("oculto");
  } else {
    img.classList.add("oculto");
  }
}

function adicionarMaterial() {
  const materialId = parseInt(document.getElementById("select-material").value);
  const qtd = parseFloat(document.getElementById("qtd-material").value);
  if (!materialId) { alert("Você não tem materiais no seu estoque pessoal pra usar"); return; }
  if (!qtd || qtd <= 0) { alert("Informe uma quantidade válida"); return; }

  const material = estoquePessoalCache.find(m => m.material_id === materialId);
  if (material && qtd > material.qtd_atual) {
    if (!confirm(`Você tem só ${material.qtd_atual} ${material.unidade} desse item. Registrar mesmo assim?`)) return;
  }

  const client_uuid = uuid();
  osAtiva.materiais.push({
    client_uuid, material_id: materialId, nome: material ? material.nome : "material",
    quantidade: qtd, sincronizado: false,
  });

  // atualiza cache local otimisticamente, pra próxima adição já refletir
  if (material) material.qtd_atual -= qtd;

  enfileirar({
    tipo: "registrar_material",
    payload: {
      ordem_id: osAtiva.id_servidor, ordem_client_uuid: osAtiva.client_uuid,
      material_id: materialId, quantidade: qtd, client_uuid,
    },
  });

  document.getElementById("qtd-material").value = "";
  salvarEstado();
  preencherSelectMaterial();
  renderizarMeuSaldo();
  renderizarItensOs();
  sincronizarFila();
}

function renderizarItensOs() {
  const div = document.getElementById("lista-itens-os");
  let html = "";
  osAtiva.materiais.forEach(m => {
    html += `<div class="item-lista"><span>${m.nome} — ${m.quantidade}</span>
      ${m.sincronizado ? "" : '<span class="pendente">aguardando sync</span>'}</div>`;
  });
  div.innerHTML = html || "<p style='color:#64748b;font-size:13px;'>Nenhum item ainda.</p>";
  renderizarFotosOs();
}

// ===== FOTOS DA ATIVIDADE =====
function fotoSelecionada(event) {
  const arquivo = event.target.files[0];
  event.target.value = ""; // permite selecionar a mesma foto de novo depois
  if (!arquivo || !osAtiva) return;

  const img = new Image();
  const leitor = new FileReader();
  leitor.onload = (e) => {
    img.onload = () => {
      // reduz o tamanho antes de guardar, pra não pesar a fila offline
      const MAX_LARGURA = 1024;
      const escala = Math.min(1, MAX_LARGURA / img.width);
      const canvas = document.createElement("canvas");
      canvas.width = img.width * escala;
      canvas.height = img.height * escala;
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      const base64 = canvas.toDataURL("image/jpeg", 0.7);

      const client_uuid = uuid();
      if (!osAtiva.fotos) osAtiva.fotos = [];
      osAtiva.fotos.push({ client_uuid, base64, sincronizada: false });

      enfileirar({
        tipo: "anexar_foto",
        payload: {
          ordem_id: osAtiva.id_servidor, ordem_client_uuid: osAtiva.client_uuid,
          imagem_base64: base64, client_uuid,
        },
      });

      salvarEstado();
      renderizarFotosOs();
      sincronizarFila();
    };
    img.src = e.target.result;
  };
  leitor.readAsDataURL(arquivo);
}

function renderizarFotosOs() {
  const div = document.getElementById("lista-fotos-os");
  if (!div || !osAtiva) return;
  const fotos = osAtiva.fotos || [];
  div.innerHTML = fotos.map(f => `
    <div style="position:relative;">
      <img src="${f.base64}" style="width:80px; height:80px; object-fit:cover; border-radius:8px;">
      ${f.sincronizada ? "" : '<span style="position:absolute; bottom:2px; right:2px; background:#7c2d12; color:#fdba74; font-size:10px; padding:1px 5px; border-radius:6px;">pendente</span>'}
    </div>
  `).join("");
}

async function fecharOrdem() {
  if (!confirm("Finalizar esta OS? Você não poderá mais adicionar itens, e o relatório em PDF vai ser gerado.")) return;
  const idServidor = osAtiva.id_servidor, clientUuid = osAtiva.client_uuid;
  const checklist = {
    checklist_limpar_conector: document.getElementById("chk-limpar-conector").checked,
    checklist_testar_sinal: document.getElementById("chk-testar-sinal").checked,
    checklist_verificar_otdr: document.getElementById("chk-verificar-otdr").checked,
  };
  osAtiva = null;
  salvarEstado();
  document.getElementById("card-os-ativa").classList.add("oculto");

  const { lat, lon } = await obterLocalizacao();
  enfileirar({
    tipo: "fechar_ordem",
    payload: { ordem_id: idServidor, ordem_client_uuid: clientUuid, lat, lon, ...checklist },
  });
  await sincronizarFila();
}

// ===== FILA OFFLINE / SINCRONIZAÇÃO =====
// Cada ação fica na fila até o backend confirmar. Isso garante que nada se
// perde quando o técnico está numa fazenda sem sinal — ele continua
// trabalhando normalmente e tudo sincroniza sozinho depois.

function enfileirar(acao) {
  acao.id = uuid();
  fila.push(acao);
  salvarEstado();
  atualizarBadgeFila();
}

function atualizarBadgeFila() {
  const badge = document.getElementById("fila-contador");
  const lista = document.getElementById("lista-fila");
  if (fila.length > 0) {
    badge.textContent = fila.length;
    badge.classList.remove("oculto");
  } else {
    badge.classList.add("oculto");
  }
  lista.innerHTML = fila.length
    ? fila.map(a => `<div>⏳ ${a.tipo}</div>`).join("")
    : "<span style='color:#64748b;'>tudo sincronizado</span>";
}

// mapa client_uuid da OS -> id real no servidor, pra resolver dependências
let mapaOrdens = JSON.parse(localStorage.getItem("mapa_ordens") || "{}");

async function sincronizarFila() {
  if (!navigator.onLine || fila.length === 0) { atualizarBadgeFila(); return; }

  const restantes = [];
  for (const acao of fila) {
    try {
      if (acao.tipo === "criar_ordem") {
        const r = await fetch(`${API_URL}/ordens`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(acao.payload),
        });
        if (!r.ok) throw new Error();
        const ordem = await r.json();
        mapaOrdens[acao.payload.client_uuid] = ordem.id;

      } else if (acao.tipo === "deslocamento") {
        const ordemId = acao.payload.ordem_id || mapaOrdens[acao.payload.ordem_client_uuid];
        if (!ordemId) throw new Error("ordem ainda não sincronizada");
        const r = await fetch(`${API_URL}/ordens/${ordemId}/deslocamento`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat: acao.payload.lat, lon: acao.payload.lon }),
        });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "iniciar_ordem") {
        const ordemId = acao.payload.ordem_id || mapaOrdens[acao.payload.ordem_client_uuid];
        if (!ordemId) throw new Error("ordem ainda não sincronizada");
        const r = await fetch(`${API_URL}/ordens/${ordemId}/iniciar`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat: acao.payload.lat, lon: acao.payload.lon }),
        });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "registrar_material") {
        const ordemId = acao.payload.ordem_id || mapaOrdens[acao.payload.ordem_client_uuid];
        if (!ordemId) throw new Error("ordem ainda não sincronizada"); // tenta de novo depois
        const r = await fetch(`${API_URL}/movimentacoes`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ordem_id: ordemId, material_id: acao.payload.material_id,
            quantidade: acao.payload.quantidade, client_uuid: acao.payload.client_uuid,
          }),
        });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "fechar_ordem") {
        const ordemId = acao.payload.ordem_id || mapaOrdens[acao.payload.ordem_client_uuid];
        if (!ordemId) throw new Error("ordem ainda não sincronizada");
        const r = await fetch(`${API_URL}/ordens/${ordemId}/fechar`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            lat: acao.payload.lat, lon: acao.payload.lon,
            checklist_limpar_conector: acao.payload.checklist_limpar_conector,
            checklist_testar_sinal: acao.payload.checklist_testar_sinal,
            checklist_verificar_otdr: acao.payload.checklist_verificar_otdr,
          }),
        });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "confirmar_transferencia") {
        const r = await fetch(`${API_URL}/transferencias/${acao.payload.id}/confirmar`, { method: "POST" });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "recusar_transferencia") {
        const r = await fetch(`${API_URL}/transferencias/${acao.payload.id}/recusar`, { method: "POST" });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "notificar_problema") {
        const r = await fetch(`${API_URL}/ferramentas/avisos`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(acao.payload),
        });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "criar_solicitacao") {
        const r = await fetch(`${API_URL}/solicitacoes`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(acao.payload),
        });
        if (!r.ok) throw new Error();

      } else if (acao.tipo === "anexar_foto") {
        const ordemId = acao.payload.ordem_id || mapaOrdens[acao.payload.ordem_client_uuid];
        if (!ordemId) throw new Error("ordem ainda não sincronizada");
        const r = await fetch(`${API_URL}/ordens/${ordemId}/fotos`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ imagem_base64: acao.payload.imagem_base64, client_uuid: acao.payload.client_uuid }),
        });
        if (!r.ok) throw new Error();
        // marca a foto como sincronizada no cache local da OS ativa, se ainda for a mesma
        if (osAtiva && osAtiva.fotos) {
          const foto = osAtiva.fotos.find(f => f.client_uuid === acao.payload.client_uuid);
          if (foto) foto.sincronizada = true;
        }
      }
      // ação sincronizada com sucesso -> não entra em "restantes"
    } catch (e) {
      restantes.push(acao); // mantém na fila, tenta de novo na próxima sincronização
    }
  }
  fila = restantes;
  localStorage.setItem("mapa_ordens", JSON.stringify(mapaOrdens));
  salvarEstado();
  atualizarBadgeFila();
  await carregarTudo(); // atualiza estoque pessoal/transferências/ferramentas na tela
  if (osAtiva) renderizarItensOs(); // atualiza status "pendente" das fotos/materiais já sincronizados
}

// tenta sincronizar periodicamente (cobre o caso de "voltou o sinal" sem evento online)
setInterval(sincronizarFila, 15000);

// atualiza OS/transferências/ferramentas/solicitações automaticamente, mesmo
// sem nada pendente na fila — assim o técnico vê o que o admin mandou sem
// precisar sair e entrar do app de novo
setInterval(() => {
  if (tecnico && navigator.onLine) {
    carregarPendentes();
    carregarTransferencias();
    carregarMinhasFerramentas();
    carregarMinhasSolicitacoes();
  }
}, 20000);

// ===== INICIALIZAÇÃO =====
function mostrarTelaPrincipal() {
  document.getElementById("tela-login").classList.add("oculto");
  document.getElementById("tela-principal").classList.remove("oculto");
  document.getElementById("tabbar").classList.remove("oculto");
  document.getElementById("nome-tecnico").textContent = `👤 ${tecnico.nome}${tecnico.is_adm ? " (ADM)" : ""}`;
  document.getElementById("card-os-avulsa").classList.toggle("oculto", !tecnico.is_adm);
  preencherSelectMaterial();
  renderizarMeuSaldo();
  renderizarPendentes();
  renderizarTransferencias();
  renderizarMinhasFerramentas();
  renderizarMinhasSolicitacoes();
  if (osAtiva) mostrarOsAtiva();
  atualizarBadgeFila();
}

(async function init() {
  atualizarStatusConexao();
  if (tecnico) {
    mostrarTelaPrincipal();
    await carregarTudo();
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
})();
