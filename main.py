# Copyright (C) @TheSmartBisnu
# Channel: https://t.me/itsSmartDev

import os
import shutil
import psutil
import asyncio
from time import time

from pyleaves import Leaves
from pyrogram.enums import ParseMode
from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid, BadRequest
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from helpers.utils import (
    getChatMsgID,
    processMediaGroup,
    get_parsed_msg,
    fileSizeLimit,
    progressArgs,
    send_media,
    get_readable_file_size,
    get_readable_time,
)

from config import PyroConf
from logger import LOGGER

# Load LOG_CHANNEL_ID from config
LOG_CHANNEL_ID = int(PyroConf.LOG_CHANNEL_ID)

# Initialize the bot client
bot = Client(
    "media_bot",
    api_id=PyroConf.API_ID,
    api_hash=PyroConf.API_HASH,
    bot_token=PyroConf.BOT_TOKEN,
    workers=1000,
    parse_mode=ParseMode.MARKDOWN,
)

# Client for user session
user = Client("user_session", workers=1000, session_string=PyroConf.SESSION_STRING)

RUNNING_TASKS = set()

def track_task(coro):
    task = asyncio.create_task(coro)
    RUNNING_TASKS.add(task)
    def _remove(_):
        RUNNING_TASKS.discard(task)
    task.add_done_callback(_remove)
    return task

@bot.on_message(filters.command("start") & filters.private)
async def start(_, message: Message):
    welcome_text = (
        "👋 **Welcome to Media Downloader Bot!**\n\n"
        "I can grab photos, videos, audio, and documents from any Telegram post.\n"
        "Just send me a link (paste it directly or use `/dl <link>`),\n"
        "or reply to a message with `/dl`.\n\n"
        "ℹ️ Use `/help` to view all commands and examples.\n"
        "🔒 Make sure the user client is part of the chat.\n\n"
        "Ready? Send me a Telegram post link!"
    )

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Update Channel", url="https://t.me/itsSmartDev")]]
    )
    await message.reply(welcome_text, reply_markup=markup, disable_web_page_preview=True)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(_, message: Message):
    help_text = (
        "💡 **Media Downloader Bot Help**\n\n"
        "➤ **Download Media**\n"
        "   – Send `/dl <post_URL>` **or** just paste a Telegram post link.\n\n"
        "➤ **Batch Download**\n"
        "   – `/bdl start_link end_link` to grab a series of posts.\n"
        "**Example:** `/bdl https://t.me/mychannel/100 https://t.me/mychannel/120`\n\n"
        "➤ **If the bot hangs**\n"
        "   – `/killall` to cancel running downloads.\n\n"
        "➤ **Logs**\n"
        "   – `/logs` to download logs file.\n\n"
        "➤ **Stats**\n"
        "   – `/stats` to view bot status."
    )
    
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Update Channel", url="https://t.me/itsSmartDev")]]
    )
    await message.reply(help_text, reply_markup=markup, disable_web_page_preview=True)

async def handle_download(bot: Client, message: Message, post_url: str):
    if "?" in post_url:
        post_url = post_url.split("?", 1)[0]

    try:
        chat_id, message_id = getChatMsgID(post_url)
        chat_message = await user.get_messages(chat_id=chat_id, message_ids=message_id)

        LOGGER(__name__).info(f"Downloading from: {post_url}")

        if chat_message.document or chat_message.video or chat_message.audio:
            file_size = (
                chat_message.document.file_size
                if chat_message.document else
                chat_message.video.file_size
                if chat_message.video else
                chat_message.audio.file_size
            )
            if not await fileSizeLimit(file_size, message, "download", user.me.is_premium):
                return

        parsed_caption = await get_parsed_msg(chat_message.caption or "", chat_message.caption_entities)
        parsed_text = await get_parsed_msg(chat_message.text or "", chat_message.entities)

        if chat_message.media_group_id:
            if not await processMediaGroup(chat_message, bot, message):
                await message.reply("**Could not extract any valid media from the media group.**")
            return

        elif chat_message.media:
            start_time = time()
            progress_message = await message.reply("**📥 Downloading Progress...**")
            media_path = await chat_message.download(
                progress=Leaves.progress_for_pyrogram,
                progress_args=progressArgs("📥 Downloading Progress", progress_message, start_time)
            )
            LOGGER(__name__).info(f"Downloaded: {media_path}")

            media_type = (
                "photo" if chat_message.photo else
                "video" if chat_message.video else
                "audio" if chat_message.audio else
                "document"
            )

            await send_media(
                bot,
                message,
                media_path,
                media_type,
                parsed_caption,
                progress_message,
                start_time,
            )

            os.remove(media_path)
            await progress_message.delete()

        elif chat_message.text or chat_message.caption:
            await message.reply(parsed_text or parsed_caption)
        else:
            await message.reply("**No media or text found in the post URL.**")

    except (PeerIdInvalid, BadRequest, KeyError):
        await message.reply("**Make sure the user client is part of the chat.**")
    except Exception as e:
        await message.reply(f"**❌ {str(e)}**")
        LOGGER(__name__).error(e)

