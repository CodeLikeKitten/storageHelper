import os
import logging
from typing import Optional, Dict
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Локальные модули
from database import StorageDB

# --- Инициализация окружения ---
load_dotenv()

# --- Инициализация базы данных ---
db = StorageDB()

# --- Настройка бота ---
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# --- Состояния FSM ---
class NewItemStates(StatesGroup):
    CHOOSE_TYPE = State()
    INPUT_EQUIPMENT = State()
    INPUT_COMPONENT = State()

# --- Вспомогательные функции ---
def format_item_info(item_type: str, item: Dict) -> str:
    """Форматирование информации о позиции"""
    base = (
        f"Тип: {item_type}\n"
        f"ID: {item['id']}\n"
        f"Название: {item['название']}\n"
        f"Количество: {item['количество']}"
    )
    
    if item_type == "Оборудование":
        return f"{base}\nТип оборудования: {item['тип']}"
    else:
        return (
            f"{base}\n"
            f"Размер:{item['размер']}\n"
            f"Тип компонента: {item['тип']}"
        )

def create_type_keyboard():
    """Клавиатура для выбора типа позиции"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🛠 Оборудование", callback_data="equipment")
    builder.button(text="🔩 Компонент", callback_data="component")
    builder.adjust(1)
    return builder.as_markup()

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🏭 Система управления складом\n\n"
        "Доступные команды:\n"
        "/search [ID или название] - Поиск позиции\n"
        "/add [тип] [ID] [кол-во] - Добавить количество\n"
        "/give [тип] [ID] [кол-во] - Взять количество\n"
        "/add_new - Добавить новую позицию\n"
        "/cancel - Отменить текущее действие"
    )

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🚫 Действие отменено")

@dp.message(Command("search"))
async def cmd_search(message: Message):
    args = message.text.split(maxsplit=2)
    print(args)
    if len(args) < 3:
        return await message.answer("❌ Укажите таблицу, название или ID для поиска")
    
    item_type = args[1].strip()
    search_term = args[2].strip()
    
    # Поиск по ID
    if search_term.isdigit():
        item_id = int(search_term)
        item = db.get_by_id(item_type, item_id)
        if not item:
            return await message.answer("🔎 Позиция не найдена")
            
        response = format_item_info(item['item_type'], item)
        db.log_action(
            user_id=message.from_user.id,
            action="SEARCH",
            item_type=item['item_type'],
            item_id=item_id
        )
        return await message.answer(response)
    
    # Поиск по названию
    results = db.search_by_name(search_term)
    if not results:
        return await message.answer("🔎 Ничего не найдено")
    
    response = ["🔍 Результаты поиска:"]
    for item in results:
        response.append(
            f"{item['item_type']} ID{item['id']}: "
            f"{item['название']} ({item['количество']} шт)"
        )
    
    db.log_action(
        user_id=message.from_user.id,
        action="SEARCH",
        item_type="ALL",
        item_id=0,
        details=f"Поиск: {search_term}"
    )
    await message.answer("\n".join(response))

@dp.message(Command("add", "give"))
async def cmd_modify(message: Message):
    try:
        command, item_type, item_id, qty = message.text.split()
        item_id = int(item_id)
        qty = int(qty)
        
        if command == "/give":
            qty = -abs(qty)

        if item_type not in ["Оборудование", "Компоненты"]:
            raise ValueError("Некорректный тип")
            
        if db.update_quantity(item_type, item_id, qty):
            item = db.get_by_id(item_type, item_id)
            response = (
                "✅ Успешно обновлено!\n"
                f"{format_item_info(item_type, item)}"
            )
            action = "ADD" if qty > 0 else "GIVE"
            db.log_action(
                user_id=message.from_user.id,
                action=action,
                item_type=item_type,
                item_id=item_id,
                details=f"Изменение на {qty}"
            )
        else:
            response = "❌ Ошибка обновления"
            
        await message.answer(response)
        
    except (ValueError, IndexError):
        await message.answer(
            "❌ Неверный формат команды\n"
            "Примеры:\n"
            "/add Оборудование 123 10\n"
            "/give Компоненты 456 5"
        )

@dp.message(Command("add_new"))
async def cmd_add_new(message: Message, state: FSMContext):
    await message.answer(
        "📝 Выберите тип новой позиции:",
        reply_markup=create_type_keyboard()
    )
    await state.set_state(NewItemStates.CHOOSE_TYPE)

# --- Обработчики FSM ---
@dp.callback_query(NewItemStates.CHOOSE_TYPE, F.data.in_(["equipment", "component"]))
async def process_type(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    item_type = "Оборудование" if callback.data == "equipment" else "Компоненты"
    
    await state.update_data(item_type=item_type)
    
    if item_type == "Оборудование":
        await callback.message.answer(
            "📝 Введите данные оборудования через вертикальную черту (|):\n"
            "Название | Тип | Количество\n\n"
            "Пример:\n"
            "Станок ЧПУ | Металлообработка | 5"
        )
        await state.set_state(NewItemStates.INPUT_EQUIPMENT)
    else:
        await callback.message.answer(
            "📝 Введите данные компонента через вертикальную черту (|):\n"
            "Название | Количество | Размер | Тип\n\n"
            "Пример:\n"
            "Болт М12 | 100 | 12x50 мм | Крепеж"
        )
        await state.set_state(NewItemStates.INPUT_COMPONENT)

@dp.message(NewItemStates.INPUT_EQUIPMENT)
async def process_equipment(message: Message, state: FSMContext):
    try:
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) != 3:
            raise ValueError("Неверное количество параметров")
            
        name, eq_type, qty = parts
        item_id = db.add_new_equipment(name, eq_type, int(qty))
        
        await message.answer(
            f"✅ Оборудование добавлено!\n"
            f"ID: {item_id}"
        )
        db.log_action(
            user_id=message.from_user.id,
            action="ADD_NEW",
            item_type="Оборудование",
            item_id=item_id
        )
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}\nПопробуйте снова")

@dp.message(NewItemStates.INPUT_COMPONENT)
async def process_component(message: Message, state: FSMContext):
    try:
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) != 4:
            raise ValueError("Неверное количество параметров")
            
        name, qty, size, comp_type = parts
        item_id = db.add_new_component(name, int(qty), size, comp_type)
        
        await message.answer(
            f"✅ Компонент добавлен!\n"
            f"ID: {item_id}"
        )
        db.log_action(
            user_id=message.from_user.id,
            action="ADD_NEW",
            item_type="Компоненты",
            item_id=item_id
        )
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}\nПопробуйте снова")

# --- Запуск приложения ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())