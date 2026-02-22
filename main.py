import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from pyrogram.enums import ParseMode, ChatMemberStatus
from pyrogram.errors import FloodWait, RPCError

# --- إعدادات البيانات الخاصة بك ---
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
BOT_TOKEN = "8576422165:AAFS1w9OrSoq5yLISbfNw60VilfHpdBqmgY"
MY_USER_ID = 1486879970 

# ملفات البيانات
REPLIES_FILE = "auto_replies.json"
WARNS_FILE = "user_warns.json"
MEDIA_FILE = "media_replies.json"
MEDIA_INDEX_FILE = "media_index.json"
STATUS_FILE = "bot_status.txt" 
REMINDERS_FILE = "reminders.json"
COUNTDOWN_FILE = "countdowns.json"

def load_data(file_path, default_value):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return default_value
    return default_value

def save_data(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"Error saving data to {file_path}: {e}")

# تحميل البيانات
auto_replies = load_data(REPLIES_FILE, {"السلام عليكم": "وعليكم السلام"})
user_warns = load_data(WARNS_FILE, {})
media_replies = load_data(MEDIA_FILE, {})
media_indices = load_data(MEDIA_INDEX_FILE, {})
reminders = load_data(REMINDERS_FILE, {})
countdowns = load_data(COUNTDOWN_FILE, {})

waiting_for_media = {}
waiting_for_reminder = {}
waiting_for_countdown = {}
active_mentions = set()

# إعداد البوت
app = Client(
    "mention_session_v16", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    workers=100, 
    ipv6=False   
)

async def is_admin(client, user_id, chat_id):
    if user_id == MY_USER_ID: return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]
    except: return False

# --- ميزة العد التنازلي المطور ---
def get_countdown_buttons(target_date):
    now = datetime.now()
    diff = target_date - now
    if diff.total_seconds() <= 0:
        return None
    
    days = diff.days
    weeks = days // 7
    rem_days = days % 7
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    months = days // 30
    
    buttons = []
    # ترتيب عربي من اليمين لليسار: الأصغر يمين والأكبر يسار
    if days > 0:
        if rem_days > 0: buttons.append(InlineKeyboardButton(f"{rem_days} يوم", callback_data="none"))
        if weeks > 0: buttons.append(InlineKeyboardButton(f"{weeks} أسبوع", callback_data="none"))
        if months > 0: buttons.append(InlineKeyboardButton(f"{months} شهر", callback_data="none"))
    else:
        buttons.append(InlineKeyboardButton(f"{minutes} دقيقة", callback_data="none"))
        buttons.append(InlineKeyboardButton(f"{hours} ساعة", callback_data="none"))
    
    return InlineKeyboardMarkup([buttons])

async def countdown_updater():
    while True:
        for cid_str, data in list(countdowns.items()):
            if not data.get("active"): continue
            try:
                target = datetime.fromisoformat(data["target"])
                kb = get_countdown_buttons(target)
                if not kb:
                    countdowns[cid_str]["active"] = False
                    save_data(COUNTDOWN_FILE, countdowns)
                    continue
                
                # تحديث الرسالة المثبتة للعداد
                if "msg_id" in data:
                    await app.edit_message_reply_markup(int(cid_str), data["msg_id"], reply_markup=kb)
            except: pass
        await asyncio.sleep(60)

async def countdown_alert_loop():
    while True:
        now = datetime.now()
        for cid_str, data in list(countdowns.items()):
            if not data.get("active") or not data.get("alert_time"): continue
            # فحص إذا حان وقت التنبيه (كل 30 دقيقة أو وقت محدد)
            alert = data["alert_time"]
            should_alert = False
            
            if "دقيقة" in alert:
                mins = int(re.search(r'\d+', alert).group())
                last = datetime.fromisoformat(data.get("last_alert", data["target"]))
                if (now - last).total_seconds() >= mins * 60: should_alert = True
            elif "الساعة" in alert:
                # تنبيه يومي في ساعة محددة
                target_hour = alert.replace("الساعة", "").strip()
                # تحويل الوقت المبسط 10 مساء إلى تنسيق 24 ساعة برمجياً
                if now.strftime("%I %p").lower().replace("am", "صباحا").replace("pm", "مساء") in target_hour:
                    if data.get("last_alert_day") != now.day: should_alert = True

            if should_alert:
                try:
                    target = datetime.fromisoformat(data["target"])
                    diff = target - now
                    msg = f"تنبيه الوقت ⏳\nمتبقي على {data['text']}: {diff.days} يوم و {diff.seconds//3600} ساعة"
                    await app.send_message(int(cid_str), msg)
                    countdowns[cid_str]["last_alert"] = now.isoformat()
                    countdowns[cid_str]["last_alert_day"] = now.day
                    save_data(COUNTDOWN_FILE, countdowns)
                except: pass
        await asyncio.sleep(30)

