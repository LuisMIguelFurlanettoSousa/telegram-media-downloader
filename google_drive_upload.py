"""
Google Drive Upload - Streaming direto do Telegram para o Google Drive.

Permite fazer upload de arquivos em chunks sem salvar no disco local,
usando a API de resumable upload do Google Drive v3.
"""

import json
import logging
import mimetypes
import queue
import random
import threading
import time
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = Path(__file__).parent / "drive_token.json"
CREDENTIALS_FILE = Path(__file__).parent / "drive_credentials.json"
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB - múltiplo de 256KB conforme exigido pela API
MAX_UPLOAD_RETRIES = 5
INITIAL_UPLOAD_RETRY_DELAY = 2

RETRYABLE_STATUS_CODES = {403, 429, 500, 502, 503, 504}


class GoogleDriveService:
    """Gerencia autenticação e operações com o Google Drive."""

    def __init__(self):
        self._service = None
        self._session = None
        self._folder_cache: dict[str, str] = {}

    def authenticate(self) -> bool:
        """Autentica via OAuth2. Abre o navegador na primeira vez."""
        creds = None

        if TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Token inválido, será recriado: %s", e)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning("Falha ao renovar token: %s", e)
                creds = None

        if not creds or not creds.valid:
            if not CREDENTIALS_FILE.exists():
                print(f"\n❌ Arquivo '{CREDENTIALS_FILE.name}' não encontrado!")
                print("   Para usar o Google Drive, siga os passos:")
                print("   1. Acesse: https://console.cloud.google.com")
                print("   2. Crie um projeto e ative a Google Drive API")
                print("   3. Crie credenciais OAuth 2.0 (tipo: Desktop)")
                print(f"   4. Baixe o JSON como '{CREDENTIALS_FILE.name}' na raiz do projeto\n")
                return False

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())
        self._service = build("drive", "v3", credentials=creds)
        self._session = AuthorizedSession(creds)
        print("  ✅ Autenticado no Google Drive!\n")
        return True

    def get_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """Retorna o ID da pasta, criando se não existir. Usa cache interno."""
        cache_key = f"{parent_id or 'root'}:{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = self._service.files().list(
            q=query, spaces="drive", fields="files(id, name)", pageSize=1
        ).execute()

        files = results.get("files", [])
        if files:
            folder_id = files[0]["id"]
        else:
            metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            if parent_id:
                metadata["parents"] = [parent_id]

            folder = self._service.files().create(body=metadata, fields="id").execute()
            folder_id = folder["id"]

        self._folder_cache[cache_key] = folder_id
        return folder_id

    def ensure_folder_path(self, path_parts: list[str], root_id: str | None = None) -> str:
        """Cria pastas aninhadas e retorna o ID da última."""
        current_parent = root_id
        for part in path_parts:
            current_parent = self.get_or_create_folder(part, current_parent)
        return current_parent

    def list_files_in_folder(self, folder_id: str) -> dict[str, dict]:
        """Lista arquivos de uma pasta. Retorna dict[nome, {id, size}]."""
        files_dict = {}
        page_token = None

        while True:
            results = self._service.files().list(
                q=f"'{folder_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
                spaces="drive",
                fields="nextPageToken, files(id, name, size)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()

            for f in results.get("files", []):
                files_dict[f["name"]] = {
                    "id": f["id"],
                    "size": int(f.get("size", 0)),
                }

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        return files_dict

    def initiate_resumable_upload(
        self, file_name: str, mime_type: str, parent_id: str, file_size: int | None = None
    ) -> str:
        """Inicia um upload resumível e retorna a URI de upload."""
        metadata = json.dumps({"name": file_name, "parents": [parent_id]})

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": mime_type,
        }
        if file_size and file_size > 0:
            headers["X-Upload-Content-Length"] = str(file_size)

        response = self._session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            data=metadata,
            headers=headers,
        )
        response.raise_for_status()
        return response.headers["Location"]

    def upload_chunk(
        self, upload_uri: str, chunk_data: bytes, offset: int, total_size: int | None
    ) -> dict | None:
        """Envia um chunk para o upload resumível. Retorna metadata do arquivo se finalizado."""
        chunk_end = offset + len(chunk_data) - 1

        if total_size and total_size > 0:
            content_range = f"bytes {offset}-{chunk_end}/{total_size}"
        else:
            content_range = f"bytes {offset}-{chunk_end}/*"

        headers = {
            "Content-Length": str(len(chunk_data)),
            "Content-Range": content_range,
        }

        for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
            try:
                response = self._session.put(upload_uri, data=chunk_data, headers=headers)

                if response.status_code == 200 or response.status_code == 201:
                    return response.json()

                if response.status_code == 308:
                    return None

                if response.status_code in RETRYABLE_STATUS_CODES:
                    delay = INITIAL_UPLOAD_RETRY_DELAY * (2 ** (attempt - 1))
                    jitter = random.uniform(0, delay * 0.3)
                    logger.warning(
                        "Erro retentável %d no chunk (offset=%d), tentativa %d/%d, aguardando %.1fs",
                        response.status_code, offset, attempt, MAX_UPLOAD_RETRIES, delay + jitter,
                    )
                    time.sleep(delay + jitter)
                    continue

                response.raise_for_status()

            except Exception as e:
                if attempt >= MAX_UPLOAD_RETRIES:
                    raise
                delay = INITIAL_UPLOAD_RETRY_DELAY * (2 ** (attempt - 1))
                jitter = random.uniform(0, delay * 0.3)
                logger.warning("Erro no upload chunk (offset=%d): %s, retentando em %.1fs", offset, e, delay + jitter)
                time.sleep(delay + jitter)

        raise RuntimeError(f"Falha ao enviar chunk após {MAX_UPLOAD_RETRIES} tentativas")

    def finalize_upload(self, upload_uri: str, chunk_data: bytes, offset: int, total_size: int) -> dict:
        """Envia o chunk final com o tamanho total conhecido."""
        chunk_end = offset + len(chunk_data) - 1
        content_range = f"bytes {offset}-{chunk_end}/{total_size}"

        headers = {
            "Content-Length": str(len(chunk_data)),
            "Content-Range": content_range,
        }

        for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
            try:
                response = self._session.put(upload_uri, data=chunk_data, headers=headers)

                if response.status_code in (200, 201):
                    return response.json()

                if response.status_code in RETRYABLE_STATUS_CODES:
                    delay = INITIAL_UPLOAD_RETRY_DELAY * (2 ** (attempt - 1))
                    jitter = random.uniform(0, delay * 0.3)
                    logger.warning("Erro retentável %d no chunk final, tentativa %d/%d", response.status_code, attempt, MAX_UPLOAD_RETRIES)
                    time.sleep(delay + jitter)
                    continue

                response.raise_for_status()

            except Exception as e:
                if attempt >= MAX_UPLOAD_RETRIES:
                    raise
                delay = INITIAL_UPLOAD_RETRY_DELAY * (2 ** (attempt - 1))
                jitter = random.uniform(0, delay * 0.3)
                logger.warning("Erro no chunk final: %s, retentando em %.1fs", e, delay + jitter)
                time.sleep(delay + jitter)

        raise RuntimeError(f"Falha ao finalizar upload após {MAX_UPLOAD_RETRIES} tentativas")


