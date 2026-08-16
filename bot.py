"""
بوت تليجرام لإدارة كلان Free Fire
- تتبع نقاط الـ Glory (بنظام تقديم + اعتماد من الأدمن)
- ليدر بورد تلقائي
- تذكير بالتبرع اليومي/الأسبوعي
- إدارة طلبات الانضمام للجروب
- إحصائيات ونشاط الأعضاء

طريقة التشغيل: python bot.py
(البوت شغال بنظام polling، مش محتاج سيرفر بعنوان عام أو webhook)
"""

import os
import sqlite3
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ChatJoinRequestHandler,
    CallbackQueryHandler,
)

# ---------------------------------------------------------------------------
# الإعدادات (تتاخد من متغيرات البيئة)
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# أرقام الـ Telegram ID بتاعت الأدمنز، مفصولة بفاصلة. مثال: "111111,222222"
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
}
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Africa/Cairo"))
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID")  # الجروب اللي هيتبعتله التذكير
DAILY_REMINDER_HOUR = int(os.environ.get("DAILY_REMINDER_HOUR", "20"))  # الساعة 8 مساءً افتراضيًا
WEEKLY_REMINDER_DAY = int(os.environ.get("WEEKLY_REMINDER_DAY", "4"))  # 0=الاثنين .. 4=الجمعة

DB_PATH = os.path.join(os.path.dirname(__file__), "clan.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# قاعدة البيانات
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            ff_id TEXT,
            ff_name TEXT,
            glory_points INTEGER DEFAULT 0,
            joined_at TEXT,
            last_active TEXT
        );

        CREATE TABLE IF NOT EXISTS glory_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            points INTEGER,
            status TEXT DEFAULT 'pending', -- pending / approved / rejected
            submitted_at TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            period TEXT, -- مثال: 2026-08-16 لليومي أو 2026-W33 للأسبوعي
            kind TEXT,   -- daily / weekly
            confirmed_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def touch_member(user_id: int, username: str | None):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(TIMEZONE).isoformat()
    cur.execute(
        """
        INSERT INTO members (user_id, username, joined_at, last_active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, last_active=excluded.last_active
        """,
        (user_id, username, now, now),
    )
    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------------------------------------------------------------------------
# أوامر عامة للأعضاء
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    touch_member(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text(
        "أهلاً بيك في بوت الكلان! 🎮\n\n"
        "الأوامر المتاحة:\n"
        "/register <FF_ID> <الاسم> - تسجيل بياناتك في فري فاير\n"
        "/submit_glory <النقاط> - إرسال نقاط الجلوري بتاعتك للاعتماد\n"
        "/mystats - إحصائياتك\n"
        "/leaderboard - ترتيب أعضاء الكلان\n"
        "/donate - تأكيد إنك تبرعت النهاردة\n"
        "/donate_status - مين تبرع ومين لأ\n"
    )


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if len(context.args) < 2:
        await update.message.reply_text(
            "استخدم الأمر كده: /register <ID بتاع فري فاير> <اسمك في اللعبة>\n"
            "مثال: /register 123456789 ProGamer"
        )
        return
    ff_id = context.args[0]
    ff_name = " ".join(context.args[1:])
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(TIMEZONE).isoformat()
    cur.execute(
        """
        INSERT INTO members (user_id, username, ff_id, ff_name, joined_at, last_active)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username, ff_id=excluded.ff_id,
            ff_name=excluded.ff_name, last_active=excluded.last_active
        """,
        (user.id, user.username, ff_id, ff_name, now, now),
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(f"تم تسجيلك ✅\nID: {ff_id}\nالاسم: {ff_name}")


async def submit_glory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    touch_member(user.id, user.username)
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("استخدم: /submit_glory <عدد النقاط>\nمثال: /submit_glory 1500")
        return
    points = int(context.args[0])
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(TIMEZONE).isoformat()
    cur.execute(
        "INSERT INTO glory_requests (user_id, points, submitted_at) VALUES (?, ?, ?)",
        (user.id, points, now),
    )
    request_id = cur.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"تم إرسال طلبك (رقم #{request_id}) بـ {points} نقطة جلوري، في انتظار اعتماد الأدمن ⏳"
    )

    # إشعار الأدمنز
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ اعتماد", callback_data=f"glory_approve_{request_id}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"glory_reject_{request_id}"),
            ]
        ]
    )
    name = user.username or user.full_name
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"طلب جلوري جديد #{request_id}\nمن: {name} (ID: {user.id})\nالنقاط: {points}",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning("مقدرش أبعت للأدمن %s: %s", admin_id, e)


