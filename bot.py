import os
import logging
import asyncio
import sqlite3
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, InlineQueryHandler, Application, ContextTypes
from nullbr_api import NullbrAPI
from telegram.constants import ParseMode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# --- Database Setup ---
DB_FILE = "auth.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS whitelist
                 (chat_id TEXT PRIMARY KEY,
                  added_by TEXT,
                  add_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (app_id TEXT PRIMARY KEY,
                  api_key TEXT,
                  add_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Ensure ADMIN is always authorized
    if ADMIN_ID:
        c.execute("INSERT OR IGNORE INTO whitelist (chat_id, added_by) VALUES (?, ?)", (str(ADMIN_ID), "System"))
        
    # Seed default API key from .env if table is empty
    c.execute("SELECT COUNT(*) FROM api_keys")
    if c.fetchone()[0] == 0:
        env_app_id = os.getenv("X_APP_ID")
        env_api_key = os.getenv("X_API_KEY")
        if env_app_id and env_api_key:
            c.execute("INSERT INTO api_keys (app_id, api_key) VALUES (?, ?)", (env_app_id, env_api_key))
            
    conn.commit()
    conn.close()

def is_authorized(chat_id: str) -> bool:
    """Check if a user or group is authorized."""
    # To easily allow global toggle later, we can also add a 'global_open' config flag,
    # but for now we enforce whitelist strictly as requested.
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM whitelist WHERE chat_id = ? LIMIT 1", (str(chat_id),))
    result = c.fetchone()
    conn.close()
    return bool(result)

init_db()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

api_client = NullbrAPI()

# --- Common Helper Functions ---
def escape_md(text):
    """Escapes markdown special characters for standard Markdown."""
    if not text: return ""
    escape_chars = r'_*`['
    return "".join(f"\\{char}" if char in escape_chars else char for char in str(text))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 你好！我是你的私人影视资源助手（Nullbr Search）。\n"
        "可以使用 `/s <关键字>` 搜索影视，或 `/help` 查看帮助。"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Nullbr Bot 帮助文档*\n\n"
        "🔍 *基础搜索*\n"
        "`/s <关键字>` - 搜索影视\n"
        "`/sid <对应类型> <id>` - 按 TMDB ID 查询详情 (类型默认 movie)\n"
        "支持类型: `movie`, `tv`, `person`, `collection`.\n\n"
        "*(该程序仍在开发中，当前已支持查数据及请求115资源)*"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def check_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ 只有管理员可以使用此命令。")
        return
        
    # Read whitelist and API keys
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT chat_id, added_by, add_time FROM whitelist")
    whitelist_rows = c.fetchall()
    
    c.execute("SELECT app_id, add_time FROM api_keys")
    key_rows = c.fetchall()
    conn.close()
    
    auth_list_text = "\n".join([f"ID: `{r[0]}` (由 {r[1]} 添加于 {r[2][:10]})" for r in whitelist_rows])
    if not auth_list_text: auth_list_text = "空白"
    
    keys_list_text = "\n".join([f"AppID: `{r[0]}` (添加于 {r[1][:10]})" for r in key_rows])
    if not keys_list_text: keys_list_text = "无可用接口！请从.env或命令添加。"
    
    text = (
        "🛡️ *机器人管理中心*\n\n"
        f"👥 *当前白名单：*\n{auth_list_text}\n\n"
        f"🔑 *当前接口池 (轮询调度)：*\n{keys_list_text}\n\n"
        "---\n"
        "如需添加/删除白名单，请使用:\n"
        "`/auth add <TelegramID>`\n"
        "`/auth del <TelegramID>`\n\n"
        "如需添加/删除API配置，请使用:\n"
        "`/key add <AppID> <APIKey>`\n"
        "`/key del <AppID>`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def key_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
        
    if len(context.args) < 2 and not (len(context.args) == 2 and context.args[0] == "del"):
        await update.message.reply_text("⚠️ 格式错误。\n添加: `/key add <AppID> <APIKey>`\n删除: `/key del <AppID>`", parse_mode=ParseMode.MARKDOWN)
        return
        
    action = context.args[0]
    app_id = context.args[1]
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    if action == "add":
        if len(context.args) < 3:
            await update.message.reply_text("⚠️ 缺少 API Key。\n添加: `/key add <AppID> <APIKey>`", parse_mode=ParseMode.MARKDOWN)
            return
        api_key = context.args[2]
        c.execute("INSERT OR REPLACE INTO api_keys (app_id, api_key) VALUES (?, ?)", (app_id, api_key))
        await update.message.reply_text(f"✅ 已将 AppID `{app_id}` 添加入接口轮询池！", parse_mode=ParseMode.MARKDOWN)
        
    elif action == "del":
        c.execute("DELETE FROM api_keys WHERE app_id = ?", (app_id,))
        if c.rowcount > 0:
            await update.message.reply_text(f"🗑️ 已将 AppID `{app_id}` 从接口池移除。", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"⚠️ 接口池中未找到 AppID `{app_id}`。", parse_mode=ParseMode.MARKDOWN)
            
    conn.commit()
    conn.close()

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
        
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ 格式错误。\n添加: `/auth add 12345`\n删除: `/auth del 12345`", parse_mode=ParseMode.MARKDOWN)
        return
        
    action = context.args[0]
    target_id = context.args[1]
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    if action == "add":
        c.execute("INSERT OR IGNORE INTO whitelist (chat_id, added_by) VALUES (?, ?)", (str(target_id), str(update.effective_user.id)))
        await update.message.reply_text(f"✅ 已将 `{target_id}` 添加入授权白名单！\n如果这是一个群组，机器人现在可以在贴内回复请求了。", parse_mode=ParseMode.MARKDOWN)
    elif action == "del":
        if str(target_id) == str(ADMIN_ID):
            await update.message.reply_text("⚠️ 无法移除最高管理员！")
        else:
            c.execute("DELETE FROM whitelist WHERE chat_id = ?", (str(target_id),))
            await update.message.reply_text(f"🗑️ 已将 `{target_id}` 从白名单中移除。", parse_mode=ParseMode.MARKDOWN)
    conn.commit()
    conn.close()

# --- Command Handlers ---
async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /s 命令"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ 该群组或用户未被授权使用此机器人。")
        return

    if not context.args:
        await update.message.reply_text("❌ 请提供搜索关键字，例如: `/s 蜘蛛侠`", parse_mode=ParseMode.MARKDOWN)
        return
        
    query = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 正在搜索: `{escape_md(query)}`...", parse_mode=ParseMode.MARKDOWN)
    
    data = await api_client.search(query)
    if not data or not isinstance(data, dict):
        await msg.edit_text("❌ 搜索请求失败。")
        return
        
    results = data.get("items", [])
    if not results:
        await msg.edit_text("📭 未找到相关影视。")
        return
        
    # Show list with inline buttons
    keyboard = []
    for item in results[:10]: # Limit to 10 results
        title = item.get('name') or item.get('title') or '未知'
        tmdbid = item.get('tmdbid', '')
        date = item.get('release_date', '')
        year = date[:4] if date else "未知年份"
        media_type = item.get('media_type', 'movie')
        
        btn_text = f"{title} ({year})"
        # shorten type to save callback data limit
        callback_data = f"st_{media_type}_{tmdbid}" 
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await msg.edit_text(f"🔍 找到 {len(results)} 个结果，请选择：", reply_markup=reply_markup)

async def sid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /sid 命令"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ 未经授权。")
        return

    if len(context.args) == 0:
        await update.message.reply_text("❌ 请提供TMDB ID，例如: `/sid 299536` 或 `/sid tv 1399`", parse_mode=ParseMode.MARKDOWN)
        return
        
    media_type = "movie"
    tmdbid = context.args[0]
    if len(context.args) >= 2:
        media_type = context.args[0]
        tmdbid = context.args[1]
        
    if not tmdbid.isdigit():
        await update.message.reply_text("❌ TMDB ID 必须是数字。")
        return

    msg = await update.message.reply_text(f"🔍 正在获取详情: `{tmdbid}`...", parse_mode=ParseMode.MARKDOWN)
    # Re-use the handler logic
    await send_detail_message(msg, tmdbid, media_type)

async def inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调响应"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    # data format: st_movie_12345 (st = show_tmdb)
    if data.startswith("st_"):
        _, media_type, tmdbid = data.split("_", 2)
        await query.edit_message_text(f"🔄 正在加载数据 ID:{tmdbid}...")
        await send_detail_message(query.message, tmdbid, media_type)
        
    # data format: r115_movie_12345 (r115 = res_115)
    elif data.startswith("r115_"):
        _, media_type, tmdbid = data.split("_", 2)
        if query.message:
            await query.message.reply_text(f"🔄 正在获取 ID:{tmdbid} 的 115 资源...")
            await send_res_message(query.message, tmdbid, media_type, "115")
        else:
            # For inline query results, there is no message object
            await send_res_message_inline(update, context, tmdbid, media_type, "115")
        
    elif data.startswith("rmag_"):
        _, media_type, tmdbid = data.split("_", 2)
        if query.message:
            await query.message.reply_text(f"🔄 正在获取 ID:{tmdbid} 的磁力资源...")
            await send_res_message(query.message, tmdbid, media_type, "magnet")
        else:
            await send_res_message_inline(update, context, tmdbid, media_type, "magnet")

async def send_detail_message(msg_obj, tmdbid, media_type):
    """提取详情的公共函数"""
    data = None
    if media_type == 'movie':
        data = await api_client.get_movie_info(tmdbid)
    elif media_type == 'tv':
        data = await api_client.get_tv_info(tmdbid)
    elif media_type == 'person':
        data = await api_client.get_person_info(tmdbid)
    elif media_type == 'collection':
        data = await api_client.get_collection_info(tmdbid)
        
    if not data or not isinstance(data, dict):
        await msg_obj.edit_text("❌ 获取详情失败，条目可能不存在。")
        return
        
    title = escape_md(data.get('name') or data.get('title', '未知'))
    desc = escape_md(data.get('overview', '无简介信息')[:300] + ('...' if len(data.get('overview', '')) > 300 else ''))
    rating = data.get('vote') or data.get('vote_average', 0)
    poster = data.get('poster') or data.get('poster_path', '')
    if poster and not poster.startswith('http'):
        poster = f"https://image.tmdb.org/t/p/w500{poster}"
    
    text = (
        f"🎬 *{title}*\n"
        f"⭐ 评分：`{rating}`\n"
        f"🏷️ 类型：`{escape_md(media_type.capitalize())}`\n"
        f"🆔 TMDB ID：`{tmdbid}`\n\n"
        f"📝 简介：\n{desc}"
    )

    keyboard = [
        [
            InlineKeyboardButton("🔗 获取 115 网盘", callback_data=f"r115_{media_type}_{tmdbid}"),
            InlineKeyboardButton("🧲 获取磁力", callback_data=f"rmag_{media_type}_{tmdbid}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        # Instead of sending a new photo message, try to edit the current message text and add embedded poster link (Telegram markdown trick)
        if poster:
            # Markdown trick: Invisible link for preview [‎](image_url)
            text = f"[‎]({poster}){text}"
            
        await msg_obj.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        await msg_obj.edit_text(f"❌ 发送消息时出错，但数据已拉取。(ID: {tmdbid})")


async def send_res_message(msg_obj, tmdbid, media_type, res_type):
    """获取具体资源的公共函数"""
    data = None
    if media_type == 'movie':
        if res_type == '115':
            data = await api_client.get_movie_115(tmdbid)
        elif res_type == 'magnet':
            data = await api_client.get_movie_magnet(tmdbid)
    elif media_type == 'tv':
        if res_type == '115':
            data = await api_client.get_tv_115(tmdbid)
        # 剧集的magnet较复杂（涉及季、集），此处暂只实现115，如果有其他之后补充
            
    if not data or not isinstance(data, dict):
        await msg_obj.reply_text(f"❌ 获取该资源失败，或者你没有配额。")
        return
        
    # data lists usually under resource type key instead of 'list'
    res_list = data.get(res_type, [])
    if not res_list:
        await msg_obj.reply_text(f"📭 服务器中目前没有关于该资源的 {res_type} 链接。")
        return
        
    text_blocks = []
    for item in res_list[:10]: # Max 10 to fit in message limit
        file_name = escape_md(item.get('name') or item.get('title', '未命名文件'))
        size = escape_md(str(item.get('size', '未知大小')))
        link = item.get('url') or item.get('link') or item.get('share_link') or item.get('magnet', '')
        
        # Format based on user requirements: filename, properties, hyperlink
        res_str = f"大小: {size}"
        
        resolution = item.get('resolution')
        if resolution: res_str += f" 分辨率: {resolution}"
        
        source = item.get('source')
        if source: res_str += f" 来源: {source}"
        
        quality = item.get('quality')
        if quality:
            if isinstance(quality, list): quality = " / ".join(quality)
            res_str += f" 质量: {quality}"
            
        group = item.get('group') # Note: API may or may not return 'group'/'release_group' explicitly, adapt as needed
        if group: res_str += f" 发布组: {group}"
        
        if link and link.startswith('magnet:'):
            # Telegram doesn't support magnet links in markdown hrefs, so we make it a copy-able block
            text_blocks.append(f"📄 *{file_name}*\n{escape_md(res_str)}\n🧲 磁力链接 (点击复制):\n`{link}`\n\n")
        else:
            text_blocks.append(f"📄 *{file_name}*\n{escape_md(res_str)}\n🔗 [点击获取此资源]({link})\n\n")
        
    final_text = f"✅ *获取资源成功 ({len(res_list)}条)*\n\n" + "\n".join(text_blocks)
    
    # Due to telegram limits, chunk message if too long
    if len(final_text) > 4000:
        final_text = final_text[:4000] + "...\n(截断)"
        
    await msg_obj.reply_text(final_text, parse_mode=ParseMode.MARKDOWN)

async def send_res_message_inline(update: Update, context: ContextTypes.DEFAULT_TYPE, tmdbid, media_type, res_type):
    """用于处理全局行内查询发出的消息（没有原始的机器人上文 msg_obj，需要向用户单独发送或原路编辑）"""
    # 针对 Inline Mode, 由于无法直接回复用户的内联气泡消息，可以选择发送一个新的消息给用户如果是在私聊
    # 但 Inline Keyboard 触发的 CallbackQuery 包含 inline_message_id，可以直接编辑那条气泡消息
    
    query = update.callback_query
    data = None
    if media_type == 'movie':
        if res_type == '115':
            data = await api_client.get_movie_115(tmdbid)
        elif res_type == 'magnet':
            data = await api_client.get_movie_magnet(tmdbid)
    elif media_type == 'tv':
        if res_type == '115':
            data = await api_client.get_tv_115(tmdbid)
            
    if not data or not isinstance(data, dict):
        await context.bot.edit_message_text(f"❌ 获取该资源失败，或者你没有配额。", inline_message_id=query.inline_message_id)
        return
        
    res_list = data.get(res_type, [])
    if not res_list:
        await context.bot.edit_message_text(f"📭 服务器中目前没有关于该资源的 {res_type} 链接。", inline_message_id=query.inline_message_id)
        return
        
    text_blocks = []
    for item in res_list[:10]:
        file_name = escape_md(item.get('name') or item.get('title', '未命名文件'))
        size = escape_md(str(item.get('size', '未知大小')))
        link = item.get('url') or item.get('link') or item.get('share_link') or item.get('magnet', '')
        
        res_str = f"大小: {size}"
        resolution = item.get('resolution')
        if resolution: res_str += f" 分辨率: {resolution}"
        source = item.get('source')
        if source: res_str += f" 来源: {source}"
        quality = item.get('quality')
        if quality:
            if isinstance(quality, list): quality = " / ".join(quality)
            res_str += f" 质量: {quality}"
        group = item.get('group')
        if group: res_str += f" 发布组: {group}"
        
        if link and link.startswith('magnet:'):
            text_blocks.append(f"📄 *{file_name}*\n{escape_md(res_str)}\n🧲 磁力链接 (点击复制):\n`{link}`\n\n")
        else:
            text_blocks.append(f"📄 *{file_name}*\n{escape_md(res_str)}\n🔗 [点击获取此资源]({link})\n\n")
            
    final_text = f"✅ *获取资源成功 ({len(res_list)}条)*\n\n" + "\n".join(text_blocks)
    if len(final_text) > 4000:
        final_text = final_text[:4000] + "...\n(截断)"
        
    await context.bot.edit_message_text(
        final_text, 
        inline_message_id=query.inline_message_id, 
        parse_mode=ParseMode.MARKDOWN
    )

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 @botname <关键字> 形式的全局行内查询"""
    user_id = str(update.effective_user.id)
    if not is_authorized(user_id):
        return # Silently ignore unauthorized inline queries

    query_str = update.inline_query.query.strip()
    if not query_str:
        return
        
    data = await api_client.search(query_str)
    if not data or not isinstance(data, dict):
        return
        
    results = data.get("items", [])
    if not results:
        return
        
    inline_results = []
    # Maximum API results per inline response is 50, but we just take top 10 for speed
    for i, item in enumerate(results[:10]):
        title = escape_md(item.get('name') or item.get('title') or '未知')
        tmdbid = item.get('tmdbid', '')
        date = item.get('release_date', '')
        year = date[:4] if date else "未知年份"
        media_type = item.get('media_type', 'movie')
        overview = item.get('overview', '无简介信息')[:150]
        poster = item.get('poster') or item.get('poster_path', '')
        if poster and not poster.startswith('http'):
            poster = f"https://image.tmdb.org/t/p/w200{poster}"
            
        desc = escape_md(overview + ('...' if len(item.get('overview', '')) > 150 else ''))
        rating = item.get('vote') or item.get('vote_average', 0)
        
        text = (
            f"🎬 *{title}* ({escape_md(year)})\n"
            f"⭐ 评分：`{rating}`\n"
            f"🏷️ 类型：`{escape_md(media_type.capitalize())}`\n"
            f"🆔 TMDB ID：`{tmdbid}`\n\n"
            f"📝 简介：\n{desc}"
        )
        if poster:
            text = f"[‎]({poster}){text}"
            
        keyboard = [
            [
                InlineKeyboardButton("🔗 获取 115 网盘", callback_data=f"r115_{media_type}_{tmdbid}"),
                InlineKeyboardButton("🧲 获取磁力", callback_data=f"rmag_{media_type}_{tmdbid}")
            ]
        ]
        
        inline_results.append(
            InlineQueryResultArticle(
                id=str(tmdbid),
                title=f"{item.get('name') or item.get('title') or '未知'} ({year})",
                description=overview[:50],
                thumbnail_url=poster if poster else None,
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode=ParseMode.MARKDOWN
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        )
        
    await update.inline_query.answer(inline_results, cache_time=10)


async def post_init(application: Application):
    """自动给新运行机器人的账号设置左侧快捷菜单"""
    commands = [
        BotCommand("s", "搜索影视 例如：/s 蜘蛛侠"),
        BotCommand("sid", "ID搜索 例如：/sid tv 1234"),
        BotCommand("admin", "面板 (仅管理员可见) 管理白名单"),
        BotCommand("help", "查看 Nullbr Bot 帮助文档")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands menu has been synced.")

if __name__ == '__main__':
    if not BOT_TOKEN:
        logger.error("请在 .env 文件中设置 BOT_TOKEN！")
        exit(1)
        
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check_api", check_api))
    app.add_handler(CommandHandler("admin", check_api)) # alias
    app.add_handler(CommandHandler("auth", auth_cmd))
    app.add_handler(CommandHandler("key", key_cmd))
    app.add_handler(CommandHandler("s", search_cmd))
    app.add_handler(CommandHandler("sid", sid_cmd))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(inline_callback_handler))

    logger.info("Bot 已启动并开始轮询...")
    try:
        app.run_polling()
    except Exception as e:
        logger.error(e)
    finally:
        asyncio.run(api_client.close())
