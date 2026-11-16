"""Inline keyboards for the resource collection flow."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import DEPARTMENTS, SEMESTERS, TYPES, years_for


def _with_cancel(builder: InlineKeyboardBuilder) -> InlineKeyboardMarkup:
    builder.row(InlineKeyboardButton(text="Cancel", callback_data="cancel"))
    return builder.as_markup()


def _with_back_cancel(builder: InlineKeyboardBuilder) -> InlineKeyboardMarkup:
    builder.row(InlineKeyboardButton(text="Back", callback_data="back"))
    builder.row(InlineKeyboardButton(text="Cancel", callback_data="cancel"))
    return builder.as_markup()


def department_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for name, tag in DEPARTMENTS:
        builder.button(text=name, callback_data=f"dept:{tag}")
    builder.adjust(2)
    return _with_cancel(builder)


def year_kb(dept_tag: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    years = years_for(dept_tag)
    for year in years:
        builder.button(text=str(year), callback_data=f"year:{year}")
    builder.adjust(len(years))
    return _with_back_cancel(builder)


def semester_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for semester in SEMESTERS:
        builder.button(text=str(semester), callback_data=f"sem:{semester}")
    builder.adjust(len(SEMESTERS))
    return _with_back_cancel(builder)


def type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label, _tag in TYPES:
        builder.button(text=label, callback_data=f"type:{code}")
    builder.adjust(2)
    return _with_back_cancel(builder)


def course_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    return _with_back_cancel(builder)


def upload_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Done", callback_data="done")
    builder.button(text="Cancel", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


def submit_another_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Submit another", callback_data="another")
    return builder.as_markup()
