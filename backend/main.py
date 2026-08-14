import os
import secrets
from pathlib import Path
import base64
import uuid as uuid_lib
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fpdf import FPDF
import bcrypt
import jwt

import models
from database import Base, engine, get_db

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Estoque de Campo API")

PASTA_RELATORIOS = os.path.join(os.path.dirname(__file__), "relatorios")
PASTA_FOTOS_PERFIL = os.path.join(os.path.dirname(__file__), "fotos_perfil")
PASTA_FOTOS_OS = os.path.join(os.path.dirname(__file__), "fotos_os")
PASTA_ROTAS_CABO = os.path.join(os.path.dirname(__file__), "rotas_cabo")
os.makedirs(PASTA_RELATORIOS, exist_ok=True)
os.makedirs(PASTA_FOTOS_PERFIL, exist_ok=True)
os.makedirs(PASTA_ROTAS_CABO, exist_ok=True)
os.makedirs(PASTA_FOTOS_OS, exist_ok=True)

BASE_DIR = Path(__file__).resolve().parent

PASTAS_ARQUIVOS = {
    "fotos_perfil",
    "rotas_cabo",
    "fotos_os",
    "relatorios",
}


def resolver_caminho_arquivo(caminho):
    if not caminho:
        return None

    bruto = str(caminho)
    caminho_obj = Path(bruto)

    # Se o caminho cont?m uma das pastas gerenciadas pelo projeto,
    # prioriza sempre a c?pia que est? dentro do backend atual.
    partes = bruto.replace("\\", "/").split("/")

    for indice, parte in enumerate(partes):
        if parte in PASTAS_ARQUIVOS:
            candidato_atual = BASE_DIR.joinpath(*partes[indice:])

            if candidato_atual.exists():
                return candidato_atual

    # Novo formato relativo.
    if not caminho_obj.is_absolute():
        return BASE_DIR / caminho_obj

    # Compatibilidade tempor?ria com caminho absoluto antigo,
    # caso o arquivo ainda n?o tenha sido migrado para o projeto atual.
    if caminho_obj.exists():
        return caminho_obj

    return caminho_obj

# Em produção, restrinja para o domínio do seu app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Senha única do painel Admin/Desktop. TROQUE isso em produção definindo a
# Senha do PRIMEIRO usuário admin (gerência), criado pelo seed.py. Depois
# disso, todo controle de acesso é por login/senha individuais — veja
# admin_usuarios no banco. Troque isso via variável de ambiente no VPS.
ADMIN_SENHA_INICIAL = os.getenv("ADMIN_SENHA", "admin123")

# JWT do aplicativo do t?cnico.
# Desenvolvimento local: usa chave padr?o.
# VPS: definir JWT_SECRET_KEY no ambiente.
JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    "aven-local-development-change-in-vps"
)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

AVEN_MONITOR_API_TOKEN = os.getenv("AVEN_MONITOR_API_TOKEN")


def criar_token_tecnico(tecnico: models.Tecnico) -> str:
    agora = datetime.utcnow()

    payload = {
        "sub": str(tecnico.id),
        "tipo": "tecnico",
        "iat": agora,
        "exp": agora + timedelta(hours=JWT_EXPIRE_HOURS),
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )



def criar_token_admin(admin: models.AdminUsuario) -> str:
    agora = datetime.utcnow()

    papel = (
        admin.papel.value
        if hasattr(admin.papel, "value")
        else str(admin.papel)
    )

    payload = {
        "sub": str(admin.id),
        "tipo": "admin",
        "papel": papel,
        "iat": agora,
        "exp": agora + timedelta(hours=JWT_EXPIRE_HOURS),
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


monitor_bearer = HTTPBearer(auto_error=False)

def exigir_aven_monitor(
    credenciais: Optional[HTTPAuthorizationCredentials] = Depends(monitor_bearer),
):
    if not AVEN_MONITOR_API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Integracao AVEN Monitor nao configurada",
        )

    if credenciais is None:
        raise HTTPException(
            status_code=401,
            detail="Token do AVEN Monitor obrigatorio",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credenciais.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Tipo de autenticacao invalido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(
        credenciais.credentials,
        AVEN_MONITOR_API_TOKEN,
    ):
        raise HTTPException(
            status_code=401,
            detail="Token do AVEN Monitor invalido",
            headers={"WWW-Authenticate": "Bearer"},
        )


admin_bearer = HTTPBearer(auto_error=False)

def obter_admin(
    credenciais: Optional[HTTPAuthorizationCredentials] = Depends(admin_bearer),
    db: Session = Depends(get_db),
):
    if not credenciais:
        raise HTTPException(status_code=401, detail="Token administrativo obrigatorio")

    try:
        payload = jwt.decode(
            credenciais.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token administrativo expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token administrativo invalido")

    if payload.get("tipo") != "admin":
        raise HTTPException(status_code=401, detail="Token nao pertence a um administrador")

    try:
        admin_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Token administrativo invalido")

    admin = db.query(models.AdminUsuario).filter_by(
        id=admin_id,
        ativo=True,
    ).first()

    if not admin:
        raise HTTPException(status_code=401, detail="Administrador nao encontrado ou desativado")

    return admin


def exigir_papel(*papeis_permitidos):
    """Gerência sempre tem acesso total. Outros papéis só passam se
    estiverem explicitamente na lista permitida pra essa rota."""
    def dependencia(admin: models.AdminUsuario = Depends(obter_admin)):
        if admin.papel == models.PapelAdmin.gerencia:
            return admin
        if admin.papel not in papeis_permitidos:
            raise HTTPException(status_code=403, detail="Sem permissão pra acessar essa área")
        return admin
    return dependencia


def gerar_pdf_ordem(ordem: models.OrdemServico) -> str:
    """Gera um PDF com todas as informações da OS + materiais usados,
    salva em disco e retorna o caminho do arquivo."""
    caminho_logo = os.path.join(os.path.dirname(__file__), "assets", "logo.png")

    pdf = FPDF()
    pdf.add_page()
    if os.path.exists(caminho_logo):
        pdf.image(caminho_logo, x=170, y=8, w=25)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Aven Connect", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "Solucoes em Conectividade", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Relatorio de Ordem de Servico", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(4)

    from fpdf.enums import XPos, YPos

    def linha(rotulo, valor):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(45, 8, f"{rotulo}:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 8, str(valor), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    linha("OS numero", f"#{ordem.id}")
    linha("Origem", "Avulsa (aberta pelo tecnico)" if not ordem.criada_por_admin else "Atribuida pelo admin")
    linha("Tipo", ordem.tipo.value if hasattr(ordem.tipo, "value") else ordem.tipo)
    linha("Cliente / Local", ordem.cliente_local)
    if ordem.nome_cliente:
        linha("Nome do cliente", ordem.nome_cliente)
    if ordem.endereco:
        linha("Endereco", ordem.endereco)
    if ordem.prioridade:
        linha("Prioridade", "SIM - Atendimento prioritario")
    linha("Tecnico", ordem.tecnico.nome if ordem.tecnico else "Nao atribuido")
    if ordem.lat_inicio and ordem.lon_inicio:
        linha("Local de inicio", f"{ordem.lat_inicio:.6f}, {ordem.lon_inicio:.6f}")
    if ordem.lat_fim and ordem.lon_fim:
        linha("Local de finalizacao", f"{ordem.lat_fim:.6f}, {ordem.lon_fim:.6f}")
    linha("Status", ordem.status.value if hasattr(ordem.status, "value") else ordem.status)
    linha("Aberta em", ordem.data_abertura.strftime("%d/%m/%Y %H:%M") if ordem.data_abertura else "-")
    linha("Deslocamento", ordem.data_deslocamento.strftime("%d/%m/%Y %H:%M") if ordem.data_deslocamento else "-")
    linha("Iniciada em", ordem.data_inicio.strftime("%d/%m/%Y %H:%M") if ordem.data_inicio else "-")
    linha("Finalizada em", ordem.data_fechamento.strftime("%d/%m/%Y %H:%M") if ordem.data_fechamento else "-")

    marco_inicial = ordem.data_deslocamento or ordem.data_inicio
    if marco_inicial and ordem.data_fechamento:
        total_min = round((ordem.data_fechamento - marco_inicial).total_seconds() / 60)
        linha("Tempo total", f"{total_min} minutos")
    if ordem.observacoes:
        linha("Observacoes", ordem.observacoes)

    if ordem.tipo == models.TipoOS.manutencao:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Checklist de boas praticas (fibra optica)", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"{'[X]' if ordem.checklist_limpar_conector else '[ ]'} Limpou o conector", ln=True)
        pdf.cell(0, 7, f"{'[X]' if ordem.checklist_testar_sinal else '[ ]'} Testou o sinal", ln=True)
        pdf.cell(0, 7, f"{'[X]' if ordem.checklist_verificar_otdr else '[ ]'} Verificou integridade com OTDR", ln=True)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Materiais utilizados", ln=True)
    pdf.set_font("Helvetica", "", 11)
    if ordem.movimentacoes:
        for mov in ordem.movimentacoes:
            pdf.cell(0, 7, f"- {mov.material.nome}: {mov.quantidade} {mov.material.unidade}", ln=True)
    else:
        pdf.cell(0, 7, "Nenhum material registrado.", ln=True)

    if ordem.fotos:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Fotos da atividade", ln=True)
        pdf.ln(2)
        x, y = 10, pdf.get_y()
        largura_foto = 90
        for i, foto in enumerate(ordem.fotos):
            caminho_foto = resolver_caminho_arquivo(foto.caminho)

            if not caminho_foto or not caminho_foto.exists():
                continue
            coluna = i % 2
            if coluna == 0 and i > 0:
                y += 75
            if y > 250:
                pdf.add_page()
                y = 20
            pos_x = 10 if coluna == 0 else 110
            try:
                pdf.image(str(caminho_foto), x=pos_x, y=y, w=largura_foto)
            except Exception:
                pass

    nome_arquivo = f"os_{ordem.id}.pdf"

    caminho_absoluto = Path(PASTA_RELATORIOS) / nome_arquivo
    caminho_relativo = Path("relatorios") / nome_arquivo

    pdf.output(str(caminho_absoluto))

    return caminho_relativo.as_posix()


# ---------- Schemas ----------


# Autentica??o Bearer do aplicativo do t?cnico.
bearer_tecnico = HTTPBearer(auto_error=False)


def erro_autenticacao_tecnico(detail: str = "N?o autenticado"):
    raise HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def obter_tecnico_atual(
    credenciais: HTTPAuthorizationCredentials = Depends(bearer_tecnico),
    db: Session = Depends(get_db),
) -> models.Tecnico:

    if credenciais is None:
        erro_autenticacao_tecnico("Token de autentica??o ausente")

    if credenciais.scheme.lower() != "bearer":
        erro_autenticacao_tecnico("Tipo de autentica??o inv?lido")

    try:
        payload = jwt.decode(
            credenciais.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

    except jwt.ExpiredSignatureError:
        erro_autenticacao_tecnico("Token expirado")

    except jwt.InvalidTokenError:
        erro_autenticacao_tecnico("Token inv?lido")

    if payload.get("tipo") != "tecnico":
        erro_autenticacao_tecnico("Token n?o pertence a um t?cnico")

    tecnico_id = payload.get("sub")

    try:
        tecnico_id = int(tecnico_id)
    except (TypeError, ValueError):
        erro_autenticacao_tecnico("Token inv?lido")

    tecnico = (
        db.query(models.Tecnico)
        .filter(
            models.Tecnico.id == tecnico_id,
            models.Tecnico.ativo == True,
        )
        .first()
    )

    if not tecnico:
        erro_autenticacao_tecnico("T?cnico n?o encontrado ou inativo")

    if not tecnico.aprovado:
        raise HTTPException(
            status_code=403,
            detail="Cadastro aguardando aprova??o do estoque",
        )

    return tecnico



def exigir_mesmo_tecnico(
    tecnico_id: int,
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
) -> models.Tecnico:
    """
    Garante que o ID solicitado na URL pertence ao t?cnico autenticado.
    """
    if tecnico_atual.id != tecnico_id:
        raise HTTPException(
            status_code=403,
            detail="Voc? n?o tem permiss?o para acessar dados de outro t?cnico",
        )

    return tecnico_atual


class TecnicoLogin(BaseModel):
    login: str
    pin: str


class TecnicoOut(BaseModel):
    id: int
    nome: str
    login: str
    aprovado: bool
    is_adm: bool
    telefone: Optional[str] = None
    data_contratacao: Optional[str] = None
    tem_foto_perfil: bool = False

    class Config:
        from_attributes = True


class TecnicoLoginOut(TecnicoOut):
    access_token: str
    token_type: str = "bearer"


class MaterialOut(BaseModel):
    id: int
    nome: str
    categoria: Optional[str]
    unidade: str
    qtd_atual: float
    qtd_minima: float

    class Config:
        from_attributes = True


class FerramentaOut(BaseModel):
    id: int
    nome: str
    codigo_patrimonio: Optional[str]
    categoria: str
    status: str

    class Config:
        from_attributes = True


class OrdemCreate(BaseModel):
    tecnico_id: int
    tipo: str  # "instalacao" | "manutencao"
    cliente_local: str
    cliente_id: Optional[int] = None
    nome_cliente: Optional[str] = None
    endereco: Optional[str] = None
    prioridade: bool = False
    observacoes: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    client_uuid: Optional[str] = None  # gerado no celular p/ evitar duplicidade ao sincronizar


class MonitorIncidenteCreate(BaseModel):
    tipo: str
    dispositivo_id: str
    codigo: str
    local: str
    cidade: str
    fabricante: str
    inicio: datetime

    equipamento: Optional[str] = None
    link: Optional[str] = None
    operadora: Optional[str] = None
    papel: Optional[str] = None

    @model_validator(mode="after")
    def validar_tipo_incidente(self):
        if self.tipo == "LINK":
            if not self.link:
                raise ValueError(
                    "Incidente LINK exige link"
                )

            if not self.operadora:
                raise ValueError(
                    "Incidente LINK exige operadora"
                )

            if not self.papel:
                raise ValueError(
                    "Incidente LINK exige papel"
                )

        elif self.tipo == "DISPOSITIVO":
            if not self.equipamento:
                raise ValueError(
                    "Incidente DISPOSITIVO exige equipamento"
                )

        else:
            raise ValueError(
                "tipo deve ser LINK ou DISPOSITIVO"
            )

        return self


def gerar_client_uuid_monitor(
    dados: MonitorIncidenteCreate,
) -> str:
    partes = [
        "AVEN_MONITOR",
        dados.tipo,
        dados.dispositivo_id,
    ]

    if dados.tipo == "LINK":
        partes.append(dados.link)

    partes.append(
        dados.inicio.isoformat(
            timespec="seconds"
        )
    )

    chave = "|".join(partes)

    identificador = uuid_lib.uuid5(
        uuid_lib.NAMESPACE_URL,
        chave,
    )

    return f"monitor:{identificador}"


class OrdemOut(BaseModel):
    id: int
    tipo: str
    cliente_local: str
    cliente_id: Optional[int] = None
    nome_cliente: Optional[str] = None
    endereco: Optional[str] = None
    prioridade: bool = False
    status: str
    tecnico_id: Optional[int] = None
    data_abertura: datetime

    class Config:
        from_attributes = True


class OrdemAtribuir(BaseModel):
    tecnico_id: int
    tipo: str
    cliente_local: str
    cliente_id: Optional[int] = None
    nome_cliente: Optional[str] = None
    endereco: Optional[str] = None
    prioridade: bool = False
    observacoes: Optional[str] = None


class TecnicoCreate(BaseModel):
    nome: str
    login: str
    pin: str
    is_adm: bool = False
    telefone: Optional[str] = None
    data_contratacao: Optional[str] = None


class TecnicoPermissao(BaseModel):
    is_adm: bool


class AdminLogin(BaseModel):
    login: str
    senha: str


class AdminUsuarioOut(BaseModel):
    id: int
    nome: str
    login: str
    papel: str
    ativo: bool

    class Config:
        from_attributes = True


class AdminLoginOut(AdminUsuarioOut):
    access_token: str
    token_type: str = "bearer"


class AdminUsuarioCreate(BaseModel):
    nome: str
    login: str
    senha: str
    papel: str  # "gerencia" | "almoxarifado"


class AdminUsuarioPapel(BaseModel):
    papel: str


class AdminUsuarioAtivo(BaseModel):
    ativo: bool


class MovimentacaoCreate(BaseModel):
    ordem_id: int
    material_id: int
    quantidade: float = Field(gt=0)
    client_uuid: Optional[str] = None


class MaterialCreate(BaseModel):
    nome: str
    categoria: Optional[str] = None
    unidade: str = "un"
    qtd_atual: float = Field(default=0, ge=0)
    qtd_minima: float = Field(default=0, ge=0)
    custo_unitario: float = Field(default=0, ge=0)


class FerramentaCreate(BaseModel):
    nome: str
    codigo_patrimonio: Optional[str] = None
    categoria: str = "ferramenta"  # "ferramenta" | "epi"


class EntradaEstoque(BaseModel):
    material_id: int
    quantidade: float = Field(gt=0)


class TransferenciaCreate(BaseModel):
    tecnico_id: int
    tipo: str  # "material" | "ferramenta"
    material_id: Optional[int] = None
    quantidade: Optional[float] = Field(default=None, gt=0)
    ferramenta_id: Optional[int] = None


class SolicitacaoCreate(BaseModel):
    tecnico_id: int
    material_id: int
    quantidade: float = Field(gt=0)
    observacao: Optional[str] = None
    client_uuid: Optional[str] = None


class FotoOrdemCreate(BaseModel):
    imagem_base64: str
    client_uuid: Optional[str] = None


class AvisoCreate(BaseModel):
    ferramenta_id: int
    tecnico_id: int
    descricao: str


class AvisoResolver(BaseModel):
    acao: str  # "baixar" | "manutencao" | "devolver_uso"


class LocalizacaoOpcional(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None


class FecharOrdemBody(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    checklist_limpar_conector: bool = False
    checklist_testar_sinal: bool = False
    checklist_verificar_otdr: bool = False


class ClienteCreate(BaseModel):
    nome: str
    endereco: Optional[str] = None
    observacoes: Optional[str] = None


class ClienteOut(BaseModel):
    id: int
    nome: str
    endereco: Optional[str] = None
    observacoes: Optional[str] = None
    tem_imagem_rota: bool = False

    class Config:
        from_attributes = True


class ResetarPin(BaseModel):
    novo_pin: str


# ---------- Auth simples por PIN ----------

@app.post("/tecnicos/login", response_model=TecnicoLoginOut)
def login(dados: TecnicoLogin, db: Session = Depends(get_db)):
    tecnico = db.query(models.Tecnico).filter(
        models.Tecnico.login == dados.login, models.Tecnico.ativo == True
    ).first()
    if not tecnico or not bcrypt.checkpw(dados.pin.encode(), tecnico.pin_hash.encode()):
        raise HTTPException(status_code=401, detail="Login ou PIN inválido")
    if not tecnico.aprovado:
        raise HTTPException(status_code=403, detail="Cadastro aguardando aprovação do estoque")
    dados_tecnico = TecnicoOut.model_validate(
        tecnico
    ).model_dump()

    return {
        **dados_tecnico,
        "access_token": criar_token_tecnico(tecnico),
        "token_type": "bearer",
    }



@app.get("/tecnicos/me", response_model=TecnicoOut)
def tecnico_me(
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
):
    return tecnico_atual


# ---------- Materiais (catálogo / estoque central) ----------

@app.get("/materiais", response_model=List[MaterialOut])
def listar_materiais(
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
):
    return db.query(models.Material).order_by(models.Material.nome).all()


@app.get(
    "/materiais/baixo-estoque",
    response_model=List[MaterialOut],
    dependencies=[Depends(exigir_papel())],
)
def materiais_baixo_estoque(db: Session = Depends(get_db)):
    materiais = db.query(models.Material).all()
    return [m for m in materiais if m.qtd_atual <= m.qtd_minima]


@app.post("/materiais", response_model=MaterialOut, dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def criar_material(dados: MaterialCreate, db: Session = Depends(get_db)):
    material = models.Material(**dados.model_dump())
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


@app.post("/materiais/entrada", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def registrar_entrada(dados: EntradaEstoque, db: Session = Depends(get_db)):
    """Reposição de estoque CENTRAL (compra de material novo)."""
    material = db.query(models.Material).get(dados.material_id)
    if not material:
        raise HTTPException(404, "Material não encontrado")
    material.qtd_atual += dados.quantidade
    mov = models.MovimentacaoEstoque(
        material_id=dados.material_id,
        quantidade=dados.quantidade,
        tipo=models.TipoMovimentacao.entrada,
    )
    db.add(mov)
    db.commit()
    return {"status": "ok", "estoque_atual": material.qtd_atual}


# ---------- Ferramentas / EPIs (catálogo central) ----------

@app.get(
    "/ferramentas",
    response_model=List[FerramentaOut],
    dependencies=[Depends(exigir_papel())],
)
def listar_ferramentas(db: Session = Depends(get_db)):
    return db.query(models.Ferramenta).order_by(models.Ferramenta.nome).all()


@app.post("/ferramentas", response_model=FerramentaOut, dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def criar_ferramenta(dados: FerramentaCreate, db: Session = Depends(get_db)):
    ferramenta = models.Ferramenta(**dados.model_dump())
    db.add(ferramenta)
    db.commit()
    db.refresh(ferramenta)
    return ferramenta


@app.post("/admin/ferramentas/{ferramenta_id}/devolver", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def devolver_ferramenta_ao_estoque(ferramenta_id: int, db: Session = Depends(get_db)):
    """Ferramenta/EPI volta fisicamente pro almoxarifado."""
    ferramenta = db.query(models.Ferramenta).get(ferramenta_id)
    if not ferramenta:
        raise HTTPException(404, "Ferramenta não encontrada")
    ferramenta.status = models.StatusFerramenta.disponivel
    ferramenta.tecnico_atual_id = None
    db.commit()
    return {"status": "disponivel"}


@app.post("/admin/ferramentas/{ferramenta_id}/baixar", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def dar_baixa_ferramenta(ferramenta_id: int, db: Session = Depends(get_db)):
    """Item quebrado/gasto, sai de circulação definitivamente."""
    ferramenta = db.query(models.Ferramenta).get(ferramenta_id)
    if not ferramenta:
        raise HTTPException(404, "Ferramenta não encontrada")
    ferramenta.status = models.StatusFerramenta.baixada
    ferramenta.tecnico_atual_id = None
    db.commit()
    return {"status": "baixada"}


@app.post("/admin/ferramentas/{ferramenta_id}/manutencao", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def enviar_ferramenta_manutencao(ferramenta_id: int, db: Session = Depends(get_db)):
    ferramenta = db.query(models.Ferramenta).get(ferramenta_id)
    if not ferramenta:
        raise HTTPException(404, "Ferramenta não encontrada")
    ferramenta.status = models.StatusFerramenta.manutencao
    ferramenta.tecnico_atual_id = None
    db.commit()
    return {"status": "manutencao"}


# ---------- Avisos de problema (técnico notifica, admin resolve) ----------

@app.post("/ferramentas/avisos")
def criar_aviso(dados: AvisoCreate, db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    """Técnico avisa que uma ferramenta/EPI que está com ele quebrou ou
    gastou. Não muda o estoque sozinho — só o admin resolve isso."""
    ferramenta = db.query(models.Ferramenta).get(dados.ferramenta_id)
    if not ferramenta:
        raise HTTPException(404, "Ferramenta não encontrada")

    if dados.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Nao e permitido criar aviso em nome de outro tecnico",
        )

    if ferramenta.tecnico_atual_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta ferramenta nao pertence ao tecnico autenticado",
        )
    aviso = models.AvisoFerramenta(
        ferramenta_id=dados.ferramenta_id, tecnico_id=dados.tecnico_id,
        descricao=dados.descricao,
    )
    db.add(aviso)
    db.commit()
    db.refresh(aviso)
    return {"status": "ok", "aviso_id": aviso.id}


@app.get("/admin/avisos", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def listar_avisos(status: str = "aberto", db: Session = Depends(get_db)):
    avisos = db.query(models.AvisoFerramenta).filter_by(status=status).order_by(
        models.AvisoFerramenta.data_criacao.desc()
    ).all()
    return [
        {
            "id": a.id, "ferramenta": a.ferramenta.nome, "tecnico": a.tecnico.nome,
            "descricao": a.descricao, "data_criacao": a.data_criacao,
        }
        for a in avisos
    ]


@app.post("/admin/avisos/{aviso_id}/resolver", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def resolver_aviso(aviso_id: int, dados: AvisoResolver, db: Session = Depends(get_db)):
    aviso = db.query(models.AvisoFerramenta).get(aviso_id)
    if not aviso:
        raise HTTPException(404, "Aviso não encontrado")

    ferramenta = aviso.ferramenta
    if dados.acao == "baixar":
        ferramenta.status = models.StatusFerramenta.baixada
        ferramenta.tecnico_atual_id = None
    elif dados.acao == "manutencao":
        ferramenta.status = models.StatusFerramenta.manutencao
        ferramenta.tecnico_atual_id = None
    elif dados.acao == "devolver_uso":
        pass  # segue com o técnico, só fecha o aviso
    else:
        raise HTTPException(400, "Ação inválida")

    aviso.status = models.StatusAviso.resolvido
    aviso.data_resolucao = datetime.utcnow()
    db.commit()
    return {"status": "resolvido"}


# ---------- Transferências (admin envia, técnico confirma) ----------

@app.post("/admin/transferencias", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def criar_transferencia(dados: TransferenciaCreate, db: Session = Depends(get_db)):
    tecnico = db.query(models.Tecnico).get(dados.tecnico_id)
    if not tecnico:
        raise HTTPException(404, "Técnico não encontrado")

    if dados.tipo == "material":
        if not dados.material_id or not dados.quantidade or dados.quantidade <= 0:
            raise HTTPException(400, "Informe material e quantidade válidos")
        material = db.query(models.Material).get(dados.material_id)
        if not material:
            raise HTTPException(404, "Material não encontrado")
        if material.qtd_atual < dados.quantidade:
            raise HTTPException(400, "Estoque central insuficiente")
        # reserva já debitando do estoque central (some do almoxarifado assim
        # que sai pra entrega, mesmo antes do técnico confirmar)
        material.qtd_atual -= dados.quantidade
        transferencia = models.Transferencia(
            tecnico_id=dados.tecnico_id, tipo=models.TipoTransferencia.material,
            material_id=dados.material_id, quantidade=dados.quantidade,
        )

    elif dados.tipo == "ferramenta":
        if not dados.ferramenta_id:
            raise HTTPException(400, "Informe a ferramenta")
        ferramenta = db.query(models.Ferramenta).get(dados.ferramenta_id)
        if not ferramenta:
            raise HTTPException(404, "Ferramenta não encontrada")
        if ferramenta.status != models.StatusFerramenta.disponivel:
            raise HTTPException(400, "Ferramenta não está disponível")
        ferramenta.status = models.StatusFerramenta.em_transito
        transferencia = models.Transferencia(
            tecnico_id=dados.tecnico_id, tipo=models.TipoTransferencia.ferramenta,
            ferramenta_id=dados.ferramenta_id,
        )
    else:
        raise HTTPException(400, "Tipo inválido")

    db.add(transferencia)
    db.commit()
    db.refresh(transferencia)
    return {"status": "enviada", "transferencia_id": transferencia.id}


@app.get("/admin/transferencias", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def listar_transferencias(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Transferencia)
    if status:
        query = query.filter_by(status=status)
    transferencias = query.order_by(models.Transferencia.data_envio.desc()).all()
    return [
        {
            "id": t.id, "tecnico": t.tecnico.nome, "tipo": t.tipo, "status": t.status,
            "item": t.material.nome if t.tipo == models.TipoTransferencia.material else t.ferramenta.nome,
            "quantidade": t.quantidade, "data_envio": t.data_envio,
        }
        for t in transferencias
    ]


@app.get("/tecnicos/{tecnico_id}/transferencias-pendentes")
def transferencias_pendentes_do_tecnico(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    """App do técnico chama isso pra mostrar o que precisa confirmar recebimento."""
    transferencias = db.query(models.Transferencia).filter_by(
        tecnico_id=tecnico_id, status=models.StatusTransferencia.pendente
    ).order_by(models.Transferencia.data_envio).all()
    return [
        {
            "id": t.id, "tipo": t.tipo,
            "item": t.material.nome if t.tipo == models.TipoTransferencia.material else t.ferramenta.nome,
            "quantidade": t.quantidade,
            "unidade": t.material.unidade if t.tipo == models.TipoTransferencia.material else None,
            "categoria_ferramenta": t.ferramenta.categoria if t.tipo == models.TipoTransferencia.ferramenta else None,
        }
        for t in transferencias
    ]


@app.post("/transferencias/{transferencia_id}/confirmar")
def confirmar_transferencia(transferencia_id: int, db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    t = db.query(models.Transferencia).get(transferencia_id)
    if not t:
        raise HTTPException(404, "Transferência não encontrada")

    if t.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta transfer?ncia pertence a outro t?cnico",
        )
    if t.status != models.StatusTransferencia.pendente:
        return {"status": "já processada"}

    if t.tipo == models.TipoTransferencia.material:
        pessoal = db.query(models.EstoquePessoal).filter_by(
            tecnico_id=t.tecnico_id, material_id=t.material_id
        ).first()
        if not pessoal:
            pessoal = models.EstoquePessoal(
                tecnico_id=t.tecnico_id, material_id=t.material_id, qtd_atual=0
            )
            db.add(pessoal)
        pessoal.qtd_atual += t.quantidade
    else:
        ferramenta = t.ferramenta
        ferramenta.status = models.StatusFerramenta.com_tecnico
        ferramenta.tecnico_atual_id = t.tecnico_id

    t.status = models.StatusTransferencia.confirmada
    t.data_confirmacao = datetime.utcnow()
    db.commit()
    return {"status": "confirmada"}


@app.post("/transferencias/{transferencia_id}/recusar")
def recusar_transferencia(transferencia_id: int, db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    t = db.query(models.Transferencia).get(transferencia_id)
    if not t:
        raise HTTPException(404, "Transferência não encontrada")

    if t.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta transfer?ncia pertence a outro t?cnico",
        )
    if t.status != models.StatusTransferencia.pendente:
        return {"status": "já processada"}

    if t.tipo == models.TipoTransferencia.material:
        t.material.qtd_atual += t.quantidade  # volta pro estoque central
    else:
        t.ferramenta.status = models.StatusFerramenta.disponivel

    t.status = models.StatusTransferencia.recusada
    t.data_confirmacao = datetime.utcnow()
    db.commit()
    return {"status": "recusada"}


# ---------- Estoque pessoal e ferramentas do técnico (consulta) ----------

@app.get("/tecnicos/{tecnico_id}/estoque-pessoal")
def estoque_pessoal_do_tecnico(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    itens = db.query(models.EstoquePessoal).filter_by(tecnico_id=tecnico_id).all()
    return [
        {
            "material_id": i.material_id, "nome": i.material.nome,
            "unidade": i.material.unidade, "qtd_atual": i.qtd_atual,
        }
        for i in itens if i.qtd_atual > 0
    ]


@app.get("/tecnicos/{tecnico_id}/ferramentas")
def ferramentas_do_tecnico(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    ferramentas = db.query(models.Ferramenta).filter_by(
        tecnico_atual_id=tecnico_id, status=models.StatusFerramenta.com_tecnico
    ).all()
    return [
        {"id": f.id, "nome": f.nome, "categoria": f.categoria} for f in ferramentas
    ]


# ---------- Acesso do tecnico aos clientes ----------

def obter_cliente_do_tecnico(
    cliente_id: int,
    tecnico_atual: models.Tecnico,
    db: Session,
) -> models.Cliente:

    cliente = db.query(models.Cliente).get(cliente_id)

    if not cliente:
        raise HTTPException(
            status_code=404,
            detail="Cliente nao encontrado",
        )

    vinculo = (
        db.query(models.OrdemServico.id)
        .filter(
            models.OrdemServico.cliente_id == cliente_id,
            models.OrdemServico.tecnico_id == tecnico_atual.id,
        )
        .first()
    )

    if not vinculo:
        raise HTTPException(
            status_code=403,
            detail="Este cliente nao pertence a uma OS do tecnico autenticado",
        )

    return cliente


@app.get("/clientes/{cliente_id}", response_model=ClienteOut)
def ver_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
):
    return obter_cliente_do_tecnico(
        cliente_id,
        tecnico_atual,
        db,
    )


@app.get("/clientes/{cliente_id}/rota-cabo")
def ver_rota_cabo(
    cliente_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
):
    cliente = obter_cliente_do_tecnico(
        cliente_id,
        tecnico_atual,
        db,
    )

    caminho_rota = resolver_caminho_arquivo(
        cliente.imagem_rota_cabo
    )

    if (
        not caminho_rota
        or not caminho_rota.exists()
    ):
        raise HTTPException(
            status_code=404,
            detail="Sem imagem de rota cadastrada",
        )

    return FileResponse(str(caminho_rota))


# ---------- Clientes (cadastro central, com foto da rota do cabo) ----------

@app.get("/admin/clientes", response_model=List[ClienteOut], dependencies=[Depends(exigir_papel())])
def listar_clientes(db: Session = Depends(get_db)):
    return db.query(models.Cliente).order_by(models.Cliente.nome).all()


@app.post("/admin/clientes", response_model=ClienteOut, dependencies=[Depends(exigir_papel())])
def criar_cliente(dados: ClienteCreate, db: Session = Depends(get_db)):
    cliente = models.Cliente(**dados.model_dump())
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


@app.post("/admin/clientes/{cliente_id}/rota-cabo", dependencies=[Depends(exigir_papel())])
async def upload_rota_cabo(cliente_id: int, arquivo: UploadFile = File(...), db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).get(cliente_id)
    if not cliente:
        raise HTTPException(404, "Cliente não encontrado")
    extensao = os.path.splitext(arquivo.filename or "rota.jpg")[1] or ".jpg"
    nome_arquivo = f"cliente_{cliente_id}{extensao}"

    caminho_absoluto = Path(PASTA_ROTAS_CABO) / nome_arquivo
    caminho_relativo = Path("rotas_cabo") / nome_arquivo

    conteudo = await arquivo.read()

    with open(caminho_absoluto, "wb") as f:
        f.write(conteudo)

    cliente.imagem_rota_cabo = caminho_relativo.as_posix()
    db.commit()
    return {"status": "ok"}


@app.get("/admin/clientes/{cliente_id}/historico", dependencies=[Depends(exigir_papel())])
def historico_cliente(cliente_id: int, db: Session = Depends(get_db)):
    """Todas as OS já feitas nesse cliente — pra detectar problema
    recorrente no mesmo local."""
    cliente = db.query(models.Cliente).get(cliente_id)
    if not cliente:
        raise HTTPException(404, "Cliente não encontrado")
    ordens = db.query(models.OrdemServico).filter_by(cliente_id=cliente_id).order_by(
        models.OrdemServico.data_abertura.desc()
    ).all()
    return {
        "cliente": cliente.nome,
        "ordens": [
            {
                "id": o.id, "tipo": o.tipo, "status": o.status, "tecnico": o.tecnico.nome if o.tecnico else "Nao atribuido",
                "data_abertura": o.data_abertura, "data_fechamento": o.data_fechamento,
            }
            for o in ordens
        ],
    }


# ---------- Sugestão de compra (informativo — não mexe no Financeiro) ----------

@app.get("/admin/materiais/sugestao-compra", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def sugestao_compra(db: Session = Depends(get_db)):
    """Pra cada material com estoque baixo, sugere uma quantidade de compra
    baseada no consumo médio dos últimos 90 dias. Só sugestão — não cria
    nada no Financeiro nem mexe em estoque, é o admin quem decide comprar."""
    limite = datetime.utcnow() - timedelta(days=90)
    materiais = db.query(models.Material).filter(
        models.Material.qtd_atual <= models.Material.qtd_minima
    ).all()

    sugestoes = []
    for m in materiais:
        consumo_total = db.query(models.MovimentacaoEstoque).filter(
            models.MovimentacaoEstoque.material_id == m.id,
            models.MovimentacaoEstoque.tipo == models.TipoMovimentacao.saida,
            models.MovimentacaoEstoque.timestamp >= limite,
        ).all()
        total_consumido = sum(mv.quantidade for mv in consumo_total)
        consumo_mensal_medio = total_consumido / 3  # 90 dias ≈ 3 meses

        # sugere estoque pra cobrir 2 meses de consumo médio, descontando o
        # que já tem; nunca sugere menos do que o mínimo já configurado
        sugestao = max((consumo_mensal_medio * 2) - m.qtd_atual, m.qtd_minima - m.qtd_atual, 0)
        sugestoes.append({
            "material_id": m.id, "nome": m.nome, "unidade": m.unidade,
            "qtd_atual": m.qtd_atual, "qtd_minima": m.qtd_minima,
            "consumo_mensal_medio": round(consumo_mensal_medio, 1),
            "sugestao_compra": round(sugestao, 1) if sugestao > 0 else round(m.qtd_minima, 1),
        })
    return sugestoes


# ---------- Ordens de Serviço ----------

@app.post("/ordens", response_model=OrdemOut)
def criar_ordem(
    dados: OrdemCreate,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
):
    # O tecnico informado no JSON precisa ser o mesmo do JWT.
    if dados.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Nao e permitido abrir OS em nome de outro tecnico",
        )

    # Reenvio offline/idempotencia.
    if dados.client_uuid:
        existente = db.query(models.OrdemServico).filter_by(
            client_uuid=dados.client_uuid
        ).first()

        if existente:
            if existente.tecnico_id != tecnico_atual.id:
                raise HTTPException(
                    status_code=403,
                    detail="OS existente pertence a outro tecnico",
                )

            return existente

    # OS avulsa continua restrita a tecnico ADM.
    if not tecnico_atual.is_adm:
        raise HTTPException(
            status_code=403,
            detail="Apenas tecnicos ADM podem abrir OS avulsa",
        )

    dados_ordem = dados.model_dump()
    lat = dados_ordem.pop("lat")
    lon = dados_ordem.pop("lon")

    ordem = models.OrdemServico(
        **dados_ordem,
        status=models.StatusOS.deslocamento,
        data_deslocamento=datetime.utcnow(),
        lat_deslocamento=lat,
        lon_deslocamento=lon,
    )

    db.add(ordem)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ordem ja registrada (client_uuid duplicado)",
        )

    db.refresh(ordem)
    return ordem


@app.get("/tecnicos/{tecnico_id}/ordens-pendentes")
def ordens_pendentes_do_tecnico(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    """O app do técnico chama isso após o login pra mostrar as OS que o
    admin atribuiu e que ainda não foram iniciadas (aguardando o técnico
    apertar 'Deslocamento')."""
    ordens = db.query(models.OrdemServico).filter_by(
        tecnico_id=tecnico_id, status=models.StatusOS.pendente
    ).order_by(models.OrdemServico.data_abertura).all()
    return [
        {
            "id": o.id, "tipo": o.tipo, "cliente_local": o.cliente_local,
            "cliente_id": o.cliente_id, "nome_cliente": o.nome_cliente,
            "endereco": o.endereco, "prioridade": o.prioridade,
            "observacoes": o.observacoes, "data_abertura": o.data_abertura,
        }
        for o in ordens
    ]


@app.get("/tecnicos/{tecnico_id}/os-ativa")
def os_ativa_do_tecnico(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    """OS que o técnico já começou (deslocamento ou em_andamento) — usado
    pro app recuperar o estado certo se ele sair e entrar de novo."""
    ordem = db.query(models.OrdemServico).filter(
        models.OrdemServico.tecnico_id == tecnico_id,
        models.OrdemServico.status.in_([models.StatusOS.deslocamento, models.StatusOS.em_andamento]),
    ).first()
    if not ordem:
        return None
    return {
        "id": ordem.id, "status": ordem.status, "tipo": ordem.tipo,
        "cliente_local": ordem.cliente_local, "cliente_id": ordem.cliente_id,
        "nome_cliente": ordem.nome_cliente, "endereco": ordem.endereco,
        "prioridade": ordem.prioridade,
    }


@app.post("/ordens/{ordem_id}/deslocamento", response_model=OrdemOut)
def iniciar_deslocamento(ordem_id: int, dados: LocalizacaoOpcional = LocalizacaoOpcional(), db: Session = Depends(get_db), tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    """Técnico apertou 'Deslocamento' — está a caminho do local."""
    ordem = db.query(models.OrdemServico).get(ordem_id)
    if not ordem:
        raise HTTPException(404, "Ordem não encontrada")

    if ordem.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta OS pertence a outro tecnico",
        )
    if ordem.status != models.StatusOS.pendente:
        raise HTTPException(400, "Esta OS não está pendente")
    ordem.status = models.StatusOS.deslocamento
    ordem.data_deslocamento = datetime.utcnow()
    ordem.lat_deslocamento = dados.lat
    ordem.lon_deslocamento = dados.lon
    db.commit()
    db.refresh(ordem)
    return ordem


@app.post("/ordens/{ordem_id}/iniciar", response_model=OrdemOut)
def iniciar_ordem(ordem_id: int, dados: LocalizacaoOpcional = LocalizacaoOpcional(), db: Session = Depends(get_db), tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    """Técnico chegou no local e apertou 'Iniciar atendimento'."""
    ordem = db.query(models.OrdemServico).get(ordem_id)
    if not ordem:
        raise HTTPException(404, "Ordem não encontrada")

    if ordem.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta OS pertence a outro tecnico",
        )
    if ordem.status not in (models.StatusOS.pendente, models.StatusOS.deslocamento):
        raise HTTPException(400, "Esta OS não pode ser iniciada nesse estado")
    ordem.status = models.StatusOS.em_andamento
    ordem.data_inicio = datetime.utcnow()
    ordem.lat_inicio = dados.lat
    ordem.lon_inicio = dados.lon
    db.commit()
    db.refresh(ordem)
    return ordem


def verificar_manutencao_preventiva(ordem: models.OrdemServico, db: Session):
    """Se essa OS de manutenção fechada for a 2ª do mesmo cliente em menos
    de 30 dias, abre automaticamente uma 3ª OS do tipo 'preventiva',
    com prioridade mais baixa, pro mesmo técnico."""
    if ordem.tipo != models.TipoOS.manutencao or not ordem.cliente_id:
        return

    limite = datetime.utcnow() - timedelta(days=30)
    manutencoes_recentes = db.query(models.OrdemServico).filter(
        models.OrdemServico.cliente_id == ordem.cliente_id,
        models.OrdemServico.tipo == models.TipoOS.manutencao,
        models.OrdemServico.status == models.StatusOS.fechada,
        models.OrdemServico.data_fechamento >= limite,
    ).count()

    if manutencoes_recentes != 2:
        return  # só dispara exatamente na 2ª, pra não repetir a cada manutenção seguinte

    ja_existe_preventiva_aberta = db.query(models.OrdemServico).filter(
        models.OrdemServico.cliente_id == ordem.cliente_id,
        models.OrdemServico.tipo == models.TipoOS.preventiva,
        models.OrdemServico.status != models.StatusOS.fechada,
    ).first()
    if ja_existe_preventiva_aberta:
        return

    preventiva = models.OrdemServico(
        tecnico_id=ordem.tecnico_id, cliente_id=ordem.cliente_id,
        tipo=models.TipoOS.preventiva, cliente_local=ordem.cliente_local,
        nome_cliente=ordem.nome_cliente, endereco=ordem.endereco,
        prioridade=False,  # prioridade mais baixa, é preventiva, não emergência
        observacoes="Gerada automaticamente: 2 manutenções nesse local em menos de 30 dias.",
        status=models.StatusOS.pendente, criada_por_admin=True,
    )
    db.add(preventiva)
    db.commit()


@app.post("/ordens/{ordem_id}/fechar")
def fechar_ordem(ordem_id: int, dados: FecharOrdemBody = FecharOrdemBody(), db: Session = Depends(get_db), tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    ordem = db.query(models.OrdemServico).get(ordem_id)
    if not ordem:
        raise HTTPException(404, "Ordem não encontrada")

    if ordem.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta OS pertence a outro tecnico",
        )
    ordem.status = models.StatusOS.fechada
    ordem.data_fechamento = datetime.utcnow()
    ordem.lat_fim = dados.lat
    ordem.lon_fim = dados.lon
    ordem.checklist_limpar_conector = dados.checklist_limpar_conector
    ordem.checklist_testar_sinal = dados.checklist_testar_sinal
    ordem.checklist_verificar_otdr = dados.checklist_verificar_otdr
    db.commit()
    db.refresh(ordem)

    verificar_manutencao_preventiva(ordem, db)

    # Gera o relatório em PDF com tudo que foi usado nessa OS, já disponível
    # pro sistema de controle (app desktop) baixar.
    try:
        caminho = gerar_pdf_ordem(ordem)
        ordem.pdf_path = caminho
        db.commit()
    except Exception:
        pass  # não trava o fechamento da OS se a geração do PDF falhar

    return {"status": "fechada", "pdf_gerado": bool(ordem.pdf_path)}


@app.post("/ordens/{ordem_id}/fotos")
def anexar_foto_ordem(ordem_id: int, dados: FotoOrdemCreate, db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    """Técnico anexa uma foto (base64) tirada durante a OS. Funciona com a
    fila offline do app — a foto fica pendente até sincronizar."""
    if dados.client_uuid:
        existente = db.query(models.FotoOrdem).filter_by(client_uuid=dados.client_uuid).first()
        if existente:
            return {"status": "já registrada", "foto_id": existente.id}

    ordem = db.query(models.OrdemServico).get(ordem_id)
    if not ordem:
        raise HTTPException(404, "Ordem não encontrada")


    if ordem.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta OS pertence a outro tecnico",
        )
    try:
        dados_binarios = base64.b64decode(dados.imagem_base64.split(",")[-1])
    except Exception:
        raise HTTPException(400, "Imagem em base64 inválida")

    nome_arquivo = f"os_{ordem_id}_{dados.client_uuid or uuid_lib.uuid4().hex}.jpg"

    caminho_absoluto = Path(PASTA_FOTOS_OS) / nome_arquivo
    caminho_relativo = Path("fotos_os") / nome_arquivo

    with open(caminho_absoluto, "wb") as f:
        f.write(dados_binarios)

    foto = models.FotoOrdem(
        ordem_id=ordem_id,
        caminho=caminho_relativo.as_posix(),
        client_uuid=dados.client_uuid,
    )
    db.add(foto)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Foto já registrada")
    db.refresh(foto)
    return {"status": "ok", "foto_id": foto.id}


@app.get("/admin/ordens/{ordem_id}/fotos/{foto_id}", dependencies=[Depends(exigir_papel())])
def ver_foto_ordem(ordem_id: int, foto_id: int, db: Session = Depends(get_db)):
    foto = db.query(models.FotoOrdem).filter_by(
        id=foto_id,
        ordem_id=ordem_id,
    ).first()

    caminho_foto = (
        resolver_caminho_arquivo(foto.caminho)
        if foto
        else None
    )

    if not foto or not caminho_foto or not caminho_foto.exists():
        raise HTTPException(404, "Foto n?o encontrada")

    return FileResponse(str(caminho_foto))


@app.get("/ordens/{ordem_id}")
def ver_ordem(
    ordem_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
):
    ordem = db.query(models.OrdemServico).get(ordem_id)
    if not ordem:
        raise HTTPException(404, "Ordem não encontrada")

    if ordem.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta OS pertence a outro tecnico",
        )
    return {
        "id": ordem.id,
        "cliente_local": ordem.cliente_local,
        "tipo": ordem.tipo,
        "status": ordem.status,
        "materiais_usados": [
            {"material": m.material.nome, "quantidade": m.quantidade}
            for m in ordem.movimentacoes
        ],
        "qtd_fotos": len(ordem.fotos),
    }


# ---------- Movimentação de estoque (baixa automática no estoque PESSOAL) ----------

@app.post("/movimentacoes")
def registrar_uso_material(dados: MovimentacaoCreate, db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual)):
    # idempotência: se o celular reenviar a mesma ação offline, não duplica
    if dados.client_uuid:
        existente = db.query(models.MovimentacaoEstoque).filter_by(
            client_uuid=dados.client_uuid
        ).first()
        if existente:
            return {"status": "já registrado", "movimentacao_id": existente.id}

    material = db.query(models.Material).get(dados.material_id)
    if not material:
        raise HTTPException(404, "Material não encontrado")

    ordem = db.query(models.OrdemServico).get(dados.ordem_id)
    if not ordem:
        raise HTTPException(404, "Ordem não encontrada")


    if ordem.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="Esta OS pertence a outro tecnico",
        )
    # BAIXA AUTOMÁTICA no estoque PESSOAL do técnico dono da OS (não no
    # estoque central — esse já foi debitado quando a transferência saiu)
    pessoal = db.query(models.EstoquePessoal).filter_by(
        tecnico_id=ordem.tecnico_id, material_id=dados.material_id
    ).first()
    if not pessoal:
        pessoal = models.EstoquePessoal(
            tecnico_id=ordem.tecnico_id, material_id=dados.material_id, qtd_atual=0
        )
        db.add(pessoal)
    if not pessoal or pessoal.qtd_atual < dados.quantidade:
        disponivel = pessoal.qtd_atual if pessoal else 0

        raise HTTPException(
            status_code=400,
            detail=f"Estoque pessoal insuficiente. Disponivel: {disponivel}",
        )

    pessoal.qtd_atual -= dados.quantidade

    mov = models.MovimentacaoEstoque(
        material_id=dados.material_id,
        ordem_id=dados.ordem_id,
        quantidade=dados.quantidade,
        tipo=models.TipoMovimentacao.saida,
        client_uuid=dados.client_uuid,
    )
    db.add(mov)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Movimentação já registrada")
    db.refresh(mov)

    return {
        "status": "ok",
        "movimentacao_id": mov.id,
        "estoque_pessoal_restante": pessoal.qtd_atual,
        "alerta_estoque_negativo": pessoal.qtd_atual < 0,
    }


# ---------- Solicitações de material (técnico pede, admin aprova) ----------

@app.post("/solicitacoes")
def criar_solicitacao(
    dados: SolicitacaoCreate,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(obter_tecnico_atual),
):
    """Técnico pede material do estoque central. Fica pendente até o admin
    aprovar ou rejeitar."""
    if dados.tecnico_id != tecnico_atual.id:
        raise HTTPException(
            status_code=403,
            detail="N?o ? permitido solicitar material em nome de outro t?cnico",
        )

    if dados.client_uuid:
        existente = db.query(models.SolicitacaoMaterial).filter_by(
            client_uuid=dados.client_uuid
        ).first()
        if existente:
            return {"status": "já registrada", "solicitacao_id": existente.id}

    material = db.query(models.Material).get(dados.material_id)
    if not material:
        raise HTTPException(404, "Material não encontrado")

    solicitacao = models.SolicitacaoMaterial(
        tecnico_id=dados.tecnico_id, material_id=dados.material_id,
        quantidade=dados.quantidade, observacao=dados.observacao,
        client_uuid=dados.client_uuid,
    )
    db.add(solicitacao)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Solicitação já registrada")
    db.refresh(solicitacao)
    return {"status": "enviada", "solicitacao_id": solicitacao.id}


@app.get("/tecnicos/{tecnico_id}/solicitacoes")
def listar_solicitacoes_do_tecnico(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    """Técnico acompanha o status dos pedidos que fez (pra ele saber se já
    foi aprovado, sem precisar perguntar pra ninguém)."""
    solicitacoes = db.query(models.SolicitacaoMaterial).filter_by(
        tecnico_id=tecnico_id
    ).order_by(models.SolicitacaoMaterial.data_solicitacao.desc()).limit(20).all()
    return [
        {
            "id": s.id, "material": s.material.nome, "quantidade": s.quantidade,
            "status": s.status, "data_solicitacao": s.data_solicitacao,
        }
        for s in solicitacoes
    ]


@app.get("/admin/solicitacoes", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def admin_listar_solicitacoes(status: str = "pendente", db: Session = Depends(get_db)):
    solicitacoes = db.query(models.SolicitacaoMaterial).filter_by(status=status).order_by(
        models.SolicitacaoMaterial.data_solicitacao
    ).all()
    return [
        {
            "id": s.id, "tecnico": s.tecnico.nome, "material": s.material.nome,
            "quantidade": s.quantidade, "observacao": s.observacao,
            "data_solicitacao": s.data_solicitacao,
        }
        for s in solicitacoes
    ]


@app.post("/admin/solicitacoes/{solicitacao_id}/aprovar", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def aprovar_solicitacao(solicitacao_id: int, db: Session = Depends(get_db)):
    """Aprovar já debita o estoque central e joga direto no estoque pessoal
    do técnico — sem precisar de uma segunda confirmação dele, já que foi
    ele quem pediu."""
    s = db.query(models.SolicitacaoMaterial).get(solicitacao_id)
    if not s:
        raise HTTPException(404, "Solicitação não encontrada")
    if s.status != models.StatusSolicitacao.pendente:
        return {"status": "já processada"}

    if s.material.qtd_atual < s.quantidade:
        raise HTTPException(400, "Estoque central insuficiente pra aprovar essa quantidade")

    s.material.qtd_atual -= s.quantidade

    pessoal = db.query(models.EstoquePessoal).filter_by(
        tecnico_id=s.tecnico_id, material_id=s.material_id
    ).first()
    if not pessoal:
        pessoal = models.EstoquePessoal(tecnico_id=s.tecnico_id, material_id=s.material_id, qtd_atual=0)
        db.add(pessoal)
    pessoal.qtd_atual += s.quantidade

    s.status = models.StatusSolicitacao.aprovada
    s.data_resposta = datetime.utcnow()
    db.commit()
    return {"status": "aprovada"}


@app.post("/admin/solicitacoes/{solicitacao_id}/rejeitar", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def rejeitar_solicitacao(solicitacao_id: int, db: Session = Depends(get_db)):
    s = db.query(models.SolicitacaoMaterial).get(solicitacao_id)
    if not s:
        raise HTTPException(404, "Solicitação não encontrada")
    if s.status != models.StatusSolicitacao.pendente:
        return {"status": "já processada"}
    s.status = models.StatusSolicitacao.rejeitada
    s.data_resposta = datetime.utcnow()
    db.commit()
    return {"status": "rejeitada"}


# ---------- Visão detalhada por técnico (materiais + ferramentas) ----------

@app.get("/admin/tecnicos/{tecnico_id}/estoque", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def admin_estoque_do_tecnico(tecnico_id: int, db: Session = Depends(get_db)):
    tecnico = db.query(models.Tecnico).get(tecnico_id)
    if not tecnico:
        raise HTTPException(404, "Técnico não encontrado")

    materiais = db.query(models.EstoquePessoal).filter(
        models.EstoquePessoal.tecnico_id == tecnico_id, models.EstoquePessoal.qtd_atual > 0
    ).all()
    ferramentas = db.query(models.Ferramenta).filter_by(
        tecnico_atual_id=tecnico_id, status=models.StatusFerramenta.com_tecnico
    ).all()

    return {
        "tecnico": tecnico.nome,
        "materiais": [
            {"material": m.material.nome, "unidade": m.material.unidade, "qtd_atual": m.qtd_atual}
            for m in materiais
        ],
        "ferramentas": [
            {"nome": f.nome, "categoria": f.categoria} for f in ferramentas
        ],
    }


# ---------- Painel Admin: login, técnicos, ordens, estoque geral ----------

@app.post("/admin/login", response_model=AdminLoginOut)
def admin_login(dados: AdminLogin, db: Session = Depends(get_db)):
    admin = db.query(models.AdminUsuario).filter_by(
        login=dados.login,
        ativo=True,
    ).first()

    if not admin or not bcrypt.checkpw(
        dados.senha.encode(),
        admin.senha_hash.encode(),
    ):
        raise HTTPException(401, "Login ou senha inv?lidos")

    return {
        "id": admin.id,
        "nome": admin.nome,
        "login": admin.login,
        "papel": admin.papel,
        "ativo": admin.ativo,
        "access_token": criar_token_admin(admin),
        "token_type": "bearer",
    }


@app.get("/admin/me", response_model=AdminUsuarioOut)
def admin_me(
    admin: models.AdminUsuario = Depends(obter_admin),
):
    return admin


@app.get("/admin/usuarios", response_model=List[AdminUsuarioOut], dependencies=[Depends(exigir_papel())])
def listar_admin_usuarios(db: Session = Depends(get_db)):
    return db.query(models.AdminUsuario).all()


@app.post("/admin/usuarios", response_model=AdminUsuarioOut, dependencies=[Depends(exigir_papel())])
def criar_admin_usuario(dados: AdminUsuarioCreate, db: Session = Depends(get_db)):
    if dados.papel not in ("gerencia", "almoxarifado"):
        raise HTTPException(400, "Papel inválido")
    if db.query(models.AdminUsuario).filter_by(login=dados.login).first():
        raise HTTPException(409, "Já existe um usuário admin com esse login")
    usuario = models.AdminUsuario(
        nome=dados.nome, login=dados.login,
        senha_hash=bcrypt.hashpw(dados.senha.encode(), bcrypt.gensalt()).decode(),
        papel=dados.papel,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@app.post("/admin/usuarios/{usuario_id}/papel", response_model=AdminUsuarioOut, dependencies=[Depends(exigir_papel())])
def alterar_papel_admin(usuario_id: int, dados: AdminUsuarioPapel, db: Session = Depends(get_db)):
    if dados.papel not in ("gerencia", "almoxarifado"):
        raise HTTPException(400, "Papel inválido")
    usuario = db.query(models.AdminUsuario).get(usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuário não encontrado")
    usuario.papel = dados.papel
    db.commit()
    db.refresh(usuario)
    return usuario


@app.post("/admin/usuarios/{usuario_id}/ativo", response_model=AdminUsuarioOut, dependencies=[Depends(exigir_papel())])
def alterar_ativo_admin(usuario_id: int, dados: AdminUsuarioAtivo, db: Session = Depends(get_db)):
    usuario = db.query(models.AdminUsuario).get(usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuário não encontrado")
    usuario.ativo = dados.ativo
    db.commit()
    db.refresh(usuario)
    return usuario


# ---------- Financeiro (contas a pagar/receber) — só gerência ----------

class ContaFinanceiraCreate(BaseModel):
    tipo: str  # "pagar" | "receber"
    descricao: str
    valor: float
    vencimento: str  # "AAAA-MM-DD"
    categoria: Optional[str] = None
    observacoes: Optional[str] = None


@app.get("/admin/financeiro", dependencies=[Depends(exigir_papel())])
def listar_financeiro(tipo: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.ContaFinanceira)
    if tipo:
        query = query.filter_by(tipo=tipo)
    if status:
        query = query.filter_by(status=status)
    contas = query.order_by(models.ContaFinanceira.vencimento).all()
    hoje = datetime.utcnow().strftime("%Y-%m-%d")
    return [
        {
            "id": c.id, "tipo": c.tipo, "descricao": c.descricao, "valor": c.valor,
            "vencimento": c.vencimento, "categoria": c.categoria, "status": c.status,
            "data_pagamento": c.data_pagamento, "observacoes": c.observacoes,
            "atrasada": c.status == models.StatusConta.pendente and c.vencimento < hoje,
        }
        for c in contas
    ]


@app.get("/admin/financeiro/resumo", dependencies=[Depends(exigir_papel())])
def resumo_financeiro(db: Session = Depends(get_db)):
    contas = db.query(models.ContaFinanceira).all()
    hoje = datetime.utcnow().strftime("%Y-%m-%d")

    def soma(tipo, status=None, atrasada=None):
        total = 0
        for c in contas:
            if c.tipo != tipo:
                continue
            if status and c.status != status:
                continue
            if atrasada is True and not (c.status == models.StatusConta.pendente and c.vencimento < hoje):
                continue
            total += c.valor
        return round(total, 2)

    return {
        "a_pagar_pendente": soma("pagar", models.StatusConta.pendente),
        "a_pagar_atrasado": soma("pagar", atrasada=True),
        "a_receber_pendente": soma("receber", models.StatusConta.pendente),
        "a_receber_atrasado": soma("receber", atrasada=True),
    }


@app.post("/admin/financeiro", dependencies=[Depends(exigir_papel())])
def criar_conta_financeira(dados: ContaFinanceiraCreate, db: Session = Depends(get_db)):
    if dados.tipo not in ("pagar", "receber"):
        raise HTTPException(400, "Tipo inválido")
    conta = models.ContaFinanceira(**dados.model_dump())
    db.add(conta)
    db.commit()
    db.refresh(conta)
    return {"status": "ok", "id": conta.id}


@app.post("/admin/financeiro/{conta_id}/marcar-pago", dependencies=[Depends(exigir_papel())])
def marcar_conta_paga(conta_id: int, db: Session = Depends(get_db)):
    conta = db.query(models.ContaFinanceira).get(conta_id)
    if not conta:
        raise HTTPException(404, "Conta não encontrada")
    conta.status = models.StatusConta.pago
    conta.data_pagamento = datetime.utcnow().strftime("%Y-%m-%d")
    db.commit()
    return {"status": "ok"}


@app.post("/admin/financeiro/{conta_id}/cancelar", dependencies=[Depends(exigir_papel())])
def cancelar_conta_financeira(conta_id: int, db: Session = Depends(get_db)):
    conta = db.query(models.ContaFinanceira).get(conta_id)
    if not conta:
        raise HTTPException(404, "Conta não encontrada")
    conta.status = models.StatusConta.cancelado
    db.commit()
    return {"status": "ok"}


@app.get("/admin/tecnicos", response_model=List[TecnicoOut], dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def admin_listar_tecnicos(db: Session = Depends(get_db)):
    return db.query(models.Tecnico).filter_by(ativo=True).all()


@app.get("/admin/tecnicos/pendentes", response_model=List[TecnicoOut], dependencies=[Depends(exigir_papel())])
def admin_listar_tecnicos_pendentes(db: Session = Depends(get_db)):
    return db.query(models.Tecnico).filter_by(ativo=True, aprovado=False).all()


@app.post("/admin/tecnicos", response_model=TecnicoOut, dependencies=[Depends(exigir_papel())])
def admin_criar_tecnico(dados: TecnicoCreate, db: Session = Depends(get_db)):
    if db.query(models.Tecnico).filter_by(login=dados.login).first():
        raise HTTPException(409, "Já existe um técnico com esse login")
    tecnico = models.Tecnico(
        nome=dados.nome, login=dados.login,
        pin_hash=bcrypt.hashpw(dados.pin.encode(), bcrypt.gensalt()).decode(),
        aprovado=False,  # precisa ser aprovado antes de conseguir logar
        is_adm=dados.is_adm, telefone=dados.telefone, data_contratacao=dados.data_contratacao,
    )
    db.add(tecnico)
    db.commit()
    db.refresh(tecnico)
    return tecnico


@app.post("/admin/tecnicos/{tecnico_id}/aprovar", response_model=TecnicoOut, dependencies=[Depends(exigir_papel())])
def admin_aprovar_tecnico(tecnico_id: int, db: Session = Depends(get_db)):
    tecnico = db.query(models.Tecnico).get(tecnico_id)
    if not tecnico:
        raise HTTPException(404, "Técnico não encontrado")
    tecnico.aprovado = True
    db.commit()
    db.refresh(tecnico)
    return tecnico


@app.post("/admin/tecnicos/{tecnico_id}/permissao", response_model=TecnicoOut, dependencies=[Depends(exigir_papel())])
def admin_alterar_permissao(tecnico_id: int, dados: TecnicoPermissao, db: Session = Depends(get_db)):
    """Define se o técnico é ADM (pode abrir OS avulsa) ou não."""
    tecnico = db.query(models.Tecnico).get(tecnico_id)
    if not tecnico:
        raise HTTPException(404, "Técnico não encontrado")
    tecnico.is_adm = dados.is_adm
    db.commit()
    db.refresh(tecnico)
    return tecnico


@app.post("/admin/tecnicos/{tecnico_id}/resetar-pin", dependencies=[Depends(exigir_papel())])
def admin_resetar_pin(tecnico_id: int, dados: ResetarPin, db: Session = Depends(get_db)):
    tecnico = db.query(models.Tecnico).get(tecnico_id)
    if not tecnico:
        raise HTTPException(404, "Técnico não encontrado")
    if not dados.novo_pin or len(dados.novo_pin) < 4:
        raise HTTPException(400, "O PIN precisa ter pelo menos 4 dígitos")
    tecnico.pin_hash = bcrypt.hashpw(dados.novo_pin.encode(), bcrypt.gensalt()).decode()
    db.commit()
    return {"status": "ok"}


@app.post("/admin/tecnicos/{tecnico_id}/foto-perfil", dependencies=[Depends(exigir_papel())])
async def admin_upload_foto_perfil(tecnico_id: int, arquivo: UploadFile = File(...), db: Session = Depends(get_db)):
    tecnico = db.query(models.Tecnico).get(tecnico_id)
    if not tecnico:
        raise HTTPException(404, "Técnico não encontrado")
    extensao = os.path.splitext(arquivo.filename or "foto.jpg")[1] or ".jpg"
    nome_arquivo = f"tecnico_{tecnico_id}{extensao}"

    caminho_absoluto = Path(PASTA_FOTOS_PERFIL) / nome_arquivo
    caminho_relativo = Path("fotos_perfil") / nome_arquivo

    conteudo = await arquivo.read()

    with open(caminho_absoluto, "wb") as f:
        f.write(conteudo)

    tecnico.foto_perfil = caminho_relativo.as_posix()
    db.commit()
    return {"status": "ok"}


@app.get(
    "/tecnicos/{tecnico_id}/foto-perfil",
)
def ver_foto_perfil(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    tecnico = db.query(models.Tecnico).get(tecnico_id)

    caminho_foto = (
        resolver_caminho_arquivo(tecnico.foto_perfil)
        if tecnico
        else None
    )

    if (
        not tecnico
        or not caminho_foto
        or not caminho_foto.exists()
    ):
        raise HTTPException(
            status_code=404,
            detail="Sem foto de perfil",
        )

    return FileResponse(str(caminho_foto))


@app.get(
    "/admin/tecnicos/{tecnico_id}/foto-perfil",
    dependencies=[Depends(exigir_papel())],
)
def admin_ver_foto_perfil(
    tecnico_id: int,
    db: Session = Depends(get_db),
):
    tecnico = db.query(models.Tecnico).get(tecnico_id)

    caminho_foto = (
        resolver_caminho_arquivo(tecnico.foto_perfil)
        if tecnico
        else None
    )

    if (
        not tecnico
        or not caminho_foto
        or not caminho_foto.exists()
    ):
        raise HTTPException(
            status_code=404,
            detail="Sem foto de perfil",
        )

    return FileResponse(str(caminho_foto))


@app.get("/tecnicos/{tecnico_id}/perfil", response_model=TecnicoOut)
def ver_perfil_tecnico(
    tecnico_id: int,
    db: Session = Depends(get_db),
    tecnico_atual: models.Tecnico = Depends(exigir_mesmo_tecnico),
):
    """O próprio app do técnico usa isso pra mostrar a aba Perfil."""
    tecnico = db.query(models.Tecnico).get(tecnico_id)
    if not tecnico:
        raise HTTPException(404, "Técnico não encontrado")
    return tecnico


@app.post("/admin/ordens", response_model=OrdemOut, dependencies=[Depends(exigir_papel())])
def admin_atribuir_ordem(dados: OrdemAtribuir, db: Session = Depends(get_db)):
    """Admin cria uma OS e já designa pra um técnico específico. Ela aparece
    pro técnico como pendente até ele iniciar em campo."""
    nome_cliente, endereco = dados.nome_cliente, dados.endereco
    if dados.cliente_id:
        cliente = db.query(models.Cliente).get(dados.cliente_id)
        if not cliente:
            raise HTTPException(404, "Cliente não encontrado")
        nome_cliente = nome_cliente or cliente.nome
        endereco = endereco or cliente.endereco

    ordem = models.OrdemServico(
        tecnico_id=dados.tecnico_id, cliente_id=dados.cliente_id,
        tipo=dados.tipo, cliente_local=dados.cliente_local,
        nome_cliente=nome_cliente, endereco=endereco, prioridade=dados.prioridade,
        observacoes=dados.observacoes, status=models.StatusOS.pendente,
        criada_por_admin=True,
    )
    db.add(ordem)
    db.commit()
    db.refresh(ordem)
    return ordem


@app.get("/admin/ordens/{ordem_id}/pdf", dependencies=[Depends(exigir_papel())])
def baixar_pdf_ordem(ordem_id: int, db: Session = Depends(get_db)):
    ordem = db.query(models.OrdemServico).get(ordem_id)

    caminho_pdf = (
        resolver_caminho_arquivo(ordem.pdf_path)
        if ordem and ordem.pdf_path
        else None
    )

    if not ordem or not caminho_pdf or not caminho_pdf.exists():
        raise HTTPException(404, "PDF n?o dispon?vel pra essa OS")

    return FileResponse(
        str(caminho_pdf),
        media_type="application/pdf",
        filename=f"OS_{ordem.id}.pdf",
    )


@app.get("/admin/ordens", dependencies=[Depends(exigir_papel())])
def admin_listar_ordens(status: Optional[str] = None, cliente_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Lista todas as OS (com nome do técnico e itens usados) pro dashboard."""
    query = db.query(models.OrdemServico)
    if status:
        query = query.filter_by(status=status)
    if cliente_id:
        query = query.filter_by(cliente_id=cliente_id)
    ordens = query.order_by(models.OrdemServico.data_abertura.desc()).all()

    def calcular_tempos(o):
        deslocamento_min = inicio_min = total_min = None
        if o.data_deslocamento and o.data_inicio:
            deslocamento_min = round((o.data_inicio - o.data_deslocamento).total_seconds() / 60)
        if o.data_inicio and o.data_fechamento:
            inicio_min = round((o.data_fechamento - o.data_inicio).total_seconds() / 60)
        marco_inicial = o.data_deslocamento or o.data_inicio
        if marco_inicial and o.data_fechamento:
            total_min = round((o.data_fechamento - marco_inicial).total_seconds() / 60)
        return deslocamento_min, inicio_min, total_min

    resultado = []
    for o in ordens:
        min_deslocamento, min_execucao, min_total = calcular_tempos(o)
        resultado.append({
            "id": o.id, "tipo": o.tipo, "cliente_local": o.cliente_local,
            "cliente_id": o.cliente_id,
            "nome_cliente": o.nome_cliente, "endereco": o.endereco, "prioridade": o.prioridade,
            "status": o.status, "tecnico": o.tecnico.nome if o.tecnico else "Nao atribuido",
            "criada_por_admin": o.criada_por_admin,
            "lat_inicio": o.lat_inicio, "lon_inicio": o.lon_inicio,
            "lat_fim": o.lat_fim, "lon_fim": o.lon_fim,
            "data_abertura": o.data_abertura, "data_fechamento": o.data_fechamento,
            "tem_pdf": bool(o.pdf_path),
            "qtd_fotos": len(o.fotos),
            "checklist": {
                "limpar_conector": o.checklist_limpar_conector,
                "testar_sinal": o.checklist_testar_sinal,
                "verificar_otdr": o.checklist_verificar_otdr,
            },
            "minutos_deslocamento": min_deslocamento,
            "minutos_execucao": min_execucao,
            "minutos_total": min_total,
            "materiais_usados": [
                {"material": m.material.nome, "quantidade": m.quantidade}
                for m in o.movimentacoes
            ],
        })
    return resultado


@app.get("/admin/estoque-completo", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def admin_estoque_completo(db: Session = Depends(get_db)):
    """Visão geral do estoque central + ferramentas, pro dashboard do app desktop."""
    materiais = db.query(models.Material).order_by(models.Material.nome).all()
    ferramentas = db.query(models.Ferramenta).order_by(models.Ferramenta.nome).all()
    return {
        "materiais": [
            {"id": m.id, "nome": m.nome, "categoria": m.categoria, "unidade": m.unidade,
             "qtd_atual": m.qtd_atual, "qtd_minima": m.qtd_minima,
             "alerta": m.qtd_atual <= m.qtd_minima}
            for m in materiais
        ],
        "ferramentas": [
            {"id": f.id, "nome": f.nome, "categoria": f.categoria, "status": f.status,
             "tecnico_atual": f.tecnico_atual.nome if f.tecnico_atual else None}
            for f in ferramentas
        ],
    }


@app.get("/admin/estoque-pessoal-geral", dependencies=[Depends(exigir_papel(models.PapelAdmin.almoxarifado))])
def admin_estoque_pessoal_geral(db: Session = Depends(get_db)):
    """O que cada técnico tem fisicamente com ele agora — visão consolidada."""
    itens = db.query(models.EstoquePessoal).filter(models.EstoquePessoal.qtd_atual > 0).all()
    return [
        {
            "tecnico": i.tecnico.nome, "material": i.material.nome,
            "unidade": i.material.unidade, "qtd_atual": i.qtd_atual,
        }
        for i in itens
    ]
