import io
import re
import asyncio
import logging
import datetime
import requests
import pandas as pd

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
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

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# =========================
# ЗАГРУЗКА РАСПИСАНИЯ
# =========================

def load_schedule_from_yandex(public_link):

    global lessons_db

    db_builder = []

    meta_url = (
        f"https://cloud-api.yandex.net/v1/disk/public/resources"
        f"?public_key={public_link}"
    )

    try:

        response = requests.get(meta_url)

        if response.status_code != 200:
            return

        items = response.json().get("_embedded", {}).get("items", [])

        for item in items:

            if (
                item.get("type") == "file"
                and item.get("name", "").endswith(".xls")
            ):

                file_path = item["path"]

                download_api_url = (
                    f"https://cloud-api.yandex.net/v1/disk/public/resources/download"
                    f"?public_key={public_link}&path={file_path}"
                )

                download_meta = requests.get(download_api_url).json()

                direct_url = download_meta.get("href")

                if not direct_url:
                    continue

                file_bytes = requests.get(direct_url).content

                excel_buffer = io.BytesIO(file_bytes)

                sheets = pd.read_excel(
                    excel_buffer,
                    sheet_name=None,
                    header=None,
                    engine="xlrd"
                )

                for _, df in sheets.items():

                    df = df.fillna("")
                    rows = df.values.tolist()

                    header_row = None

                    for r in rows:

                        if (
                            r
                            and len(r) > 0
                            and "День недели" in str(r[0])
                        ):
                            header_row = r
                            break

                    if not header_row and rows:
                        header_row = rows[0]

                    current_day = ""

                    for row in rows:

                        if not row or len(row) < 3:
                            continue

                        if (
                            str(row[0]).strip()
                            and "День недели" not in str(row[0])
                        ):
                            current_day = str(row[0]).strip()

                        lesson_num = str(row[1]).strip()
                        lesson_time = str(row[2]).strip()

                        if (
                            not lesson_num
                            or not lesson_time
                            or "№" in lesson_num
                        ):
                            continue

                        for col_idx in range(3, len(row), 3):

                            if col_idx + 2 >= len(row):
                                break

                            group_name = (
                                str(header_row[col_idx]).strip()
                                if col_idx < len(header_row)
                                else ""
                            )

                            if (
                                not group_name
                                or "Фамилия" in group_name
                                or "Каб" in group_name
                            ):
                                continue

                            subject = str(row[col_idx]).strip()
                            teacher = str(row[col_idx + 1]).strip()
                            room = str(row[col_idx + 2]).strip()

                            if (
                                subject
                                and subject.lower() != "сессия"
                                and subject.lower() != "гия"
                            ):

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

    except Exception as e:
        logging.error(e)

# =========================
# ВСПОМОГАТЕЛЬНЫЕ
# =========================

def get_unique_items(search_type):

    if search_type == "group":

        return sorted(list(set(
            l["group"] for l in lessons_db
            if l["group"] and l["group"].strip() not in ["", "."]
        )))

    elif search_type == "teacher":

        return sorted(list(set(
            l["teacher"] for l in lessons_db
            if l["teacher"] and l["teacher"].strip() not in ["", "."]
        )))

    elif search_type == "room":

        return sorted(list(set(
            l["room"] for l in lessons_db
            if l["room"] and l["room"].strip() not in ["", "."]
        )))

    return []


def get_unique_days():

    def get_date_key(day_str):

        match = re.search(r'\d{2}\.\d{2}\.\d{2}', day_str)

        if match:

            try:
                return datetime.datetime.strptime(
                    match.group(0),
                    "%d.%m.%y"
                )
            except:
                pass

        return datetime.datetime.min

    return sorted(
        list(set(
            l["day_str"] for l in lessons_db
            if l["day_str"]
        )),
        key=get_date_key
    )


def parse_day_string(day_str):

    match = re.search(r'([А-я]+)\s+(\d{2}\.\d{2}\.\d{2})', day_str)

    if match:

        day_of_week = match.group(1)
        full_date = match.group(2)

        short_date = full_date[:-3]

        return short_date, day_of_week

    return "", ""

# =========================
# ROUTER
# =========================

router = Router()

# =========================
# START
# =========================

