#!/usr/bin/env python3
"""
Telegram Group Downloader
Baixa vídeos e arquivos de grupos do Telegram via API (MTProto).
"""

import os
import re
import sys
import asyncio
import json
import logging
import shutil
import time
from pathlib import Path

from telethon import TelegramClient, errors
from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    InputMessagesFilterDocument,
    InputMessagesFilterPhotos,
    InputMessagesFilterVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

SESSION_NAME = "telegram_session"
CONFIG_FILE = Path(__file__).parent / "config.json"
LOG_FILE = Path(__file__).parent / "download_log.json"
COURSE_STRUCTURE_FILE = Path(__file__).parent / "course_structure.json"

MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300
MAX_CONCURRENT_DOWNLOADS = 3
DOWNLOAD_DELAY = 1.0

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "downloader.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

MEDIA_FILTERS = {
    "1": {"label": "Apenas vídeos", "types": ["video"]},
    "2": {"label": "Apenas fotos", "types": ["photo"]},
    "3": {"label": "Apenas documentos/arquivos", "types": ["document"]},
    "4": {"label": "Tudo (vídeos + fotos + documentos)", "types": ["video", "photo", "document"]},
}


def load_course_structure(file_path: Path = COURSE_STRUCTURE_FILE) -> dict | None:
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Falha ao carregar estrutura do curso: %s", e)
        return None


def resolve_folder_from_message(message_text: str | None, structure: dict) -> str | None:
    if not message_text:
        return None

    tags = re.findall(r'#([A-Za-z]+)(\d+)', message_text)
    if not tags:
        return None

    for tag_prefix, tag_number_str in tags:
        tag_number = int(tag_number_str)
        for section in structure.get("sections", []):
            if section["prefix"].lower() != tag_prefix.lower():
                continue
            start, end = section["range"]
            if start <= tag_number <= end:
                return section["folder"]

    return None


