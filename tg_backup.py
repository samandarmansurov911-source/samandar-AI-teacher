"""
Shared helper for memory backups kept as pinned documents in the owner's chat.

Several managers (Telegram channel, Instagram) each keep their own pinned JSON
document. The Bot API only exposes the most recently pinned message, so to
find an older one we temporarily unpin the newer ones and pin them back in
the original order.
"""

import asyncio
import logging

log = logging.getLogger("tg_backup")

_lock = asyncio.Lock()
MAX_PINS_SCANNED = 6


async def find_pinned_document(bot, chat_id: int, filename: str):
    """Return the pinned message holding `filename`, or None."""
    async with _lock:
        unpinned = []
        found = None
        try:
            for _ in range(MAX_PINS_SCANNED):
                chat = await bot.get_chat(chat_id)
                msg = chat.pinned_message
                if not msg:
                    break
                if msg.document and msg.document.file_name == filename:
                    found = msg
                    break
                await bot.unpin_chat_message(chat_id, msg.message_id)
                unpinned.append(msg.message_id)
        finally:
            # Oldest first, so the originally newest pin is newest again.
            for message_id in reversed(unpinned):
                try:
                    await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
                except Exception as e:
                    log.warning("Could not re-pin message %s: %s", message_id, e)
        return found
