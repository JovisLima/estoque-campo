import mimetypes
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi.responses import FileResponse, StreamingResponse

from settings import settings


PASTAS_GERENCIADAS = {
    "fotos_perfil",
    "rotas_cabo",
    "fotos_os",
    "relatorios",
}


class ArquivoNaoEncontrado(FileNotFoundError):
    pass


def normalizar_chave(chave: str | Path) -> str:
    bruto = str(chave).replace("\\", "/")
    partes = [parte for parte in bruto.split("/") if parte not in {"", "."}]

    for indice, parte in enumerate(partes):
        if parte in PASTAS_GERENCIADAS:
            partes = partes[indice:]
            break

    if not partes or partes[0] not in PASTAS_GERENCIADAS:
        raise ValueError("chave fora das pastas de arquivos gerenciadas")
    if any(parte == ".." for parte in partes):
        raise ValueError("chave de arquivo invalida")
    return "/".join(partes)


class ArmazenamentoArquivos:
    def __init__(self):
        self.backend = settings.object_storage_backend
        self.raiz = settings.data_dir.resolve()
        self.raiz_legada = Path(__file__).resolve().parent
        self.raiz.mkdir(parents=True, exist_ok=True)
        self._s3 = None

    def _cliente_s3(self):
        if self._s3 is None:
            import boto3

            self._s3 = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                region_name=settings.s3_region,
            )
        return self._s3

    @staticmethod
    def _erro_cliente_s3():
        from botocore.exceptions import ClientError

        return ClientError

    def _chave_s3(self, chave: str) -> str:
        prefixo = settings.s3_prefix
        return f"{prefixo}/{chave}" if prefixo else chave

    def verificar_acesso(self) -> None:
        if self.backend == "local":
            self.raiz.mkdir(parents=True, exist_ok=True)
            return
        prefixo = settings.s3_prefix
        if prefixo:
            prefixo += "/"
        self._cliente_s3().list_objects_v2(
            Bucket=settings.s3_bucket,
            Prefix=prefixo,
            MaxKeys=1,
        )

    def caminho_local(self, chave: str | Path) -> Path:
        normalizada = normalizar_chave(chave)
        caminho = (self.raiz / normalizada).resolve()
        try:
            caminho.relative_to(self.raiz)
        except ValueError as erro:
            raise ValueError("caminho de arquivo fora da area permitida") from erro
        return caminho

    def _caminho_local_existente(self, chave: str | Path) -> Path:
        normalizada = normalizar_chave(chave)
        atual = self.caminho_local(normalizada)
        if atual.is_file():
            return atual
        legado = (self.raiz_legada / normalizada).resolve()
        try:
            legado.relative_to(self.raiz_legada)
        except ValueError as erro:
            raise ValueError("caminho legado fora da area permitida") from erro
        return legado

    def salvar_bytes(
        self,
        chave: str | Path,
        conteudo: bytes,
        content_type: str | None = None,
    ) -> str:
        normalizada = normalizar_chave(chave)
        tipo = content_type or mimetypes.guess_type(normalizada)[0]
        if self.backend == "s3":
            parametros = {
                "Bucket": settings.s3_bucket,
                "Key": self._chave_s3(normalizada),
                "Body": conteudo,
            }
            if tipo:
                parametros["ContentType"] = tipo
            self._cliente_s3().put_object(**parametros)
            return normalizada

        destino = self.caminho_local(normalizada)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(f".{destino.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporario.write_bytes(conteudo)
            os.replace(temporario, destino)
        finally:
            if temporario.exists():
                temporario.unlink()
        return normalizada

    def salvar_arquivo(
        self,
        chave: str | Path,
        origem: str | Path,
        content_type: str | None = None,
    ) -> str:
        normalizada = normalizar_chave(chave)
        origem_path = Path(origem)
        if self.backend == "s3":
            argumentos = {}
            tipo = content_type or mimetypes.guess_type(normalizada)[0]
            if tipo:
                argumentos["ContentType"] = tipo
            self._cliente_s3().upload_file(
                str(origem_path),
                settings.s3_bucket,
                self._chave_s3(normalizada),
                ExtraArgs=argumentos or None,
            )
            return normalizada
        return self.salvar_bytes(
            normalizada,
            origem_path.read_bytes(),
            content_type,
        )

    def existe(self, chave: str | Path) -> bool:
        try:
            normalizada = normalizar_chave(chave)
        except ValueError:
            return False
        if self.backend == "local":
            return self._caminho_local_existente(normalizada).is_file()
        try:
            self._cliente_s3().head_object(
                Bucket=settings.s3_bucket,
                Key=self._chave_s3(normalizada),
            )
            return True
        except self._erro_cliente_s3() as erro:
            codigo = erro.response.get("Error", {}).get("Code")
            if codigo in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def resposta(
        self,
        chave: str | Path,
        *,
        media_type: str | None = None,
        filename: str | None = None,
    ):
        normalizada = normalizar_chave(chave)
        tipo = media_type or mimetypes.guess_type(normalizada)[0]
        if self.backend == "local":
            caminho = self._caminho_local_existente(normalizada)
            if not caminho.is_file():
                raise ArquivoNaoEncontrado(normalizada)
            return FileResponse(
                str(caminho),
                media_type=tipo,
                filename=filename,
            )

        try:
            objeto = self._cliente_s3().get_object(
                Bucket=settings.s3_bucket,
                Key=self._chave_s3(normalizada),
            )
        except self._erro_cliente_s3() as erro:
            codigo = erro.response.get("Error", {}).get("Code")
            if codigo in {"404", "NoSuchKey", "NotFound"}:
                raise ArquivoNaoEncontrado(normalizada) from erro
            raise
        headers = {}
        if filename:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return StreamingResponse(
            objeto["Body"].iter_chunks(chunk_size=64 * 1024),
            media_type=tipo or objeto.get("ContentType"),
            headers=headers,
        )

    @contextmanager
    def materializar(self, chave: str | Path) -> Iterator[Path]:
        normalizada = normalizar_chave(chave)
        if self.backend == "local":
            caminho = self._caminho_local_existente(normalizada)
            if not caminho.is_file():
                raise ArquivoNaoEncontrado(normalizada)
            yield caminho
            return

        pasta_temporaria = self.raiz / ".storage_tmp"
        pasta_temporaria.mkdir(parents=True, exist_ok=True)
        sufixo = Path(normalizada).suffix
        descritor, nome = tempfile.mkstemp(
            prefix="aven-",
            suffix=sufixo,
            dir=pasta_temporaria,
        )
        os.close(descritor)
        caminho = Path(nome)
        try:
            with caminho.open("wb") as arquivo:
                self._cliente_s3().download_fileobj(
                    settings.s3_bucket,
                    self._chave_s3(normalizada),
                    arquivo,
                )
            yield caminho
        finally:
            caminho.unlink(missing_ok=True)


armazenamento = ArmazenamentoArquivos()
