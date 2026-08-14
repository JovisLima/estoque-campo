// Endereço do backend — troque aqui quando for apontar pro servidor de
// produção (ex: "https://estoque.suaempresa.com.br").
const API_URL = "http://localhost:8000";

let adminToken = localStorage.getItem("admin_token") || "";
let adminAtual = JSON.parse(localStorage.getItem("admin_atual") || "null"); // {id, nome, login, papel}
let adminLogin = adminAtual?.login || "";
let tecnicosCache = [];
let ferramentasDisponiveisCache = [];

function authHeaders() {
  const resultado = {};

  if (adminToken) {
    resultado["Authorization"] = `Bearer ${adminToken}`;
  }

  return resultado;
}

function headers() {
  return {
    ...authHeaders(),
    "Content-Type": "application/json",
  };
}

async function carregarFotoTecnicoAdmin(img, tecnicoId) {
  try {
    const resposta = await fetch(
      `${API_URL}/admin/tecnicos/${tecnicoId}/foto-perfil`,
      { headers: headers() }
    );

    if (!resposta.ok) {
      throw new Error(`HTTP ${resposta.status}`);
    }

    const blob = await resposta.blob();
    const objectUrl = URL.createObjectURL(blob);

    img.dataset.objectUrl = objectUrl;
    img.src = objectUrl;
  } catch (erro) {
    console.error(
      `Erro ao carregar foto do tecnico ${tecnicoId}:`,
      erro
    );

    img.style.display = "none";
  }
}

// Abas que só o papel "gerencia" pode ver. Almoxarifado só mexe em
// estoque/transferências/solicitações/avisos.
const ABAS_SOMENTE_GERENCIA = ["ordens", "tecnicos", "financeiro", "usuarios", "clientes"];

