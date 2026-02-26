import os
import logging
import asyncio
import sqlite3
import time
import secrets
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, InlineQueryHandler, Application, ContextTypes
from nullbr_api import NullbrAPI
from message_utils import escape_md, build_resource_message
from telegram.constants import ParseMode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Database Setup ---
DB_FILE = "auth.db"
AUTH_CACHE_TTL = int(os.getenv("AUTH_CACHE_TTL", "60"))
METRICS_LOG_INTERVAL = int(os.getenv("METRICS_LOG_INTERVAL", "60"))
SEARCH_SESSION_TTL = int(os.getenv("SEARCH_SESSION_TTL", "300"))
SEARCH_SESSION_MAX = int(os.getenv("SEARCH_SESSION_MAX", "200"))
_AUTH_CACHE = set()
_AUTH_CACHE_AT = 0.0
_SEARCH_SESSIONS = {}


def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def refresh_auth_cache(force=False):
    global _AUTH_CACHE, _AUTH_CACHE_AT
    now = time.time()
    if not force and (now - _AUTH_CACHE_AT) <= AUTH_CACHE_TTL and _AUTH_CACHE:
        return

    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT chat_id FROM whitelist")
            _AUTH_CACHE = {str(row[0]) for row in c.fetchall()}
            _AUTH_CACHE_AT = now
    except Exception as e:
        logger.error("刷新白名单缓存失败: %s", e)

def init_db():
    with get_db_connection() as conn:
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
            env_app_id = os.getenv("X_APP_ID") or os.getenv("NULLBR_APP_ID")
            env_api_key = os.getenv("X_API_KEY") or os.getenv("NULLBR_API_KEY")
            if env_app_id and env_api_key:
                c.execute("INSERT INTO api_keys (app_id, api_key) VALUES (?, ?)", (env_app_id, env_api_key))

    refresh_auth_cache(force=True)

def is_authorized(chat_id: str) -> bool:
    """Check if a user or group is authorized."""
    refresh_auth_cache(force=False)
    return str(chat_id) in _AUTH_CACHE

init_db()

api_client = NullbrAPI()

# --- Common Helper Functions ---


def cleanup_search_sessions():
    now = time.time()
    expired = [k for k, v in _SEARCH_SESSIONS.items() if now - v.get("ts", 0) > SEARCH_SESSION_TTL]
    for k in expired:
        _SEARCH_SESSIONS.pop(k, None)

    if len(_SEARCH_SESSIONS) > SEARCH_SESSION_MAX:
        ordered = sorted(_SEARCH_SESSIONS.items(), key=lambda x: x[1].get("ts", 0))
        for key, _ in ordered[: len(_SEARCH_SESSIONS) - SEARCH_SESSION_MAX]:
            _SEARCH_SESSIONS.pop(key, None)


def create_search_session(query):
    cleanup_search_sessions()
    token = secrets.token_hex(4)
    _SEARCH_SESSIONS[token] = {
        "query": query,
        "filter": "all",
        "ts": time.time(),
    }
    return token


def get_search_session(token):
    session = _SEARCH_SESSIONS.get(token)
    if session:
        session["ts"] = time.time()
    return session


def filter_results(items, media_filter):
    if media_filter == "all":
        return items
    return [x for x in items if str(x.get("media_type", "")).lower() == media_filter]


def build_search_keyboard(items, token, page, media_filter):
    keyboard = []
    for item in items[:8]:
        title = item.get('name') or item.get('title') or '未知'
        tmdbid = item.get('tmdbid', '')
        date = item.get('release_date', '')
        year = date[:4] if date else "未知年份"
        media_type = item.get('media_type', 'movie')
        keyboard.append([InlineKeyboardButton(f"{title} ({year})", callback_data=f"st_{media_type}_{tmdbid}")])

    keyboard.append(
        [
            InlineKeyboardButton("⬅️ 上一页", callback_data=f"sp_{token}_{max(1, page - 1)}"),
            InlineKeyboardButton(f"第 {page} 页", callback_data="noop"),
            InlineKeyboardButton("下一页 ➡️", callback_data=f"sp_{token}_{page + 1}"),
        ]
    )

    keyboard.append(
        [
            InlineKeyboardButton("全部", callback_data=f"sf_{token}_all_{page}"),
            InlineKeyboardButton("电影", callback_data=f"sf_{token}_movie_{page}"),
            InlineKeyboardButton("剧集", callback_data=f"sf_{token}_tv_{page}"),
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton("人物", callback_data=f"sf_{token}_person_{page}"),
            InlineKeyboardButton("合集", callback_data=f"sf_{token}_collection_{page}"),
            InlineKeyboardButton(f"当前: {media_filter}", callback_data="noop"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def build_detail_keyboard(media_type, tmdbid):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📦 资源菜单", callback_data=f"rs_{media_type}_{tmdbid}")]]
    )


def build_resource_menu_keyboard(media_type, tmdbid):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔗 获取 115 网盘", callback_data=f"r115_{media_type}_{tmdbid}"),
                InlineKeyboardButton("🧲 获取磁力", callback_data=f"rmag_{media_type}_{tmdbid}"),
            ],
            [InlineKeyboardButton("↩️ 返回详情", callback_data=f"rd_{media_type}_{tmdbid}")],
        ]
    )