@app.on_message(filters.regex(r"^(عد تنازلي|تعديل)\s*\((.*?)\)") & filters.group)
async def start_countdown(client, message):
    if not await is_admin(client, message.from_user.id, message.chat.id): return
    name = message.matches[0].group(2).strip()
    is_edit = "تعديل" in message.text
    waiting_for_countdown[message.from_user.id] = {"name": name, "step": "date", "is_edit": is_edit}
    await message.reply("حسناً، أضف التاريخ المستهدف 📅")

@app.on_message(filters.regex(r"^حذف\s*\((.*?)\)") & filters.group)
async def delete_countdown(client, message):
    if not await is_admin(client, message.from_user.id, message.chat.id): return
    name = message.matches[0].group(1).strip()
    found = False
    for k, v in list(countdowns.items()):
        if v["text"] == name:
            del countdowns[k]
            found = True
    if found:
        save_data(COUNTDOWN_FILE, countdowns)
        await message.reply("تم الحذف ✅")
    else: await message.reply("غير موجود ❌")

# --- ميزة رسالة الترحيب للأعضاء الجدد ---
@app.on_message(filters.new_chat_members & filters.group)
async def welcome_new_members(client, message):
    for member in message.new_chat_members:
        if not member.is_bot:
            welcome_text = f"""أهلاً بك في قروب فجر جديد 🌅
[{member.first_name}](tg://user?id={member.id})
هنا نبدأ صفحة مختلفة…

* ممنوع السلبية ❌
* ممنوع نشر أي محتوى غير لائق ❌
* ممنوع الإحباط أو التقليل من عزيمة الآخرين ❌
* الدعم والتشجيع واجب بيننا 🤝
* هدفنا التعافي… ليس الكمال ✅"""
            await message.reply(welcome_text)

# --- ميزة التذكير الدوري ---
async def reminder_loop(client, chat_id, reminder_text, interval_seconds):
    while True:
        chat_id_str = str(chat_id)
        if chat_id_str not in reminders or not reminders[chat_id_str].get("active", False):
            break
        try:
            await client.send_message(chat_id, f"تذكير ⏰\n\n{reminder_text}")
        except: pass
        await asyncio.sleep(interval_seconds)

@app.on_message(filters.command(["تذكير"], prefixes=["", "/", "!"]) & filters.group)
async def start_reminder(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id):
        return await message.reply("للمشرفين فقط 🚫")
    waiting_for_reminder[message.from_user.id] = {"chat_id": message.chat.id, "step": "text"}
    await message.reply("حسناً، قم بإضافة التذكير ⏳\n\nأرسل نص التذكير الآن:")

@app.on_message(filters.text & filters.group, group=2)
async def receive_all_text_data(client, message):
    uid = message.from_user.id
    
    # معالجة العد التنازلي
    if uid in waiting_for_countdown:
        data = waiting_for_countdown[uid]
        if data["step"] == "date":
            # محاولة فهم التاريخ (دعم 20 مارس، اليوم 10 مساء.. إلخ)
            try:
                txt = message.text.strip()
                target_dt = None
                if "مارس" in txt: target_dt = datetime(2026, 3, int(re.search(r'\d+', txt).group()))
                elif "ابريل" in txt: target_dt = datetime(2026, 4, int(re.search(r'\d+', txt).group()))
                elif "اليوم" in txt: target_dt = datetime.now().replace(hour=int(re.search(r'\d+', txt).group()), minute=0)
                
                if not target_dt: target_dt = datetime.now() + timedelta(days=1) # افتراضي
                
                data["target"] = target_dt.isoformat()
                data["step"] = "alert"
                await message.reply("هل ترغب في تنبيه يومي؟")
            except: await message.reply("التاريخ غير مفهوم ❌")
            
        elif data["step"] == "alert":
            alert_choice = message.text.strip()
            cid_str = str(message.chat.id)
            kb = get_countdown_buttons(datetime.fromisoformat(data["target"]))
            msg = await message.reply(f"تم ضبط العد التنازلي لـ ({data['name']}) ✅\n{'سيتم تنبيهك: ' + alert_choice if alert_choice != 'لا' else ''}", reply_markup=kb)
            
            countdowns[cid_str] = {
                "text": data["name"],
                "target": data["target"],
                "alert_time": alert_choice if alert_choice != "لا" else None,
                "msg_id": msg.id,
                "active": True
            }
            save_data(COUNTDOWN_FILE, countdowns)
            del waiting_for_countdown[uid]
        return

    # معالجة التذكير (الكود الأصلي)
    if uid not in waiting_for_reminder: return
    user_data = waiting_for_reminder[uid]
    if user_data["step"] == "text":
        user_data["text"] = message.text.strip()
        user_data["step"] = "interval"
        await message.reply("تم حفظ نص التذكير ✅\n\nالآن حدد مدة التذكير:\n• اكتب: كل 3 ساعات أو كل ساعة\n• اكتب: كل يوم\n• اكتب: كل اسبوع\n• اكتب: كل 30 دقيقة")
    elif user_data["step"] == "interval":
        text = message.text.strip().lower()
        interval_seconds = None
        if "دقيقة" in text or "دقائق" in text:
            match = re.search(r'(\d+)', text)
            if match: interval_seconds = int(match.group(1)) * 60
        elif "ساعة" in text or "ساعات" in text:
            match = re.search(r'(\d+)', text)
            if match: interval_seconds = (int(match.group(1)) if match else 1) * 3600
        elif "يوم" in text or "ايام" in text:
            match = re.search(r'(\d+)', text)
            interval_seconds = (int(match.group(1)) if match else 1) * 86400
        elif "اسبوع" in text or "أسبوع" in text:
            match = re.search(r'(\d+)', text)
            interval_seconds = (int(match.group(1)) if match else 1) * 604800
        if interval_seconds:
            chat_id_str = str(user_data["chat_id"])
            if chat_id_str in reminders: reminders[chat_id_str]["active"] = False
            reminders[chat_id_str] = {"text": user_data["text"], "interval": interval_seconds, "active": True}
            save_data(REMINDERS_FILE, reminders)
            asyncio.create_task(reminder_loop(client, user_data["chat_id"], user_data["text"], interval_seconds))
            await message.reply(f"تم تفعيل التذكير بنجاح ✅\n\n📝 النص: {user_data['text']}\n⏰ المدة: {text}")
            del waiting_for_reminder[uid]
        else:
            await message.reply("صيغة خاطئة! حاول مرة أخرى ❌")