// ===== LOGIN =====
async function fazerLoginAdmin() {
  const login = document.getElementById("admin-login").value.trim();
  const senha = document.getElementById("admin-senha").value;
  const erroEl = document.getElementById("login-erro");
  try {
    const r = await fetch(`${API_URL}/admin/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login, senha }),
    });
    if (!r.ok) throw new Error("Login ou senha incorretos");
    const dadosLogin = await r.json();

    adminToken = dadosLogin.access_token;

    adminAtual = {
      id: dadosLogin.id,
      nome: dadosLogin.nome,
      login: dadosLogin.login,
      papel: dadosLogin.papel,
      ativo: dadosLogin.ativo,
    };

    adminLogin = adminAtual.login;

    localStorage.setItem("admin_token", adminToken);
    localStorage.setItem("admin_atual", JSON.stringify(adminAtual));

    // Remove credenciais antigas caso existam de versoes anteriores.
    localStorage.removeItem("admin_login");
    localStorage.removeItem("admin_senha");
    entrarNoApp();
    await carregarTudo();
    await carregarDashboard();
  } catch (e) {
    erroEl.textContent = e.message;
  }
}

function entrarNoApp() {
  document.getElementById("tela-login").style.display = "none";
  document.getElementById("app").style.display = "flex";
  document.getElementById("nome-admin-atual").textContent =
    `${adminAtual.nome} (${adminAtual.papel === "gerencia" ? "Gerência" : "Almoxarifado"})`;

  // esconde do menu lateral as abas que esse papel não pode acessar
  const somenteGerencia = adminAtual.papel === "gerencia";
  ABAS_SOMENTE_GERENCIA.forEach(aba => {
    const el = document.querySelector(`.aba[data-aba="${aba}"]`);
    if (el) el.classList.toggle("oculto", !somenteGerencia);
  });
  document.querySelectorAll(".grupo-gerencia.grupo-titulo").forEach(el => {
    el.classList.toggle("oculto", !somenteGerencia);
  });
  // se a aba ativa hoje não é permitida, volta pro Estoque
  const abaAtiva = document.querySelector(".aba.ativa");
  if (abaAtiva && ABAS_SOMENTE_GERENCIA.includes(abaAtiva.dataset.aba) && !somenteGerencia) {
    mudarAba("estoque");
  }
}

function logoutAdmin() {
  adminAtual = null;
  adminLogin = "";
  adminToken = "";

  localStorage.removeItem("admin_token");
  localStorage.removeItem("admin_atual");

  // Limpeza de credenciais antigas.
  localStorage.removeItem("admin_login");
  localStorage.removeItem("admin_senha");

  location.reload();
}

(async function initAuto() {
  if (!adminToken) {
    return;
  }

  const r = await fetch(`${API_URL}/admin/me`, {
    headers: headers(),
  }).catch(() => null);

  if (r && r.ok) {
    adminAtual = await r.json();
    adminLogin = adminAtual.login;

    localStorage.setItem("admin_atual", JSON.stringify(adminAtual));

    entrarNoApp();
    await carregarTudo();
    await carregarDashboard();
    return;
  }

  // Token ausente, expirado ou invalido.
  adminToken = "";
  adminAtual = null;
  adminLogin = "";

  localStorage.removeItem("admin_token");
  localStorage.removeItem("admin_atual");

  // Remove qualquer credencial do sistema antigo.
  localStorage.removeItem("admin_login");
  localStorage.removeItem("admin_senha");
})();

// ===== NAVEGAÇÃO ENTRE ABAS =====
function mudarAba(aba) {
  document.querySelectorAll(".aba").forEach(el => el.classList.toggle("ativa", el.dataset.aba === aba));
  ["inicio", "estoque", "transferencias", "solicitacoes", "ordens", "tecnicos", "avisos", "financeiro", "usuarios", "clientes"].forEach(a => {
    const painel = document.getElementById(`painel-${a}`);
    if (painel) painel.classList.toggle("oculto", a !== aba);
  });
  if (aba === "inicio") carregarDashboard();
  if (aba === "financeiro") carregarFinanceiro();
  if (aba === "usuarios") carregarAdminUsuarios();
  if (aba === "clientes") carregarClientes();
  if (aba === "ordens") carregarClientesParaSelect();
}

async function carregarTudo() {
  const chamadas = [
    carregarEstoque(), carregarTecnicos(), carregarTransferencias(),
    carregarAvisos(), carregarSolicitacoes(),
  ];
  if (adminAtual && adminAtual.papel === "gerencia") {
    chamadas.push(carregarOrdens());
  }
  await Promise.all(chamadas);
}

// ===== DASHBOARD (Início) =====
async function carregarDashboard() {
  const cardsDiv = document.getElementById("dashboard-cards");
  const prioridadesDiv = document.getElementById("dashboard-prioridades");
  const somenteGerencia = adminAtual && adminAtual.papel === "gerencia";

  const [rBaixoEstoque, rSolicitacoes, rAvisos, rTransferencias] = await Promise.all([
    fetch(`${API_URL}/materiais/baixo-estoque`, { headers: headers() }),
    fetch(`${API_URL}/admin/solicitacoes?status=pendente`, { headers: headers() }),
    fetch(`${API_URL}/admin/avisos?status=aberto`, { headers: headers() }),
    fetch(`${API_URL}/admin/transferencias?status=pendente`, { headers: headers() }),
  ]);
  const baixoEstoque = await rBaixoEstoque.json();
  const solicitacoes = await rSolicitacoes.json();
  const avisos = await rAvisos.json();
  const transferencias = await rTransferencias.json();

  let cards = `
    <div class="painel" style="margin-bottom:0; cursor:pointer;" onclick="mudarAba('estoque')">
      <div style="font-size:13px; color:#94a3b8;">⚠️ Estoque baixo</div>
      <div style="font-size:28px; font-weight:700; ${baixoEstoque.length > 0 ? 'color:#fca5a5;' : ''}">${baixoEstoque.length}</div>
    </div>
    <div class="painel" style="margin-bottom:0; cursor:pointer;" onclick="mudarAba('solicitacoes')">
      <div style="font-size:13px; color:#94a3b8;">📦 Solicitações pendentes</div>
      <div style="font-size:28px; font-weight:700; ${solicitacoes.length > 0 ? 'color:#fdba74;' : ''}">${solicitacoes.length}</div>
    </div>
    <div class="painel" style="margin-bottom:0; cursor:pointer;" onclick="mudarAba('transferencias')">
      <div style="font-size:13px; color:#94a3b8;">📥 Transferências aguardando confirmação</div>
      <div style="font-size:28px; font-weight:700;">${transferencias.length}</div>
    </div>
    <div class="painel" style="margin-bottom:0; cursor:pointer;" onclick="mudarAba('avisos')">
      <div style="font-size:13px; color:#94a3b8;">🔧 Avisos de ferramentas/EPIs</div>
      <div style="font-size:28px; font-weight:700; ${avisos.length > 0 ? 'color:#fdba74;' : ''}">${avisos.length}</div>
    </div>
  `;

  let prioridadesHtml = "";
  if (somenteGerencia) {
    const rOrdens = await fetch(`${API_URL}/admin/ordens`, { headers: headers() });
    const ordens = await rOrdens.json();
    const prioritarias = ordens.filter(o => o.prioridade && o.status !== "fechada");

    const rFin = await fetch(`${API_URL}/admin/financeiro/resumo`, { headers: headers() });
    const fin = await rFin.json();

    cards += `
      <div class="painel" style="margin-bottom:0; cursor:pointer;" onclick="mudarAba('ordens')">
        <div style="font-size:13px; color:#94a3b8;">🔴 OS prioritárias em aberto</div>
        <div style="font-size:28px; font-weight:700; ${prioritarias.length > 0 ? 'color:#fca5a5;' : ''}">${prioritarias.length}</div>
      </div>
      <div class="painel" style="margin-bottom:0; cursor:pointer;" onclick="mudarAba('financeiro')">
        <div style="font-size:13px; color:#94a3b8;">💰 A receber (pendente)</div>
        <div style="font-size:22px; font-weight:700; color:#86efac;">${fin.a_receber_pendente.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</div>
      </div>
      <div class="painel" style="margin-bottom:0; cursor:pointer;" onclick="mudarAba('financeiro')">
        <div style="font-size:13px; color:#94a3b8;">💸 A pagar (pendente)</div>
        <div style="font-size:22px; font-weight:700; color:#fca5a5;">${fin.a_pagar_pendente.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</div>
      </div>
    `;

    if (prioritarias.length > 0) {
      prioridadesHtml = `
        <div class="painel">
          <h3 style="margin-top:0;">🔴 Ordens de Serviço prioritárias em aberto</h3>
          <table>
            <thead><tr><th>ID</th><th>Cliente/Local</th><th>Técnico</th><th>Status</th></tr></thead>
            <tbody>
              ${prioritarias.map(o => `
                <tr><td>#${o.id}</td><td>${o.cliente_local}</td><td>${o.tecnico}</td>
                <td class="status-${o.status}">${o.status.replace("_"," ")}</td></tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;
    }
  }

  cardsDiv.innerHTML = cards;
  prioridadesDiv.innerHTML = prioridadesHtml;

  // sugestão de compra: informativa, não mexe em nada sozinha
  const rSugestoes = await fetch(`${API_URL}/admin/materiais/sugestao-compra`, { headers: headers() });
  const sugestoes = await rSugestoes.json();
  const sugestoesDiv = document.getElementById("dashboard-sugestoes");
  sugestoesDiv.innerHTML = sugestoes.length ? `
    <div class="painel">
      <h3 style="margin-top:0;">💡 Sugestão de compra</h3>
      <p style="color:#94a3b8; font-size:13px;">
        Baseado no consumo médio dos últimos 90 dias. É só uma sugestão —
        não cria nada automaticamente no Financeiro nem no estoque.
      </p>
      <table>
        <thead><tr><th>Material</th><th>Estoque atual</th><th>Consumo médio/mês</th><th>Sugestão de compra</th></tr></thead>
        <tbody>
          ${sugestoes.map(s => `
            <tr>
              <td>${s.nome}</td>
              <td class="alerta">${s.qtd_atual} ${s.unidade}</td>
              <td>${s.consumo_mensal_medio} ${s.unidade}/mês</td>
              <td><strong>${s.sugestao_compra} ${s.unidade}</strong></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  ` : "";
}

// ===== FINANCEIRO (só gerência) =====
let filtroFinTipo = null, filtroFinStatus = null;

async function carregarFinanceiro() {
  const r = await fetch(`${API_URL}/admin/financeiro/resumo`, { headers: headers() });
  const resumo = await r.json();
  document.getElementById("fin-a-pagar").textContent =
    resumo.a_pagar_pendente.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  document.getElementById("fin-a-receber").textContent =
    resumo.a_receber_pendente.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  document.getElementById("fin-a-pagar-atrasado").textContent =
    resumo.a_pagar_atrasado > 0 ? `⚠️ ${resumo.a_pagar_atrasado.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })} atrasado` : "";
  document.getElementById("fin-a-receber-atrasado").textContent =
    resumo.a_receber_atrasado > 0 ? `⚠️ ${resumo.a_receber_atrasado.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })} atrasado` : "";

  let url = `${API_URL}/admin/financeiro?`;
  if (filtroFinTipo) url += `tipo=${filtroFinTipo}&`;
  if (filtroFinStatus) url += `status=${filtroFinStatus}&`;
  const rc = await fetch(url, { headers: headers() });
  const contas = await rc.json();

  document.getElementById("tabela-financeiro").innerHTML = contas.length ? contas.map(c => `
    <tr style="${c.atrasada ? 'background:rgba(220,38,38,0.08);' : ''}">
      <td>${c.tipo === "pagar" ? "🔴 Pagar" : "🟢 Receber"}</td>
      <td>${c.descricao}</td>
      <td>${c.categoria || "-"}</td>
      <td>${c.valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</td>
      <td>${new Date(c.vencimento + "T00:00:00").toLocaleDateString("pt-BR")}${c.atrasada ? " ⚠️" : ""}</td>
      <td class="status-${c.status === 'pago' ? 'fechada' : c.status === 'cancelado' ? 'baixada' : 'pendente'}">${c.status}</td>
      <td>
        ${c.status === "pendente" ? `
          <button class="pequeno" onclick="marcarContaPaga(${c.id})">✅ Pago</button>
          <button class="pequeno perigo" onclick="cancelarConta(${c.id})">Cancelar</button>
        ` : ""}
      </td>
    </tr>
  `).join("") : `<tr><td colspan="7" style="color:#64748b;">Nenhuma conta encontrada.</td></tr>`;
}

function filtrarFinanceiro(tipo, status) {
  filtroFinTipo = tipo; filtroFinStatus = status;
  carregarFinanceiro();
}

async function criarContaFinanceira() {
  const tipo = document.getElementById("fin-tipo").value;
  const descricao = document.getElementById("fin-descricao").value.trim();
  const categoria = document.getElementById("fin-categoria").value.trim();
  const valor = parseFloat(document.getElementById("fin-valor").value);
  const vencimento = document.getElementById("fin-vencimento").value;
  const observacoes = document.getElementById("fin-observacoes").value.trim();
  const msg = document.getElementById("fin-msg");

  if (!descricao || !valor || valor <= 0 || !vencimento) {
    alert("Preencha descrição, valor e vencimento"); return;
  }

  const r = await fetch(`${API_URL}/admin/financeiro`, {
    method: "POST", headers: headers(),
    body: JSON.stringify({ tipo, descricao, valor, vencimento, categoria: categoria || null, observacoes: observacoes || null }),
  });
  if (!r.ok) { msg.style.color = "#f87171"; msg.textContent = "Erro ao criar conta"; return; }

  msg.style.color = "#86efac";
  msg.textContent = "Conta adicionada!";
  document.getElementById("fin-descricao").value = "";
  document.getElementById("fin-categoria").value = "";
  document.getElementById("fin-valor").value = "";
  document.getElementById("fin-vencimento").value = "";
  document.getElementById("fin-observacoes").value = "";
  carregarFinanceiro();
}

async function marcarContaPaga(id) {
  await fetch(`${API_URL}/admin/financeiro/${id}/marcar-pago`, { method: "POST", headers: headers() });
  carregarFinanceiro();
}

async function cancelarConta(id) {
  if (!confirm("Cancelar essa conta?")) return;
  await fetch(`${API_URL}/admin/financeiro/${id}/cancelar`, { method: "POST", headers: headers() });
  carregarFinanceiro();
}

// ===== USUÁRIOS DO PAINEL ADMIN (só gerência) =====
async function carregarAdminUsuarios() {
  const r = await fetch(`${API_URL}/admin/usuarios`, { headers: headers() });
  const usuarios = await r.json();
  document.getElementById("tabela-admin-usuarios").innerHTML = usuarios.map(u => `
    <tr>
      <td>${u.nome}</td><td>${u.login}</td>
      <td>
        <select onchange="alterarPapelAdmin(${u.id}, this.value)" ${u.login === adminLogin ? "disabled" : ""}>
          <option value="almoxarifado" ${u.papel === "almoxarifado" ? "selected" : ""}>Almoxarifado</option>
          <option value="gerencia" ${u.papel === "gerencia" ? "selected" : ""}>Gerência</option>
        </select>
      </td>
      <td>${u.ativo ? "✅ ativo" : "🚫 desativado"}</td>
      <td>
        ${u.login !== adminLogin ? `
          <button class="pequeno secundario" onclick="alterarAtivoAdmin(${u.id}, ${!u.ativo})">
            ${u.ativo ? "Desativar" : "Reativar"}
          </button>
        ` : `<span style="color:#64748b; font-size:12px;">você</span>`}
      </td>
    </tr>
  `).join("");
}

async function criarAdminUsuario() {
  const nome = document.getElementById("usr-nome").value.trim();
  const login = document.getElementById("usr-login").value.trim();
  const senha = document.getElementById("usr-senha").value;
  const papel = document.getElementById("usr-papel").value;
  const msg = document.getElementById("usr-msg");
  if (!nome || !login || !senha) { alert("Preencha nome, login e senha"); return; }

  const r = await fetch(`${API_URL}/admin/usuarios`, {
    method: "POST", headers: headers(),
    body: JSON.stringify({ nome, login, senha, papel }),
  });
  if (!r.ok) {
    msg.style.color = "#f87171";
    msg.textContent = (await r.json()).detail || "Erro ao criar usuário";
    return;
  }
  msg.style.color = "#86efac";
  msg.textContent = `Usuário ${nome} cadastrado! Repasse o login e a senha pra ele acessar o painel.`;
  document.getElementById("usr-nome").value = "";
  document.getElementById("usr-login").value = "";
  document.getElementById("usr-senha").value = "";
  carregarAdminUsuarios();
}

async function alterarPapelAdmin(id, papel) {
  await fetch(`${API_URL}/admin/usuarios/${id}/papel`, {
    method: "POST", headers: headers(), body: JSON.stringify({ papel }),
  });
  carregarAdminUsuarios();
}

async function alterarAtivoAdmin(id, ativo) {
  await fetch(`${API_URL}/admin/usuarios/${id}/ativo`, {
    method: "POST", headers: headers(), body: JSON.stringify({ ativo }),
  });
  carregarAdminUsuarios();
}

// ===== ESTOQUE (central + ferramentas + pessoal dos técnicos) =====
async function carregarEstoque() {
  const r = await fetch(`${API_URL}/admin/estoque-completo`, { headers: headers() });
  const dados = await r.json();

  document.getElementById("tabela-materiais").innerHTML = dados.materiais.map(m => `
    <tr>
      <td>${m.nome}</td><td>${m.categoria || "-"}</td>
      <td class="${m.alerta ? "alerta" : ""}">${m.qtd_atual} ${m.unidade}</td>
      <td>${m.qtd_minima}</td>
      <td>${m.alerta ? "⚠️ estoque baixo" : ""}</td>
    </tr>
  `).join("");

  ferramentasDisponiveisCache = dados.ferramentas.filter(f => f.status === "disponivel");

  document.getElementById("tabela-ferramentas").innerHTML = dados.ferramentas.map(f => `
    <tr>
      <td>${f.categoria === "epi" ? "🦺" : "🔧"} ${f.nome}</td>
      <td>${f.categoria}</td>
      <td class="status-${f.status}">${f.status.replace("_", " ")}</td>
      <td>${f.tecnico_atual || "-"}</td>
      <td>
        ${f.status === "com_tecnico" || f.status === "em_transito" ? `<button class="pequeno secundario" onclick="devolverFerramenta(${f.id})">Devolver</button>` : ""}
        ${f.status !== "baixada" ? `<button class="pequeno perigo" onclick="baixarFerramenta(${f.id})">Dar baixa</button>` : ""}
        ${f.status === "disponivel" ? `<button class="pequeno secundario" onclick="ferramentaManutencao(${f.id})">Manutenção</button>` : ""}
      </td>
    </tr>
  `).join("");

  const sel = document.getElementById("entrada-material");
  sel.innerHTML = dados.materiais.map(m => `<option value="${m.id}">${m.nome}</option>`).join("");

  const selTransfMat = document.getElementById("transf-material");
  if (selTransfMat) selTransfMat.innerHTML = dados.materiais.map(m =>
    `<option value="${m.id}">${m.nome} (${m.qtd_atual} ${m.unidade} no central)</option>`
  ).join("");

  const selTransfFer = document.getElementById("transf-ferramenta");
  if (selTransfFer) selTransfFer.innerHTML = ferramentasDisponiveisCache.map(f =>
    `<option value="${f.id}">${f.categoria === "epi" ? "🦺" : "🔧"} ${f.nome}</option>`
  ).join("");

  const rp = await fetch(`${API_URL}/admin/estoque-pessoal-geral`, { headers: headers() });
  const pessoal = await rp.json();
  document.getElementById("tabela-estoque-pessoal").innerHTML = pessoal.length
    ? pessoal.map(i => `<tr><td>${i.tecnico}</td><td>${i.material}</td><td>${i.qtd_atual} ${i.unidade}</td></tr>`).join("")
    : `<tr><td colspan="3" style="color:#64748b;">Nenhum técnico tem material com ele no momento.</td></tr>`;
}

async function cadastrarMaterial() {
  const nome = document.getElementById("novo-mat-nome").value.trim();
  const categoria = document.getElementById("novo-mat-categoria").value.trim();
  const unidade = document.getElementById("novo-mat-unidade").value;
  const qtd_atual = parseFloat(document.getElementById("novo-mat-qtd").value) || 0;
  const qtd_minima = parseFloat(document.getElementById("novo-mat-minimo").value) || 0;
  const msg = document.getElementById("novo-mat-msg");
  if (!nome) { alert("Informe o nome do material"); return; }

  const r = await fetch(`${API_URL}/materiais`, {
    method: "POST", headers: headers(),
    body: JSON.stringify({ nome, categoria, unidade, qtd_atual, qtd_minima }),
  });
  if (!r.ok) {
    msg.style.color = "#f87171";
    msg.textContent = (await r.json()).detail || "Erro ao cadastrar material";
    return;
  }
  msg.style.color = "#86efac";
  msg.textContent = `"${nome}" cadastrado no estoque central!`;
  document.getElementById("novo-mat-nome").value = "";
  document.getElementById("novo-mat-categoria").value = "";
  document.getElementById("novo-mat-qtd").value = "0";
  document.getElementById("novo-mat-minimo").value = "0";
  carregarEstoque();
}

async function cadastrarFerramenta() {
  const nome = document.getElementById("nova-fer-nome").value.trim();
  const codigo_patrimonio = document.getElementById("nova-fer-codigo").value.trim() || null;
  const categoria = document.getElementById("nova-fer-categoria").value;
  const msg = document.getElementById("nova-fer-msg");
  if (!nome) { alert("Informe o nome da ferramenta/EPI"); return; }

  const r = await fetch(`${API_URL}/ferramentas`, {
    method: "POST", headers: headers(),
    body: JSON.stringify({ nome, codigo_patrimonio, categoria }),
  });
  if (!r.ok) {
    msg.style.color = "#f87171";
    msg.textContent = (await r.json()).detail || "Erro ao cadastrar";
    return;
  }
  msg.style.color = "#86efac";
  msg.textContent = `"${nome}" cadastrado!`;
  document.getElementById("nova-fer-nome").value = "";
  document.getElementById("nova-fer-codigo").value = "";
  carregarEstoque();
}

async function registrarEntrada() {
  const material_id = parseInt(document.getElementById("entrada-material").value);
  const quantidade = parseFloat(document.getElementById("entrada-qtd").value);
  if (!quantidade || quantidade <= 0) { alert("Informe uma quantidade válida"); return; }
  await fetch(`${API_URL}/materiais/entrada`, { method: "POST", headers: headers(), body: JSON.stringify({ material_id, quantidade }) });
  document.getElementById("entrada-qtd").value = "";
  carregarEstoque();
}

async function devolverFerramenta(id) {
  await fetch(`${API_URL}/admin/ferramentas/${id}/devolver`, { method: "POST", headers: headers() });
  carregarEstoque();
}
async function baixarFerramenta(id) {
  if (!confirm("Dar baixa definitiva neste item? Ele sai de circulação.")) return;
  await fetch(`${API_URL}/admin/ferramentas/${id}/baixar`, { method: "POST", headers: headers() });
  carregarEstoque();
}
async function ferramentaManutencao(id) {
  await fetch(`${API_URL}/admin/ferramentas/${id}/manutencao`, { method: "POST", headers: headers() });
  carregarEstoque();
}

// ===== TRANSFERÊNCIAS =====
function alternarTipoTransferencia() {
  const tipo = document.getElementById("transf-tipo").value;
  document.getElementById("transf-campos-material").classList.toggle("oculto", tipo !== "material");
  document.getElementById("transf-campos-ferramenta").classList.toggle("oculto", tipo !== "ferramenta");
}

async function enviarTransferencia() {
  const tecnico_id = parseInt(document.getElementById("transf-tecnico").value);
  const tipo = document.getElementById("transf-tipo").value;
  const msg = document.getElementById("transf-msg");
  if (!tecnico_id) { alert("Escolha o técnico"); return; }

  const payload = { tecnico_id, tipo };
  if (tipo === "material") {
    payload.material_id = parseInt(document.getElementById("transf-material").value);
    payload.quantidade = parseFloat(document.getElementById("transf-qtd").value);
    if (!payload.quantidade || payload.quantidade <= 0) { alert("Informe uma quantidade válida"); return; }
  } else {
    payload.ferramenta_id = parseInt(document.getElementById("transf-ferramenta").value);
    if (!payload.ferramenta_id) { alert("Escolha uma ferramenta/EPI disponível"); return; }
  }

  const r = await fetch(`${API_URL}/admin/transferencias`, { method: "POST", headers: headers(), body: JSON.stringify(payload) });
  if (!r.ok) {
    msg.style.color = "#f87171";
    msg.textContent = (await r.json()).detail || "Erro ao enviar";
    return;
  }
  msg.style.color = "#86efac";
  msg.textContent = "Enviado! Vai aparecer pro técnico confirmar o recebimento no app.";
  document.getElementById("transf-qtd").value = "";
  carregarEstoque();
  carregarTransferencias();
}

async function carregarTransferencias() {
  const r = await fetch(`${API_URL}/admin/transferencias`, { headers: headers() });
  const transferencias = await r.json();
  document.getElementById("tabela-transferencias").innerHTML = transferencias.map(t => `
    <tr>
      <td>${t.tecnico}</td><td>${t.tipo}</td><td>${t.item}</td>
      <td>${t.quantidade ?? "-"}</td>
      <td class="status-${t.status}">${t.status}</td>
    </tr>
  `).join("");
}

// ===== SOLICITAÇÕES DE MATERIAL (feitas pelos técnicos) =====
async function carregarSolicitacoes() {
  const r = await fetch(`${API_URL}/admin/solicitacoes?status=pendente`, { headers: headers() });
  const solicitacoes = await r.json();

  const badge = document.getElementById("badge-solicitacoes");
  if (solicitacoes.length > 0) { badge.textContent = solicitacoes.length; badge.classList.remove("oculto"); }
  else { badge.classList.add("oculto"); }

  document.getElementById("tabela-solicitacoes").innerHTML = solicitacoes.length ? solicitacoes.map(s => `
    <tr>
      <td>${s.tecnico}</td><td>${s.material}</td><td>${s.quantidade}</td>
      <td>${s.observacao || "-"}</td>
      <td>
        <button class="pequeno" onclick="responderSolicitacao(${s.id}, 'aprovar')">✅ Aprovar</button>
        <button class="pequeno secundario" onclick="responderSolicitacao(${s.id}, 'rejeitar')">Rejeitar</button>
      </td>
    </tr>
  `).join("") : `<tr><td colspan="5" style="color:#64748b;">Nenhuma solicitação pendente.</td></tr>`;
}

async function responderSolicitacao(id, acao) {
  const r = await fetch(`${API_URL}/admin/solicitacoes/${id}/${acao}`, { method: "POST", headers: headers() });
  if (!r.ok) { alert((await r.json()).detail || "Erro ao processar"); return; }
  carregarSolicitacoes();
  carregarEstoque();
}

// ===== TÉCNICOS =====
async function carregarTecnicos() {
  const rTodos = await fetch(`${API_URL}/admin/tecnicos`, { headers: headers() });
  tecnicosCache = await rTodos.json();

  let pendentes = [];
  if (adminAtual && adminAtual.papel === "gerencia") {
    const rPendentes = await fetch(`${API_URL}/admin/tecnicos/pendentes`, { headers: headers() });
    pendentes = await rPendentes.json();
  }

  const badge = document.getElementById("badge-pendentes");
  if (pendentes.length > 0) { badge.textContent = pendentes.length; badge.classList.remove("oculto"); }
  else { badge.classList.add("oculto"); }

  const painelPendentes = document.getElementById("painel-tecnicos-pendentes");
  if (pendentes.length > 0) {
    painelPendentes.classList.remove("oculto");
    document.getElementById("tabela-tecnicos-pendentes").innerHTML = pendentes.map(t => `
      <tr><td>${t.nome}</td><td>${t.login}</td>
        <td><input type="checkbox" id="adm-pendente-${t.id}" ${t.is_adm ? "checked" : ""} style="width:auto;"></td>
        <td><button class="pequeno" onclick="aprovarTecnico(${t.id})">✅ Aprovar</button></td></tr>
    `).join("");
  } else {
    painelPendentes.classList.add("oculto");
  }

  document.getElementById("tabela-tecnicos").innerHTML = tecnicosCache.map(t => `
    <tr>
      <td style="display:flex; align-items:center; gap:8px;">
        ${t.tem_foto_perfil
          ? `<img class="foto-tecnico-admin" data-tecnico-id="${t.id}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;">`
          : `<span style="width:28px;height:28px;border-radius:50%;background:#334155;display:inline-flex;align-items:center;justify-content:center;font-size:14px;">👤</span>`}
        ${t.nome}
      </td>
      <td>${t.login}${t.telefone ? `<br><span style="color:#94a3b8;font-size:12px;">${t.telefone}</span>` : ""}</td>
      <td>${t.aprovado ? "✅ aprovado" : "⏳ pendente"}</td>
      <td><input type="checkbox" ${t.is_adm ? "checked" : ""} style="width:auto;" onchange="alternarAdm(${t.id}, this.checked)"></td>
      <td>
        ${t.aprovado ? `<button class="pequeno secundario" onclick="verDetalheTecnico(${t.id})">Ver estoque</button>` : ""}
        <button class="pequeno secundario" onclick="abrirSeletorFoto(${t.id})">📷 Foto</button>
        <button class="pequeno secundario" onclick="resetarPinTecnico(${t.id}, '${t.nome.replace(/'/g, "")}')">🔑 Resetar PIN</button>
      </td>
    </tr>
  `).join("");

  document
    .querySelectorAll(".foto-tecnico-admin")
    .forEach((img) => {
      carregarFotoTecnicoAdmin(
        img,
        img.dataset.tecnicoId
      );
    });

  // só técnicos aprovados aparecem pra atribuir OS / receber transferência
  const aprovados = tecnicosCache.filter(t => t.aprovado);
  document.getElementById("os-tecnico").innerHTML = aprovados.map(t => `<option value="${t.id}">${t.nome}</option>`).join("");
  const selTransfTec = document.getElementById("transf-tecnico");
  if (selTransfTec) selTransfTec.innerHTML = aprovados.map(t => `<option value="${t.id}">${t.nome}</option>`).join("");
}

async function aprovarTecnico(id) {
  const checkboxAdm = document.getElementById(`adm-pendente-${id}`);
  if (checkboxAdm) {
    await fetch(`${API_URL}/admin/tecnicos/${id}/permissao`, {
      method: "POST", headers: headers(), body: JSON.stringify({ is_adm: checkboxAdm.checked }),
    });
  }
  await fetch(`${API_URL}/admin/tecnicos/${id}/aprovar`, { method: "POST", headers: headers() });
  carregarTecnicos();
}

async function alternarAdm(id, isAdm) {
  await fetch(`${API_URL}/admin/tecnicos/${id}/permissao`, {
    method: "POST", headers: headers(), body: JSON.stringify({ is_adm: isAdm }),
  });
  carregarTecnicos();
}

async function verDetalheTecnico(id) {
  const r = await fetch(`${API_URL}/admin/tecnicos/${id}/estoque`, { headers: headers() });
  const dados = await r.json();
  const div = document.getElementById("detalhe-tecnico");
  div.classList.remove("oculto");
  div.innerHTML = `
    <h3 style="margin-top:0;">📦 Estoque de ${dados.tecnico}</h3>
    <strong>Materiais</strong>
    <table>
      <thead><tr><th>Material</th><th>Quantidade</th></tr></thead>
      <tbody>
        ${dados.materiais.length
          ? dados.materiais.map(m => `<tr><td>${m.material}</td><td>${m.qtd_atual} ${m.unidade}</td></tr>`).join("")
          : `<tr><td colspan="2" style="color:#64748b;">Nenhum material com ele.</td></tr>`}
      </tbody>
    </table>
    <strong style="display:block; margin-top:16px;">Ferramentas / EPIs</strong>
    <table>
      <thead><tr><th>Item</th><th>Categoria</th></tr></thead>
      <tbody>
        ${dados.ferramentas.length
          ? dados.ferramentas.map(f => `<tr><td>${f.nome}</td><td>${f.categoria}</td></tr>`).join("")
          : `<tr><td colspan="2" style="color:#64748b;">Nenhuma ferramenta/EPI com ele.</td></tr>`}
      </tbody>
    </table>
    <button class="secundario" onclick="document.getElementById('detalhe-tecnico').classList.add('oculto')">Fechar</button>
  `;
}

async function criarTecnico() {
  const nome = document.getElementById("tec-nome").value.trim();
  const login = document.getElementById("tec-login").value.trim();
  const pin = document.getElementById("tec-pin").value.trim();
  const is_adm = document.getElementById("tec-is-adm").checked;
  const telefone = document.getElementById("tec-telefone").value.trim();
  const data_contratacao = document.getElementById("tec-data-contratacao").value;
  const arquivoFoto = document.getElementById("tec-foto").files[0];
  const msg = document.getElementById("tec-msg");
  if (!nome || !login || !pin) { alert("Preencha nome, login e PIN"); return; }

  const r = await fetch(`${API_URL}/admin/tecnicos`, {
    method: "POST", headers: headers(),
    body: JSON.stringify({ nome, login, pin, is_adm, telefone: telefone || null, data_contratacao: data_contratacao || null }),
  });
  if (!r.ok) {
    msg.style.color = "#f87171";
    msg.textContent = (await r.json()).detail || "Erro ao criar técnico";
    return;
  }
  const novoTecnico = await r.json();

  if (arquivoFoto) {
    const form = new FormData();
    form.append("arquivo", arquivoFoto);
    await fetch(`${API_URL}/admin/tecnicos/${novoTecnico.id}/foto-perfil`, {
      method: "POST", headers: authHeaders(), body: form,
    });
  }

  msg.style.color = "#86efac";
  msg.textContent = `Técnico ${nome} cadastrado, mas ainda precisa ser APROVADO (veja a lista acima) antes de conseguir logar no app.`;
  document.getElementById("tec-nome").value = "";
  document.getElementById("tec-login").value = "";
  document.getElementById("tec-pin").value = "";
  document.getElementById("tec-telefone").value = "";
  document.getElementById("tec-data-contratacao").value = "";
  document.getElementById("tec-foto").value = "";
  document.getElementById("tec-is-adm").checked = false;
  carregarTecnicos();
}

let tecnicoFotoAlvo = null;
function abrirSeletorFoto(id) {
  tecnicoFotoAlvo = id;
  document.getElementById("input-foto-tecnico").click();
}
async function fotoTecnicoSelecionada(event) {
  const arquivo = event.target.files[0];
  event.target.value = "";
  if (!arquivo || !tecnicoFotoAlvo) return;
  const form = new FormData();
  form.append("arquivo", arquivo);
  await fetch(`${API_URL}/admin/tecnicos/${tecnicoFotoAlvo}/foto-perfil`, {
    method: "POST", headers: authHeaders(), body: form,
  });
  carregarTecnicos();
}

async function resetarPinTecnico(id, nome) {
  const novoPin = prompt(`Novo PIN pra ${nome} (mínimo 4 dígitos):`);
  if (!novoPin) return;
  if (novoPin.length < 4) { alert("O PIN precisa ter pelo menos 4 dígitos"); return; }
  const r = await fetch(`${API_URL}/admin/tecnicos/${id}/resetar-pin`, {
    method: "POST", headers: headers(), body: JSON.stringify({ novo_pin: novoPin }),
  });
  if (!r.ok) { alert("Erro ao resetar PIN"); return; }
  alert(`PIN de ${nome} atualizado! Repasse o novo PIN "${novoPin}" pra ele.`);
}

// ===== AVISOS DE FERRAMENTAS/EPIS =====
async function carregarAvisos() {
  const r = await fetch(`${API_URL}/admin/avisos?status=aberto`, { headers: headers() });
  const avisos = await r.json();

  const badge = document.getElementById("badge-avisos");
  if (avisos.length > 0) { badge.textContent = avisos.length; badge.classList.remove("oculto"); }
  else { badge.classList.add("oculto"); }

  document.getElementById("tabela-avisos").innerHTML = avisos.length ? avisos.map(a => `
    <tr>
      <td>${a.ferramenta}</td><td>${a.tecnico}</td><td>${a.descricao}</td>
      <td>
        <button class="pequeno perigo" onclick="resolverAviso(${a.id}, 'baixar')">Dar baixa</button>
        <button class="pequeno secundario" onclick="resolverAviso(${a.id}, 'manutencao')">Manutenção</button>
        <button class="pequeno secundario" onclick="resolverAviso(${a.id}, 'devolver_uso')">Sem problema, manter em uso</button>
      </td>
    </tr>
  `).join("") : `<tr><td colspan="4" style="color:#64748b;">Nenhum aviso em aberto.</td></tr>`;
}

async function resolverAviso(id, acao) {
  await fetch(`${API_URL}/admin/avisos/${id}/resolver`, { method: "POST", headers: headers(), body: JSON.stringify({ acao }) });
  carregarAvisos();
  carregarEstoque();
}

// ===== ORDENS DE SERVIÇO =====
let filtroAtual = null;

function formatarMinutos(min) {
  if (min === null || min === undefined) return "-";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  return `${h}h${m > 0 ? m + "min" : ""}`;
}

async function carregarOrdens() {
  if (tecnicosCache.length === 0) {
    await carregarTecnicos();
  }

  const url = filtroAtual ? `${API_URL}/admin/ordens?status=${filtroAtual}` : `${API_URL}/admin/ordens`;
  const r = await fetch(url, { headers: headers() });
  const ordens = await r.json();

  const iconeTipo = { preventiva: "🛠️ Preventiva", manutencao: "Manutenção", instalacao: "Instalação" };

  const tecnicosAprovados = tecnicosCache.filter(
    t => t.aprovado
  );

  const opcoesTecnicos = tecnicosAprovados
    .map(
      t => `<option value="${t.id}">${t.nome}</option>`
    )
    .join("");

  document.getElementById("tabela-ordens").innerHTML = ordens.map(o => `
    <tr style="${o.prioridade ? 'background:rgba(220,38,38,0.08);' : ''}">
      <td>${o.prioridade ? "🔴" : ""}</td>
      <td>#${o.id}</td>
      <td>${o.criada_por_admin
          ? (o.tipo === "preventiva" ? `<span style="color:#a78bfa;">🛠️ Auto (preventiva)</span>` : `<span style="color:#93c5fd;">Atribuída</span>`)
          : `<span style="color:#fbbf24;">⚡ Avulsa (técnico)</span>`}</td>
      <td>${o.cliente_local}${o.nome_cliente ? `<br><span style="color:#94a3b8;font-size:12px;">👤 ${o.nome_cliente}</span>` : ""}${o.endereco ? `<br><span style="color:#94a3b8;font-size:12px;">📍 ${o.endereco}</span>` : ""}
        ${o.cliente_id ? `<br><span style="color:#60a5fa; font-size:11px; cursor:pointer; text-decoration:underline;" onclick="mudarAba('clientes'); verHistoricoCliente(${o.cliente_id})">ver histórico</span>` : ""}
      </td>
      <td>${iconeTipo[o.tipo] || o.tipo}</td><td>${o.tecnico}</td>
      <td class="status-${o.status}">${o.status.replace("_", " ")}</td>
      <td>${o.materiais_usados.map(m => `${m.material} (${m.quantidade})`).join(", ") || "-"}</td>
      <td>${o.qtd_fotos > 0 ? `📷 ${o.qtd_fotos}` : "-"}</td>
      <td style="font-size:12px;">
        ${o.minutos_deslocamento !== null ? `🚗 ${formatarMinutos(o.minutos_deslocamento)}<br>` : ""}
        ${o.minutos_execucao !== null ? `🔧 ${formatarMinutos(o.minutos_execucao)}<br>` : ""}
        ${o.minutos_total !== null ? `<strong>Total: ${formatarMinutos(o.minutos_total)}</strong>` : "-"}
      </td>
      <td>
        ${o.status === "pendente" && o.tecnico_id === null ? `
          <select
            id="atribuir-tecnico-${o.id}"
            style="min-width:140px; margin-bottom:6px;"
          >
            <option value="">Escolha o tecnico</option>
            ${opcoesTecnicos}
          </select>
          <button
            class="pequeno"
            onclick="atribuirOrdemExistente(${o.id})"
          >
            Atribuir
          </button>
        ` : ""}
        ${o.tem_pdf
          ? `<button class="pequeno secundario" onclick="baixarPdfOrdem(${o.id})">Baixar PDF</button>`
          : (
              o.status === "pendente"
              && o.tecnico_id === null
                ? ""
                : "-"
            )}
      </td>
    </tr>
  `).join("");
}

async function atribuirOrdemExistente(id) {
  const select = document.getElementById(
    `atribuir-tecnico-${id}`
  );

  const tecnico_id = parseInt(
    select?.value,
    10
  );

  if (!tecnico_id) {
    alert("Escolha o tecnico.");
    return;
  }

  const tecnico = tecnicosCache.find(
    t => t.id === tecnico_id
  );

  const nomeTecnico = tecnico?.nome || tecnico_id;

  if (
    !confirm(
      `Atribuir a OS #${id} para ${nomeTecnico}?`
    )
  ) {
    return;
  }

  const resposta = await fetch(
    `${API_URL}/admin/ordens/${id}/atribuir`,
    {
      method: "PATCH",
      headers: headers(),
      body: JSON.stringify({
        tecnico_id,
      }),
    }
  );

  let dados = {};

  try {
    dados = await resposta.json();
  }
  catch (_) {
    dados = {};
  }

  if (!resposta.ok) {
    alert(
      dados.detail
      || "Nao foi possivel atribuir a OS."
    );
    return;
  }

  alert(
    `OS #${id} atribuida para ${nomeTecnico}.`
  );

  await carregarOrdens();
}


async function baixarPdfOrdem(id) {
  const r = await fetch(`${API_URL}/admin/ordens/${id}/pdf`, { headers: headers() });
  if (!r.ok) { alert("PDF não disponível pra essa OS"); return; }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `OS_${id}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function filtrarOrdens(status) {
  filtroAtual = status;
  carregarOrdens();
}

let clientesCache = [];

async function carregarClientesParaSelect() {
  const r = await fetch(`${API_URL}/admin/clientes`, { headers: headers() });
  clientesCache = await r.json();
  const sel = document.getElementById("os-cliente");
  if (sel) {
    sel.innerHTML = `<option value="">— nenhum —</option>` +
      clientesCache.map(c => `<option value="${c.id}">${c.nome}</option>`).join("");
  }
}

function preencherClienteNaOS() {
  const id = parseInt(document.getElementById("os-cliente").value);
  const cliente = clientesCache.find(c => c.id === id);
  if (!cliente) return;
  document.getElementById("os-local").value = cliente.nome;
  document.getElementById("os-nome-cliente").value = cliente.nome;
  document.getElementById("os-endereco").value = cliente.endereco || "";
}

async function atribuirOrdem() {
  const tecnico_id = parseInt(document.getElementById("os-tecnico").value);
  const tipo = document.getElementById("os-tipo").value;
  const cliente_local = document.getElementById("os-local").value.trim();
  const cliente_id = document.getElementById("os-cliente").value ? parseInt(document.getElementById("os-cliente").value) : null;
  const nome_cliente = document.getElementById("os-nome-cliente").value.trim();
  const endereco = document.getElementById("os-endereco").value.trim();
  const prioridade = document.getElementById("os-prioridade").checked;
  const observacoes = document.getElementById("os-obs").value.trim();
  const msg = document.getElementById("os-msg");

  if (!tecnico_id || !cliente_local) { alert("Escolha o técnico e informe o local"); return; }

  const r = await fetch(`${API_URL}/admin/ordens`, {
    method: "POST", headers: headers(),
    body: JSON.stringify({
      tecnico_id, tipo, cliente_local, cliente_id,
      nome_cliente: nome_cliente || null, endereco: endereco || null,
      prioridade, observacoes,
    }),
  });
  if (!r.ok) { msg.style.color = "#f87171"; msg.textContent = "Erro ao atribuir OS"; return; }

  msg.style.color = "#86efac";
  msg.textContent = "OS atribuída! Vai aparecer no app do técnico automaticamente, sem precisar sair e entrar.";
  document.getElementById("os-local").value = "";
  document.getElementById("os-cliente").value = "";
  document.getElementById("os-nome-cliente").value = "";
  document.getElementById("os-endereco").value = "";
  document.getElementById("os-prioridade").checked = false;
  document.getElementById("os-obs").value = "";
  carregarOrdens();
}

// ===== CLIENTES (cadastro + foto da rota do cabo) =====
async function carregarClientes() {
  const r = await fetch(`${API_URL}/admin/clientes`, { headers: headers() });
  clientesCache = await r.json();
  document.getElementById("tabela-clientes").innerHTML = clientesCache.length ? clientesCache.map(c => `
    <tr>
      <td>${c.nome}</td>
      <td>${c.endereco || "-"}</td>
      <td>${c.tem_imagem_rota ? "✅ cadastrada" : "—"}</td>
      <td>
        <button class="pequeno secundario" onclick="abrirSeletorRotaCabo(${c.id})">🗺️ ${c.tem_imagem_rota ? "Trocar" : "Adicionar"} rota</button>
        <button class="pequeno secundario" onclick="verHistoricoCliente(${c.id})">📋 Histórico</button>
      </td>
    </tr>
  `).join("") : `<tr><td colspan="4" style="color:#64748b;">Nenhum cliente cadastrado ainda.</td></tr>`;
}

async function criarCliente() {
  const nome = document.getElementById("cli-nome").value.trim();
  const endereco = document.getElementById("cli-endereco").value.trim();
  const observacoes = document.getElementById("cli-observacoes").value.trim();
  const msg = document.getElementById("cli-msg");
  if (!nome) { alert("Informe o nome do cliente"); return; }

  const r = await fetch(`${API_URL}/admin/clientes`, {
    method: "POST", headers: headers(),
    body: JSON.stringify({ nome, endereco: endereco || null, observacoes: observacoes || null }),
  });
  if (!r.ok) { msg.style.color = "#f87171"; msg.textContent = "Erro ao cadastrar cliente"; return; }

  msg.style.color = "#86efac";
  msg.textContent = `Cliente "${nome}" cadastrado!`;
  document.getElementById("cli-nome").value = "";
  document.getElementById("cli-endereco").value = "";
  document.getElementById("cli-observacoes").value = "";
  carregarClientes();
}

let clienteRotaAlvo = null;
function abrirSeletorRotaCabo(id) {
  clienteRotaAlvo = id;
  document.getElementById("input-rota-cabo").click();
}

async function rotaCaboSelecionada(event) {
  const arquivo = event.target.files[0];
  event.target.value = "";
  if (!arquivo || !clienteRotaAlvo) return;
  const form = new FormData();
  form.append("arquivo", arquivo);
  await fetch(`${API_URL}/admin/clientes/${clienteRotaAlvo}/rota-cabo`, {
    method: "POST", headers: authHeaders(), body: form,
  });
  carregarClientes();
}

async function verHistoricoCliente(id) {
  const r = await fetch(`${API_URL}/admin/clientes/${id}/historico`, { headers: headers() });
  const dados = await r.json();
  const div = document.getElementById("detalhe-cliente");
  div.classList.remove("oculto");
  div.innerHTML = `
    <h3 style="margin-top:0;">📋 Histórico de ${dados.cliente}</h3>
    <table>
      <thead><tr><th>ID</th><th>Tipo</th><th>Status</th><th>Técnico</th><th>Aberta em</th><th>Fechada em</th></tr></thead>
      <tbody>
        ${dados.ordens.length ? dados.ordens.map(o => `
          <tr><td>#${o.id}</td><td>${o.tipo}</td>
            <td class="status-${o.status}">${o.status.replace("_"," ")}</td>
            <td>${o.tecnico}</td>
            <td>${new Date(o.data_abertura).toLocaleDateString("pt-BR")}</td>
            <td>${o.data_fechamento ? new Date(o.data_fechamento).toLocaleDateString("pt-BR") : "-"}</td>
          </tr>
        `).join("") : `<tr><td colspan="6" style="color:#64748b;">Nenhuma OS registrada ainda.</td></tr>`}
      </tbody>
    </table>
    <button class="secundario" onclick="document.getElementById('detalhe-cliente').classList.add('oculto')">Fechar</button>
  `;
}

// atualiza os dados a cada 20s pra refletir o que os técnicos foram fazendo em campo
setInterval(() => {
  if (document.getElementById("app").style.display === "flex") carregarTudo();
}, 20000);
