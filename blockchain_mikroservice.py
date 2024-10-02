from flask import Flask, request, jsonify
from tronpy import Tron
from tronpy.keys import PrivateKey
import requests
from flask_sqlalchemy import SQLAlchemy
import os
import random
import time

app = Flask(__name__)


app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blockchain.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    address = db.Column(db.String(100), nullable=False)
    private_key = db.Column(db.String(200), nullable=False)

with app.app_context():
    db.create_all()


api_keys = [
    "ddcbffe6-0d67-4bbc-b4df-950f6659850b",
    "a3f87d06-2216-48b2-8989-f2b833c0c64e",
    "13b96a48-5c67-4948-abf0-8df79d0c7699"
]


balance_cache = {}
cache_expiry_time = 60  


def get_random_api_key():
    return random.choice(api_keys)


def get_tron_client():
    api_key = get_random_api_key()
    client = Tron(network="mainnet")  
    client.default_headers = {"TRON-PRO-API-KEY": api_key}  
    return client

client = get_tron_client()  


def get_trx_balance(address):
    current_time = time.time()

    if address in balance_cache and current_time - balance_cache[address]['timestamp'] < cache_expiry_time:
        return balance_cache[address]['balance']

    url = f"https://apilist.tronscan.org/api/account?address={address}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        balance = data.get('balance')  
        if balance is not None:
            balance_in_trx = balance / 1e6  
            balance_cache[address] = {
                'balance': balance_in_trx,
                'timestamp': current_time
            }
            return balance_in_trx
        else:
            return "Баланс TRX не знайдено"
    except requests.RequestException as e:
        return f"Помилка запиту: {str(e)}"


def get_tokens(address):
    url = f"https://apilist.tronscan.org/api/account/tokens?address={address}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        tokens = data.get('data')  
        if tokens:
            token_balances = {}
            for token in tokens:
                token_name = token.get('tokenName')
                try:
                    token_balance = float(token.get('balance', '0')) / 10**token.get('tokenDecimal', 6)
                except ValueError:
                    token_balance = 0
                token_balances[token_name] = token_balance
            return token_balances
        else:
            return {}
    except requests.RequestException as e:
        return f"Помилка запиту: {str(e)}"


def check_transaction_status(txid):
    url = f"https://apilist.tronscan.org/api/transaction-info?hash={txid}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        
        if data.get('contractRet') == 'SUCCESS':
            return True  
        else:
            return False  
    except requests.RequestException as e:
        print(f"Помилка при перевірці статусу транзакції: {str(e)}")
        return None  


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    data = request.json
    user_id = data.get('user_id')

    
    wallet = client.generate_address()

    new_wallet = Wallet(
        user_id=user_id,
        address=wallet['base58check_address'],
        private_key=wallet['private_key']
    )
    db.session.add(new_wallet)
    db.session.commit()

    return jsonify({
        "address": wallet['base58check_address'],
        "private_key": wallet['private_key']
    })


@app.route('/add_wallet', methods=['POST'])
def add_wallet():
    data = request.json
    user_id = data.get('user_id')
    address = data.get('address')
    private_key = data.get('private_key')

    if not user_id or not address or not private_key:
        return jsonify({"error": "Необхідні дані: user_id, address, private_key"}), 400

    if not address.startswith('T') or len(address) != 34:
        return jsonify({"error": "Некоректна адреса гаманця"}), 400

    existing_wallet = Wallet.query.filter_by(address=address).first()
    if existing_wallet:
        return jsonify({"error": "Гаманець вже існує"}), 400

    new_wallet = Wallet(user_id=user_id, address=address, private_key=private_key)
    db.session.add(new_wallet)
    db.session.commit()

    return jsonify({"message": "Гаманець успішно додано!", "address": address}), 200


@app.route('/get_wallets', methods=['GET'])
def get_wallets():
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "user_id не вказаний"}), 400

    wallets = Wallet.query.filter_by(user_id=user_id).all()

    if not wallets:
        return jsonify({"message": "У користувача немає гаманців"}), 404

    wallet_list = [{"address": wallet.address, "private_key": wallet.private_key} for wallet in wallets]

    return jsonify(wallet_list)


@app.route('/get_balance', methods=['GET'])
def get_balance():
    address = request.args.get('address')

    if not address:
        return jsonify({"error": "Адреса гаманця не вказана"}), 400

    trx_balance = get_trx_balance(address)
    token_balances = get_tokens(address)

    return jsonify({
        "trx_balance": trx_balance,
        "token_balances": token_balances
    })


@app.route('/send_transaction', methods=['POST'])
def send_transaction():
    data = request.json
    sender_address = data.get('sender_address')
    recipient_address = data.get('recipient_address')
    amount = data.get('amount')  
    webhook_url = data.get('webhook_url')  

    if not all([sender_address, recipient_address, amount, webhook_url]):
        return jsonify({"error": "Необхідні дані: sender_address, recipient_address, amount, webhook_url"}), 400

    sender_wallet = Wallet.query.filter_by(address=sender_address).first()

    if sender_wallet is None:
        return jsonify({"error": "Адреса гаманця не знайдена"}), 404

    private_key = sender_wallet.private_key

    if not recipient_address.startswith('T') or len(recipient_address) != 34:
        return jsonify({"error": "Некоректна адреса отримувача"}), 400
    
    try:
        client = get_tron_client()

        print(f"Відправка транзакції з адреси {sender_address} на адресу {recipient_address} сумою {amount} TRX")

        priv_key = PrivateKey(bytes.fromhex(private_key))
        txn = (
            client.trx.transfer(sender_address, recipient_address, int(float(amount) * 1e6))  
            .build()
            .sign(priv_key)
        )
        result = txn.broadcast()
        
        txid = result['txid']
        print(f"TXID транзакції: {txid}")
        
        time.sleep(5)

        transaction_successful = check_transaction_status(txid)

        if transaction_successful is True:
            print(f"Транзакція успішна, TXID: {txid}")
            requests.post(webhook_url, json={"status": "success", "transaction_id": txid})
            return jsonify({"message": "Транзакція успішно відправлена!", "transaction_id": txid})
        elif transaction_successful is False:
            print(f"Транзакція не вдалася, TXID: {txid}")
            requests.post(webhook_url, json={"status": "failure", "transaction_id": txid})
            return jsonify({"error": "Транзакція не вдалася.", "transaction_id": txid}), 400
        else:
            print(f"Не вдалося перевірити статус транзакції, TXID: {txid}")
            requests.post(webhook_url, json={"status": "failure", "message": "Не вдалося перевірити статус транзакції"})
            return jsonify({"error": "Не вдалося перевірити статус транзакції.", "transaction_id": txid}), 500

    except requests.exceptions.HTTPError as http_err:
        print(f"Помилка HTTP: {str(http_err)}")
        requests.post(webhook_url, json={"status": "failure", "message": "HTTP error"})
        return jsonify({"error": f"HTTP помилка: {str(http_err)}"}), 500
    except Exception as e:
        print(f"Помилка під час транзакції: {str(e)}")
        requests.post(webhook_url, json={"status": "failure", "message": str(e)})
        return jsonify({"error": f"Помилка під час транзакції: {str(e)}"}), 500


@app.route('/transaction_webhook', methods=['POST'])
def transaction_webhook():
    data = request.json
    transaction_status = data.get('status')
    transaction_id = data.get('transaction_id')

    print(f"Транзакція {transaction_id} завершена зі статусом: {transaction_status}")

    return jsonify({"message": "Результат транзакції отримано"}), 200

if __name__ == '__main__':
    app.run(debug=True)