@bot.on_message(filters.command("dl") & filters.private)
async def download_media(bot: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("**Provide a post URL after the /dl command.**")
        return
    post_url = message.command[1]
    await track_task(handle_download(bot, message, post_url))

@bot.on_message(filters.command("bdl") & filters.private)
async def download_range(bot: Client, message: Message):
    args = message.text.split()
    if len(args) != 3 or not all(arg.startswith("https://t.me/") for arg in args[1:]):
        await message.reply("Usage: `/bdl start_link end_link`")
        return

    try:
        start_chat, start_id = getChatMsgID(args[1])
        end_chat, end_id = getChatMsgID(args[2])
    except Exception as e:
        return await message.reply(f"**❌ Error:\n{e}**")

    if start_chat != end_chat:
        return await message.reply("**❌ Both links must be from the same channel.**")
    if start_id > end_id:
        return await message.reply("**❌ Start ID cannot be greater than End ID.**")

    await user.get_chat(start_chat)
    prefix = args[1].rsplit("/", 1)[0]
    loading = await message.reply(f"📥 **Downloading posts {start_id}–{end_id}…**")

    downloaded = skipped = failed = 0
    for msg_id in range(start_id, end_id + 1):
        url = f"{prefix}/{msg_id}"
        try:
            chat_msg = await user.get_messages(start_chat, msg_id)
            if not chat_msg:
                skipped += 1
                continue

            if not (chat_msg.media_group_id or chat_msg.media or chat_msg.text or chat_msg.caption):
                skipped += 1
                continue

            await handle_download(bot, message, url)
            downloaded += 1

        except Exception as e:
            failed += 1
            LOGGER(__name__).error(f"{url}: {e}")
        await asyncio.sleep(3)

    await loading.delete()
    await message.reply(f"✅ Done!\n• Downloaded: `{downloaded}`\n• Skipped: `{skipped}`\n• Failed: `{failed}`")

@bot.on_message(filters.command("stats") & filters.private)
async def stats(_, message: Message):
    currentTime = get_readable_time(time() - PyroConf.BOT_START_TIME)
    total, used, free = shutil.disk_usage(".")
    total = get_readable_file_size(total)
    used = get_readable_file_size(used)
    free = get_readable_file_size(free)
    sent = get_readable_file_size(psutil.net_io_counters().bytes_sent)
    recv = get_readable_file_size(psutil.net_io_counters().bytes_recv)
    cpuUsage = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    process = psutil.Process(os.getpid())

    stats = (
        "**📊 Bot Status:**\n\n"
        f"**Uptime:** `{currentTime}`\n"
        f"**Disk:** `{used}/{total}` Free: `{free}`\n"
        f"**Memory:** `{round(process.memory_info()[0] / 1024**2)} MiB`\n"
        f"**Upload:** `{sent}` | **Download:** `{recv}`\n"
        f"**CPU:** `{cpuUsage}%` | **RAM:** `{memory}%` | **Disk:** `{disk}%`"
    )
    await message.reply(stats)

@bot.on_message(filters.command("logs") & filters.private)
async def logs(_, message: Message):
    if os.path.exists("logs.txt"):
        await message.reply_document(document="logs.txt", caption="**Logs**")
    else:
        await message.reply("**No logs file found.**")

@bot.on_message(filters.command("killall") & filters.private)
async def cancel_all_tasks(_, message: Message):
    cancelled = 0
    for task in list(RUNNING_TASKS):
        if not task.done():
            task.cancel()
            cancelled += 1
    await message.reply(f"**Cancelled {cancelled} running task(s).**")

# ✅ Log Channel Forwarder
@bot.on_message(filters.private & ~filters.command(["start", "help", "dl", "bdl", "stats", "logs", "killall"]))
async def log_everything(bot: Client, message: Message):
    user = message.from_user
    username = f"@{user.username}" if user and user.username else "Unknown User"
    caption = f"📩 Message from {username} (ID: {user.id if user else 'N/A'})"
    try:
        if message.text:
            await bot.send_message(LOG_CHANNEL_ID, f"{caption}\n\n{message.text}")
        elif message.media:
            sent = await message.copy(LOG_CHANNEL_ID)
            await bot.send_message(LOG_CHANNEL_ID, caption, reply_to_message_id=sent.id)
        else:
            await message.forward(LOG_CHANNEL_ID)
            await bot.send_message(LOG_CHANNEL_ID, caption)
    except Exception as e:
        LOGGER(__name__).error(f"Failed to log message: {e}")

# ✅ Run the bot
if __name__ == "__main__":
    try:
        LOGGER(__name__).info("Bot Started!")
        user.start()
        bot.run()
    except KeyboardInterrupt:
        pass
    except Exception as err:
        LOGGER(__name__).error(err)
    finally:
        LOGGER(__name__).info("Bot Stopped")