@app.on_message(filters.command(["ايقاف التذكير", "إيقاف التذكير"], prefixes=["", "/", "!"]) & filters.group)
async def stop_reminder_cmd(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    chat_id_str = str(message.chat.id)
    if chat_id_str in reminders:
        reminders[chat_id_str]["active"] = False
        save_data(REMINDERS_FILE, reminders)
        await message.reply("تم إيقاف التذكير ✅")
    else: await message.reply("لا يوجد تذكير نشط ❌")

# --- ميزة حذف الصور والفيديوهات ---
@app.on_message(filters.regex(r"^احذف\s+(فيديو|صورة)\s*\((.*?)\)") & filters.group)
async def delete_media(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    media_type = "video" if "فيديو" in message.text else "photo"
    match = re.search(r"\((.*?)\)", message.text)
    if match:
        name = match.group(1).strip()
        if name in media_replies:
            del media_replies[name]
            save_data(MEDIA_FILE, media_replies)
            if name in media_indices: del media_indices[name]; save_data(MEDIA_INDEX_FILE, media_indices)
            await message.reply(f"تم حذف ال{'فيديو' if media_type == 'video' else 'صورة'}: {name} 🗑️")
        else: await message.reply(f"لم يتم العثور على: {name} ❌")

# --- ميزة الإنذارات ---
@app.on_message(filters.command(["warn", "انذار"], prefixes=["", "/", "!"]) & filters.group)
async def warn_user(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return await message.reply("للمشرفين فقط 🚫")
    if not message.reply_to_message or not message.reply_to_message.from_user: return await message.reply("رد على رسالة الشخص ⚠️")
    target = message.reply_to_message.from_user
    if target.is_bot or await is_admin(client, target.id, message.chat.id): return await message.reply("لا يمكن إنذاره ❌")
    cid, uid = str(message.chat.id), str(target.id)
    if cid not in user_warns: user_warns[cid] = {}
    user_warns[cid][uid] = user_warns[cid].get(uid, 0) + 1
    save_data(WARNS_FILE, user_warns)
    if user_warns[cid][uid] >= 3:
        try:
            await client.restrict_chat_member(message.chat.id, target.id, ChatPermissions(can_send_messages=False), until_date=datetime.now() + timedelta(hours=2))
            user_warns[cid][uid] = 0
            save_data(WARNS_FILE, user_warns)
            await message.reply(f"تم كتم {target.first_name} لمدة ساعتين (3 إنذارات) 🚫")
        except: await message.reply("فشل الكتم ❌")
    else: await message.reply(f"إنذار لـ {target.first_name} ({user_warns[cid][uid]}/3) ⚠️")

# --- ميزة الميديا والردود ---
@app.on_message(filters.regex(r"^(فيديو|صورة)\s*\((.*?)\)") & filters.group)
async def start_add_media(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    m_type, name = ("video" if "فيديو" in message.text else "photo"), message.matches[0].group(2).strip()
    if name:
        waiting_for_media[message.from_user.id] = {"name": name, "type": m_type}
        await message.reply(f"أرسل ال{'فيديو' if m_type == 'video' else 'صورة'} الآن.")

@app.on_message((filters.video | filters.photo) & filters.group)
async def receive_media(client, message):
    uid = message.from_user.id if message.from_user else None
    if uid in waiting_for_media:
        info = waiting_for_media[uid]
        fid = message.video.file_id if info["type"] == "video" and message.video else message.photo.file_id if info["type"] == "photo" and message.photo else None
        if fid:
            if info["name"] not in media_replies: media_replies[info["name"]] = {"type": info["type"], "ids": []}
            media_replies[info["name"]]["ids"].append(fid)
            save_data(MEDIA_FILE, media_replies)
            del waiting_for_media[uid]
            await message.reply(f"تم الإضافة: {info['name']} ✅")

@app.on_message(filters.command("اضف رد", prefixes=["", "/", "!"]) & filters.group)
async def add_reply_cmd(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    m = re.search(r"\((.*?)\)\s\((.*?)\)", message.text, re.DOTALL)
    if m:
        auto_replies[m.group(1).strip()] = m.group(2).strip()
        save_data(REPLIES_FILE, auto_replies)
        await message.reply(f"تم إضافة الرد: {m.group(1).strip()} ✅")

@app.on_message(filters.command("حذف رد", prefixes=["", "/", "!"]) & filters.group)
async def del_reply_cmd(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    m = re.search(r"\((.*?)\)", message.text, re.DOTALL)
    if m:
        k = m.group(1).strip()
        if k in auto_replies: del auto_replies[k]; save_data(REPLIES_FILE, auto_replies)
        if k in media_replies: del media_replies[k]; save_data(MEDIA_FILE, media_replies)
        await message.reply(f"تم الحذف: {k} 🗑️")

# --- الردود التلقائية ---
@app.on_message(filters.text & filters.group, group=1)
async def auto_reply_handler(client, message):
    if not message.text: return
    t = message.text.strip()
    if t in auto_replies: await message.reply(auto_replies[t])
    elif t in media_replies:
        d = media_replies[t]
        ids = d["ids"]
        if ids:
            idx = media_indices.get(t, 0) % len(ids)
            try:
                if d["type"] == "video": await message.reply_video(ids[idx])
                else: await message.reply_photo(ids[idx])
                media_indices[t] = idx + 1
                save_data(MEDIA_INDEX_FILE, media_indices)
            except: pass

# --- المنشن (all) ---
async def mention_task(client, chat_id, msg, members):
    for i in range(0, len(members), 5):
        if chat_id not in active_mentions: break
        try:
            await client.send_message(chat_id, " ".join(members[i:i+5]) + f"\n\n*{msg}*")
            await asyncio.sleep(4) 
        except FloodWait as e: await asyncio.sleep(e.value)
        except: break
    active_mentions.discard(chat_id)

@app.on_message(filters.command(["all", "mentionall"], prefixes=["", "/", "."]) & filters.group)
async def mentionall(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    if message.chat.id in active_mentions: return await message.reply("جاري المنشن بالفعل ⚠️")
    msg = message.text.split(None, 1)[1] if len(message.command) > 1 else "نداء للجميع 📣"
    active_mentions.add(message.chat.id)
    members = []
    async for m in client.get_chat_members(message.chat.id):
        if m.user and not m.user.is_bot:
            members.append(f"@{m.user.username}" if m.user.username else f"[{m.user.first_name}](tg://user?id={m.user.id})")
    asyncio.create_task(mention_task(client, message.chat.id, msg, members))
    await message.reply(f"بدأ المنشن لـ {len(members)} عضو ✅")

@app.on_message(filters.command(["cancel", "stop"], prefixes=["/", "."]) & filters.group)
async def cancel_spam(client, message):
    active_mentions.discard(message.chat.id)
    await message.reply('توقف ✅')

# --- استعادة التذكيرات ---
async def restore_reminders():
    await asyncio.sleep(5)
    for chat_id_str, reminder_data in reminders.items():
        if reminder_data.get("active", False):
            asyncio.create_task(reminder_loop(app, int(chat_id_str), reminder_data["text"], reminder_data["interval"]))

# --- التشغيل الرئيسي ---
async def main():
    await app.start()
    print("Bot LIVE with Countdown Feature!")
    asyncio.create_task(restore_reminders())
    asyncio.create_task(countdown_updater())
    asyncio.create_task(countdown_alert_loop())
    await idle()
    await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
