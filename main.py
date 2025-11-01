import requests
import pandas as pd
import time
import json
import os
from datetime import datetime, timezone

# === TELEGRAM ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8295198129:AAGwdBjPNTZbBoVoLYCP8pUxeX7ZrfT7j_8")
CHAT_ID = os.getenv("CHAT_ID", "-1001660662034")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
        print("✅ Telegram gönderildi.")
        time.sleep(1)
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")

# === LOCAL DATA ===
STATE_FILE = "last_signal.json"

def load_last_signals():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_last_signals(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# === OKX API ===
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

# === BINANCE API ===
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

# === PineScript 'a' ve 'c' ===
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

# === Sinyal Algılama ===
def detect_and_send(df, symbol_name, last_signals):
    cond_ac = calc_a_c_signal(df)
    lows = df["l"].values
    closes = df["c"].values
    times = df["ts"]

    for i in range(4, len(df)):
        # Sinyal bitmişse
        if cond_ac.iloc[i-1] and not cond_ac.iloc[i]:
            zaman = str(times.iloc[i])
            entry = round(closes[i], 2)
            stop = round(min(lows[i-4:i]), 2)

            signal_key = f"{symbol_name}_{zaman}_{entry}_{stop}"

            # Aynı sinyal zaten gönderildiyse atla
            if signal_key in last_signals:
                print(f"{symbol_name}: {zaman} sinyali zaten gönderilmiş, atlanıyor.")
                continue

            msg = (
                f"🟢 YESIL YAKTI SİNYALİ (a or c) BİTTİ\n"
                f"Pair: {symbol_name} (6H)\n"
                f"Zaman: {zaman}\n"
                f"Entry (Close): {entry}\n"
                f"Stop (4 Mum Low): {stop}"
            )
            send_telegram(msg)

            last_signals[signal_key] = str(datetime.now(timezone.utc))
            save_last_signals(last_signals)

            print(f"{symbol_name}: Yeni sinyal gönderildi ({zaman}).")
            break  # Sadece en yeni sinyali gönder

# === Döngü ===
def run_cycle():
    print(f"\n--- Yeni kontrol başlatıldı: {datetime.utcnow()} UTC ---")
    last_signals = load_last_signals()

    # OKX kontrolü
    df_okx = get_okx_ohlcv("ETH-USDT-SWAP", "6H")
    if df_okx is not None:
        detect_and_send(df_okx, "OKX ETH-USDT-SWAP", last_signals)

    # Binance kontrolü
    df_bin = get_binance_ohlcv("ETHUSDT", "6h")
    if df_bin is not None:
        detect_and_send(df_bin, "BINANCE ETHUSDT_PERP", last_signals)

    print("--- Kontrol tamamlandı ---")

if __name__ == "__main__":
    while True:
        run_cycle()
        print("⏳ 6 saat bekleniyor...")
        time.sleep(6 * 60 * 60)
