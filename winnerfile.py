import os
import sqlite3
import asyncio
import sqlite3
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Sozlamalarni config.py dan import qilish
from winner import API_TOKEN, ADMIN_ID, CHANNEL_LINK, DATABASE_NAME, MESSAGES

# Windows uchun event loop policy
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Bot va dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# --- STATES ---
class AddCategory(StatesGroup):
    waiting_for_name = State()

class AddItem(StatesGroup):
    waiting_for_category = State()
    waiting_for_photo = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_stock = State()

class PlaceOrder(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_phone = State()

# --- DATABASE ---
def get_db():
    db = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
    return db

def init_db():
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cat_id INTEGER,
        photo_id TEXT,
        price TEXT,
        stock TEXT,
        description TEXT
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        phone TEXT,
        order_details TEXT,
        total_amount TEXT,
        order_date TEXT,
        status TEXT DEFAULT 'Yangi'
    )""")
    
    db.commit()
    db.close()

# --- KEYBOARDS ---
def main_menu(user_id):
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="🛒 Katalog"))
    if user_id == ADMIN_ID:
        builder.row(types.KeyboardButton(text="⚙️ Admin Panel"))
    return builder.as_markup(resize_keyboard=True)

def admin_panel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Kategoriya qo'shish", callback_data="ask_add_cat")
    builder.button(text="➕ Tovar qo'shish", callback_data="ask_add_item")
    builder.button(text="🗑 Kategoriyani o'chirish", callback_data="del_cat_list")
    builder.button(text="📦 Tovarni o'chirish", callback_data="del_item_list")
    builder.button(text="🛒 Buyurtmalar ro'yxati", callback_data="view_orders_list")
    builder.adjust(1)
    return builder.as_markup()

# --- HANDLERS ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        MESSAGES["welcome"],
        reply_markup=main_menu(message.from_user.id)
    )

@router.message(F.text == "⚙️ Admin Panel")
async def admin_panel_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Sizda admin huquqi yo'q!")
        return
    
    await message.answer(
        "Admin Panel - Quyidagi amallarni bajarish mumkin:",
        reply_markup=admin_panel_kb()
    )

# KATEGORIYA QO'SHISH
@router.callback_query(F.data == "ask_add_cat")
async def ask_add_category(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Kategoriya nomini kiriting:")
    await state.set_state(AddCategory.waiting_for_name)
    await callback.answer()

@router.message(AddCategory.waiting_for_name)
async def process_category_name(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO categories (name) VALUES (?)", (message.text,))
    db.commit()
    db.close()
    
    await message.answer(
        f"✅ Kategoriya '{message.text}' qo'shildi!",
        reply_markup=main_menu(ADMIN_ID)
    )
    await state.clear()

# TOVAR QO'SHISH
@router.callback_query(F.data == "ask_add_item")
async def ask_add_item(callback: types.CallbackQuery):
    db = get_db()
    cursor = db.cursor()
    categories = cursor.execute("SELECT id, name FROM categories").fetchall()
    db.close()
    
    if not categories:
        await callback.message.answer("❌ Avval kategoriya qo'shing!")
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for cat_id, cat_name in categories:
        builder.button(text=cat_name, callback_data=f"additem_{cat_id}")
    builder.adjust(1)
    
    await callback.message.answer(
        "Qaysi kategoriyaga tovar qo'shasiz?",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("additem_"))
async def process_item_category(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[1])
    await state.update_data(cat_id=cat_id)
    await callback.message.answer("Tovar rasmini yuboring:")
    await state.set_state(AddItem.waiting_for_photo)
    await callback.answer()

@router.message(AddItem.waiting_for_photo, F.photo)
async def process_item_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("Tovar tavsifini kiriting:")
    await state.set_state(AddItem.waiting_for_description)

@router.message(AddItem.waiting_for_description)
async def process_item_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Tovar narxini kiriting (masalan: 50000):")
    await state.set_state(AddItem.waiting_for_price)

@router.message(AddItem.waiting_for_price)
async def process_item_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text)
    await message.answer("Omborda qancha dona bor?")
    await state.set_state(AddItem.waiting_for_stock)

@router.message(AddItem.waiting_for_stock)
async def process_item_stock(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO items (cat_id, photo_id, description, price, stock) VALUES (?, ?, ?, ?, ?)",
        (data['cat_id'], data['photo_id'], data['description'], data['price'], message.text)
    )
    db.commit()
    db.close()
    
    await message.answer("✅ Tovar qo'shildi!", reply_markup=main_menu(ADMIN_ID))
    await state.clear()

# TOVARNI O'CHIRISH
@router.callback_query(F.data == "del_item_list")
async def delete_item_list(callback: types.CallbackQuery):
    db = get_db()
    cursor = db.cursor()
    items = cursor.execute("SELECT id, description FROM items").fetchall()
    db.close()
    
    if not items:
        await callback.message.answer("❌ Tovarlar yo'q!")
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for item_id, description in items:
        builder.button(text=f"🗑 {description[:30]}", callback_data=f"delitem_{item_id}")
    builder.adjust(1)
    
    await callback.message.answer(
        "O'chirish uchun tovanni tanlang:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# KATEGORIYANI O'CHIRISH
@router.callback_query(F.data == "del_cat_list")
async def delete_category_list(callback: types.CallbackQuery):
    db = get_db()
    cursor = db.cursor()
    categories = cursor.execute("SELECT id, name FROM categories").fetchall()
    db.close()
    
    if not categories:
        await callback.message.answer("❌ Kategoriyalar yo'q!")
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for cat_id, cat_name in categories:
        builder.button(text=f"🗑 {cat_name}", callback_data=f"delcat_{cat_id}")
    builder.adjust(1)
    
    await callback.message.answer(
        "⚠️ O'chirish uchun kategoriyani tanlang.\nKategoriya bilan birga uning ichidagi barcha tovarlar ham o'chiriladi!",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("delcat_"))
async def delete_category_confirm(callback: types.CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    
    db = get_db()
    cursor = db.cursor()
    
    # Kategoriya ichidagi tovarlarni o'chirish
    cursor.execute("DELETE FROM items WHERE cat_id = ?", (cat_id,))
    
    # Kategoriyani o'chirish
    cursor.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    
    db.commit()
    db.close()
    
    await callback.message.edit_text("✅ Kategoriya va uning ichidagi barcha tovarlar o'chirildi!")
    await callback.answer()


@router.callback_query(F.data.startswith("delitem_"))
async def delete_item_confirm(callback: types.CallbackQuery):
    item_id = int(callback.data.split("_")[1])
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()
    db.close()
    
    await callback.message.edit_text("✅ Tovar o'chirildi!")
    await callback.answer()

# BUYURTMALAR
@router.callback_query(F.data == "view_orders_list")
async def view_orders(callback: types.CallbackQuery):
    db = get_db()
    cursor = db.cursor()
    orders = cursor.execute(
        "SELECT id, user_id, username, full_name, phone, order_details, total_amount, order_date, status FROM orders ORDER BY id DESC"
    ).fetchall()
    db.close()
    
    if not orders:
        await callback.message.answer("❌ Buyurtmalar yo'q!")
        await callback.answer()
        return
    
    text = "📋 *Buyurtmalar ro'yxati:*\n\n"
    for order_id, user_id, username, full_name, phone, details, amount, order_date, status in orders:
        text += f"🆔 Buyurtma #{order_id}\n"
        text += f"📅 Sana: {order_date}\n"
        
        # Ism-familiya va telefon
        if full_name:
            text += f"👤 Ism: {full_name}\n"
        if phone:
            text += f"📱 Telefon: {phone}\n"
        
        # Username yoki ID
        if username and username != "NoUsername":
            text += f"💬 Username: @{username}\n"
        else:
            text += f"🔢 User ID: `{user_id}`\n"
        
        text += f"📦 Mahsulotlar:\n{details}"
        text += f"💰 Jami: {amount} so'm\n"
        text += f"📊 Status: {status}\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

# KATALOG
@router.message(F.text == "🛒 Katalog")
async def show_catalog(message: types.Message):
    db = get_db()
    cursor = db.cursor()
    categories = cursor.execute("SELECT id, name FROM categories").fetchall()
    db.close()
    
    if not categories:
        await message.answer("❌ Mahsulotlar yo'q!")
        return
    
    builder = InlineKeyboardBuilder()
    for cat_id, cat_name in categories:
        builder.button(text=cat_name, callback_data=f"cat_{cat_id}")
    builder.adjust(1)
    
    await message.answer(
        "Kategoriyani tanlang:",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("cat_"))
async def show_category_items(callback: types.CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    
    db = get_db()
    cursor = db.cursor()
    items = cursor.execute(
        "SELECT id, photo_id, description, price, stock FROM items WHERE cat_id = ?",
        (cat_id,)
    ).fetchall()
    db.close()
    
    if not items:
        await callback.message.answer("❌ Bu kategoriyada tovar yo'q!")
        await callback.answer()
        return
    
    for item_id, photo_id, description, price, stock in items:
        builder = InlineKeyboardBuilder()
        builder.button(text="🛒 Savatga", callback_data=f"addcart_{item_id}")
        
        caption = f"📦 {description}\n💰 {price} so'm\n📊 {stock} dona"
        
        if photo_id:
            await callback.message.answer_photo(
                photo=photo_id,
                caption=caption,
                reply_markup=builder.as_markup()
            )
        else:
            await callback.message.answer(caption, reply_markup=builder.as_markup())
    
    await callback.answer()

# SAVAT
user_carts = {}

@router.callback_query(F.data.startswith("addcart_"))
async def add_to_cart(callback: types.CallbackQuery):
    item_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    if user_id not in user_carts:
        user_carts[user_id] = []
    
    user_carts[user_id].append(item_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Buyurtma berish", callback_data="place_order")
    builder.button(text="🗑 Tozalash", callback_data="clear_cart")
    builder.adjust(1)
    
    await callback.answer("✅ Savatga qo'shildi!")
    await callback.message.answer(
        f"Savatda {len(user_carts[user_id])} ta mahsulot",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "place_order")
async def place_order(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if user_id not in user_carts or not user_carts[user_id]:
        await callback.answer("❌ Savat bo'sh!", show_alert=True)
        return
    
    # Savatdagi ma'lumotlarni saqlash
    await state.update_data(cart_items=user_carts[user_id].copy())
    
    await callback.message.answer(
        "📝 Buyurtmani rasmiylashtirish:\n\n"
        "Ism-familiyangizni kiriting:"
    )
    await state.set_state(PlaceOrder.waiting_for_full_name)
    await callback.answer()

@router.message(PlaceOrder.waiting_for_full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer(
        "📱 Telefon raqamingizni kiriting:\n"
        "(Masalan: +998901234567 yoki 901234567)"
    )
    await state.set_state(PlaceOrder.waiting_for_phone)

@router.message(PlaceOrder.waiting_for_phone)
async def process_phone_and_complete_order(message: types.Message, state: FSMContext):
    from datetime import datetime
    
    user_id = message.from_user.id
    data = await state.get_data()
    
    full_name = data.get('full_name')
    phone = message.text
    cart_items = data.get('cart_items', [])
    
    if not cart_items:
        await message.answer("❌ Xato: Savat bo'sh!")
        await state.clear()
        return
    
    order_details = ""
    total = 0
    
    db = get_db()
    cursor = db.cursor()
    
    for item_id in cart_items:
        item = cursor.execute(
            "SELECT description, price FROM items WHERE id = ?",
            (item_id,)
        ).fetchone()
        
        if item:
            description, price = item
            order_details += f"  • {description} - {price} so'm\n"
            try:
                total += int(price.replace(" ", "").replace("so'm", ""))
            except:
                pass
    
    # Hozirgi sana va vaqt
    order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute(
        "INSERT INTO orders (user_id, username, full_name, phone, order_details, total_amount, order_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id, 
            message.from_user.username or "NoUsername", 
            full_name,
            phone,
            order_details, 
            f"{total}",
            order_date,
            "Yangi"
        )
    )
    order_id = cursor.lastrowid
    db.commit()
    db.close()
    
    # Savatni tozalash
    user_carts[user_id] = []
    
    # Foydalanuvchiga tasdiq
    await message.answer(
        f"✅ Buyurtma #{order_id} qabul qilindi!\n\n"
        f"👤 Ism: {full_name}\n"
        f"📱 Telefon: {phone}\n\n"
        f"📦 Mahsulotlar:\n{order_details}\n"
        f"💰 Jami: {total} so'm\n\n"
        f"Tez orada siz bilan bog'lanamiz!",
        reply_markup=main_menu(user_id)
    )
    
    # Adminga xabar
    try:
        admin_text = (
            f"🔔 *Yangi buyurtma!*\n\n"
            f"🆔 Buyurtma #{order_id}\n"
            f"📅 Sana: {order_date}\n\n"
            f"👤 Mijoz: {full_name}\n"
            f"📱 Telefon: {phone}\n"
        )
        if message.from_user.username:
            admin_text += f"💬 Username: @{message.from_user.username}\n"
        admin_text += f"🔢 User ID: `{user_id}`\n\n"
        admin_text += f"📦 Mahsulotlar:\n{order_details}\n"
        admin_text += f"💰 Jami: {total} so'm"
        
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    except:
        pass
    
    await state.clear()

@router.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_carts[user_id] = []
    await callback.answer("🗑 Tozalandi!", show_alert=True)

# MAIN
async def main():
    init_db()
    dp.include_router(router)
    print("✅ Bot ishga tushdi...")
    print(f"👤 Admin ID: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n❌ Bot to'xtatildi")
    except Exception as e:
        print(f"❌ Xato: {e}")