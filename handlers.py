"""Handlers for the university resource collection flow."""
import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message, User

import keyboards
from config import (
    CHANNEL_ID,
    INCLUDE_UPLOADER,
    MAX_COURSE_NAME_LENGTH,
    MAX_FILES_PER_SESSION,
    SEND_DELAY_SECONDS,
    BOT_TOKEN,
)
from data import DEPARTMENTS_BY_TAG, FRESHMAN_TAG, TYPES_BY_CODE, years_for, SEMESTERS
from states import Upload

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")
_sending_users: set[int] = set()
_file_locks: dict[int, asyncio.Lock] = {}


def _file_lock(chat_id: int) -> asyncio.Lock:
    return _file_locks.setdefault(chat_id, asyncio.Lock())

WELCOME_TEXT = "Welcome! This bot collects university resources.\n\nChoose the department:"
CANCELLED_TEXT = "Cancelled. Send /start to begin again."
EXPIRED_TEXT = "This menu has expired. Send /start to begin again."
COURSE_PROMPT = "Type the course name (for example: Data Structures):"
UPLOAD_PROMPT = (
    "Send your file(s). Please send them as File (not compressed photos) to keep the quality.\n"
    "Tap Done when finished.\n\nFiles received: {count}"
)


def _course_prompt(data: dict) -> str:
    return (
        f"Department: {DEPARTMENTS_BY_TAG[data['dept_tag']]}\n"
        f"Year: {data['year']}\nSemester: {data['semester']}\n"
        f"Type: {TYPES_BY_CODE[data['type_code']][0]}\n\n{COURSE_PROMPT}"
    )


def build_caption(data: dict, user: User) -> str:
    type_tag = TYPES_BY_CODE[data["type_code"]][1]
    lines = [
        f"#{data['dept_tag']} #Y{data['year']} #S{data['semester']} #{type_tag}",
        f"Course: {data['course']}",
    ]
    if INCLUDE_UPLOADER:
        lines.append(f"From: @{user.username}" if user.username else f"From: {user.id}")
    caption = "\n".join(lines)
    if len(caption) > 1024:
        raise ValueError("Generated caption exceeds Telegram's 1024-character limit")
    return caption


async def copy_files_to_channel(
    bot: Bot, from_chat_id: int, message_ids: list[int], caption: str
) -> tuple[int, int]:
    sent = failed = 0
    for index, message_id in enumerate(message_ids):
        while True:
            try:
                await bot.copy_message(
                    chat_id=CHANNEL_ID,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    caption=caption,
                )
                sent += 1
                break
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except TelegramBadRequest as exc:
                # TelegramBadRequest covers both an unavailable source message
                # and destination/configuration problems. Keep Telegram's
                # description in the log so these cases can be distinguished.
                log.warning(
                    "Could not copy source message %s from chat %s to channel %s: %s",
                    message_id, from_chat_id, CHANNEL_ID, exc,
                )
                failed += 1
                break
            except Exception:
                log.exception("Unexpected copy failure for source message %s from chat %s", message_id, from_chat_id)
                failed += 1
                break
        if index < len(message_ids) - 1 and SEND_DELAY_SECONDS > 0:
            await asyncio.sleep(SEND_DELAY_SECONDS)
    return sent, failed


async def edit_prompt(
    bot: Bot, chat_id: int, message_id: int, text: str, reply_markup=None
) -> None:
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            log.debug("Prompt edit failed for chat %s message %s: %s", chat_id, message_id, exc)


