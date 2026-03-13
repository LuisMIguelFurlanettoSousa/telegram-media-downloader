#!/usr/bin/env python3
"""
Telegram Group Downloader
Baixa vídeos e arquivos de grupos do Telegram via API (MTProto).
"""

import sys
import asyncio
import json
import logging
import time
from pathlib import Path

from telethon import TelegramClient, errors
from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

SESSION_NAME = "telegram_session"
CONFIG_FILE = Path(__file__).parent / "config.json"
LOG_FILE = Path(__file__).parent / "download_log.json"

MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300

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


def get_file_name(message) -> str | None:
    if not message.media:
        return None

    if isinstance(message.media, MessageMediaPhoto):
        return f"foto_{message.id}.jpg"

    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        if doc is None:
            return None

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                ext = "mp4"
                mime = getattr(doc, "mime_type", "")
                if "webm" in mime:
                    ext = "webm"
                elif "mkv" in mime:
                    ext = "mkv"
                return f"video_{message.id}.{ext}"

        mime = getattr(doc, "mime_type", "")
        ext = mime.split("/")[-1] if "/" in mime else "bin"
        return f"arquivo_{message.id}.{ext}"

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


def progress_callback(current, total):
    percent = (current / total) * 100
    bar_length = 30
    filled = int(bar_length * current // total)
    bar = "█" * filled + "░" * (bar_length - filled)
    sys.stdout.write(f"\r  [{bar}] {percent:.1f}% ({format_size(current)}/{format_size(total)})")
    sys.stdout.flush()


def load_download_log() -> dict:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_download_log(log: dict):
    try:
        LOG_FILE.write_text(json.dumps(log, indent=2, ensure_ascii=False))
    except OSError as e:
        logger.warning("Falha ao salvar log de download: %s", e)


def verify_file_integrity(file_path: Path, expected_size: int | None) -> bool:
    if not file_path.exists():
        return False
    if expected_size is None:
        return True
    actual_size = file_path.stat().st_size
    if actual_size != expected_size:
        logger.warning(
            "Tamanho incorreto: %s (esperado %d, obteve %d)",
            file_path.name, expected_size, actual_size,
        )
        return False
    return True


async def download_with_retry(client: TelegramClient, message, file_path: Path, expected_size: int | None) -> bool:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await client.download_media(
                message,
                file=str(file_path),
                progress_callback=progress_callback,
            )
            print()

            if not verify_file_integrity(file_path, expected_size):
                if file_path.exists():
                    file_path.unlink()
                raise IOError(f"Arquivo corrompido (tamanho não confere): {file_path.name}")

            return True

        except asyncio.CancelledError:
            if file_path.exists():
                file_path.unlink()
                print(f"\n  🗑  Arquivo incompleto removido: {file_path.name}")
            raise

        except errors.FloodWaitError as e:
            wait_time = e.seconds + 5
            print(f"\n  ⏳ Flood wait do Telegram: aguardando {wait_time}s antes de retentar...")
            logger.warning("FloodWaitError: aguardando %ds (tentativa %d/%d)", wait_time, attempt, MAX_RETRIES)
            if file_path.exists():
                file_path.unlink()
            await asyncio.sleep(wait_time)

        except (ConnectionError, TimeoutError, OSError) as e:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            print(f"\n  🔌 Erro de conexão: {e}")
            print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
            logger.warning("Erro de conexão: %s (tentativa %d/%d, retry em %ds)", e, attempt, MAX_RETRIES, delay)
            if file_path.exists():
                file_path.unlink()
            await asyncio.sleep(delay)

        except Exception as e:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            print(f"\n  ❌ Erro inesperado: {e}")
            print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
            logger.warning("Erro inesperado: %s (tentativa %d/%d)", e, attempt, MAX_RETRIES)
            if file_path.exists():
                file_path.unlink()
            await asyncio.sleep(delay)

    logger.error("Falha permanente após %d tentativas: %s", MAX_RETRIES, file_path.name)
    return False


async def list_groups(client: TelegramClient) -> list:
    groups = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            groups.append(dialog)
    return groups


async def get_group_media_stats(client: TelegramClient, group, media_types: list[str], limit: int | None) -> dict:
    total_size = 0
    counts = {"video": 0, "photo": 0, "document": 0}

    print(f"📊 Calculando tamanho do grupo '{group.name}'...", end="", flush=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async for message in client.iter_messages(group.entity, limit=limit, reverse=True):
                media_type = classify_media(message)
                if media_type is None or media_type not in media_types:
                    continue

                counts[media_type] += 1

                if isinstance(message.media, MessageMediaDocument) and message.media.document:
                    total_size += message.media.document.size or 0

            break
        except errors.FloodWaitError as e:
            wait_time = e.seconds + 5
            print(f"\n  ⏳ Flood wait: aguardando {wait_time}s...")
            await asyncio.sleep(wait_time)
            total_size = 0
            counts = {"video": 0, "photo": 0, "document": 0}
        except (ConnectionError, TimeoutError, OSError) as e:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            print(f"\n  🔌 Erro de conexão ao calcular stats: {e}")
            print(f"     Tentativa {attempt}/{MAX_RETRIES} — retentando em {delay}s...")
            await asyncio.sleep(delay)
            total_size = 0
            counts = {"video": 0, "photo": 0, "document": 0}

    print(" OK!\n")
    return {"total_size": total_size, "counts": counts}


async def download_media_from_group(client: TelegramClient, group, media_types: list[str], limit: int | None, base_dir: Path | None = None):
    group_name = group.name.replace("/", "_").replace("\\", "_").strip()
    if base_dir is None:
        base_dir = Path.cwd() / "downloads"
    download_dir = base_dir / group_name
    download_dir.mkdir(parents=True, exist_ok=True)

    stats = await get_group_media_stats(client, group, media_types, limit)

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
    print(f"  {'='*45}\n")

    try:
        confirma = input("👉 Deseja continuar com o download? (s/n): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        return

    if confirma != "s":
        print("⏭  Download cancelado.\n")
        return

    print(f"\n📂 Salvando em: {download_dir}")
    print(f"🔍 Baixando mídia de '{group.name}'...\n")

    downloaded = 0
    skipped = 0
    error_count = 0
    start_time = time.time()

    download_log = load_download_log()
    group_log_key = group_name
    if group_log_key not in download_log:
        download_log[group_log_key] = {"failed_files": [], "completed": 0, "errors": 0}

    async for message in client.iter_messages(group.entity, limit=limit, reverse=True):
        media_type = classify_media(message)
        if media_type is None or media_type not in media_types:
            continue

        file_name = get_file_name(message)
        if file_name is None:
            continue

        file_path = download_dir / file_name

        expected_size = None
        if isinstance(message.media, MessageMediaDocument) and message.media.document:
            expected_size = message.media.document.size

        if file_path.exists():
            if expected_size and file_path.stat().st_size != expected_size:
                print(f"  ⚠  Arquivo incompleto detectado, rebaixando: {file_name}")
                file_path.unlink()
            else:
                skipped += 1
                continue

        size_str = f" ({format_size(expected_size)})" if expected_size else ""
        current = downloaded + skipped + error_count + 1
        print(f"⬇  [{current}/{total_items}] [{media_type.upper()}] {file_name}{size_str}")

        success = await download_with_retry(client, message, file_path, expected_size)

        if success:
            downloaded += 1
            download_log[group_log_key]["completed"] = downloaded
        else:
            error_count += 1
            download_log[group_log_key]["errors"] = error_count
            if file_name not in download_log[group_log_key]["failed_files"]:
                download_log[group_log_key]["failed_files"].append(file_name)
            print(f"  💀 Falha permanente após {MAX_RETRIES} tentativas: {file_name}")

        if (downloaded + error_count) % 5 == 0:
            save_download_log(download_log)

    save_download_log(download_log)
    elapsed = time.time() - start_time
    elapsed_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))

    print(f"\n{'='*50}")
    print(f"✅ Baixados: {downloaded}")
    print(f"⏭  Já existiam (pulados): {skipped}")
    if error_count:
        print(f"❌ Erros (após {MAX_RETRIES} tentativas cada): {error_count}")
    print(f"⏱  Tempo total: {elapsed_str}")
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

        print(f"\nOnde deseja salvar os arquivos?")
        print(f"  - Digite o caminho completo da pasta (ex: /home/usuario/cursos)")
        print(f"  - Ou pressione ENTER para usar o padrão (./downloads)\n")

        try:
            dir_input = input("👉 Pasta de destino: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo...")
            break

        base_dir = None
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
            print(f"  📂 Arquivos serão salvos em: {base_dir / selected.name.replace('/', '_').replace(chr(92), '_').strip()}\n")

        try:
            await download_media_from_group(client, selected, media_types, limit, base_dir)
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