def build_admin_panel_text(whitelist_rows, key_rows):
    auth_list_text = "\n".join([f"ID: `{r[0]}` (由 {r[1]} 添加于 {r[2][:10]})" for r in whitelist_rows])
    if not auth_list_text:
        auth_list_text = "空白"

    keys_list_text = "\n".join([f"AppID: `{r[0]}` (添加于 {r[1][:10]})" for r in key_rows])
    if not keys_list_text:
        keys_list_text = "无可用接口！请从.env或命令添加。"

    return (
        "🛡️ *机器人管理中心*\n\n"
        f"👥 *当前白名单（{len(whitelist_rows)}）：*\n{auth_list_text}\n\n"
        f"🔑 *当前接口池（{len(key_rows)}）*:\n{keys_list_text}\n\n"
        "---\n"
        "如需添加/删除白名单，请使用:\n"
        "`/auth add <TelegramID>`\n"
        "`/auth del <TelegramID>`\n\n"
        "如需添加/删除API配置，请使用:\n"
        "`/key add <AppID> <APIKey>`\n"
        "`/key del <AppID>`"
    )


def build_admin_panel_markup():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 刷新面板", callback_data="admin_refresh")],
            [
                InlineKeyboardButton("📈 运行指标", callback_data="admin_metrics"),
                InlineKeyboardButton("📊 账号配额", callback_data="admin_quota"),
            ],
        ]
    )


async def metrics_reporter(application: Application):
    while True:
        await asyncio.sleep(max(10, METRICS_LOG_INTERVAL))
        metrics = api_client.get_metrics_snapshot(reset=True)
        logger.info(
            "metrics interval=%ss total=%s meta=%s res=%s user=%s hit=%s miss=%s avg_ms=%s http429=%s http_err=%s req_err=%s cache=%s",
            METRICS_LOG_INTERVAL,
            metrics["requests_total"],
            metrics["requests_meta"],
            metrics["requests_res"],
            metrics["requests_user"],
            metrics["meta_cache_hit"],
            metrics["meta_cache_miss"],
            metrics["latency_ms_avg"],
            metrics["http_429"],
            metrics["http_errors"],
            metrics["request_errors"],
            metrics["meta_cache_size"],
        )


def format_metrics_text(metrics):
    return (
        "📈 *运行指标（实时快照）*\n\n"
        f"总请求: `{metrics['requests_total']}`\n"
        f"META/RES/USER: `{metrics['requests_meta']}` / `{metrics['requests_res']}` / `{metrics['requests_user']}`\n"
        f"META缓存 命中/未命中: `{metrics['meta_cache_hit']}` / `{metrics['meta_cache_miss']}`\n"
        f"HTTP 429: `{metrics['http_429']}`\n"
        f"HTTP错误: `{metrics['http_errors']}`\n"
        f"请求异常: `{metrics['request_errors']}`\n"
        f"平均延迟(ms): `{metrics['latency_ms_avg']}`\n"
        f"META缓存大小: `{metrics['meta_cache_size']}`"
    )


def load_admin_rows():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT chat_id, added_by, add_time FROM whitelist")
        whitelist_rows = c.fetchall()
        c.execute("SELECT app_id, add_time FROM api_keys")
        key_rows = c.fetchall()
    return whitelist_rows, key_rows