def load_credentials() -> tuple[str, str]:
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
        api_id = data.get("api_id")
        api_hash = data.get("api_hash")
        if api_id and api_hash:
            return str(api_id), api_hash

    print(f"{'='*55}")
    print("  CONFIGURAÇÃO INICIAL")
    print(f"{'='*55}")
    print()
    print("  Para usar este script, você precisa de credenciais")
    print("  da API do Telegram. Siga os passos:")
    print()
    print("  1. Acesse: https://my.telegram.org")
    print("  2. Faça login com seu número de telefone")
    print("  3. Clique em 'API development tools'")
    print("  4. Crie um aplicativo (qualquer nome serve)")
    print("  5. Copie o 'api_id' e o 'api_hash'")
    print()
    print(f"{'='*55}\n")

    try:
        api_id = input("👉 Cole seu api_id: ").strip()
        api_hash = input("👉 Cole seu api_hash: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        sys.exit(0)

    if not api_id or not api_hash:
        print("❌ api_id e api_hash são obrigatórios.")
        sys.exit(1)

    CONFIG_FILE.write_text(json.dumps({"api_id": api_id, "api_hash": api_hash}, indent=2))
    print(f"\n✅ Credenciais salvas em {CONFIG_FILE.name}\n")

    return api_id, api_hash


def format_size(size_bytes: int) -> str:
    if size_bytes is None:
        return "tamanho desconhecido"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    return name[:255]


def check_cryptg():
    try:
        import cryptg
        return True
    except ImportError:
        return False


def get_file_name(message) -> str | None:
    if not message.media:
        return None

    if isinstance(message.media, MessageMediaPhoto):
        return sanitize_filename(f"foto_{message.id}.jpg")

    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        if doc is None:
            return None

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                stem = Path(attr.file_name).stem
                suffix = Path(attr.file_name).suffix
                return sanitize_filename(f"{stem}_msg{message.id}{suffix}")

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                ext = "mp4"
                mime = getattr(doc, "mime_type", "")
                if "webm" in mime:
                    ext = "webm"
                elif "mkv" in mime:
                    ext = "mkv"
                return sanitize_filename(f"video_{message.id}.{ext}")

        mime = getattr(doc, "mime_type", "")
        ext = mime.split("/")[-1] if "/" in mime else "bin"
        return sanitize_filename(f"arquivo_{message.id}.{ext}")

    return None


def classify_media(message) -> str | None:
    if not message.media:
        return None

    if isinstance(message.media, MessageMediaPhoto):
        return "photo"

    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        if doc is None:
            return None

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                return "video"

        return "document"

    return None


class DownloadProgress:
    def __init__(self):
        self.start_time = time.time()

    def callback(self, current, total):
        if total <= 0:
            return
        elapsed = time.time() - self.start_time
        speed = current / elapsed if elapsed > 0.5 else 0
        remaining = (total - current) / speed if speed > 0 else 0

        percent = (current / total) * 100
        bar_length = 30
        filled = int(bar_length * current // total)
        bar = "█" * filled + "░" * (bar_length - filled)

        speed_str = f"{format_size(int(speed))}/s" if speed > 0 else "calculando..."
        eta_str = time.strftime("%M:%S", time.gmtime(remaining)) if speed > 0 else "--:--"

        sys.stdout.write(
            f"\r  [{bar}] {percent:.1f}% ({format_size(current)}/{format_size(total)}) "
            f"{speed_str} ETA: {eta_str}  "
        )
        sys.stdout.flush()


def load_download_log() -> dict:
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

        # Migração do formato antigo para o novo (message_id como chave)
        for key, value in log.items():
            if isinstance(value, dict) and "downloaded" not in value:
                old_failed = value.get("failed_files", [])
                new_failed = {}
                for fname in old_failed:
                    new_failed[fname] = {"file": fname, "error": "migrado do formato antigo"}
                log[key] = {
                    "downloaded": {},
                    "failed": new_failed,
                    "stats": {
                        "completed": value.get("completed", 0),
                        "errors": value.get("errors", len(old_failed)),
                    },
                }

        return log
    return {}


def save_download_log(log: dict):
    try:
        tmp = LOG_FILE.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(log, indent=2, ensure_ascii=False))
        os.replace(str(tmp), str(LOG_FILE))
    except Exception as e:
        logger.warning("Falha ao salvar log de download: %s", e)



def check_disk_space(path: Path, required_bytes: int) -> bool:
    free = shutil.disk_usage(path).free
    if free < required_bytes * 1.1:
        print(f"\n  ⚠  Espaço em disco pode ser insuficiente!")
        print(f"     Necessário: ~{format_size(required_bytes)}")
        print(f"     Disponível: {format_size(free)}")
        return False
    return True


async def download_with_retry(
    client: TelegramClient, entity, message_id: int, file_path: Path, expected_size: int | None,
    show_progress: bool = True, drive_service=None, drive_folder_id: str | None = None,
    file_name: str | None = None,
) -> bool:
    is_drive = drive_service is not None and drive_folder_id is not None
    attempt = 1
    while attempt <= MAX_RETRIES:
        writer = None
        try:
            fresh_message = await client.get_messages(entity, ids=message_id)
            if fresh_message is None:
                logger.warning("Mensagem %d não encontrada ao re-buscar", message_id)
                print(f"\n  ⚠  Mensagem {message_id} não encontrada no grupo")
                return False

            progress = DownloadProgress() if show_progress else None

            if is_drive:
                from google_drive_upload import GoogleDriveWriter, get_mime_type
                mime = get_mime_type(file_name or "arquivo.bin")
                upload_uri = drive_service.initiate_resumable_upload(
                    file_name, mime, drive_folder_id, expected_size
                )
                writer = GoogleDriveWriter(drive_service, upload_uri, expected_size)
                result = await client.download_media(
                    fresh_message,
                    file=writer,
                    progress_callback=progress.callback if progress else None,
                )
                if show_progress:
                    print()
                writer.close()

                if writer.tell() == 0:
                    logger.warning("Download vazio (Drive): %s (tentativa %d/%d)", file_name, attempt, MAX_RETRIES)
                    if attempt < MAX_RETRIES:
                        delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
                        print(f"\n  ⚠  Download vazio: {file_name}")
                        print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
                        await asyncio.sleep(delay)
                    attempt += 1
                    continue

                if not writer._finalized:
                    logger.warning("Upload não finalizado (Drive): %s (tentativa %d/%d)", file_name, attempt, MAX_RETRIES)
                    if attempt < MAX_RETRIES:
                        delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
                        print(f"\n  ⚠  Upload não concluído: {file_name}")
                        print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
                        await asyncio.sleep(delay)
                    attempt += 1
                    continue

                return True

            # Modo local (original)
            result = await client.download_media(
                fresh_message,
                file=str(file_path),
                progress_callback=progress.callback if progress else None,
            )
            if show_progress:
                print()

            if result is None:
                if file_path.exists():
                    file_path.unlink()
                logger.warning("download_media retornou None: %s (tentativa %d/%d)", file_path.name, attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
                    print(f"\n  ⚠  Download silencioso falhou: {file_path.name}")
                    print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
                    await asyncio.sleep(delay)
                attempt += 1
                continue

            result_path = Path(result)
            if not result_path.exists():
                logger.warning("Arquivo não encontrado após download: %s (tentativa %d/%d)", result_path.name, attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
                    print(f"\n  ⚠  Arquivo não encontrado: {file_path.name}")
                    print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
                    await asyncio.sleep(delay)
                attempt += 1
                continue

            if result_path != file_path:
                result_path.rename(file_path)

            if file_path.stat().st_size == 0:
                logger.warning("Arquivo vazio após download: %s", file_path.name)
                file_path.unlink()
                if attempt < MAX_RETRIES:
                    delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
                    print(f"\n  ⚠  Arquivo vazio: {file_path.name}")
                    print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
                    await asyncio.sleep(delay)
                attempt += 1
                continue

            return True

        except asyncio.CancelledError:
            if not is_drive and file_path.exists():
                file_path.unlink()
                print(f"\n  🗑  Arquivo incompleto removido: {file_path.name}")
            raise

        except errors.FloodWaitError as e:
            wait_time = e.seconds + 5
            print(f"\n  ⏳ Flood wait do Telegram: aguardando {wait_time}s antes de retentar...")
            logger.warning("FloodWaitError: aguardando %ds", wait_time)
            if not is_drive and file_path.exists():
                file_path.unlink()
            await asyncio.sleep(wait_time)
            # FloodWait NÃO consome tentativa

        except (ConnectionError, TimeoutError, OSError) as e:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            print(f"\n  🔌 Erro de conexão: {e}")
            print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
            logger.warning("Erro de conexão: %s (tentativa %d/%d, retry em %ds)", e, attempt, MAX_RETRIES, delay)
            if not is_drive and file_path.exists():
                file_path.unlink()
            await asyncio.sleep(delay)
            attempt += 1

        except Exception as e:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            print(f"\n  ❌ Erro inesperado: {e}")
            print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
            logger.warning("Erro inesperado: %s (tentativa %d/%d)", e, attempt, MAX_RETRIES)
            if not is_drive and file_path.exists():
                file_path.unlink()
            await asyncio.sleep(delay)
            attempt += 1

    display_name = file_name if is_drive else file_path.name
    logger.error("Falha permanente após %d tentativas: %s", MAX_RETRIES, display_name)
    return False


async def list_groups(client: TelegramClient) -> list:
    groups = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            groups.append(dialog)
    return groups


TELETHON_FILTERS = {
    "video": InputMessagesFilterVideo,
    "photo": InputMessagesFilterPhotos,
    "document": InputMessagesFilterDocument,
}


async def scan_group_media(
    client: TelegramClient, group, media_types: list[str], limit: int | None,
    download_dir: Path, download_log: dict, group_log_key: str,
    course_structure: dict | None = None,
    drive_service=None, drive_group_folder_id: str | None = None,
):
    """Escaneia mensagens UMA vez, retornando stats e lista de pendentes."""
    total_size = 0
    counts = {"video": 0, "photo": 0, "document": 0}
    pending = []
    skipped = 0
    is_drive = drive_service is not None and drive_group_folder_id is not None

    # Cache de arquivos existentes no Drive (por pasta)
    drive_folder_files: dict[str, dict[str, dict]] = {}

    print(f"📊 Escaneando grupo '{group.name}'...", end="", flush=True)

    telethon_filter = None
    if len(media_types) == 1:
        telethon_filter = TELETHON_FILTERS.get(media_types[0])

    # Contagem instantânea quando há filtro server-side
    if telethon_filter:
        quick_count = await client.get_messages(group.entity, 0, filter=telethon_filter())
        if quick_count.total == 0:
            print(f" 0 {media_types[0]}s encontrados.\n")
            return {"total_size": 0, "counts": counts}, [], 0
        print(f" ~{quick_count.total} encontrados...", end="", flush=True)

    success = False
    for attempt_num in range(1, MAX_RETRIES + 1):
        try:
            async for message in client.iter_messages(
                group.entity, limit=limit, reverse=True,
                filter=telethon_filter
            ):
                media_type = classify_media(message)
                if media_type is None or media_type not in media_types:
                    continue

                counts[media_type] += 1
                file_name = get_file_name(message)
                if file_name is None:
                    continue

                expected_size = None
                if isinstance(message.media, MessageMediaDocument) and message.media.document:
                    expected_size = message.media.document.size or 0
                    total_size += expected_size

                # Verificar no log se já foi baixado
                msg_id_str = str(message.id)
                if msg_id_str in download_log.get(group_log_key, {}).get("downloaded", {}):
                    skipped += 1
                    continue

                if is_drive:
                    # Modo Drive: resolver pasta e verificar existência no Drive
                    if course_structure:
                        subfolder = resolve_folder_from_message(message.text, course_structure)
                        folder_name = subfolder if subfolder else "_sem_classificacao"
                        drive_folder_id = drive_service.get_or_create_folder(folder_name, drive_group_folder_id)
                    else:
                        drive_folder_id = drive_group_folder_id

                    # Cache de listagem por pasta (1 request por pasta, não por arquivo)
                    if drive_folder_id not in drive_folder_files:
                        drive_folder_files[drive_folder_id] = drive_service.list_files_in_folder(drive_folder_id)

                    existing = drive_folder_files[drive_folder_id].get(file_name)
                    if existing:
                        if expected_size and existing["size"] != expected_size:
                            pass  # Tamanho diferente, re-baixar
                        elif existing["size"] == 0:
                            pass  # Arquivo vazio, re-baixar
                        else:
                            skipped += 1
                            continue

                    pending.append((message.id, media_type, file_name, drive_folder_id, expected_size))
                else:
                    # Modo local: resolver subpasta no disco
                    if course_structure:
                        subfolder = resolve_folder_from_message(message.text, course_structure)
                        if subfolder:
                            target_dir = download_dir / subfolder
                            target_dir.mkdir(parents=True, exist_ok=True)
                        else:
                            target_dir = download_dir / "_sem_classificacao"
                            target_dir.mkdir(parents=True, exist_ok=True)
                    else:
                        target_dir = download_dir

                    file_path = target_dir / file_name

                    if file_path.exists():
                        if expected_size and file_path.stat().st_size != expected_size:
                            file_path.unlink()
                        elif file_path.stat().st_size == 0:
                            file_path.unlink()
                        else:
                            skipped += 1
                            continue

                    pending.append((message.id, media_type, file_name, file_path, expected_size))

            success = True
            break
        except errors.FloodWaitError as e:
            wait_time = e.seconds + 5
            print(f"\n  ⏳ Flood wait: aguardando {wait_time}s...")
            await asyncio.sleep(wait_time)
            total_size = 0
            counts = {"video": 0, "photo": 0, "document": 0}
            pending = []
            skipped = 0
            drive_folder_files.clear()
        except (ConnectionError, TimeoutError, OSError) as e:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt_num - 1)), MAX_RETRY_DELAY)
            print(f"\n  🔌 Erro: {e}, retentando em {delay}s...")
            await asyncio.sleep(delay)
            total_size = 0
            counts = {"video": 0, "photo": 0, "document": 0}
            pending = []
            skipped = 0
            drive_folder_files.clear()

    if not success:
        print(" FALHOU!\n")
        return None, [], 0

    print(" OK!\n")
    return {"total_size": total_size, "counts": counts}, pending, skipped


