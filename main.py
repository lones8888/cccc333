import requests
import pandas as pd
import time
import json
import os

# === Telegram Ayarları ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8295198129:AAGwdBjPNTZbBoVoLYCP8pUxeX7ZrfT7j_8")
CHAT_ID = os.getenv("CHAT_ID", "-1001660662034")

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram bilgileri eksik.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
        print("✅ Telegram gönderildi.")
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")

STATE_FILE = "last_signal.json"

def load_last_signals():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_last_signals(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)

def get_okx_ohlcv(symbol="ETH-USDT-SWAP", bar="6H", limit=300):
    url = "https://www.okx.com/api/v5/market/candles"
    params = {"instId": symbol, "bar": bar, "limit": limit}
    r = requests.get(url, params=params)
    data = r.json()
    if "data" not in data:
        return None
    df = pd.DataFrame(data["data"], columns=["ts","o","h","l","c","vol","volCcy","volCcyQuote","confirm"])
    df = df.astype({"o":float,"h":float,"l":float,"c":float})
    df = df.sort_values("ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    return df

def get_binance_ohlcv(symbol="ETHUSDT", interval="6h", limit=300):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params)
    data = r.json()
    if not isinstance(data, list):
        return None
    df = pd.DataFrame(data, columns=["ts","o","h","l","c","v","ct","qav","trades","tbbav","tbqav","ignore"])
    df = df.astype({"o":float,"h":float,"l":float,"c":float})
    df = df.sort_values("ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    return df[["ts","o","h","l","c"]].reset_index(drop=True)

def calc_a_c_signal(df):
    close = df["c"]
    high = df["h"]
    sma200 = close.rolling(200).mean()
    length = 20
    basis = close.rolling(length).mean()
    dev = 2 * close.rolling(length).std()
    upper = basis + dev
    lower = basis - dev
    bbr = (close - lower) / (upper - lower)
    cond_a = (bbr < 0.144) & (sma200 > high.shift(1))
    cond_c = (bbr < 0.144) & (sma200 > high.shift(1)) & (bbr.shift(1) < bbr)
    cond_ac = (cond_a | cond_c)
    return cond_ac.fillna(False).astype(bool)

def detect_and_send(df, symbol_name, last_signals):
    cond_ac = calc_a_c_signal(df)
    lows = df["l"].values
    closes = df["c"].values
    times = df["ts"]

    last_sent_time = last_signals.get(symbol_name)
    for i in range(4, len(df)):
        if cond_ac.iloc[i-1] and not cond_ac.iloc[i]:
            zaman = str(times.iloc[i])
            entry = closes[i]
            stop = min(lows[i-4:i])
            if last_sent_time != zaman:
                msg = (
                    f"🟢 YESIL YAKTI SİNYALİ (a or c) BİTTİ\n"
                    f"Pair: {symbol_name} (6H)\n"
                    f"Zaman: {zaman}\n"
                    f"Entry (Close): {entry:.2f}\n"
                    f"Stop (4 Mum Low): {stop:.2f}"
                )
                send_telegram(msg)
                last_signals[symbol_name] = zaman
                save_last_signals(last_signals)
            else:
                print(f"{symbol_name}: {zaman} zaten gönderildi.")

def run_cycle():
    print("\n--- Yeni 6H kontrol ---")
    last_signals = load_last_signals()

    okx_df = get_okx_ohlcv("ETH-USDT-SWAP", "6H")
    if okx_df is not None:
        detect_and_send(okx_df, "OKX ETH-USDT-SWAP", last_signals)

    bin_df = get_binance_ohlcv("ETHUSDT", "6h")
    if bin_df is not None:
        detect_and_send(bin_df, "BINANCE ETHUSDT_PERP", last_signals)

    print("--- Kontrol tamamlandı ---")

if __name__ == "__main__":
    run_cycle()