async def render_search_page(msg_obj, token, page):
    session = get_search_session(token)
    if not session:
        await msg_obj.edit_text("⚠️ 搜索会话已过期，请重新使用 `/s 关键字`。", parse_mode=ParseMode.MARKDOWN)
        return

    page = max(1, int(page))
    query = session["query"]
    media_filter = session.get("filter", "all")
    data = await api_client.search(query, page=page)
    if not data or not isinstance(data, dict):
        await msg_obj.edit_text("❌ 搜索请求失败。")
        return

    results = data.get("items", [])
    filtered = filter_results(results, media_filter)
    if not filtered:
        await msg_obj.edit_text(
            f"📭 第 {page} 页暂无 `{media_filter}` 结果。",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_search_keyboard([], token, page, media_filter),
        )
        return

    reply_markup = build_search_keyboard(filtered, token, page, media_filter)
    await msg_obj.edit_text(
        f"🔍 `{escape_md(query)}` 的搜索结果（筛选: `{media_filter}`）",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )

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
        "`/quota` - 查询当前账号配额\n"
        "`/tvmag <tmdbid> <季号> [集号]` - 获取剧集磁力（季包或单集）\n"
        "支持类型: `movie`, `tv`, `person`, `collection`.\n\n"
        "*(当前已支持影视查询、115/磁力资源、配额查询及 TV 分季分集磁力)*"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def check_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ 只有管理员可以使用此命令。")
        return
        
    whitelist_rows, key_rows = load_admin_rows()
    text = build_admin_panel_text(whitelist_rows, key_rows)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=build_admin_panel_markup())

async def key_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    args = context.args or []
        
    if len(args) < 2 and not (len(args) == 2 and args[0] == "del"):
        await update.message.reply_text("⚠️ 格式错误。\n添加: `/key add <AppID> <APIKey>`\n删除: `/key del <AppID>`", parse_mode=ParseMode.MARKDOWN)
        return
        
    action = args[0]
    app_id = args[1]
    
    with get_db_connection() as conn:
        c = conn.cursor()
    
        if action == "add":
            if len(args) < 3:
                await update.message.reply_text("⚠️ 缺少 API Key。\n添加: `/key add <AppID> <APIKey>`", parse_mode=ParseMode.MARKDOWN)
                return
            api_key = args[2]
            c.execute("INSERT OR REPLACE INTO api_keys (app_id, api_key) VALUES (?, ?)", (app_id, api_key))
            await update.message.reply_text(f"✅ 已将 AppID `{app_id}` 添加入接口轮询池！", parse_mode=ParseMode.MARKDOWN)

        elif action == "del":
            c.execute("DELETE FROM api_keys WHERE app_id = ?", (app_id,))
            if c.rowcount > 0:
                await update.message.reply_text(f"🗑️ 已将 AppID `{app_id}` 从接口池移除。", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"⚠️ 接口池中未找到 AppID `{app_id}`。", parse_mode=ParseMode.MARKDOWN)

    api_client.invalidate_credentials_cache()

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    args = context.args or []
        
    if len(args) < 2:
        await update.message.reply_text("⚠️ 格式错误。\n添加: `/auth add 12345`\n删除: `/auth del 12345`", parse_mode=ParseMode.MARKDOWN)
        return
        
    action = args[0]
    target_id = args[1]
    
    with get_db_connection() as conn:
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

    refresh_auth_cache(force=True)


async def quota_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ 未经授权。")
        return

    msg = await update.message.reply_text("📊 正在查询当前账号配额...")
    data = await api_client.get_user_info()
    if not data or not isinstance(data, dict):
        await msg.edit_text("❌ 查询失败，请稍后重试。")
        return

    plan = data.get("plan") or data.get("subscription") or "未知"
    total = data.get("limit") or data.get("total") or data.get("quota_total") or "未知"
    remain = data.get("remaining") or data.get("left") or data.get("quota_left") or "未知"
    await msg.edit_text(
        f"📊 *账号配额信息*\n\n"
        f"套餐: `{escape_md(plan)}`\n"
        f"总配额: `{escape_md(total)}`\n"
        f"剩余: `{escape_md(remain)}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def tvmag_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ 未经授权。")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "❌ 用法:\n`/tvmag <tmdbid> <季号> [集号]`\n例如: `/tvmag 1399 1` 或 `/tvmag 1399 1 2`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    tmdbid, season_num = args[0], args[1]
    episode_num = args[2] if len(args) >= 3 else None
    if not tmdbid.isdigit() or not season_num.isdigit() or (episode_num and not episode_num.isdigit()):
        await update.message.reply_text("❌ tmdbid/季号/集号必须是数字。")
        return

    msg = await update.message.reply_text("🔄 正在获取剧集磁力资源...")
    if episode_num:
        data = await api_client.get_tv_episode_magnet(tmdbid, season_num, episode_num)
        title_hint = f"S{int(season_num):02d}E{int(episode_num):02d}"
    else:
        data = await api_client.get_tv_season_magnet(tmdbid, season_num)
        title_hint = f"Season {int(season_num):02d}"

    if not data or not isinstance(data, dict):
        await msg.edit_text("❌ 获取剧集磁力失败，可能无资源或配额不足。")
        return

    res_list = data.get("magnet", [])
    if not res_list:
        await msg.edit_text("📭 暂无可用磁力资源。")
        return

    text_blocks = []
    for item in res_list[:10]:
        file_name = escape_md(item.get('name') or item.get('title', '未命名文件'))
        size = escape_md(str(item.get('size', '未知大小')))
        link = item.get('magnet') or item.get('url') or item.get('link') or ''
        text_blocks.append(f"📄 *{file_name}*\n大小: {size}\n`{link}`\n")

    final_text = f"✅ *{escape_md(title_hint)} 磁力资源 ({len(res_list)}条)*\n\n" + "\n".join(text_blocks)
    if len(final_text) > 4000:
        final_text = final_text[:4000] + "...\n(截断)"
    await msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN)


