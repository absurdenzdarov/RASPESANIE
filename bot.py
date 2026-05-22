import io
import re
import asyncio
import logging
import datetime
import requests
import pandas as pd
import json
import os
import hashlib
import zipfile
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = "8626762224:AAGdtJiY0A3yTOCh7RWrOuNKI4M9iYLVNFQ"
PUBLIC_LINK = "https://disk.360.yandex.ru/d/Xc08g8WbTavdHQ"

ADMIN_ID = 7685909494

logging.basicConfig(level=logging.INFO)

# =========================
# БАЗЫ
# =========================

lessons_db = []
subscriptions = {}
users_db = set()
auto_notify_users = {}
banned_users = set()

# Для отслеживания изменений
last_schedule_hash = None

# График питания по группам
meal_schedule = {
    "1 смена": [
        {"time": "10:15", "groups": ["ПО", "СПА"]},
        {"time": "10:40 – 11:00", "groups": ["ГР-24-9-1", "ГР-24-9-2", "ИСП-24-9-1"]},
        {"time": "11:00 – 11:20", "groups": ["ГР-25-9-1", "БУ-25-9-1", "БУ-25-11-2"]},
        {"time": "11:20 – 11:40", "groups": ["ГР-25-11-1", "ГР-25-11-2", "КМС-23-9-1", "БУ-24-9-1"]},
        {"time": "11:40 – 12:00", "groups": ["РМ-25-9-1", "РМ-25-9-2", "СД-25-11-1"]},
        {"time": "12:00 – 12:20", "groups": ["РМ-23-11-1", "ТД-25-11-1", "СД-25-9-1", "ТД-25-11-2"]}
    ],
    "2 смена": [
        {"time": "13:35", "groups": ["ПО", "СПА"]},
        {"time": "13:55 – 14:15", "groups": ["ГР-22-9-1", "ГР-23-9-1", "ГР-23-9-2", "ТД-24-9-1"]},
        {"time": "14:15 – 14:35", "groups": ["ГР-24-11-1", "ГР-24-11-2", "БУ-249-2", "ТД-24-9-2"]},
        {"time": "14:35 – 14:55", "groups": ["БУ-25-11-1", "ИСП-23-11-1", "ТД-25-9-1"]},
        {"time": "14:55 – 15:15", "groups": ["ТД-24-11-1", "ТД-24-11-2", "СД-24-9-1", "РМ-24-9-1"]},
        {"time": "15:15 – 15:35", "groups": ["РМ-25-11-1", "РМ-24-11-1"]}
    ]
}

# Файлы для сохранения данных
USERS_FILE = "users.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
START_PHOTO_FILE = "start_photo.json"
AUTO_NOTIFY_FILE = "auto_notify.json"
BANNED_USERS_FILE = "banned_users.json"
SCHEDULE_HASH_FILE = "schedule_hash.json"

# =========================
# СОСТОЯНИЯ
# =========================

class ScheduleStates(StatesGroup):
    waiting_for_type = State()
    waiting_for_item = State()
    waiting_for_date = State()

class SubscribeStates(StatesGroup):
    waiting_for_type = State()
    waiting_for_item = State()

class SubscriptionScheduleStates(StatesGroup):
    waiting_for_date = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_start_photo = State()
    waiting_for_user_search = State()
    waiting_for_ban_user = State()
    waiting_for_unban_user = State()

class AutoNotifyStates(StatesGroup):
    selecting = State()

# =========================
# ЗАГРУЗКА/СОХРАНЕНИЕ ДАННЫХ
# =========================

def load_users():
    global users_db
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                users_db = set(data)
        except:
            users_db = set()

def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(users_db), f, ensure_ascii=False)

def load_subscriptions():
    global subscriptions
    if os.path.exists(SUBSCRIPTIONS_FILE):
        try:
            with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                subscriptions = {int(k): v for k, v in data.items()}
        except:
            subscriptions = {}

def save_subscriptions():
    with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(subscriptions, f, ensure_ascii=False)

