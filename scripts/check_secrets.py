import re
import sys
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
IGNORADOS = {".git", "node_modules", "venv", ".venv", "__pycache__"}
PADROES = {
    "chave privada": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "token GitHub": re.compile(r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}"),
    "chave AWS": re.compile(r"AKIA[0-9A-Z]{16}"),
    "token Telegram": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
}


def arquivos_texto():
    for caminho in RAIZ.rglob("*"):
        if not caminho.is_file() or any(parte in IGNORADOS for parte in caminho.parts):
            continue
        if caminho.suffix.lower() in {".png", ".jpg", ".jpeg", ".ico", ".jar", ".exe"}:
            continue
        yield caminho


def executar() -> int:
    encontrados = []
    for caminho in arquivos_texto():
        try:
            conteudo = caminho.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for nome, padrao in PADROES.items():
            if padrao.search(conteudo):
                encontrados.append(f"{caminho.relative_to(RAIZ)}: {nome}")

    if encontrados:
        print("Possiveis segredos encontrados:", file=sys.stderr)
        print("\n".join(encontrados), file=sys.stderr)
        return 1

    print("Verificacao de segredos: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(executar())