async def _edit_callback(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    if callback.message:
        try:
            await callback.bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            if "message is not modified" not in str(exc).lower():
                log.warning("Could not edit menu message: %s", exc)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    prompt = await message.answer(WELCOME_TEXT, reply_markup=keyboards.department_kb())
    await state.update_data(prompt_msg_id=prompt.message_id)
    await state.set_state(Upload.department)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(CANCELLED_TEXT)


@router.callback_query(F.data == "cancel")
async def on_cancel_button(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit_callback(callback, CANCELLED_TEXT)
    await callback.answer()


@router.callback_query(Upload.department, F.data.startswith("dept:"))
async def on_department(callback: CallbackQuery, state: FSMContext) -> None:
    tag = callback.data.partition(":")[2]
    if tag not in DEPARTMENTS_BY_TAG:
        await callback.answer("Invalid department.", show_alert=True)
        return
    await state.update_data(dept_tag=tag)
    if tag == FRESHMAN_TAG:
        await state.update_data(year=1)
        await _edit_callback(callback, f"Department: {DEPARTMENTS_BY_TAG[tag]}\nYear: 1\n\nChoose the semester:", keyboards.semester_kb())
        await state.set_state(Upload.semester)
    else:
        await _edit_callback(callback, f"Department: {DEPARTMENTS_BY_TAG[tag]}\n\nChoose the year:", keyboards.year_kb(tag))
        await state.set_state(Upload.year)
    await callback.answer()


@router.callback_query(F.data == "back")
async def on_back(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    data = await state.get_data()
    if current == Upload.year.state:
        await _edit_callback(callback, WELCOME_TEXT, keyboards.department_kb())
        await state.set_state(Upload.department)
    elif current == Upload.semester.state:
        if data.get("dept_tag") == FRESHMAN_TAG:
            await _edit_callback(callback, WELCOME_TEXT, keyboards.department_kb())
            await state.set_state(Upload.department)
        else:
            await _edit_callback(
                callback,
                f"Department: {DEPARTMENTS_BY_TAG[data['dept_tag']]}\n\nChoose the year:",
                keyboards.year_kb(data["dept_tag"]),
            )
            await state.set_state(Upload.year)
    elif current == Upload.type.state:
        await _edit_callback(
            callback,
            f"Department: {DEPARTMENTS_BY_TAG[data['dept_tag']]}\nYear: {data['year']}\n\nChoose the semester:",
            keyboards.semester_kb(),
        )
        await state.set_state(Upload.semester)
    elif current == Upload.course_name.state:
        await _edit_callback(
            callback,
            f"Department: {DEPARTMENTS_BY_TAG[data['dept_tag']]}\nYear: {data['year']}\nSemester: {data['semester']}\n\nChoose the resource type:",
            keyboards.type_kb(),
        )
        await state.set_state(Upload.type)
    else:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    await callback.answer()


@router.callback_query(Upload.year, F.data.startswith("year:"))
async def on_year(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.partition(":")[2]
    data = await state.get_data()
    if not raw.isdigit() or int(raw) not in years_for(data.get("dept_tag", "")):
        await callback.answer("Invalid year for this department.", show_alert=True)
        return
    year = int(raw)
    data = await state.update_data(year=year)
    await _edit_callback(callback, f"Department: {DEPARTMENTS_BY_TAG[data['dept_tag']]}\nYear: {year}\n\nChoose the semester:", keyboards.semester_kb())
    await state.set_state(Upload.semester)
    await callback.answer()


@router.callback_query(Upload.semester, F.data.startswith("sem:"))
async def on_semester(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.partition(":")[2]
    if not raw.isdigit() or int(raw) not in SEMESTERS:
        await callback.answer("Invalid semester.", show_alert=True)
        return
    semester = int(raw)
    data = await state.update_data(semester=semester)
    await _edit_callback(callback, f"Department: {DEPARTMENTS_BY_TAG[data['dept_tag']]}\nYear: {data['year']}\nSemester: {semester}\n\nChoose the resource type:", keyboards.type_kb())
    await state.set_state(Upload.type)
    await callback.answer()


@router.callback_query(Upload.type, F.data.startswith("type:"))
async def on_type(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.partition(":")[2]
    if code not in TYPES_BY_CODE:
        await callback.answer("Invalid resource type.", show_alert=True)
        return
    data = await state.update_data(type_code=code)
    await _edit_callback(callback, _course_prompt({**data, "type_code": code}), keyboards.course_kb())
    await state.set_state(Upload.course_name)
    await callback.answer()


@router.message(Upload.course_name, F.text)
async def on_course_name(message: Message, state: FSMContext, bot: Bot) -> None:
    course = re.sub(r"\s+", " ", message.text).strip()
    if not 2 <= len(course) <= MAX_COURSE_NAME_LENGTH:
        await message.answer(f"Please enter a course name between 2 and {MAX_COURSE_NAME_LENGTH} characters.")
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return
    data = await state.update_data(course=course, file_msg_ids=[], sending=False)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    prompt_id = data.get("prompt_msg_id")
    if prompt_id:
        await edit_prompt(
            bot,
            message.chat.id,
            prompt_id,
            UPLOAD_PROMPT.format(count=0),
            keyboards.upload_kb(),
        )
    await state.set_state(Upload.uploading)


@router.message(Upload.course_name)
async def on_course_name_not_text(message: Message) -> None:
    await message.answer("Please type the course name as text.")


@router.message(Upload.uploading, F.document | F.photo | F.video | F.audio)
async def on_file(message: Message, state: FSMContext, bot: Bot) -> None:
    async with _file_lock(message.chat.id):
        data = await state.get_data()
        if data.get("sending"):
            await message.answer("Files are already being sent. Please wait.")
            return
        message_ids = data.get("file_msg_ids", [])
        if not isinstance(message_ids, list):
            message_ids = []
        if message.message_id in message_ids:
            return
        if len(message_ids) >= MAX_FILES_PER_SESSION:
            await message.answer(f"This session is limited to {MAX_FILES_PER_SESSION} files.")
            return
        message_ids.append(message.message_id)
        data = await state.update_data(file_msg_ids=message_ids)
        prompt_id = data.get("prompt_msg_id")
        if prompt_id:
            await edit_prompt(bot, message.chat.id, prompt_id, UPLOAD_PROMPT.format(count=len(message_ids)), keyboards.upload_kb())


@router.callback_query(Upload.uploading, F.data == "done")
async def on_done(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    async with _file_lock(callback.message.chat.id):
        data = await state.get_data()
        message_ids = data.get("file_msg_ids", [])
        if message_ids and not data.get("sending"):
            await state.update_data(sending=True)
    if not message_ids:
        await callback.answer("No files yet. Send at least one file.", show_alert=True)
        return
    user = callback.from_user
    if data.get("sending") or user.id in _sending_users:
        await callback.answer("Already sending...")
        return
    _sending_users.add(user.id)
    await callback.answer()
    try:
        caption = build_caption(data, user)
        sent, failed = await copy_files_to_channel(bot, callback.message.chat.id, message_ids, caption)
    except Exception:
        log.exception("Upload failed unexpectedly for user %s", user.id)
        prompt_id = data.get("prompt_msg_id")
        if prompt_id:
            await edit_prompt(bot, callback.message.chat.id, prompt_id, "Something went wrong while sending. Please try Done again.", keyboards.upload_kb())
        await state.update_data(sending=False)
        _sending_users.discard(user.id)
        return
    prompt_id = data.get("prompt_msg_id")
    if prompt_id:
        await edit_prompt(
            bot,
            callback.message.chat.id,
            prompt_id,
            f"Upload complete: {sent} sent, {failed} failed (out of {len(message_ids)}).",
        )
    try:
        await bot.send_message(
            chat_id=callback.message.chat.id,
            text="Thank you for your submission!",
            reply_markup=keyboards.submit_another_kb(),
        )
    except Exception:
        log.exception("Could not send thank-you message to user %s", user.id)
    log.info(
        "Upload complete user_id=%s dept=%s year=%s semester=%s type=%s sent=%s failed=%s",
        user.id, data.get("dept_tag"), data.get("year"), data.get("semester"),
        data.get("type_code"), sent, failed,
    )
    await state.clear()
    _sending_users.discard(user.id)


@router.callback_query(F.data == "another")
async def on_submit_another(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit_callback(callback, WELCOME_TEXT, keyboards.department_kb())
    if callback.message:
        await state.update_data(prompt_msg_id=callback.message.message_id)
    await state.set_state(Upload.department)
    await callback.answer()


@router.callback_query()
async def on_stale_callback(callback: CallbackQuery) -> None:
    await callback.answer(EXPIRED_TEXT, show_alert=True)


@router.message()
async def on_unexpected_message(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current in {Upload.department.state, Upload.year.state, Upload.semester.state, Upload.type.state}:
        await message.answer("Please use the buttons above.")
    elif current is None:
        await message.answer("Send /start to add a resource.")


@router.errors()
async def on_unexpected_error(event: ErrorEvent) -> bool:
    exception = event.exception
    message = str(exception).replace(BOT_TOKEN, "[redacted]")
    log.error("Unhandled update error (%s): %s", type(exception).__name__, message)
    return True
