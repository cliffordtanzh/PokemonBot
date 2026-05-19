import logging
import pandas as pd
import os
import re

from datetime import datetime, time
from dotenv import load_dotenv, find_dotenv

from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

import gspread
from google.oauth2.service_account import Credentials

load_dotenv(find_dotenv())

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

WORKER_TELE_IDS = [
    45182866,   # Root,
]

creds = Credentials.from_service_account_file(
    scopes=SCOPES,
    filename=os.getenv("DB_CREDENTIALS")
)


gc = gspread.authorize(creds)
sheet = gc.open("PKM DB_dev")
worksheet = sheet.get_worksheet(0)


def get_database():
    return pd.DataFrame(worksheet.get_all_records(value_render_option="FORMULA"))


def get_collection_delta(recovery_time):
    if (recovery_time == "") or (recovery_time == "Collected"):
        return pd.DateOffset(years=999)

    value, unit = recovery_time.split(" ")
    value = int(value)

    if unit == "Weeks":
        unit = "weeks"
    else:
        unit = "months"

    return pd.DateOffset(**{unit.lower(): value})


def escape_name(name):
    escape_chars = r'([\*_{}\[\]\(\)#\+\-\.!`\\])'
    return re.sub(escape_chars, r'\\\1', name)


def format_progressbar(dropoff_date, recovery_time):
    collection_delta = get_collection_delta(recovery_time)
    datenow = pd.to_datetime(datetime.now().date())

    collection_date = dropoff_date + collection_delta
    formatted_coldate = collection_date.strftime(r"%Y %B %d")

    max_duration = (collection_date.to_pydatetime().date() - dropoff_date)
    duration = (collection_date - datenow)

    perc_complete = (1 - (duration / max_duration))

    num_hashes = int(40 * perc_complete)
    num_dashes = 40 - num_hashes
    progress_bar = "[" + ("#" * num_hashes) + ("-" * num_dashes) + "]"

    return formatted_coldate, progress_bar, perc_complete * 100


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hello, you can use /get_order for you to check on your order status."
    )


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_sender
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"Hello {sender.username}, "
            f"your telegram ID is {sender.id}"
        )
    )


async def get_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    database = get_database()

    username = update.effective_chat.username
    chat_id = update.effective_chat.id

    query = database[database["Telegram Handle"] == username]
    status_columns = query.iloc[:, 6:]

    if status_columns.shape[0] == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Was not able to find your telegram handle. Please contact Jerwaen"
        )

    elif status_columns.shape[0] > 1:
        # If the same customer has multiple orders
        status_columns = status_columns.iloc[-1, :]

    else:
        status_columns = status_columns.iloc[0, :]

    for i, col in enumerate(status_columns.index):
        if "Collection" not in col:
            continue

        if status_columns[col] == "":
            break

    status_columns = status_columns.iloc[: i]

    dropoff_date = pd.to_datetime(
        query.iloc[0, 0],
        unit="D",
        origin="1899-12-30"
    ).date()

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Hello {update.effective_chat.effective_name}, fetching your order now"
    )

    num_cards = int(len(status_columns) // 5)
    for card_num in range(num_cards):
        left_idx = (card_num * 5)

        recovery_time = status_columns.iloc[left_idx]
        front_img = status_columns.iloc[left_idx + 1]
        back_img = status_columns.iloc[left_idx + 2]

        front_img_url = front_img[8: -4]
        back_img_url = back_img[8: -4]

        coldate, pbar, perc_complete = format_progressbar(
            dropoff_date, recovery_time)
        caption = (
            f"Card #{card_num + 1} Collection Date: {coldate}\n"
            f"{pbar}: {perc_complete:.2f}%"
        )

        mediagroup = [
            InputMediaPhoto(front_img_url, caption=caption),
            InputMediaPhoto(back_img_url),
        ]

        await context.bot.send_media_group(
            chat_id=chat_id,
            media=mediagroup
        )


async def weekly_callback(context: ContextTypes.DEFAULT_TYPE):
    database = get_database()
    duration_cols = [col for col in database.columns if "Collection" in col]

    dropoff_dates = pd.to_datetime(
        database["Date of Drop-off"], unit="D", origin="1899-12-30")
    deltas = database[duration_cols].map(get_collection_delta)

    datenow = pd.to_datetime(datetime.now().date())

    collection_ready = []
    for row in range(database.shape[0]):
        collection = dropoff_dates.iloc[row] + deltas.iloc[row]
        collection_date = collection.min()

        days_til_collection = collection_date - datenow
        if (days_til_collection).days > 7:
            continue

        customer_handle = database.iloc[row, :]["Telegram Handle"]
        link_to_sheet = (
            "https://docs.google.com/spreadsheets/d/"
            f"{sheet.id}/edit#gid={worksheet.id}&range=A{row + 2}"
        )

        collection_ready.append((
            f"[row {row + 2}]({link_to_sheet})",
            collection_date.strftime(r"%Y %B %d"),
            customer_handle
        ))

    message = (
        "\n".join([
            f"{escape_name('@' + handle)} {link_to_sheet} on {collection_date}"
            for (link_to_sheet, collection_date, handle) in collection_ready
        ])
        + "\n\nhas a collection this week"
    )

    for id in WORKER_TELE_IDS:
        await context.bot.send_message(
            chat_id=id,
            text=message,
            parse_mode="MarkdownV2"
        )


def main():
    try:
        application = (
            ApplicationBuilder()
            .token(os.getenv("BOT_TOKEN"))
            .connect_timeout(60)
            .read_timeout(60)
            .write_timeout(60)
            .build()
        )
        
        handlers = [
            CommandHandler("start", start),
            CommandHandler("get_id", get_id),
            CommandHandler("get_order", get_order),
        ]

        job_queue = application.job_queue

        # Every Monday at 10am
        job_queue.run_once(
            weekly_callback,
            when = 0
            # time=time(hour=10, minute=0, second=0),
            # days=(1, )
        )

        for handler in handlers:
            application.add_handler(handler)

        application.run_polling()

    except KeyboardInterrupt:
        application.stop_running()

    finally:
        application.stop_running()


if __name__ == "__main__":
    main()