def load_start_photo():
    if os.path.exists(START_PHOTO_FILE):
        try:
            with open(START_PHOTO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("photo_file_id")
        except:
            return None
    return None

def save_start_photo(photo_file_id):
    with open(START_PHOTO_FILE, "w", encoding="utf-8") as f:
        json.dump({"photo_file_id": photo_file_id}, f)

def load_auto_notify():
    global auto_notify_users
    if os.path.exists(AUTO_NOTIFY_FILE):
        try:
            with open(AUTO_NOTIFY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                auto_notify_users = {int(k): v for k, v in data.items()}
        except:
            auto_notify_users = {}

def save_auto_notify():
    with open(AUTO_NOTIFY_FILE, "w", encoding="utf-8") as f:
        json.dump(auto_notify_users, f, ensure_ascii=False)

def load_banned_users():
    global banned_users
    if os.path.exists(BANNED_USERS_FILE):
        try:
            with open(BANNED_USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                banned_users = set(data)
        except:
            banned_users = set()

def save_banned_users():
    with open(BANNED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(banned_users), f, ensure_ascii=False)

def load_schedule_hash():
    global last_schedule_hash
    if os.path.exists(SCHEDULE_HASH_FILE):
        try:
            with open(SCHEDULE_HASH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_schedule_hash = data.get("hash")
        except:
            last_schedule_hash = None

def save_schedule_hash():
    with open(SCHEDULE_HASH_FILE, "w", encoding="utf-8") as f:
        json.dump({"hash": last_schedule_hash}, f)

# =========================
# ФУНКЦИЯ ДЛЯ ВЫГРУЗКИ ВСЕХ ДАННЫХ В АРХИВ
# =========================

async def create_backup_archive():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"bot_backup_{timestamp}.zip"
    
    with zipfile.ZipFile(archive_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        files_to_backup = [
            USERS_FILE,
            SUBSCRIPTIONS_FILE,
            START_PHOTO_FILE,
            AUTO_NOTIFY_FILE,
            BANNED_USERS_FILE,
            SCHEDULE_HASH_FILE
        ]
        
        for file in files_to_backup:
            if os.path.exists(file):
                zipf.write(file)
        
        current_file = __file__
        if os.path.exists(current_file):
            zipf.write(current_file, "bot_current.py")
        
        info_text = f"""Информация о бэкапе:
Дата: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Пользователей: {len(users_db)}
Заблокировано: {len(banned_users)}
Подписок: {sum(len(v) for v in subscriptions.values())}
Автоуведомлений: {sum(len(v) for v in auto_notify_users.values())}
        """
        zipf.writestr("backup_info.txt", info_text)
    
    return archive_name

# =========================
# ФУНКЦИИ ДЛЯ ГРАФИКА ПИТАНИЯ
# =========================

def get_meal_time_for_group(group_name):
    for shift_name, schedule in meal_schedule.items():
        for meal in schedule:
            if group_name in meal["groups"]:
                return meal["time"]
    return None

def is_saturday(day_str):
    match = re.search(r'([А-я]+)', day_str)
    if match:
        day_of_week = match.group(1)
        return day_of_week.lower() == "суббота"
    return False

def convert_time_to_minutes(time_str):
    try:
        time_str = time_str.strip()
        time_str = re.sub(r'\s+', '', time_str)
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except:
        return 0

def get_lesson_end_time(lesson_time):
    lesson_time = lesson_time.strip()
    if "–" in lesson_time:
        parts = lesson_time.split("–")
        end_part = parts[-1].strip()
    elif "-" in lesson_time:
        parts = lesson_time.split("-")
        end_part = parts[-1].strip()
    else:
        start = convert_time_to_minutes(lesson_time)
        return start + 90
    return convert_time_to_minutes(end_part)

def get_lesson_start_time(lesson_time):
    lesson_time = lesson_time.strip()
    if "–" in lesson_time:
        start_part = lesson_time.split("–")[0].strip()
    elif "-" in lesson_time:
        start_part = lesson_time.split("-")[0].strip()
    else:
        start_part = lesson_time
    return convert_time_to_minutes(start_part)

def insert_meal_break(lessons_list, group_name):
    if not lessons_list:
        return lessons_list
    
    day_str = lessons_list[0].get("day_str", "")
    if is_saturday(day_str):
        return lessons_list
    
    meal_time = get_meal_time_for_group(group_name)
    if not meal_time:
        return lessons_list
    
    meal_start = None
    meal_end = None
    
    if "–" in meal_time:
        parts = meal_time.split("–")
        meal_start = convert_time_to_minutes(parts[0].strip())
        meal_end = convert_time_to_minutes(parts[1].strip())
    else:
        meal_start = convert_time_to_minutes(meal_time)
        meal_end = meal_start + 20
    
    for i in range(len(lessons_list) - 1):
        current_end = get_lesson_end_time(lessons_list[i]["time"])
        next_start = get_lesson_start_time(lessons_list[i + 1]["time"])
        
        if current_end <= meal_start and meal_end <= next_start:
            meal_item = {"is_meal": True, "time": meal_time}
            return lessons_list[:i+1] + [meal_item] + lessons_list[i+1:]
    
    first_start = get_lesson_start_time(lessons_list[0]["time"])
    if meal_end <= first_start:
        meal_item = {"is_meal": True, "time": meal_time}
        return [meal_item] + lessons_list
    
    last_end = get_lesson_end_time(lessons_list[-1]["time"])
    if meal_start >= last_end:
        meal_item = {"is_meal": True, "time": meal_time}
        return lessons_list + [meal_item]
    
    if len(lessons_list) >= 3:
        meal_item = {"is_meal": True, "time": meal_time}
        return lessons_list[:3] + [meal_item] + lessons_list[3:]
    
    return lessons_list

# =========================
# ЗАГРУЗКА РАСПИСАНИЯ С ОТСЛЕЖИВАНИЕМ ИЗМЕНЕНИЙ
# =========================

def get_schedule_hash_from_data():
    schedule_str = json.dumps(lessons_db, sort_keys=True)
    return hashlib.md5(schedule_str.encode()).hexdigest()

def build_schedule_structure():
    structure = {}
    for lesson in lessons_db:
        day = lesson["day_str"]
        group = lesson["group"]
        if day not in structure:
            structure[day] = {}
        if group not in structure[day]:
            structure[day][group] = []
        
        lesson_key = f"{lesson['lesson_num']}|{lesson['time']}|{lesson['subject']}|{lesson['teacher']}|{lesson['room']}"
        structure[day][group].append(lesson_key)
    
    return structure

def find_changed_lessons(old_structure, new_structure):
    changed = {}
    all_days = set(list(old_structure.keys()) + list(new_structure.keys()))
    
    for day in all_days:
        old_day = old_structure.get(day, {})
        new_day = new_structure.get(day, {})
        all_groups = set(list(old_day.keys()) + list(new_day.keys()))
        
        for group in all_groups:
            old_lessons = set(old_day.get(group, []))
            new_lessons = set(new_day.get(group, []))
            
            if old_lessons != new_lessons:
                if day not in changed:
                    changed[day] = {}
                changed[day][group] = {
                    'old': list(old_lessons),
                    'new': list(new_lessons)
                }
    return changed

def load_schedule_from_yandex(public_link):
    global lessons_db

    db_builder = []

    meta_url = f"https://cloud-api.yandex.net/v1/disk/public/resources?public_key={public_link}"

    try:
        response = requests.get(meta_url, timeout=30)

        if response.status_code != 200:
            logging.error(f"Ошибка загрузки: {response.status_code}")
            return False

        items = response.json().get("_embedded", {}).get("items", [])

        for item in items:
            if item.get("type") == "file" and item.get("name", "").endswith(".xls"):
                file_path = item["path"]

                download_api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={public_link}&path={file_path}"
                download_meta = requests.get(download_api_url, timeout=30).json()
                direct_url = download_meta.get("href")

                if not direct_url:
                    continue

                file_bytes = requests.get(direct_url, timeout=30).content
                excel_buffer = io.BytesIO(file_bytes)

                sheets = pd.read_excel(excel_buffer, sheet_name=None, header=None, engine="xlrd")

                for _, df in sheets.items():
                    df = df.fillna("")
                    rows = df.values.tolist()

                    header_row = None
                    for r in rows:
                        if r and len(r) > 0 and "День недели" in str(r[0]):
                            header_row = r
                            break

                    if not header_row and rows:
                        header_row = rows[0]

                    current_day = ""

                    for row in rows:
                        if not row or len(row) < 3:
                            continue

                        if str(row[0]).strip() and "День недели" not in str(row[0]):
                            current_day = str(row[0]).strip()

                        lesson_num = str(row[1]).strip()
                        lesson_time = str(row[2]).strip()

                        if not lesson_num or not lesson_time or "№" in lesson_num:
                            continue

                        for col_idx in range(3, len(row), 3):
                            if col_idx + 2 >= len(row):
                                break

                            group_name = str(header_row[col_idx]).strip() if col_idx < len(header_row) else ""

                            if not group_name or "Фамилия" in group_name or "Каб" in group_name:
                                continue

                            subject = str(row[col_idx]).strip()
                            teacher = str(row[col_idx + 1]).strip()
                            room = str(row[col_idx + 2]).strip()

                            if subject and subject.lower() != "сессия" and subject.lower() != "гия":
                                db_builder.append({
                                    "day_str": current_day,
                                    "lesson_num": lesson_num,
                                    "time": lesson_time,
                                    "group": group_name,
                                    "subject": subject,
                                    "teacher": teacher,
                                    "room": room
                                })

        lessons_db = db_builder
        logging.info(f"Загружено занятий: {len(lessons_db)}")
        return True

    except Exception as e:
        logging.error(f"Ошибка загрузки расписания: {e}")
        return False

# =========================
# ФУНКЦИИ ДЛЯ РАБОТЫ С РАСПИСАНИЕМ
# =========================

def get_unique_items(search_type):
    if search_type == "group":
        return sorted(list(set(l["group"] for l in lessons_db if l["group"] and l["group"].strip() not in ["", "."])))
    elif search_type == "teacher":
        return sorted(list(set(l["teacher"] for l in lessons_db if l["teacher"] and l["teacher"].strip() not in ["", "."])))
    elif search_type == "room":
        return sorted(list(set(l["room"] for l in lessons_db if l["room"] and l["room"].strip() not in ["", "."])))
    return []

def get_unique_days():
    def get_date_key(day_str):
        match = re.search(r'\d{2}\.\d{2}\.\d{2}', day_str)
        if match:
            try:
                return datetime.datetime.strptime(match.group(0), "%d.%m.%y")
            except:
                pass
        return datetime.datetime.min

    return sorted(list(set(l["day_str"] for l in lessons_db if l["day_str"])), key=get_date_key)

def parse_day_string(day_str):
    match = re.search(r'([А-я]+)\s+(\d{2}\.\d{2}\.\d{2})', day_str)
    if match:
        day_of_week = match.group(1)
        full_date = match.group(2)
        short_date = full_date[:-3]
        return short_date, day_of_week
    return "", ""

def get_schedule_for_item(search_type, chosen_item, day_str=None):
    filtered = []
    for l in lessons_db:
        if day_str and l["day_str"] != day_str:
            continue
        if search_type == "group" and l["group"] == chosen_item:
            filtered.append(l)
        elif search_type == "teacher" and l["teacher"] == chosen_item:
            filtered.append(l)
        elif search_type == "room" and l["room"] == chosen_item:
            filtered.append(l)
    
    filtered.sort(key=lambda x: int(x["lesson_num"]) if x["lesson_num"].isdigit() else 0)
    
    if search_type == "group" and filtered:
        filtered = insert_meal_break(filtered, chosen_item)
    
    return filtered

def get_week_schedule(search_type, chosen_item):
    days = get_unique_days()
    week_schedule = {}
    for day in days:
        filtered = get_schedule_for_item(search_type, chosen_item, day)
        if filtered:
            week_schedule[day] = filtered
    return week_schedule

def format_schedule_text(schedule_data, title, is_week=False, search_type=None):
    if is_week:
        text = f"📚 <b>Расписание на неделю</b>\n\n"
        if search_type == "group":
            text += f"👥 {title}\n\n"
        elif search_type == "teacher":
            text += f"👨‍🏫 {title}\n\n"
        elif search_type == "room":
            text += f"🚪 {title}\n\n"
        else:
            text += f"⭐ {title}\n\n"
        
        for day_str, lessons in schedule_data.items():
            short_date, day_of_week = parse_day_string(day_str)
            text += f"━━━━━━━━━━━━━━\n📅 {day_of_week} • {short_date}\n\n"
            
            for item in lessons:
                if item.get("is_meal"):
                    text += f"🍽 <b>🍴 ОБЕД</b> • {item['time']}\n\n"
                else:
                    text += f"━━━━━━━━━━━━━━\n⏰ {item['lesson_num']} • {item['time']}\n📘 {item['subject']}\n👨‍🏫 {item['teacher']}\n🚪 {item['room']}\n\n"
        
        if not schedule_data:
            text += "😴 На этой неделе занятий не найдено."
        return text
    else:
        if not schedule_data:
            return "😴 Занятий не найдено."
        
        first_day = list(schedule_data.keys())[0]
        short_date, day_of_week = parse_day_string(first_day)
        text = f"📚 <b>Расписание</b>\n\n📅 {day_of_week} • {short_date}\n"
        
        if search_type == "group":
            text += f"👥 {title}\n\n"
        elif search_type == "teacher":
            text += f"👨‍🏫 {title}\n\n"
        elif search_type == "room":
            text += f"🚪 {title}\n\n"
        else:
            text += f"⭐ {title}\n\n"
        
        for item in schedule_data[first_day]:
            if item.get("is_meal"):
                text += f"━━━━━━━━━━━━━━\n🍽 <b>🍴 ОБЕД</b> • {item['time']}\n\n"
            else:
                text += f"━━━━━━━━━━━━━━\n⏰ {item['lesson_num']} • {item['time']}\n📘 {item['subject']}\n👨‍🏫 {item['teacher']}\n🚪 {item['room']}\n\n"
        
        return text

# =========================
# НОВАЯ ФУНКЦИЯ: ОТПРАВКА САМОГО РАСПИСАНИЯ ПРИ ИЗМЕНЕНИИ
# =========================

async def send_updated_schedule(bot, changed_lessons):
    """Отправляет пользователям обновленное расписание при изменениях"""
    for day, groups in changed_lessons.items():
        short_date, day_of_week = parse_day_string(day)
        
        for group, changes in groups.items():
            # Получаем обновленное расписание для этой группы на этот день
            updated_lessons = get_schedule_for_item("group", group, day)
            
            # Форматируем расписание
            if updated_lessons:
                text = f"🔄 <b>Расписание обновлено!</b>\n\n📅 {day_of_week} • {short_date}\n👥 {group}\n\n"
                
                for item in updated_lessons:
                    if item.get("is_meal"):
                        text += f"━━━━━━━━━━━━━━\n🍽 <b>🍴 ОБЕД</b> • {item['time']}\n\n"
                    else:
                        text += f"━━━━━━━━━━━━━━\n⏰ {item['lesson_num']} • {item['time']}\n📘 {item['subject']}\n👨‍🏫 {item['teacher']}\n🚪 {item['room']}\n\n"
            else:
                text = f"🔄 <b>Расписание обновлено!</b>\n\n📅 {day_of_week} • {short_date}\n👥 {group}\n\n😴 Занятий не найдено."
            
            # Отправляем всем подписанным пользователям с включенными уведомлениями
            for user_id, sub_indices in auto_notify_users.items():
                if user_id in banned_users:
                    continue
                
                user_subs = subscriptions.get(user_id, [])
                for idx in sub_indices:
                    if idx >= len(user_subs):
                        continue
                    
                    sub_type, sub_item = user_subs[idx]
                    if sub_type == "group" and sub_item == group:
                        try:
                            await bot.send_message(user_id, text, parse_mode="HTML")
                        except:
                            pass
                        break

# =========================
# АВТООБНОВЛЕНИЕ РАСПИСАНИЯ (КАЖДЫЕ 5 МИНУТ)
# =========================

async def auto_update_schedule(bot):
    global last_schedule_hash, lessons_db
    
    while True:
        try:
            logging.info("Проверка обновления расписания...")
            
            old_structure = build_schedule_structure()
            old_hash = get_schedule_hash_from_data()
            
            success = load_schedule_from_yandex(PUBLIC_LINK)
            
            if success:
                new_hash = get_schedule_hash_from_data()
                
                if old_hash != new_hash and old_hash is not None:
                    logging.info("Обнаружены изменения в расписании!")
                    
                    new_structure = build_schedule_structure()
                    changed = find_changed_lessons(old_structure, new_structure)
                    
                    if changed:
                        # Отправляем обновленное расписание вместо простого уведомления
                        await send_updated_schedule(bot, changed)
                        logging.info(f"Обновленное расписание отправлено. Изменений: {len(changed)}")
                    
                    last_schedule_hash = new_hash
                    save_schedule_hash()
                elif old_hash is None:
                    last_schedule_hash = new_hash
                    save_schedule_hash()
                    logging.info("Первоначальная загрузка расписания выполнена")
                else:
                    logging.info("Изменений в расписании не обнаружено")
            else:
                logging.warning("Не удалось загрузить расписание")
                
        except Exception as e:
            logging.error(f"Ошибка при обновлении расписания: {e}")
        
        await asyncio.sleep(300)

# =========================
# ПРОВЕРКА БАНА (Middleware)
# =========================

async def check_ban_middleware(handler, event, data):
    if isinstance(event, Message) and event.from_user.id in banned_users:
        await event.answer("⛔ <b>Доступ запрещен!</b>\n\nВы были заблокированы администратором.", parse_mode="HTML")
        return
    elif isinstance(event, CallbackQuery) and event.from_user.id in banned_users:
        await event.answer("⛔ Вы заблокированы!", show_alert=True)
        return
    return await handler(event, data)

# =========================
# ROUTER
# =========================

router = Router()
router.message.middleware(check_ban_middleware)
router.callback_query.middleware(check_ban_middleware)

# =========================
# START
# =========================

@router.message(Command("start"))
async def cmd_start(message: Message):
    users_db.add(message.from_user.id)
    save_users()

    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Расписание", callback_data="open_schedule")
    builder.button(text="⭐ Подписки", callback_data="open_subscriptions")
    builder.button(text="➕ Подписаться", callback_data="open_subscribe")
    builder.button(text="➖ Отписаться", callback_data="open_unsubscribe")
    builder.button(text="🔔 Автоуведомления", callback_data="open_auto_notify")
    builder.button(text="ℹ️ Помощь", callback_data="open_help")
    builder.adjust(1)

    text = (
        "╔════════════════╗\n🎓 <b>БОТ РАСПИСАНИЯ</b>\n╚════════════════╝\n\n"
        "📚 Просмотр расписания\n⭐ Удобные подписки\n⚡ Быстрый доступ\n🔔 Автоуведомления\n\n"
        "━━━━━━━━━━━━━━\n📌 <b>Команды:</b>\n\n"
        "📅 /schedule — расписание\n⭐ /subscriptions — подписки\n➕ /subscribe — подписаться\n"
        "➖ /unsubscribe — отписаться\n🔔 /autonotify — автоуведомления\nℹ️ /help — помощь\n\n"
        "━━━━━━━━━━━━━━\n💡 Выберите действие:"
    )

    start_photo = load_start_photo()
    if start_photo:
        await message.answer_photo(photo=start_photo, caption=text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# =========================
# HELP
# =========================

@router.message(Command("help"))
@router.callback_query(F.data == "open_help")
async def cmd_help(event):
    builder = InlineKeyboardBuilder()
    builder.button(text="🛠 Поддержка", url="https://t.me/DevMenter")

    text = "ℹ️ <b>Помощь</b>\n\n📅 /schedule — расписание\n⭐ /subscriptions — подписки\n➕ /subscribe — подписаться\n➖ /unsubscribe — отписаться\n🔔 /autonotify — автоуведомления\n\n📌 По всем вопросам обращайтесь в поддержку:"

    if isinstance(event, Message):
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await event.message.delete()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# =========================
# AUTO NOTIFY
# =========================

@router.message(Command("autonotify"))
@router.callback_query(F.data == "open_auto_notify")
async def cmd_auto_notify(event, state: FSMContext):
    user_id = event.from_user.id
    user_subs = subscriptions.get(user_id, [])
    
    if not user_subs:
        text = "⚠️ У вас нет подписок.\n\nСначала создайте подписки через /subscribe"
        if isinstance(event, Message):
            await event.answer(text)
        else:
            await event.message.answer(text)
        return
    
    builder = InlineKeyboardBuilder()
    
    for idx, (_, item) in enumerate(user_subs):
        is_selected = user_id in auto_notify_users and idx in auto_notify_users.get(user_id, [])
        status = "✅" if is_selected else "⬜"
        builder.button(text=f"{status} {item}", callback_data=f"auto_toggle:{idx}")
    
    builder.adjust(1)
    builder.button(text="🔙 Назад", callback_data="back_to_start")
    
    selected_count = len(auto_notify_users.get(user_id, []))
    
    text = (
        "🔔 <b>Настройка автоуведомлений</b>\n\n"
        f"Выберите подписки, по которым хотите получать уведомления:\n"
        f"━━━━━━━━━━━━━━\n"
        f"✅ - уведомления включены\n"
        f"⬜ - уведомления выключены\n\n"
        f"📊 Выбрано: {selected_count} из {len(user_subs)}"
    )
    
    if isinstance(event, Message):
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await event.message.delete()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    
    await state.set_state(AutoNotifyStates.selecting)

@router.callback_query(F.data.startswith("auto_toggle:"), StateFilter(AutoNotifyStates.selecting))
async def auto_toggle_subscription(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    idx = int(callback.data.split(":")[1])
    
    if user_id not in auto_notify_users:
        auto_notify_users[user_id] = []
    
    if idx in auto_notify_users[user_id]:
        auto_notify_users[user_id].remove(idx)
    else:
        auto_notify_users[user_id].append(idx)
    
    if not auto_notify_users[user_id]:
        del auto_notify_users[user_id]
    
    save_auto_notify()
    
    user_subs = subscriptions.get(user_id, [])
    builder = InlineKeyboardBuilder()
    
    for i, (_, item) in enumerate(user_subs):
        is_selected = user_id in auto_notify_users and i in auto_notify_users.get(user_id, [])
        status = "✅" if is_selected else "⬜"
        builder.button(text=f"{status} {item}", callback_data=f"auto_toggle:{i}")
    
    builder.adjust(1)
    builder.button(text="🔙 Назад", callback_data="back_to_start")
    
    selected_count = len(auto_notify_users.get(user_id, []))
    
    text = (
        "🔔 <b>Настройка автоуведомлений</b>\n\n"
        f"Выберите подписки, по которым хотите получать уведомления:\n"
        f"━━━━━━━━━━━━━━\n"
        f"✅ - уведомления включены\n"
        f"⬜ - уведомления выключены\n\n"
        f"📊 Выбрано: {selected_count} из {len(user_subs)}"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

# =========================
# SCHEDULE
# =========================

@router.message(Command("schedule"))
@router.callback_query(F.data == "open_schedule")
async def cmd_schedule(event, state: FSMContext):
    await state.clear()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Группа", callback_data="type:group")
    builder.button(text="Преподаватель", callback_data="type:teacher")
    builder.button(text="Кабинет", callback_data="type:room")
    builder.adjust(1)

    text = "📅 <b>Просмотр расписания</b>\n\nВыберите тип:"

    if isinstance(event, Message):
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await event.message.delete()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# =========================
# SUBSCRIBE
# =========================

@router.message(Command("subscribe"))
@router.callback_query(F.data == "open_subscribe")
async def cmd_subscribe(event, state: FSMContext):
    await state.clear()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Группа", callback_data="sub_type:group")
    builder.button(text="Преподаватель", callback_data="sub_type:teacher")
    builder.button(text="Кабинет", callback_data="sub_type:room")
    builder.adjust(1)

    text = "⭐ <b>Создание подписки</b>\n\nВыберите тип:"

    if isinstance(event, Message):
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await event.message.delete()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

    await state.set_state(SubscribeStates.waiting_for_type)

# =========================
# SUBSCRIPTIONS
# =========================

@router.message(Command("subscriptions"))
@router.callback_query(F.data == "open_subscriptions")
async def cmd_subscriptions(event):
    user_id = event.from_user.id
    user_subs = subscriptions.get(user_id, [])

    if not user_subs:
        text = "⭐ У вас нет подписок."
        if isinstance(event, Message):
            await event.answer(text)
        else:
            await event.message.answer(text)
        return

    builder = InlineKeyboardBuilder()
    for idx, (_, item) in enumerate(user_subs):
        builder.button(text=item, callback_data=f"subscription:{idx}")
    builder.adjust(1)

    text = "⭐ <b>Ваши подписки</b>\n\nВыберите:"

    if isinstance(event, Message):
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await event.message.delete()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# =========================
# UNSUBSCRIBE
# =========================

@router.message(Command("unsubscribe"))
@router.callback_query(F.data == "open_unsubscribe")
async def unsubscribe_menu(event):
    user_id = event.from_user.id
    user_subs = subscriptions.get(user_id, [])

    if not user_subs:
        text = "❌ У вас нет подписок."
        if isinstance(event, Message):
            await event.answer(text)
        else:
            await event.message.answer(text)
        return

    builder = InlineKeyboardBuilder()
    for idx, (_, item) in enumerate(user_subs):
        builder.button(text=f"❌ {item}", callback_data=f"unsubscribe:{idx}")
    builder.adjust(1)

    text = "➖ <b>Удаление подписки</b>\n\nВыберите подписку:"

    if isinstance(event, Message):
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await event.message.delete()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# =========================
# УДАЛЕНИЕ ПОДПИСКИ
# =========================

@router.callback_query(F.data.startswith("unsubscribe:"))
async def unsubscribe_process(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_subs = subscriptions.get(user_id, [])

    if idx >= len(user_subs):
        return

    deleted_sub = user_subs.pop(idx)
    
    if user_id in auto_notify_users:
        auto_notify_users[user_id] = [i for i in auto_notify_users[user_id] if i != idx]
        auto_notify_users[user_id] = [i-1 if i > idx else i for i in auto_notify_users[user_id]]
        if not auto_notify_users[user_id]:
            del auto_notify_users[user_id]
    
    save_subscriptions()
    save_auto_notify()

    await callback.message.delete()
    await callback.message.answer(f"✅ Подписка удалена\n\n<b>{deleted_sub[1]}</b>", parse_mode="HTML")

# =========================
# ВЫБОР ТИПА РАСПИСАНИЯ
# =========================

@router.callback_query(F.data.startswith("type:"))
async def process_type(callback: CallbackQuery, state: FSMContext):
    search_type = callback.data.split(":")[1]
    await state.update_data(search_type=search_type)

    items = get_unique_items(search_type)
    builder = InlineKeyboardBuilder()
    
    for idx, item in enumerate(items):
        builder.button(text=str(item), callback_data=f"item:{idx}")
    builder.adjust(2)

    await callback.message.delete()
    await callback.message.answer("🔎 <b>Выберите значение</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(ScheduleStates.waiting_for_item)

# =========================
# ВЫБОР ЭЛЕМЕНТА
# =========================

@router.callback_query(F.data.startswith("item:"), StateFilter(ScheduleStates.waiting_for_item))
async def process_item(callback: CallbackQuery, state: FSMContext):
    item_idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_type = data["search_type"]
    items = get_unique_items(search_type)
    chosen_item = items[item_idx]
    await state.update_data(chosen_item=chosen_item)

    days = get_unique_days()
    builder = InlineKeyboardBuilder()

    today = datetime.date.today().strftime("%d.%m")
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d.%m")

    for idx, day in enumerate(days):
        short_date, day_of_week = parse_day_string(day)
        btn_text = f"{day_of_week} {short_date}"
        if short_date == today:
            btn_text += " • сегодня"
        elif short_date == tomorrow:
            btn_text += " • завтра"
        builder.button(text=btn_text, callback_data=f"date:{idx}")

    builder.button(text="📅 ВСЯ НЕДЕЛЯ", callback_data="week_schedule")
    builder.adjust(2)

    await callback.message.delete()
    await callback.message.answer("📅 <b>Выберите дату или всю неделю</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(ScheduleStates.waiting_for_date)

# =========================
# ПОКАЗ РАСПИСАНИЯ (ДЕНЬ)
# =========================

@router.callback_query(F.data.startswith("date:"), StateFilter(ScheduleStates.waiting_for_date))
async def process_date(callback: CallbackQuery, state: FSMContext):
    date_idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_type = data["search_type"]
    chosen_item = data["chosen_item"]
    days = get_unique_days()
    chosen_day_str = days[date_idx]

    filtered = get_schedule_for_item(search_type, chosen_item, chosen_day_str)
    short_date, day_of_week = parse_day_string(chosen_day_str)

    text = f"📚 <b>Расписание</b>\n\n📅 {day_of_week} • {short_date}\n"
    
    if search_type == "group":
        text += f"👥 {chosen_item}\n\n"
    elif search_type == "teacher":
        text += f"👨‍🏫 {chosen_item}\n\n"
    elif search_type == "room":
        text += f"🚪 {chosen_item}\n\n"

    if not filtered:
        text += "😴 Занятий не найдено."
    else:
        for item in filtered:
            if item.get("is_meal"):
                text += f"━━━━━━━━━━━━━━\n🍽 <b>🍴 ОБЕД</b> • {item['time']}\n\n"
            else:
                text += f"━━━━━━━━━━━━━━\n⏰ {item['lesson_num']} • {item['time']}\n📘 {item['subject']}\n👨‍🏫 {item['teacher']}\n🚪 {item['room']}\n\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

# =========================
# ПОКАЗ РАСПИСАНИЯ (НЕДЕЛЯ)
# =========================

@router.callback_query(F.data == "week_schedule", StateFilter(ScheduleStates.waiting_for_date))
async def process_week_schedule(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    search_type = data["search_type"]
    chosen_item = data["chosen_item"]
    
    week_schedule = get_week_schedule(search_type, chosen_item)
    text = format_schedule_text(week_schedule, chosen_item, is_week=True, search_type=search_type)
    
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()
    await state.clear()

# =========================
# СОЗДАНИЕ ПОДПИСКИ
# =========================

@router.callback_query(F.data.startswith("sub_type:"), StateFilter(SubscribeStates.waiting_for_type))
async def process_sub_type(callback: CallbackQuery, state: FSMContext):
    search_type = callback.data.split(":")[1]
    await state.update_data(search_type=search_type)

    items = get_unique_items(search_type)
    builder = InlineKeyboardBuilder()
    
    for idx, item in enumerate(items):
        builder.button(text=str(item), callback_data=f"sub_item:{idx}")
    builder.adjust(2)

    await callback.message.delete()
    await callback.message.answer("⭐ <b>Выберите объект подписки</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(SubscribeStates.waiting_for_item)

# =========================
# СОХРАНЕНИЕ ПОДПИСКИ
# =========================

@router.callback_query(F.data.startswith("sub_item:"), StateFilter(SubscribeStates.waiting_for_item))
async def process_sub_item(callback: CallbackQuery, state: FSMContext):
    item_idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_type = data["search_type"]
    items = get_unique_items(search_type)
    chosen_item = items[item_idx]

    user_id = callback.from_user.id
    if user_id not in subscriptions:
        subscriptions[user_id] = []

    if (search_type, chosen_item) not in subscriptions[user_id]:
        subscriptions[user_id].append((search_type, chosen_item))
        save_subscriptions()

    await callback.message.delete()
    await callback.message.answer(f"⭐ Подписка сохранена\n\n<b>{chosen_item}</b>", parse_mode="HTML")
    await state.clear()

# =========================
# ОТКРЫТЬ ПОДПИСКУ (ВЫБОР ДНЯ)
# =========================

@router.callback_query(F.data.startswith("subscription:"))
async def open_subscription(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_subs = subscriptions.get(user_id, [])

    if idx >= len(user_subs):
        return

    search_type, chosen_item = user_subs[idx]
    await state.update_data(subscription_idx=idx, search_type=search_type, chosen_item=chosen_item)

    days = get_unique_days()
    builder = InlineKeyboardBuilder()

    today = datetime.date.today().strftime("%d.%m")
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d.%m")

    for idx_day, day in enumerate(days):
        short_date, day_of_week = parse_day_string(day)
        btn_text = f"{day_of_week} {short_date}"
        if short_date == today:
            btn_text += " • сегодня"
        elif short_date == tomorrow:
            btn_text += " • завтра"
        builder.button(text=btn_text, callback_data=f"sub_date:{idx_day}")
    
    builder.button(text="📅 ВСЯ НЕДЕЛЯ", callback_data="sub_week_schedule")
    builder.adjust(2)

    await callback.message.delete()
    await callback.message.answer(f"⭐ <b>{chosen_item}</b>\n\n📅 Выберите дату или всю неделю:", parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(SubscriptionScheduleStates.waiting_for_date)

# =========================
# ПОКАЗ РАСПИСАНИЯ ИЗ ПОДПИСКИ (ДЕНЬ)
# =========================

@router.callback_query(F.data.startswith("sub_date:"), StateFilter(SubscriptionScheduleStates.waiting_for_date))
async def process_subscription_date(callback: CallbackQuery, state: FSMContext):
    date_idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_type = data["search_type"]
    chosen_item = data["chosen_item"]
    days = get_unique_days()
    chosen_day_str = days[date_idx]

    filtered = get_schedule_for_item(search_type, chosen_item, chosen_day_str)
    short_date, day_of_week = parse_day_string(chosen_day_str)

    text = f"📚 <b>Расписание</b>\n\n📅 {day_of_week} • {short_date}\n"
    
    if search_type == "group":
        text += f"👥 {chosen_item}\n\n"
    elif search_type == "teacher":
        text += f"👨‍🏫 {chosen_item}\n\n"
    elif search_type == "room":
        text += f"🚪 {chosen_item}\n\n"

    if not filtered:
        text += "😴 Занятий не найдено."
    else:
        for item in filtered:
            if item.get("is_meal"):
                text += f"━━━━━━━━━━━━━━\n🍽 <b>🍴 ОБЕД</b> • {item['time']}\n\n"
            else:
                text += f"━━━━━━━━━━━━━━\n⏰ {item['lesson_num']} • {item['time']}\n📘 {item['subject']}\n👨‍🏫 {item['teacher']}\n🚪 {item['room']}\n\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

# =========================
# ПОКАЗ РАСПИСАНИЯ ИЗ ПОДПИСКИ (НЕДЕЛЯ)
# =========================

@router.callback_query(F.data == "sub_week_schedule", StateFilter(SubscriptionScheduleStates.waiting_for_date))
async def process_subscription_week(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    search_type = data["search_type"]
    chosen_item = data["chosen_item"]
    
    week_schedule = get_week_schedule(search_type, chosen_item)
    text = format_schedule_text(week_schedule, chosen_item, is_week=True, search_type=search_type)
    
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()
    await state.clear()

@router.callback_query(F.data == "back_to_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await cmd_start(callback.message)

# =========================
# АДМИН ПАНЕЛЬ
# =========================

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="💾 Выгрузка данных", callback_data="admin_backup")
    builder.button(text="📸 Фото для /start", callback_data="admin_start_photo")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="🔍 Поиск пользователя", callback_data="admin_search_user")
    builder.button(text="⛔ Бан пользователя", callback_data="admin_ban_user")
    builder.button(text="✅ Разбан пользователя", callback_data="admin_unban_user")
    builder.adjust(1)

    await message.answer("🛠 <b>Админ панель</b>", parse_mode="HTML", reply_markup=builder.as_markup())

# =========================
# ВЫГРУЗКА ДАННЫХ (БЭКАП)
# =========================

@router.callback_query(F.data == "admin_backup")
async def admin_backup(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    status_msg = await callback.message.answer("⏳ Создание архива с данными...")
    
    try:
        archive_name = await create_backup_archive()
        
        await callback.message.answer_document(
            document=FSInputFile(archive_name),
            caption=f"📦 <b>Бэкап данных бота</b>\n\n"
                    f"📅 Дата: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 Пользователей: {len(users_db)}\n"
                    f"⭐ Подписок: {sum(len(v) for v in subscriptions.values())}\n"
                    f"🔔 Автоуведомлений: {sum(len(v) for v in auto_notify_users.values())}\n"
                    f"⛔ Заблокировано: {len(banned_users)}",
            parse_mode="HTML"
        )
        
        os.remove(archive_name)
        await status_msg.delete()
        
    except Exception as e:
        logging.error(f"Ошибка при создании бэкапа: {e}")
        await status_msg.edit_text(f"❌ Ошибка при создании бэкапа: {e}")

# =========================
# СТАТИСТИКА
# =========================

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    total_subscriptions = sum(len(v) for v in subscriptions.values())
    total_auto = sum(len(v) for v in auto_notify_users.values())
    
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{len(users_db)}</b>\n"
        f"⭐ Подписок: <b>{total_subscriptions}</b>\n"
        f"📚 Занятий: <b>{len(lessons_db)}</b>\n"
        f"🔔 Автоуведомлений: <b>{total_auto}</b>\n"
        f"⛔ Заблокировано: <b>{len(banned_users)}</b>"
    )

    await callback.message.answer(text, parse_mode="HTML")

# =========================
# ПОИСК ПОЛЬЗОВАТЕЛЯ
# =========================

@router.callback_query(F.data == "admin_search_user")
async def admin_search_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer("🔍 Введите ID пользователя для поиска:")
    await state.set_state(AdminStates.waiting_for_user_search)

@router.message(StateFilter(AdminStates.waiting_for_user_search))
async def process_user_search(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ Неверный формат ID. Введите число.")
        return

    is_registered = user_id in users_db
    is_banned = user_id in banned_users
    
    user_subs = subscriptions.get(user_id, [])
    user_auto = auto_notify_users.get(user_id, [])
    
    user_info = "❌ Не удалось получить"
    try:
        chat = await message.bot.get_chat(user_id)
        user_info = f"{chat.first_name or ''} {chat.last_name or ''} (@{chat.username or 'нет'})"
    except:
        pass
    
    text = (
        f"🔍 <b>Информация о пользователе</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {user_info}\n"
        f"📝 Статус: {'✅ Зарегистрирован' if is_registered else '❌ Не зарегистрирован'}\n"
        f"⛔ Бан: {'🔴 Заблокирован' if is_banned else '🟢 Не заблокирован'}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"⭐ <b>Подписки ({len(user_subs)})</b>:\n"
    )
    
    if user_subs:
        for i, (sub_type, sub_item) in enumerate(user_subs, 1):
            type_icon = "👥" if sub_type == "group" else "👨‍🏫" if sub_type == "teacher" else "🚪"
            has_auto = "🔔" if i-1 in user_auto else "🔕"
            text += f"{i}. {type_icon} {sub_item} {has_auto}\n"
    else:
        text += "Нет подписок\n"
    
    text += f"\n🔔 <b>Автоуведомления</b>: {len(user_auto)} из {len(user_subs)} включено"
    
    await message.answer(text, parse_mode="HTML")
    await state.clear()

# =========================
# БАН ПОЛЬЗОВАТЕЛЯ
# =========================

@router.callback_query(F.data == "admin_ban_user")
async def admin_ban_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer("⛔ Введите ID пользователя для бана:")
    await state.set_state(AdminStates.waiting_for_ban_user)

@router.message(StateFilter(AdminStates.waiting_for_ban_user))
async def process_ban_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ Неверный формат ID. Введите число.")
        return

    if user_id == ADMIN_ID:
        await message.answer("❌ Нельзя заблокировать администратора!")
        await state.clear()
        return

    banned_users.add(user_id)
    save_banned_users()
    
    try:
        await message.bot.send_message(user_id, "⛔ <b>Внимание!</b>\n\nВы были заблокированы администратором. Доступ к боту ограничен.", parse_mode="HTML")
    except:
        pass
    
    await message.answer(f"✅ Пользователь <code>{user_id}</code> заблокирован!", parse_mode="HTML")
    await state.clear()

# =========================
# РАЗБАН ПОЛЬЗОВАТЕЛЯ
# =========================

@router.callback_query(F.data == "admin_unban_user")
async def admin_unban_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer("✅ Введите ID пользователя для разбана:")
    await state.set_state(AdminStates.waiting_for_unban_user)

@router.message(StateFilter(AdminStates.waiting_for_unban_user))
async def process_unban_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ Неверный формат ID. Введите число.")
        return

    if user_id in banned_users:
        banned_users.remove(user_id)
        save_banned_users()
        
        try:
            await message.bot.send_message(user_id, "✅ <b>Внимание!</b>\n\nВаш доступ к боту восстановлен!", parse_mode="HTML")
        except:
            pass
        
        await message.answer(f"✅ Пользователь <code>{user_id}</code> разблокирован!", parse_mode="HTML")
    else:
        await message.answer(f"❌ Пользователь <code>{user_id}</code> не находится в бане.", parse_mode="HTML")
    
    await state.clear()

# =========================
# ПОЛЬЗОВАТЕЛИ (ВЫГРУЗКА ФАЙЛА)
# =========================

@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    if not users_db:
        await callback.message.answer("📭 Нет пользователей в базе")
        return

    file_content = "ID пользователя\n"
    file_content += "="*50 + "\n"
    for user_id in sorted(users_db):
        status = "⛔" if user_id in banned_users else "✅"
        file_content += f"{status} {user_id}\n"
    
    file_path = f"users_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"Всего пользователей: {len(users_db)}\n")
        f.write(f"Заблокировано: {len(banned_users)}\n")
        f.write("="*50 + "\n\n")
        f.write(file_content)
    
    await callback.message.answer_document(document=FSInputFile(file_path), caption=f"📊 База пользователей\n\n👥 Всего: {len(users_db)}\n⛔ Заблокировано: {len(banned_users)}")
    os.remove(file_path)

# =========================
# НАСТРОЙКА ФОТО ДЛЯ /START
# =========================

@router.callback_query(F.data == "admin_start_photo")
async def admin_start_photo_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Удалить фото", callback_data="admin_remove_photo")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    
    current_photo = load_start_photo()
    
    text = f"📸 <b>Настройка фото для /start</b>\n\nОтправьте фото в этот чат, чтобы оно отображалось при команде /start у всех пользователей.\n\n{'✅ Фото установлено' if current_photo else '❌ Фото не установлено'}"
    
    await callback.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(AdminStates.waiting_for_start_photo)

@router.message(F.photo, StateFilter(AdminStates.waiting_for_start_photo))
async def save_start_photo_handler(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    photo = message.photo[-1]
    save_start_photo(photo.file_id)
    await message.answer("✅ Фото для команды /start сохранено!")
    await state.clear()

@router.callback_query(F.data == "admin_remove_photo")
async def remove_start_photo(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    if os.path.exists(START_PHOTO_FILE):
        os.remove(START_PHOTO_FILE)
    
    await callback.message.answer("❌ Фото для /start удалено")
    await callback.message.delete()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await state.clear()
    await admin_panel(callback.message)

# =========================
# РАССЫЛКА
# =========================

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer("📢 Введите текст рассылки:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(StateFilter(AdminStates.waiting_for_broadcast))
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    sent = 0
    failed = 0
    skipped_banned = 0
    status_msg = await message.answer("⏳ Начинаю рассылку...")

    for user_id in users_db:
        if user_id in banned_users:
            skipped_banned += 1
            continue
            
        try:
            await message.bot.send_message(user_id, f"{message.text}", parse_mode="HTML")
            sent += 1
        except:
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.delete()
    await message.answer(
        f"✅ Рассылка завершена\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Не доставлено: {failed}\n"
        f"⛔ Пропущено (бан): {skipped_banned}"
    )
    await state.clear()

# =========================
# MAIN
# =========================

async def main():
    load_users()
    load_subscriptions()
    load_auto_notify()
    load_banned_users()
    load_schedule_hash()
    
    logging.info(f"Загружено пользователей: {len(users_db)}")
    logging.info(f"Загружено подписок: {sum(len(v) for v in subscriptions.values())}")
    logging.info(f"Автоуведомлений: {sum(len(v) for v in auto_notify_users.values())}")
    logging.info(f"Заблокировано: {len(banned_users)}")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    load_schedule_from_yandex(PUBLIC_LINK)
    asyncio.create_task(auto_update_schedule(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
