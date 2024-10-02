from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import requests
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
BLOCKCHAIN_API_URL = os.getenv('BLOCKCHAIN_API_URL')

USER_STATE = {}

def main_menu_keyboard():
    return ReplyKeyboardMarkup([['Створити гаманець', 'Баланс', 'Відправити транзакцію'], 
                                ['Додати гаманець з приватним ключем']], resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        text="Ласкаво просимо! Оберіть дію в меню.",
        reply_markup=main_menu_keyboard()
    )


async def create_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    response = requests.post(f'{BLOCKCHAIN_API_URL}/create_wallet', json={"user_id": user_id})

    if response.status_code == 200:
        wallet_data = response.json()
        await update.message.reply_text(
            text=f"Гаманець створено!\nАдреса: {wallet_data['address']}\nПриватний ключ: {wallet_data['private_key']}",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text("Помилка при створенні гаманця.")


def get_wallets(user_id):
    response = requests.get(f'{BLOCKCHAIN_API_URL}/get_wallets', params={"user_id": user_id})
    if response.status_code == 200:
        return response.json()
    else:
        return []


async def choose_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    wallets = get_wallets(user_id)

    if wallets:
        keyboard = []
        for wallet in wallets:
            keyboard.append([InlineKeyboardButton(wallet['address'], callback_data=wallet['address'])])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Оберіть гаманець для перевірки балансу:', reply_markup=reply_markup)
    else:
        await update.message.reply_text("У вас немає створених гаманців. Спочатку створіть гаманець.")


async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_wallet = query.data  
    response = requests.get(f'{BLOCKCHAIN_API_URL}/get_balance', params={"address": selected_wallet})

    if response.status_code == 200:
        balance_data = response.json()
        trx_balance = balance_data.get('trx_balance', 'Немає даних')
        token_balances = balance_data.get('token_balances', {})

        balance_message = f"Баланс гаманця {selected_wallet}:\n"
        balance_message += f"TRX: {trx_balance}\n\nБаланс токенів:\n"
        
        # Перевіряємо, чи token_balances є словником
        if isinstance(token_balances, dict):
            if token_balances:
                for token_name, token_balance in token_balances.items():
                    balance_message += f"{token_name}: {token_balance}\n"
            else:
                balance_message += "Токенів не знайдено.\n"
        else:
            balance_message += f"Помилка отримання токенів: {token_balances}"

        await query.edit_message_text(text=balance_message)
    else:
        await query.edit_message_text(text="Помилка при отриманні балансу гаманця.")



async def send_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    wallets = get_wallets(user_id)

    if wallets:
        keyboard = []
        for wallet in wallets:
            keyboard.append([InlineKeyboardButton(wallet['address'], callback_data=f"send_{wallet['address']}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Оберіть гаманець для відправки транзакції:', reply_markup=reply_markup)
    else:
        await update.message.reply_text("У вас немає створених гаманців. Спочатку створіть гаманець.")
 

async def transaction_step_1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sender_address = query.data.split('_')[1]
    context.user_data['sender_address'] = sender_address

    
    response = requests.get(f'{BLOCKCHAIN_API_URL}/get_balance', params={"address": sender_address})
    
    if response.status_code == 200:
        balance_data = response.json()
        trx_balance = balance_data.get('trx_balance', 0)
        fee = 1.6  
        available_amount = trx_balance - fee
        
        if available_amount < 0:
            available_amount = 0  
        
        await query.edit_message_text(
            text=f"Ви обрали гаманець {sender_address}. Баланс: {trx_balance:.6f} TRX.\n"
                 f"Ви можете відправити максимум {available_amount:.6f}\n"
                 f"Введіть адресу отримувача:"
        )
        USER_STATE[update.effective_chat.id] = 'recipient_address'
    else:
        await query.edit_message_text(text="Помилка при отриманні балансу гаманця.")



async def add_wallet_step_1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введіть адресу вашого гаманця:")
    USER_STATE[update.effective_chat.id] = 'add_wallet_address'


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    state = USER_STATE.get(user_id)

    if update.message.text == 'Створити гаманець':
        await create_wallet(update, context)
    elif update.message.text == 'Баланс':
        await choose_wallet(update, context)
    elif update.message.text == 'Відправити транзакцію':
        await send_transaction(update, context)
    elif update.message.text == 'Додати гаманець з приватним ключем':  
        await add_wallet_step_1(update, context)
    elif state == 'add_wallet_address':
        context.user_data['wallet_address'] = update.message.text.strip()
        await update.message.reply_text("Введіть приватний ключ вашого гаманця:")
        USER_STATE[user_id] = 'add_wallet_private_key'
    elif state == 'add_wallet_private_key':
        wallet_address = context.user_data.get('wallet_address')
        private_key = update.message.text.strip()

        response = requests.post(f'{BLOCKCHAIN_API_URL}/add_wallet', json={
            "user_id": user_id,
            "address": wallet_address,
            "private_key": private_key
        })

        if response.status_code == 200:
            await update.message.reply_text("Ваш гаманець успішно додано!", reply_markup=main_menu_keyboard())
        else:
            error_message = response.json().get('error', 'Сталася помилка')
            await update.message.reply_text(f"Помилка: {error_message}", reply_markup=main_menu_keyboard())

        USER_STATE[user_id] = None
    elif state == 'recipient_address':
        recipient_address = update.message.text.strip()
        if not recipient_address.startswith('T') or len(recipient_address) != 34:
            await update.message.reply_text("Некоректна адреса отримувача. Будь ласка, введіть правильну адресу TRON.")
            return

        context.user_data['recipient_address'] = recipient_address
        await update.message.reply_text("Введіть суму для відправки (у TRX):")
        USER_STATE[user_id] = 'amount'
    elif state == 'amount':
        try:
            amount = float(update.message.text)
            if amount <= 0:
                await update.message.reply_text("Сума повинна бути більше нуля.")
                return

            context.user_data['amount'] = amount

            
            webhook_url = f'/transaction_webhook?user_id={user_id}'  
            response = requests.post(f'{BLOCKCHAIN_API_URL}/send_transaction', json={
                "sender_address": context.user_data['sender_address'],
                "recipient_address": context.user_data['recipient_address'],
                "amount": context.user_data['amount'],
                "webhook_url": webhook_url
            })

            if response.status_code == 200:
                await update.message.reply_text(f"Транзакція в пройла успішна.")
            else:
                await update.message.reply_text("Помилка під час відправки транзакції.")

            USER_STATE[user_id] = None
        except ValueError:
            await update.message.reply_text("Некоректне значення суми. Будь ласка, введіть числове значення.")
    else:
        await update.message.reply_text("Невідома команда. Будь ласка, оберіть дію з меню.", reply_markup=main_menu_keyboard())


def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.add_handler(CallbackQueryHandler(check_balance, pattern="^(?!send_).*"))

    application.add_handler(CallbackQueryHandler(transaction_step_1, pattern="^send_"))
    
    application.run_polling()

if __name__ == '__main__':
    main()
