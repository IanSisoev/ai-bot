import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import agent
import storage
from config import ADMIN_CHAT_ID

logger = logging.getLogger(__name__)
router = Router()

CONFIRM_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="Подтвердить", callback_data="confirm"),
    InlineKeyboardButton(text="Не надо", callback_data="reject"),
]])
ADMIN_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="Позвать администратора", callback_data="handoff"),
]])


@router.message(CommandStart())
async def start(message: Message):
    storage.clear_history(message.chat.id)
    storage.pop_pending(message.from_user.id)
    storage.pop_handoff_question(message.from_user.id)
    await message.answer("Привет! Я ИИ-администратор вейк-парка. Спросите про цены и правила или запишитесь на реверс.")


@router.message(Command("id"))
async def chat_id(message: Message):
    await message.answer(f"id этого чата: {message.chat.id}")


@router.message(F.chat.id == ADMIN_CHAT_ID, F.reply_to_message)
async def admin_reply(message: Message, bot: Bot):
    if message.text is None:
        return
    thread = storage.get_admin_thread(message.reply_to_message.message_id)
    if thread is None:
        await message.reply("Не нашёл, какому клиенту это отправить.")
        return
    client_chat_id, question = thread
    text = f"Ответ администратора: {message.text}"
    await bot.send_message(client_chat_id, text)
    storage.remember(client_chat_id, question, text)
    await message.reply("Отправил клиенту.")


@router.message(F.chat.type == "private")
async def answer(message: Message):
    if message.text is None:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return

    user = message.from_user
    storage.pop_pending(user.id)
    storage.pop_handoff_question(user.id)

    try:
        reply = await agent.answer_client(message.text, user, message.chat.id)
    except Exception:
        logger.exception("Ошибка при обращении к GigaChat")
        await message.answer("Не получилось ответить, попробуйте через минуту.")
        return

    keyboard = None
    if agent.HANDOFF_MARK in reply:
        if ADMIN_CHAT_ID:
            storage.set_handoff_question(user.id, message.text)
            keyboard = ADMIN_KEYBOARD
        else:
            reply = "У меня нет такой информации, уточните её, пожалуйста, у администратора парка."
    elif storage.get_pending(user.id):
        keyboard = CONFIRM_KEYBOARD

    storage.remember(message.chat.id, message.text, reply)
    await message.answer(reply, reply_markup=keyboard)


@router.callback_query(F.data == "confirm")
async def confirm(callback: CallbackQuery):
    pending = storage.pop_pending(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    if pending is None:
        await callback.answer("Это действие уже неактуально")
        return
    name, action = pending
    text = agent.execute(name, action, callback.from_user)
    storage.remember(callback.message.chat.id, "Подтверждаю", text)
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "reject")
async def reject(callback: CallbackQuery):
    storage.pop_pending(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    text = "Хорошо, ничего не меняю."
    storage.remember(callback.message.chat.id, "Не надо", text)
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "handoff")
async def handoff(callback: CallbackQuery, bot: Bot):
    await callback.message.edit_reply_markup(reply_markup=None)
    question = storage.pop_handoff_question(callback.from_user.id)
    if question is None:
        await callback.answer("Это действие уже неактуально")
        return
    user = callback.from_user
    try:
        sent = await bot.send_message(
            ADMIN_CHAT_ID,
            f"Вопрос от клиента {user.full_name}:\n\n{question}\n\n"
            "Ответьте на это сообщение, и бот перешлёт ответ клиенту.",
        )
    except TelegramAPIError:
        logger.exception("Не получилось отправить вопрос администратору")
        await callback.message.answer("Не получилось связаться с администратором, попробуйте позже.")
        await callback.answer()
        return
    storage.save_admin_thread(sent.message_id, callback.message.chat.id, question)
    await callback.message.answer("Передал ваш вопрос администратору. Он ответит прямо в этом чате.")
    await callback.answer()