@router.message(Command("start"))
async def cmd_start(message: Message):

    users_db.add(message.from_user.id)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📅 Расписание",
        callback_data="open_schedule"
    )

    builder.button(
        text="⭐ Подписки",
        callback_data="open_subscriptions"
    )

    builder.button(
        text="➕ Подписаться",
        callback_data="open_subscribe"
    )

    builder.button(
        text="➖ Отписаться",
        callback_data="open_unsubscribe"
    )

    builder.button(
        text="ℹ️ Помощь",
        callback_data="open_help"
    )

    builder.button(
        text="🛠 Поддержка",
        url="https://t.me/DevMenter"
    )

    builder.adjust(1)

    text = (
        "╔════════════════╗\n"
        " 🎓 <b>БОТ РАСПИСАНИЯ</b>\n"
        "╚════════════════╝\n\n"

        "📚 Просмотр расписания\n"
        "⭐ Удобные подписки\n"
        "⚡ Быстрый доступ\n"
        "🕒 Автообновление\n\n"

        "━━━━━━━━━━━━━━\n"
        "📌 <b>Команды:</b>\n\n"

        "📅 /schedule — расписание\n"
        "⭐ /subscriptions — подписки\n"
        "➕ /subscribe — подписаться\n"
        "➖ /unsubscribe — отписаться\n"
        "ℹ️ /help — помощь\n"
        "🛠 /admin — админ панель\n\n"

        "━━━━━━━━━━━━━━\n"
        "💡 Выберите действие:"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

# =========================
# HELP
# =========================

@router.message(Command("help"))
@router.callback_query(F.data == "open_help")
async def cmd_help(event):

    text = (
        "ℹ️ <b>Помощь</b>\n\n"

        "📅 /schedule — расписание\n"
        "⭐ /subscriptions — подписки\n"
        "➕ /subscribe — подписаться\n"
        "➖ /unsubscribe — отписаться\n\n"

        "🛠 Поддержка:\n"
        "@DevMenter"
    )

    if isinstance(event, Message):

        await event.answer(
            text,
            parse_mode="HTML"
        )

    else:

        await event.message.delete()

        await event.message.answer(
            text,
            parse_mode="HTML"
        )

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

    text = (
        "📅 <b>Просмотр расписания</b>\n\n"
        "Выберите тип:"
    )

    if isinstance(event, Message):

        await event.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

    else:

        await event.message.delete()

        await event.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

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

    text = (
        "⭐ <b>Создание подписки</b>\n\n"
        "Выберите тип:"
    )

    if isinstance(event, Message):

        await event.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

    else:

        await event.message.delete()

        await event.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

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

        builder.button(
            text=item,
            callback_data=f"subscription:{idx}"
        )

    builder.adjust(1)

    text = (
        "⭐ <b>Ваши подписки</b>\n\n"
        "Выберите:"
    )

    if isinstance(event, Message):

        await event.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

    else:

        await event.message.delete()

        await event.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

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

        builder.button(
            text=f"❌ {item}",
            callback_data=f"unsubscribe:{idx}"
        )

    builder.adjust(1)

    text = (
        "➖ <b>Удаление подписки</b>\n\n"
        "Выберите подписку:"
    )

    if isinstance(event, Message):

        await event.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

    else:

        await event.message.delete()

        await event.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

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

    await callback.message.delete()

    await callback.message.answer(
        f"✅ Подписка удалена\n\n<b>{deleted_sub[1]}</b>",
        parse_mode="HTML"
    )

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

        builder.button(
            text=str(item),
            callback_data=f"item:{idx}"
        )

    builder.adjust(2)

    await callback.message.delete()

    await callback.message.answer(
        "🔎 <b>Выберите значение</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

    await state.set_state(ScheduleStates.waiting_for_item)

# =========================
# ВЫБОР ЭЛЕМЕНТА
# =========================

@router.callback_query(
    ScheduleStates.waiting_for_item,
    F.data.startswith("item:")
)
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

    tomorrow = (
        datetime.date.today() + datetime.timedelta(days=1)
    ).strftime("%d.%m")

    for idx, day in enumerate(days):

        short_date, day_of_week = parse_day_string(day)

        btn_text = f"{day_of_week} {short_date}"

        if short_date == today:
            btn_text += " • сегодня"

        elif short_date == tomorrow:
            btn_text += " • завтра"

        builder.button(
            text=btn_text,
            callback_data=f"date:{idx}"
        )

    builder.adjust(2)

    await callback.message.delete()

    await callback.message.answer(
        "📅 <b>Выберите дату</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

    await state.set_state(ScheduleStates.waiting_for_date)

# =========================
# ПОКАЗ РАСПИСАНИЯ
# =========================

@router.callback_query(
    ScheduleStates.waiting_for_date,
    F.data.startswith("date:")
)
async def process_date(callback: CallbackQuery, state: FSMContext):

    date_idx = int(callback.data.split(":")[1])

    data = await state.get_data()

    search_type = data["search_type"]
    chosen_item = data["chosen_item"]

    days = get_unique_days()

    chosen_day_str = days[date_idx]

    filtered = []

    for l in lessons_db:

        if l["day_str"] != chosen_day_str:
            continue

        if search_type == "group" and l["group"] == chosen_item:
            filtered.append(l)

        elif search_type == "teacher" and l["teacher"] == chosen_item:
            filtered.append(l)

        elif search_type == "room" and l["room"] == chosen_item:
            filtered.append(l)

    short_date, day_of_week = parse_day_string(chosen_day_str)

    text = (
        f"📚 <b>Расписание</b>\n\n"
        f"📅 {day_of_week} • {short_date}\n"
        f"🔎 {chosen_item}\n\n"
    )

    if not filtered:

        text += "😴 Занятий не найдено."

    else:

        for l in filtered:

            text += (
                f"━━━━━━━━━━━━━━\n"
                f"⏰ {l['lesson_num']} • {l['time']}\n"
                f"📘 {l['subject']}\n"
                f"👨‍🏫 {l['teacher']}\n"
                f"🚪 {l['room']}\n\n"
            )

    await callback.message.delete()

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await state.clear()

# =========================
# СОЗДАНИЕ ПОДПИСКИ
# =========================

@router.callback_query(
    SubscribeStates.waiting_for_type,
    F.data.startswith("sub_type:")
)
async def process_sub_type(callback: CallbackQuery, state: FSMContext):

    search_type = callback.data.split(":")[1]

    await state.update_data(search_type=search_type)

    items = get_unique_items(search_type)

    builder = InlineKeyboardBuilder()

    for idx, item in enumerate(items):

        builder.button(
            text=str(item),
            callback_data=f"sub_item:{idx}"
        )

    builder.adjust(2)

    await callback.message.delete()

    await callback.message.answer(
        "⭐ <b>Выберите объект подписки</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

    await state.set_state(SubscribeStates.waiting_for_item)

# =========================
# СОХРАНЕНИЕ ПОДПИСКИ
# =========================

@router.callback_query(
    SubscribeStates.waiting_for_item,
    F.data.startswith("sub_item:")
)
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

        subscriptions[user_id].append(
            (search_type, chosen_item)
        )

    await callback.message.delete()

    await callback.message.answer(
        f"⭐ Подписка сохранена\n\n<b>{chosen_item}</b>",
        parse_mode="HTML"
    )

    await state.clear()

# =========================
# ОТКРЫТЬ ПОДПИСКУ
# =========================

@router.callback_query(F.data.startswith("subscription:"))
async def open_subscription(callback: CallbackQuery):

    idx = int(callback.data.split(":")[1])

    user_id = callback.from_user.id

    user_subs = subscriptions.get(user_id, [])

    if idx >= len(user_subs):
        return

    search_type, chosen_item = user_subs[idx]

    today = datetime.date.today().strftime("%d.%m")

    found_day = None

    for day in get_unique_days():

        short_date, _ = parse_day_string(day)

        if short_date == today:
            found_day = day
            break

    if not found_day:

        await callback.answer("Расписание не найдено")
        return

    filtered = []

    for l in lessons_db:

        if l["day_str"] != found_day:
            continue

        if search_type == "group" and l["group"] == chosen_item:
            filtered.append(l)

        elif search_type == "teacher" and l["teacher"] == chosen_item:
            filtered.append(l)

        elif search_type == "room" and l["room"] == chosen_item:
            filtered.append(l)

    short_date, day_of_week = parse_day_string(found_day)

    text = (
        f"📚 <b>{chosen_item}</b>\n\n"
        f"📅 {day_of_week} • {short_date}\n\n"
    )

    if not filtered:

        text += "😴 Занятий нет."

    else:

        for l in filtered:

            text += (
                f"━━━━━━━━━━━━━━\n"
                f"⏰ {l['lesson_num']} • {l['time']}\n"
                f"📘 {l['subject']}\n"
                f"👨‍🏫 {l['teacher']}\n"
                f"🚪 {l['room']}\n\n"
            )

    await callback.message.delete()

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

# =========================
# АДМИН ПАНЕЛЬ
# =========================

@router.message(Command("admin"))
async def admin_panel(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📢 Рассылка",
        callback_data="admin_broadcast"
    )

    builder.button(
        text="📊 Статистика",
        callback_data="admin_stats"
    )

    builder.adjust(1)

    await message.answer(
        "🛠 <b>Админ панель</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

# =========================
# СТАТИСТИКА
# =========================

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{len(users_db)}</b>\n"
        f"⭐ Подписок: <b>{sum(len(v) for v in subscriptions.values())}</b>\n"
        f"📚 Занятий: <b>{len(lessons_db)}</b>"
    )

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

# =========================
# РАССЫЛКА
# =========================

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):

    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer(
        "📢 Введите текст рассылки:"
    )

    await state.set_state(AdminStates.waiting_for_broadcast)

# =========================
# ОТПРАВКА РАССЫЛКИ
# =========================

@router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):

    if message.from_user.id != ADMIN_ID:
        return

    sent = 0

    for user_id in users_db:

        try:

            await message.bot.send_message(
                user_id,
                (
                    "📢 <b>Сообщение от администрации</b>\n\n"
                    f"{message.text}"
                ),
                parse_mode="HTML"
            )

            sent += 1

        except:
            pass

    await message.answer(
        f"✅ Рассылка завершена\n\nОтправлено: {sent}"
    )

    await state.clear()

# =========================
# АВТООБНОВЛЕНИЕ
# =========================

async def scheduler_loop():

    while True:

        now = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=3)
        )

        target = now.replace(
            hour=2,
            minute=0,
            second=0,
            microsecond=0
        )

        if now >= target:
            target += datetime.timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()

        await asyncio.sleep(sleep_seconds)

        load_schedule_from_yandex(PUBLIC_LINK)

# =========================
# MAIN
# =========================

async def main():

    bot = Bot(token=BOT_TOKEN)

    dp = Dispatcher()

    dp.include_router(router)

    load_schedule_from_yandex(PUBLIC_LINK)

    asyncio.create_task(scheduler_loop())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