async def download_media_from_group(
    client: TelegramClient, group, media_types: list[str], limit: int | None,
    base_dir: Path | None = None, course_structure: dict | None = None,
    drive_service=None, drive_root_folder_id: str | None = None,
):
    group_name = sanitize_filename(group.name)
    is_drive = drive_service is not None and drive_root_folder_id is not None

    if is_drive:
        download_dir = Path.cwd()  # Placeholder, não será usado para salvar arquivos
        drive_group_folder_id = drive_service.get_or_create_folder(group_name, drive_root_folder_id)
    else:
        if base_dir is None:
            base_dir = Path.cwd() / "downloads"
        download_dir = base_dir / group_name
        download_dir.mkdir(parents=True, exist_ok=True)
        drive_group_folder_id = None

    # Inicializar log ANTES do scan (o scan precisa consultá-lo)
    download_log = load_download_log()
    group_log_key = group_name
    if group_log_key not in download_log:
        download_log[group_log_key] = {"downloaded": {}, "failed": {}, "stats": {"completed": 0, "errors": 0}}

    if course_structure:
        num_sections = len(course_structure.get("sections", []))
        print(f"📁 Estrutura de pastas ativa: {num_sections} seções configuradas\n")

    stats, pending, skipped = await scan_group_media(
        client, group, media_types, limit, download_dir, download_log, group_log_key,
        course_structure, drive_service, drive_group_folder_id,
    )
    if stats is None:
        print("❌ Falha ao escanear o grupo. Verifique sua conexão.\n")
        return

    total_items = sum(stats["counts"].values())
    if total_items == 0:
        print("❌ Nenhuma mídia encontrada com os filtros selecionados.\n")
        return

    print(f"  {'='*45}")
    print(f"  RESUMO DO GRUPO")
    print(f"  {'='*45}")
    if stats["counts"]["video"]:
        print(f"  🎬 Vídeos:     {stats['counts']['video']}")
    if stats["counts"]["photo"]:
        print(f"  🖼  Fotos:      {stats['counts']['photo']}")
    if stats["counts"]["document"]:
        print(f"  📄 Documentos: {stats['counts']['document']}")
    print(f"  📦 Total:      {total_items} arquivos")
    print(f"  💾 Tamanho:    ~{format_size(stats['total_size'])} (sem contar fotos)")
    is_parallel = MAX_CONCURRENT_DOWNLOADS > 1
    if is_parallel:
        print(f"  🚀 Modo:       {MAX_CONCURRENT_DOWNLOADS} downloads simultâneos")
    if is_drive:
        print(f"  ☁️  Destino:    Google Drive")
    print(f"  {'='*45}")

    if not is_drive and stats["total_size"] > 0 and not check_disk_space(download_dir, stats["total_size"]):
        try:
            cont = input("\n  Deseja continuar mesmo assim? (s/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            return
        if cont != "s":
            print("⏭  Download cancelado.\n")
            return
    print()

    if not pending:
        print(f"✅ Todos os {skipped} arquivos já foram baixados!\n")
        return

    print(f"  📥 {len(pending)} para baixar | ⏭ {skipped} já existem\n")

    try:
        confirma = input("👉 Deseja continuar com o download? (s/n): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        return

    if confirma != "s":
        print("⏭  Download cancelado.\n")
        return

    if is_drive:
        print(f"\n☁️  Salvando no Google Drive\n")
    else:
        print(f"\n📂 Salvando em: {download_dir}\n")

    downloaded = 0
    error_count = 0
    start_time = time.time()

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    counter_lock = asyncio.Lock()

    async def download_one(item_index: int, message_id: int, media_type: str, file_name: str, file_path_or_folder_id, expected_size: int | None):
        nonlocal downloaded, error_count

        async with semaphore:
            if is_parallel:
                await asyncio.sleep(DOWNLOAD_DELAY)

            size_str = f" ({format_size(expected_size)})" if expected_size else ""
            print(f"⬇  [{item_index}/{len(pending)}] [{media_type.upper()}] {file_name}{size_str}")

            if is_drive:
                success = await download_with_retry(
                    client, group.entity, message_id, None, expected_size,
                    show_progress=not is_parallel,
                    drive_service=drive_service, drive_folder_id=file_path_or_folder_id,
                    file_name=file_name,
                )
            else:
                success = await download_with_retry(
                    client, group.entity, message_id, file_path_or_folder_id, expected_size,
                    show_progress=not is_parallel,
                )

            async with counter_lock:
                if success:
                    downloaded += 1
                    if is_drive:
                        download_log[group_log_key]["downloaded"][str(message_id)] = {
                            "file": file_name,
                            "size": expected_size or 0,
                        }
                    else:
                        download_log[group_log_key]["downloaded"][str(message_id)] = {
                            "file": file_name,
                            "size": file_path_or_folder_id.stat().st_size,
                        }
                    download_log[group_log_key]["stats"]["completed"] = len(download_log[group_log_key]["downloaded"])
                    if is_parallel:
                        print(f"  ✅ {file_name} — concluído ({downloaded}/{len(pending)})")
                else:
                    error_count += 1
                    download_log[group_log_key]["failed"][str(message_id)] = {
                        "file": file_name,
                        "error": "falha permanente",
                    }
                    download_log[group_log_key]["stats"]["errors"] = len(download_log[group_log_key]["failed"])
                    print(f"  💀 Falha permanente após {MAX_RETRIES} tentativas: {file_name}")

                if (downloaded + error_count) % 5 == 0:
                    save_download_log(download_log)

    tasks = [
        download_one(i + 1, msg_id, mt, fn, fp_or_fid, es)
        for i, (msg_id, mt, fn, fp_or_fid, es) in enumerate(pending)
    ]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("Exceção não tratada em task de download: %s", r)
    finally:
        save_download_log(download_log)
    elapsed = time.time() - start_time
    elapsed_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))

    print(f"\n{'='*50}")
    print(f"✅ Baixados: {downloaded}")
    print(f"⏭  Já existiam (pulados): {skipped}")
    if error_count:
        print(f"❌ Erros (após {MAX_RETRIES} tentativas cada): {error_count}")
    print(f"⏱  Tempo total: {elapsed_str}")
    if is_drive:
        print(f"☁️  Destino: Google Drive")
    else:
        print(f"📂 Pasta: {download_dir}")