async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM members WHERE user_id=?", (user.id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("لسه معملتش /register. سجل بياناتك الأول.")
        return

    cur.execute(
        "SELECT COUNT(*) c FROM glory_requests WHERE user_id=? AND status='pending'",
        (user.id,),
    )
    pending = cur.fetchone()["c"]
    cur.execute(
        "SELECT COUNT(*) c FROM donations WHERE user_id=? AND kind='daily'", (user.id,)
    )
    daily_donations = cur.fetchone()["c"]
    conn.close()

    await update.message.reply_text(
        f"📊 إحصائياتك:\n"
        f"الاسم في اللعبة: {row['ff_name'] or '—'}\n"
        f"ID: {row['ff_id'] or '—'}\n"
        f"نقاط الجلوري المعتمدة: {row['glory_points']}\n"
        f"طلبات في انتظار الاعتماد: {pending}\n"
        f"عدد مرات التبرع اليومي: {daily_donations}\n"
        f"آخر نشاط: {row['last_active']}"
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT ff_name, username, glory_points FROM members "
        "ORDER BY glory_points DESC LIMIT 15"
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("مفيش نقاط متسجلة لسه.")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 ترتيب الكلان (Glory):\n"]
    for i, r in enumerate(rows):
        prefix = medals[i] if i < 3 else f"{i+1}."
        name = r["ff_name"] or r["username"] or "بدون اسم"
        lines.append(f"{prefix} {name} — {r['glory_points']} نقطة")
    await update.message.reply_text("\n".join(lines))


async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    touch_member(user.id, user.username)
    today = datetime.now(TIMEZONE).date().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM donations WHERE user_id=? AND period=? AND kind='daily'",
        (user.id, today),
    )
    if cur.fetchone():
        conn.close()
        await update.message.reply_text("إنت مسجل التبرع بتاعك النهارده خلاص ✅")
        return
    cur.execute(
        "INSERT INTO donations (user_id, period, kind, confirmed_at) VALUES (?, ?, 'daily', ?)",
        (user.id, today, datetime.now(TIMEZONE).isoformat()),
    )
    conn.commit()
    conn.close()
    await update.message.reply_text("تم تسجيل تبرعك النهارده 🙌")


async def donate_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(TIMEZONE).date().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.ff_name, m.username FROM donations d
        JOIN members m ON m.user_id = d.user_id
        WHERE d.period=? AND d.kind='daily'
        """,
        (today,),
    )
    donated = cur.fetchall()
    cur.execute("SELECT ff_name, username, user_id FROM members")
    all_members = cur.fetchall()
    conn.close()

    donated_ids_names = {(r["ff_name"] or r["username"] or "بدون اسم") for r in donated}
    not_donated = [
        (m["ff_name"] or m["username"] or "بدون اسم")
        for m in all_members
    ]
    # استبعاد اللي تبرعوا من قايمة اللي لسه ماتبرعوش (بالمقارنة بالاسم لتبسيط الكود)
    not_donated = [n for n in not_donated if n not in donated_ids_names]

    msg = "📅 حالة التبرع النهاردة:\n\n"
    msg += "✅ اتبرعوا:\n" + ("\n".join(f"- {n}" for n in donated_ids_names) or "— محدش لسه —")
    msg += "\n\n❌ لسه ماتبرعوش:\n" + ("\n".join(f"- {n}" for n in not_donated) or "— الكل اتبرع 🎉 —")
    await update.message.reply_text(msg)


# ---------------------------------------------------------------------------
# أوامر الأدمن
# ---------------------------------------------------------------------------
async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده للأدمن بس.")
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT gr.id, gr.points, gr.submitted_at, m.ff_name, m.username
        FROM glory_requests gr
        LEFT JOIN members m ON m.user_id = gr.user_id
        WHERE gr.status='pending'
        ORDER BY gr.id
        """
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("مفيش طلبات معلقة حاليًا 👍")
        return
    lines = ["📋 الطلبات المعلقة:\n"]
    for r in rows:
        name = r["ff_name"] or r["username"] or "بدون اسم"
        lines.append(f"#{r['id']} — {name} — {r['points']} نقطة")
    lines.append("\nاستخدم /approve <رقم> أو /reject <رقم>")
    await update.message.reply_text("\n".join(lines))