_SENTINEL = object()


class GoogleDriveWriter:
    """File-like object que faz streaming do Telethon direto para o Google Drive.

    O Telethon chama write(data) repetidamente durante o download.
    Os dados são bufferizados e enviados em chunks de 10MB ao Drive.

    Usa uma thread dedicada de upload para não bloquear o event loop do asyncio.
    Usa bytearray para evitar cópias desnecessárias de memória.
    """

    def __init__(self, drive_service: GoogleDriveService, upload_uri: str, total_size: int | None = None):
        self._drive = drive_service
        self._upload_uri = upload_uri
        self._total_size = total_size
        self._buffer = bytearray()
        self._bytes_uploaded = 0
        self._finalized = False
        self._error: Exception | None = None

        # Thread dedicada para upload — não bloqueia o event loop
        self._upload_queue: queue.Queue = queue.Queue(maxsize=2)
        self._upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self._upload_thread.start()

    def write(self, data: bytes) -> int:
        """Bufferiza dados e envia chunks de CHUNK_SIZE ao Drive via thread."""
        if self._error:
            raise self._error

        self._buffer.extend(data)

        while len(self._buffer) >= CHUNK_SIZE:
            chunk = bytes(self._buffer[:CHUNK_SIZE])
            del self._buffer[:CHUNK_SIZE]
            self._upload_queue.put(("chunk", chunk, self._bytes_uploaded))
            self._bytes_uploaded += len(chunk)

        return len(data)

    def tell(self) -> int:
        """Retorna total de bytes processados (enviados + buffer). Necessário pelo Telethon."""
        return self._bytes_uploaded + len(self._buffer)

    def close(self):
        """Envia o buffer restante como chunk final e aguarda a thread finalizar."""
        if self._finalized:
            return

        if len(self._buffer) > 0:
            total = self._bytes_uploaded + len(self._buffer)
            remaining = bytes(self._buffer)
            self._buffer.clear()
            self._upload_queue.put(("finalize", remaining, self._bytes_uploaded, total))
            self._bytes_uploaded += len(remaining)
        elif self._bytes_uploaded > 0:
            self._finalized = True

        # Sinalizar fim da thread e aguardar
        self._upload_queue.put(_SENTINEL)
        self._upload_thread.join(timeout=300)

        if self._error:
            raise self._error

        if not self._finalized and self._bytes_uploaded > 0:
            self._finalized = True

    def release_buffer(self):
        """Libera recursos. Chamado em caso de erro para evitar leak."""
        self._buffer.clear()
        # Drenar a fila e sinalizar fim
        while not self._upload_queue.empty():
            try:
                self._upload_queue.get_nowait()
            except queue.Empty:
                break
        self._upload_queue.put(_SENTINEL)
        self._upload_thread.join(timeout=10)

    def _upload_worker(self):
        """Thread dedicada que processa a fila de chunks para upload."""
        while True:
            item = self._upload_queue.get()

            if item is _SENTINEL:
                break

            try:
                if item[0] == "chunk":
                    _, chunk_data, offset = item
                    self._drive.upload_chunk(
                        self._upload_uri, chunk_data, offset, self._total_size
                    )
                elif item[0] == "finalize":
                    _, chunk_data, offset, total = item
                    result = self._drive.finalize_upload(
                        self._upload_uri, chunk_data, offset, total
                    )
                    self._finalized = result is not None
            except Exception as e:
                self._error = e
                break


def get_mime_type(file_name: str) -> str:
    """Detecta o MIME type pelo nome do arquivo."""
    mime, _ = mimetypes.guess_type(file_name)
    return mime or "application/octet-stream"
