from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.config import settings
from app.database.session import SessionLocal
from app.services.users import get_or_create_user

router = Router()
router.message.filter(F.chat.type == "private")

WELCOME = (
    "Привет! Это сервис автоматической отправки сообщений.\n"
    "Всё настраивается в приложении: нажми кнопку ниже."
)
HELP = (
    "<b>Как это работает</b>\n"
    "1. Открой приложение кнопкой в меню.\n"
    "2. Подключи свой аккаунт и создай рассылку.\n"
    "3. Бот будет присылать уведомления о ходе работы.\n\n"
    "Сервис отправляет сообщения только туда, куда у тебя есть право писать."
)


def main_menu() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.webapp_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Открыть приложение",
                    web_app=WebAppInfo(url=settings.webapp_url),
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Помощь", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    async with SessionLocal() as session:
        await get_or_create_user(
            session, message.from_user.id, message.from_user.language_code
        )
    text = WELCOME
    if not settings.webapp_url:
        text += "\n\nПриложение пока не подключено (не задан WEBAPP_URL)."
    await message.answer(text, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu())


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery) -> None:
    await call.answer()
    if call.message is not None:
        await call.message.answer(HELP, reply_markup=main_menu())