async def main():
    api_id, api_hash = load_credentials()

    client = TelegramClient(
        SESSION_NAME,
        int(api_id),
        api_hash,
        connection_retries=10,
        request_retries=10,
        retry_delay=5,
        auto_reconnect=True,
        flood_sleep_threshold=120,
        timeout=30,
    )
    try:
        await client.start()
    except errors.PhoneNumberInvalidError:
        print("\n❌ Número de telefone inválido. Verifique o formato (ex: +5511999999999) e tente novamente.")
        return
    except errors.ApiIdInvalidError:
        print("\n❌ API ID ou API Hash inválidos. Verifique suas credenciais no arquivo .env.")
        return

    print(f"\n{'='*50}")
    print("  TELEGRAM GROUP DOWNLOADER")
    print(f"{'='*50}")

    if not check_cryptg():
        print("  ⚠  cryptg não instalado — downloads podem ser lentos")
        print("     Instale com: pip install cryptg\n")

    me = await client.get_me()
    print(f"  Logado como: {me.first_name} (@{me.username or 'sem username'})")
    print(f"{'='*50}\n")

    while True:
        print("🔄 Carregando seus grupos/canais...\n")
        groups = await list_groups(client)

        if not groups:
            print("❌ Nenhum grupo ou canal encontrado.")
            break

        for i, g in enumerate(groups, 1):
            member_count = ""
            entity = g.entity
            if hasattr(entity, "participants_count") and entity.participants_count:
                member_count = f" ({entity.participants_count} membros)"
            tipo = "Canal" if isinstance(entity, Channel) and entity.broadcast else "Grupo"
            print(f"  {i:3d}. [{tipo}] {g.name}{member_count}")

        print(f"\n  0. Sair\n")

        try:
            choice = input("👉 Escolha o número do grupo: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo...")
            break

        if choice == "0":
            break

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(groups):
                print("❌ Número inválido.\n")
                continue
        except ValueError:
            print("❌ Digite um número válido.\n")
            continue

        selected = groups[idx]
        print(f"\n✅ Selecionado: {selected.name}\n")

        print("Que tipo de mídia deseja baixar?\n")
        for key, val in MEDIA_FILTERS.items():
            print(f"  {key}. {val['label']}")
        print()

        try:
            media_choice = input("👉 Escolha (1-4): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo...")
            break

        if media_choice not in MEDIA_FILTERS:
            print("❌ Opção inválida.\n")
            continue

        media_types = MEDIA_FILTERS[media_choice]["types"]

        print("\nQuantas mensagens verificar? (quanto maior, mais tempo leva)")
        print("  - Digite um número (ex: 100, 500, 1000)")
        print("  - Ou 'todas' para verificar todas\n")

        try:
            limit_input = input("👉 Limite: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo...")
            break

        limit = None if limit_input == "todas" else int(limit_input) if limit_input.isdigit() else 100

        if limit and not limit_input.isdigit():
            print(f"  (valor inválido, usando padrão: {limit})")

        # Opção Google Drive
        drive_service = None
        drive_root_folder_id = None

        print(f"\nDeseja enviar direto para o Google Drive? (sem usar disco local)")
        try:
            usar_drive = input("👉 Google Drive? (s/n) [n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo...")
            break

        if usar_drive == "s":
            from google_drive_upload import GoogleDriveService
            drive_service = GoogleDriveService()
            if not drive_service.authenticate():
                print("❌ Falha na autenticação com o Google Drive.\n")
                continue

            try:
                drive_folder_name = input("👉 Nome da pasta raiz no Drive [Telegram Downloads]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nSaindo...")
                break
            if not drive_folder_name:
                drive_folder_name = "Telegram Downloads"

            drive_root_folder_id = drive_service.get_or_create_folder(drive_folder_name)
            print(f"  ☁️  Pasta raiz no Drive: {drive_folder_name}\n")

        base_dir = None
        if drive_service is None:
            print(f"Onde deseja salvar os arquivos?")
            print(f"  - Digite o caminho completo da pasta (ex: /home/usuario/cursos)")
            print(f"  - Ou pressione ENTER para usar o padrão (./downloads)\n")

            try:
                dir_input = input("👉 Pasta de destino: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nSaindo...")
                break

            if dir_input:
                base_dir = Path(dir_input).expanduser().resolve()
                if not base_dir.exists():
                    try:
                        criar = input(f"  📁 A pasta '{base_dir}' não existe. Deseja criá-la? (s/n): ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\nSaindo...")
                        break
                    if criar != "s":
                        print("⏭  Download cancelado.\n")
                        continue
                print(f"  📂 Arquivos serão salvos em: {base_dir / sanitize_filename(selected.name)}\n")

        # Verificar se existe estrutura de curso
        course_structure = None
        structure_data = load_course_structure()
        if structure_data:
            num_sections = len(structure_data.get("sections", []))
            print(f"📁 Arquivo course_structure.json encontrado ({num_sections} seções).")
            print(f"   Os downloads serão organizados em subpastas por módulo.\n")
            try:
                usar_estrutura = input("👉 Usar organização por pastas? (s/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nSaindo...")
                break
            if usar_estrutura == "s":
                course_structure = structure_data
                print("  ✅ Organização por pastas ativada!\n")
            else:
                print("  ⏭  Downloads serão salvos em pasta única.\n")

        try:
            await download_media_from_group(
                client, selected, media_types, limit, base_dir, course_structure,
                drive_service, drive_root_folder_id,
            )
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error("Conexão perdida durante download: %s", e)
            print(f"\n🔌 Conexão perdida: {e}")
            print("   Tentando reconectar...")
            try:
                await client.connect()
                print("   ✅ Reconectado! Rode novamente para continuar de onde parou.\n")
            except Exception as re:
                logger.error("Falha ao reconectar: %s", re)
                print(f"   ❌ Falha ao reconectar: {re}")
                print("   Execute o script novamente para retomar.\n")
        except errors.FloodWaitError as e:
            wait_time = e.seconds + 10
            print(f"\n⏳ Flood wait do Telegram: aguardando {wait_time}s...")
            logger.warning("FloodWaitError no loop principal: aguardando %ds", wait_time)
            await asyncio.sleep(wait_time)
            print("   ✅ Tempo de espera concluído. Rode novamente para continuar.\n")

        print()
        try:
            cont = input("Deseja baixar de outro grupo? (s/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if cont != "s":
            break

    await client.disconnect()
    print("\n👋 Até mais!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Download interrompido. Execute novamente para continuar de onde parou.")
