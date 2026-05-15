import logging
import pandas as pd
import os
import requests

from datetime import datetime
from dotenv import load_dotenv, find_dotenv

from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

import gspread
from google.oauth2.service_account import Credentials

load_dotenv(find_dotenv())
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
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


def format_progressbar(dropoff_date, recovery_time):
    value, unit = recovery_time.split(" ")
    value = int(value)

    if unit == "Weeks":
        unit = "weeks"
    else:
        unit = "months"

    datenow = pd.to_datetime(datetime.now().date())

    collection_date = dropoff_date + pd.DateOffset(**{unit.lower(): value})
    formatted_coldate = collection_date.strftime(r"%Y %B %d")

    max_duration = (collection_date.to_pydatetime().date() - dropoff_date)
    duration = (collection_date - datenow)
    perc_complete = 50 * (1 - (duration / max_duration))

    num_hashes = int(perc_complete)
    num_dashes = 50 - num_hashes
    progress_bar = "[" + ("#" * num_hashes) + ("-" * num_dashes) + "]"

    return formatted_coldate, progress_bar, perc_complete * 2


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hello, you can use /get_order for you to check on your order status."
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

        coldate, pbar, perc_complete = format_progressbar(dropoff_date, recovery_time)
        caption = (
            f"Card #{card_num + 1} Collection Date: {coldate}\n"
            f"{pbar}: {perc_complete * 2:.2f}%"
        )

        mediagroup = [
            InputMediaPhoto(front_img_url, caption=caption),
            InputMediaPhoto(back_img_url),
        ]

        await context.bot.send_media_group(
            chat_id=chat_id,
            media=mediagroup
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
            CommandHandler("get_order", get_order)
        ]

        for handler in handlers:
            application.add_handler(handler)

        application.run_polling()

    except KeyboardInterrupt:
        application.stop_running()

    finally:
        application.stop_running()


if __name__ == "__main__":
    main()