async def metrics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ 只有管理员可以使用此命令。")
        return

    metrics = api_client.get_metrics_snapshot(reset=False)
    text = format_metrics_text(metrics)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# --- Command Handlers ---
async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /s 命令"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ 该群组或用户未被授权使用此机器人。")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text("❌ 请提供搜索关键字，例如: `/s 蜘蛛侠`", parse_mode=ParseMode.MARKDOWN)
        return
        
    query = " ".join(args)
    msg = await update.message.reply_text(f"🔍 正在搜索: `{escape_md(query)}`...", parse_mode=ParseMode.MARKDOWN)
    
    token = create_search_session(query)
    await render_search_page(msg, token, 1)

async def sid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /sid 命令"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ 未经授权。")
        return

    args = context.args or []
    if len(args) == 0:
        await update.message.reply_text("❌ 请提供TMDB ID，例如: `/sid 299536` 或 `/sid tv 1399`", parse_mode=ParseMode.MARKDOWN)
        return
        
    media_type = "movie"
    tmdbid = args[0]
    if len(args) >= 2:
        media_type = args[0]
        tmdbid = args[1]
        
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
    if data == "noop":
        return

    if data.startswith("admin_"):
        if str(update.effective_user.id) != str(ADMIN_ID):
            return
        if data == "admin_refresh":
            whitelist_rows, key_rows = load_admin_rows()
            text = build_admin_panel_text(whitelist_rows, key_rows)
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=build_admin_panel_markup())
            return
        if data == "admin_metrics":
            metrics = api_client.get_metrics_snapshot(reset=False)
            await query.edit_message_text(format_metrics_text(metrics), parse_mode=ParseMode.MARKDOWN)
            return
        if data == "admin_quota":
            res = await api_client.get_user_info()
            if not res or not isinstance(res, dict):
                await query.edit_message_text("❌ 查询失败，请稍后重试。")
                return
            plan = res.get("plan") or res.get("subscription") or "未知"
            total = res.get("limit") or res.get("total") or res.get("quota_total") or "未知"
            remain = res.get("remaining") or res.get("left") or res.get("quota_left") or "未知"
            text = (
                f"📊 *账号配额信息*\n\n"
                f"套餐: `{escape_md(plan)}`\n"
                f"总配额: `{escape_md(total)}`\n"
                f"剩余: `{escape_md(remain)}`"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
            return

    if data.startswith("sp_"):
        _, token, page = data.split("_", 2)
        await render_search_page(query.message, token, int(page))
        return

    if data.startswith("sf_"):
        _, token, media_filter, page = data.split("_", 3)
        session = get_search_session(token)
        if not session:
            await query.edit_message_text("⚠️ 搜索会话已过期，请重新使用 `/s 关键字`。", parse_mode=ParseMode.MARKDOWN)
            return
        session["filter"] = media_filter
        await render_search_page(query.message, token, int(page))
        return

    # data format: st_movie_12345 (st = show_tmdb)
    if data.startswith("st_"):
        _, media_type, tmdbid = data.split("_", 2)
        await query.edit_message_text(f"🔄 正在加载数据 ID:{tmdbid}...")
        await send_detail_message(query.message, tmdbid, media_type)
        return

    if data.startswith("rd_"):
        _, media_type, tmdbid = data.split("_", 2)
        await query.edit_message_text(f"🔄 正在加载详情 ID:{tmdbid}...")
        await send_detail_message(query.message, tmdbid, media_type)
        return

    if data.startswith("rs_"):
        _, media_type, tmdbid = data.split("_", 2)
        await query.edit_message_reply_markup(reply_markup=build_resource_menu_keyboard(media_type, tmdbid))
        return
        
    # data format: r115_movie_12345 (r115 = res_115)
    elif data.startswith("r115_"):
        _, media_type, tmdbid = data.split("_", 2)
        if query.message:
            await query.message.reply_text(f"🔄 正在获取 ID:{tmdbid} 的 115 资源...")
            await send_res_message(query.message, tmdbid, media_type, "115")
        else:
            # For inline query results, there is no message object
            await send_res_message_inline(update, context, tmdbid, media_type, "115")
        return
        
    elif data.startswith("rmag_"):
        _, media_type, tmdbid = data.split("_", 2)
        if query.message:
            await query.message.reply_text(f"🔄 正在获取 ID:{tmdbid} 的磁力资源...")
            await send_res_message(query.message, tmdbid, media_type, "magnet")
        else:
            await send_res_message_inline(update, context, tmdbid, media_type, "magnet")
        return

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

    reply_markup = build_detail_keyboard(media_type, tmdbid)

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
        elif res_type == 'magnet':
            await msg_obj.reply_text(
                f"ℹ️ 剧集磁力需要指定季/集。\n请使用命令: `/tvmag {tmdbid} <季号> [集号]`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
            
    if not data or not isinstance(data, dict):
        await msg_obj.reply_text(f"❌ 获取该资源失败，或者你没有配额。")
        return
        
    # data lists usually under resource type key instead of 'list'
    res_list = data.get(res_type, [])
    if not res_list:
        await msg_obj.reply_text(f"📭 服务器中目前没有关于该资源的 {res_type} 链接。")
        return
        
    final_text = build_resource_message("获取资源成功", res_list)
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
        elif res_type == 'magnet':
            await context.bot.edit_message_text(
                f"ℹ️ 剧集磁力需要指定季/集。\n请私聊机器人使用: /tvmag {tmdbid} <季号> [集号]",
                inline_message_id=query.inline_message_id,
            )
            return
            
    if not data or not isinstance(data, dict):
        await context.bot.edit_message_text(f"❌ 获取该资源失败，或者你没有配额。", inline_message_id=query.inline_message_id)
        return
        
    res_list = data.get(res_type, [])
    if not res_list:
        await context.bot.edit_message_text(f"📭 服务器中目前没有关于该资源的 {res_type} 链接。", inline_message_id=query.inline_message_id)
        return
        
    final_text = build_resource_message("获取资源成功", res_list)
        
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
            
        keyboard = [[InlineKeyboardButton("📦 资源菜单", callback_data=f"rs_{media_type}_{tmdbid}")]]
        
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
        
    inline_cache_time = int(os.getenv("INLINE_CACHE_TIME", "30"))
    await update.inline_query.answer(inline_results, cache_time=inline_cache_time)


async def post_init(application: Application):
    """自动给新运行机器人的账号设置左侧快捷菜单"""
    commands = [
        BotCommand("s", "搜索影视 例如：/s 蜘蛛侠"),
        BotCommand("sid", "ID搜索 例如：/sid tv 1234"),
        BotCommand("tvmag", "剧集磁力 /tvmag 1399 1 [2]"),
        BotCommand("quota", "查询当前账号配额"),
        BotCommand("metrics", "查看运行指标(管理员)"),
        BotCommand("admin", "面板 (仅管理员可见) 管理白名单"),
        BotCommand("help", "查看 Nullbr Bot 帮助文档")
    ]
    await application.bot.set_my_commands(commands)
    task = asyncio.create_task(metrics_reporter(application))
    application.bot_data["metrics_reporter_task"] = task
    logger.info("Bot commands menu has been synced.")


async def post_shutdown(application: Application):
    task = application.bot_data.get("metrics_reporter_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

if __name__ == '__main__':
    if not BOT_TOKEN:
        logger.error("请在 .env 文件中设置 BOT_TOKEN！")
        exit(1)
        
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check_api", check_api))
    app.add_handler(CommandHandler("admin", check_api)) # alias
    app.add_handler(CommandHandler("auth", auth_cmd))
    app.add_handler(CommandHandler("key", key_cmd))
    app.add_handler(CommandHandler("s", search_cmd))
    app.add_handler(CommandHandler("sid", sid_cmd))
    app.add_handler(CommandHandler("quota", quota_cmd))
    app.add_handler(CommandHandler("tvmag", tvmag_cmd))
    app.add_handler(CommandHandler("metrics", metrics_cmd))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(inline_callback_handler))

    logger.info("Bot 已启动并开始轮询...")
    try:
        app.run_polling(poll_interval=1.0, timeout=20)
    except Exception as e:
        logger.error(e)
    finally:
        asyncio.run(api_client.close())