async def _resolve_request(request_id: int, approve: bool, reviewer_id: int, bot):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM glory_requests WHERE id=? AND status='pending'", (request_id,))
    req = cur.fetchone()
    if not req:
        conn.close()
        return None

    now = datetime.now(TIMEZONE).isoformat()
    new_status = "approved" if approve else "rejected"
    cur.execute(
        "UPDATE glory_requests SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
        (new_status, reviewer_id, now, request_id),
    )
    if approve:
        cur.execute(
            "UPDATE members SET glory_points = glory_points + ? WHERE user_id=?",
            (req["points"], req["user_id"]),
        )
    conn.commit()
    conn.close()

    try:
        if approve:
            await bot.send_message(
                req["user_id"], f"تم اعتماد طلبك #{request_id} ({req['points']} نقطة) ✅"
            )
        else:
            await bot.send_message(req["user_id"], f"تم رفض طلبك #{request_id} ❌")
    except Exception as e:
        logger.warning("مقدرش أبلغ العضو: %s", e)

    return req


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده للأدمن بس.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("استخدم: /approve <رقم الطلب>")
        return
    req = await _resolve_request(int(context.args[0]), True, update.effective_user.id, context.bot)
    await update.message.reply_text("تم الاعتماد ✅" if req else "الطلب مش موجود أو اتراجع عليه قبل كده.")


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده للأدمن بس.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("استخدم: /reject <رقم الطلب>")
        return
    req = await _resolve_request(int(context.args[0]), False, update.effective_user.id, context.bot)
    await update.message.reply_text("تم الرفض ❌" if req else "الطلب مش موجود أو اتراجع عليه قبل كده.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("الأمر ده للأدمن بس.")
        return

    data = query.data
    if data.startswith("glory_approve_"):
        request_id = int(data.split("_")[-1])
        req = await _resolve_request(request_id, True, query.from_user.id, context.bot)
        await query.edit_message_text(
            f"تم اعتماد الطلب #{request_id} ✅" if req else "الطلب اتراجع عليه قبل كده."
        )
    elif data.startswith("glory_reject_"):
        request_id = int(data.split("_")[-1])
        req = await _resolve_request(request_id, False, query.from_user.id, context.bot)
        await query.edit_message_text(
            f"تم رفض الطلب #{request_id} ❌" if req else "الطلب اتراجع عليه قبل كده."
        )
    elif data.startswith("join_approve_") or data.startswith("join_reject_"):
        user_id = int(data.split("_")[-1])
        chat_id = query.message.chat_id
        try:
            if data.startswith("join_approve_"):
                await context.bot.approve_chat_join_request(chat_id, user_id)
                await query.edit_message_text("تم قبول طلب الانضمام ✅")
            else:
                await context.bot.decline_chat_join_request(chat_id, user_id)
                await query.edit_message_text("تم رفض طلب الانضمام ❌")
        except Exception as e:
            await query.edit_message_text(f"حصل خطأ: {e}")


async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة نقاط مباشرة من غير ما تعدي على نظام الطلبات (لتصحيح الأخطاء يدويًا)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده للأدمن بس.")
        return
    if len(context.args) < 2 or not context.args[1].lstrip("-").isdigit():
        await update.message.reply_text("استخدم: /addpoints <user_id> <عدد النقاط>")
        return
    target_id = int(context.args[0])
    points = int(context.args[1])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM members WHERE user_id=?", (target_id,))
    if not cur.fetchone():
        conn.close()
        await update.message.reply_text("العضو ده مش مسجل.")
        return
    cur.execute("UPDATE members SET glory_points = glory_points + ? WHERE user_id=?", (points, target_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"تم تعديل نقاط العضو {target_id} بمقدار {points} ✅")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده للأدمن بس.")
        return
    if not context.args:
        await update.message.reply_text("استخدم: /broadcast <الرسالة>")
        return
    msg = " ".join(context.args)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM members")
    rows = cur.fetchall()
    conn.close()
    sent = 0
    for r in rows:
        try:
            await context.bot.send_message(r["user_id"], f"📢 {msg}")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"تم الإرسال لـ {sent} عضو.")


# ---------------------------------------------------------------------------
# طلبات الانضمام للجروب
# ---------------------------------------------------------------------------
async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    user = req.from_user
    chat = req.chat

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ قبول", callback_data=f"join_approve_{user.id}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"join_reject_{user.id}"),
            ]
        ]
    )
    text = (
        f"طلب انضمام جديد لجروب «{chat.title}»\n"
        f"الاسم: {user.full_name}\n"
        f"يوزر: @{user.username if user.username else '—'}\n"
        f"ID: {user.id}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, reply_markup=keyboard)
        except Exception as e:
            logger.warning("مقدرش أبعت طلب الانضمام للأدمن %s: %s", admin_id, e)


# ---------------------------------------------------------------------------
# تذكيرات مجدولة
# ---------------------------------------------------------------------------
async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID:
        return
    await context.bot.send_message(
        GROUP_CHAT_ID,
        "⏰ تذكير: متنسوش تتبرعوا النهاردة في الكلان!\n"
        "أرسل /donate في الخاص للبوت عشان تسجل تبرعك.",
    )


async def weekly_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID:
        return
    await context.bot.send_message(
        GROUP_CHAT_ID,
        "📅 تذكير أسبوعي: راجعوا تبرعاتكم الأسبوعية ونقاط الجلوري بتاعتكم.\n"
        "استخدموا /submit_glory لإرسال نقاطكم للاعتماد.",
    )


# ---------------------------------------------------------------------------
# التشغيل
# ---------------------------------------------------------------------------
def main():
    if not BOT_TOKEN:
        raise SystemExit("لازم تحدد BOT_TOKEN في متغيرات البيئة.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # أوامر الأعضاء
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("submit_glory", submit_glory))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CommandHandler("donate_status", donate_status))

    # أوامر الأدمن
    app.add_handler(CommandHandler("pending", pending_requests))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # الأزرار (اعتماد/رفض جلوري + طلبات انضمام)
    app.add_handler(CallbackQueryHandler(button_handler))

    # طلبات الانضمام للجروب
    app.add_handler(ChatJoinRequestHandler(handle_join_request))

    # التذكيرات المجدولة (لو حددت GROUP_CHAT_ID)
    if GROUP_CHAT_ID:
        job_queue = app.job_queue
        job_queue.run_daily(
            daily_reminder_job,
            time=dtime(hour=DAILY_REMINDER_HOUR, minute=0, tzinfo=TIMEZONE),
        )
        job_queue.run_daily(
            weekly_reminder_job,
            time=dtime(hour=DAILY_REMINDER_HOUR, minute=0, tzinfo=TIMEZONE),
            days=(WEEKLY_REMINDER_DAY,),
        )

    logger.info("البوت شغال...")
    app.run_polling()


if __name__ == "__main__":
    main()
