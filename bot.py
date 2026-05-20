import io
import re
import asyncio
import logging
import datetime
import requests
import pandas as pd

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = "8626762224:AAGdtJiY0A3yTOCh7RWrOuNKI4M9iYLVNFQ"
PUBLIC_LINK = "https://disk.360.yandex.ru/d/Xc08g8WbTavdHQ"

logging.basicConfig(level=logging.INFO)

lessons_db = []

class ScheduleStates(StatesGroup):
    waiting_for_type = State()
    waiting_for_item = State()
    waiting_for_date = State()

def load_schedule_from_yandex(public_link):
    global lessons_db
    db_builder = []
    meta_url = f"https://cloud-api.yandex.net/v1/disk/public/resources?public_key={public_link}"
    try:
        response = requests.get(meta_url)
        if response.status_code != 200:
            return
        items = response.json().get("_embedded", {}).get("items", [])
        for item in items:
            if item.get("type") == "file" and item.get("name", "").endswith(".xls"):
                filename = item["name"]
                file_path = item["path"]
                download_api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={public_link}&path={file_path}"
                download_meta = requests.get(download_api_url).json()
                direct_url = download_meta.get("href")
                if not direct_url:
                    continue
                file_bytes = requests.get(direct_url).content
                excel_buffer = io.BytesIO(file_bytes)
                sheets = pd.read_excel(excel_buffer, sheet_name=None, header=None, engine="xlrd")
                for sheet_name, df in sheets.items():
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
                            teacher = str(row[col_idx+1]).strip()
                            room = str(row[col_idx+2]).strip()
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
    except Exception as e:
        pass

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
            except ValueError:
                pass
        return datetime.datetime.min
    return sorted(list(set(l["day_str"] for l in lessons_db if l["day_str"])), key=get_date_key)

def parse_day_string(day_str):
    match = re.search(r'([А-я]+)\s+(\d{2}\.\d{2}\.\d{2})', day_str)
    if match:
        day_of_week = match.group(1)
        full_date = match.group(2)
        short_date = full_date[:-3]
        wd_map = {
            "Понедельник": "Пн", "Вторник": "Вт", "Среда": "Ср",
            "Четверг": "Чт", "Пятница": "Пт", "Пянтица": "Пт", "Суббота": "Сб", "Воскресенье": "Вс"
        }
        return wd_map.get(day_of_week, day_of_week[:2]), short_date, day_of_week
    return "", "", ""

router = Router()

@router.message(Command("schedule"))
async def cmd_schedule(message: Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="группа", callback_data="type:group")
    builder.button(text="преподаватель", callback_data="type:teacher")
    builder.button(text="кабинет", callback_data="type:room")
    builder.adjust(1)
    await message.answer("Выберете что искать", reply_markup=builder.as_markup())
    await state.set_state(ScheduleStates.waiting_for_type)

@router.callback_query(ScheduleStates.waiting_for_type, F.data.startswith("type:"))
async def process_type(callback: CallbackQuery, state: FSMContext):
    search_type = callback.data.split(":")[1]
    await state.update_data(search_type=search_type)
    items = get_unique_items(search_type)
    builder = InlineKeyboardBuilder()
    for idx, item in enumerate(items):
        builder.button(text=str(item), callback_data=f"item:{idx}")
    columns = 2 if search_type == "teacher" else 3
    builder.adjust(columns)
    type_labels = {"group": "группу", "teacher": "преподавателя", "room": "кабинет"}
    await callback.message.edit_text(f"Выберите {type_labels[search_type]}:", reply_markup=builder.as_markup())
    await state.set_state(ScheduleStates.waiting_for_item)
    await callback.answer()

@router.callback_query(ScheduleStates.waiting_for_item, F.data.startswith("item:"))
async def process_item(callback: CallbackQuery, state: FSMContext):
    item_idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_type = data["search_type"]
    items = get_unique_items(search_type)
    chosen_item = items[item_idx]
    await state.update_data(chosen_item=chosen_item)
    days = get_unique_days()
    builder = InlineKeyboardBuilder()
    today_str = datetime.date.today().strftime("%d.%m")
    tomorrow_str = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d.%m")
    for idx, day in enumerate(days):
        short_wd, short_date, _ = parse_day_string(day)
        if not short_date:
            continue
        btn_text = f"{short_wd} {short_date}"
        if short_date == today_str:
            btn_text += " (сегодня)"
        elif short_date == tomorrow_str:
            btn_text += " (завтра)"
        builder.button(text=btn_text, callback_data=f"date:{idx}")
    builder.adjust(2)
    await callback.message.edit_text("выберите дату", reply_markup=builder.as_markup())
    await state.set_state(ScheduleStates.waiting_for_date)
    await callback.answer()

@router.callback_query(ScheduleStates.waiting_for_date, F.data.startswith("date:"))
async def process_date(callback: CallbackQuery, state: FSMContext):
    date_idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_type = data["search_type"]
    chosen_item = data["chosen_item"]
    days = get_unique_days()
    chosen_day_str = days[date_idx]
    day_lessons = [l for l in lessons_db if l["day_str"] == chosen_day_str]
    filtered = []
    for l in day_lessons:
        if search_type == "group" and chosen_item == l["group"]:
            filtered.append(l)
        elif search_type == "teacher" and chosen_item == l["teacher"]:
            filtered.append(l)
        elif search_type == "room" and chosen_item == l["room"]:
            filtered.append(l)
    filtered = sorted(filtered, key=lambda x: float(x["lesson_num"]) if x["lesson_num"].replace('.','',1).isdigit() else 0)
    _, short_date, day_of_week = parse_day_string(chosen_day_str)
    type_headers = {"group": "группы", "teacher": "преподавателя", "room": "кабинета"}
    response_text = f"Расписание на {short_date} {day_of_week.lower()} для {type_headers[search_type]} \"{chosen_item}\"\n\n"
    if not filtered:
        response_text += "Занятий не найдено."
    else:
        for l in filtered:
            try:
                num = str(int(float(l["lesson_num"])))
            except ValueError:
                num = l["lesson_num"]
            t_val = l["teacher"] if l["teacher"] and l["teacher"].strip() != "." else "Не указан"
            r_val = l["room"] if l["room"] and l["room"].strip() != "." else "Не указан"
            response_text += f"{num}. {l['time']}\n"
            response_text += f"предмет: {l['subject']}\n"
            response_text += f"преподаватель: {t_val}\n"
            response_text += f"кабинет: {r_val}\n\n"
    await callback.message.edit_text(response_text, reply_markup=None)
    await state.clear()
    await callback.answer()

async def scheduler_loop():
    while True:
        now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
        target = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now >= target:
            target += datetime.timedelta(days=1)
        sleep_seconds = (target - now).total_seconds()
        await asyncio.sleep(sleep_seconds)
        load_schedule_from_yandex(PUBLIC_LINK)

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    load_schedule_from_yandex(PUBLIC_LINK)
    asyncio.create_task(scheduler_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
