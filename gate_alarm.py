import os, json, time, statistics, requests

T, MAX_SP, SIZE, GAP, QUIET, MIN_EX = 7.0, 40.0, 50.0, 30, 6 * 3600, 5
SHOW_PAHALI = False   # True yaparsan "pahalı azınlık" bilgi alarmı da gelir
UA = {"User-Agent": "Mozilla/5.0"}
GA = "https://api.gateio.ws/api/v4"
RK = {"BTC": "XBT", "DOGE": "XDG"}

def get(u): return requests.get(u, timeout=15, headers=UA).json()
def fl(x):
    try: return float(x)
    except Exception: return 0.0

def bt(d):
    return {x["symbol"][:-4]: (fl(x["bidPrice"]), fl(x["askPrice"])) for x in d if x["symbol"].endswith("USDT")}

def kr(d):
    inv = {v: k for k, v in RK.items()}
    return {inv.get(k[:-4], k[:-4]): (fl(v["b"][0]), fl(v["a"][0])) for k, v in d["result"].items() if k.endswith("USDT")}

SRC = {
    "MEXC": ("https://api.mexc.com/api/v3/ticker/bookTicker", bt),
    "Binance": ("https://data-api.binance.vision/api/v3/ticker/bookTicker", bt),
    "OKX": ("https://www.okx.com/api/v5/market/tickers?instType=SPOT",
            lambda d: {x["instId"][:-5]: (fl(x["bidPx"]), fl(x["askPx"])) for x in d["data"] if x["instId"].endswith("-USDT")}),
    "KuCoin": ("https://api.kucoin.com/api/v1/market/allTickers",
               lambda d: {x["symbol"][:-5]: (fl(x["buy"]), fl(x["sell"])) for x in d["data"]["ticker"] if x["symbol"].endswith("-USDT")}),
    "Bybit": ("https://api.bybit.com/v5/market/tickers?category=spot",
              lambda d: {x["symbol"][:-4]: (fl(x["bid1Price"]), fl(x["ask1Price"])) for x in d["result"]["list"] if x["symbol"].endswith("USDT")}),
    "Gate": (GA + "/spot/tickers",
             lambda d: {x["currency_pair"][:-5]: (fl(x["highest_bid"]), fl(x["lowest_ask"])) for x in d if x["currency_pair"].endswith("_USDT")}),
    "Bitget": ("https://api.bitget.com/api/v2/spot/market/tickers",
               lambda d: {x["symbol"][:-4]: (fl(x["bidPr"]), fl(x["askPr"])) for x in d["data"] if x["symbol"].endswith("USDT")}),
    "HTX": ("https://api.huobi.pro/market/tickers",
            lambda d: {x["symbol"][:-4].upper(): (fl(x.get("bid")), fl(x.get("ask"))) for x in d["data"] if x["symbol"].endswith("usdt")}),
    "CryptoCom": ("https://api.crypto.com/exchange/v1/public/get-tickers",
                  lambda d: {x["i"][:-5]: (fl(x.get("b")), fl(x.get("k"))) for x in d["result"]["data"] if x["i"].endswith("_USDT")}),
    "Kraken": ("https://api.kraken.com/0/public/Ticker", kr),
}

BOOK = {
    "MEXC": lambda c: get(f"https://api.mexc.com/api/v3/depth?symbol={c}USDT&limit=20")["asks"],
    "Binance": lambda c: get(f"https://data-api.binance.vision/api/v3/depth?symbol={c}USDT&limit=20")["asks"],
    "OKX": lambda c: get(f"https://www.okx.com/api/v5/market/books?instId={c}-USDT&sz=20")["data"][0]["asks"],
    "KuCoin": lambda c: get(f"https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol={c}-USDT")["data"]["asks"],
    "Bybit": lambda c: get(f"https://api.bybit.com/v5/market/orderbook?category=spot&symbol={c}USDT&limit=25")["result"]["a"],
    "Gate": lambda c: get(f"{GA}/spot/order_book?currency_pair={c}_USDT&limit=30")["asks"],
    "Bitget": lambda c: get(f"https://api.bitget.com/api/v2/spot/market/orderbook?symbol={c}USDT&type=step0&limit=20")["data"]["asks"],
    "HTX": lambda c: get(f"https://api.huobi.pro/market/depth?symbol={c.lower()}usdt&type=step0&depth=20")["tick"]["asks"],
    "CryptoCom": lambda c: get(f"https://api.crypto.com/exchange/v1/public/get-book?instrument_name={c}_USDT&depth=20")["result"]["data"][0]["asks"],
    "Kraken": lambda c: list(get(f"https://api.kraken.com/0/public/Depth?pair={RK.get(c, c)}USDT&count=20")["result"].values())[0]["asks"],
}

def snap():
    data = {}
    for n, (u, f) in SRC.items():
        try: data[n] = f(get(u))
        except Exception: pass
    print({n: len(d) for n, d in data.items()})
    coins = set().union(*[set(d) for d in data.values()]) if data else set()
    low, high = {}, {}
    for c in coins:
        q = [(n, *d[c]) for n, d in data.items()
             if c in d and d[c][0] > 0 and d[c][1] > 0 and d[c][1] / d[c][0] < 1.02]
        if len(q) < MIN_EX: continue
        med = statistics.median([(b + a) / 2 for _, b, a in q])
        lo = [x for x in q if x[2] <= med * (1 - T / 100)]
        hi = [x for x in q if x[1] >= med * (1 + T / 100)]
        if 1 <= len(lo) <= 2:
            n0, b0, a0 = min(lo, key=lambda x: x[2])
            ref = statistics.median([b for n, b, a in q if n not in {x[0] for x in lo}])
            if T <= (ref / a0 - 1) * 100 <= MAX_SP:
                low[c] = dict(ex=n0, ref=ref, k=len(q))
        if SHOW_PAHALI and 1 <= len(hi) <= 2:
            n0, b0, a0 = max(hi, key=lambda x: x[1])
            ref = statistics.median([a for n, b, a in q if n not in {x[0] for x in hi}])
            if T <= (b0 / ref - 1) * 100 <= MAX_SP:
                high[c] = dict(ex=n0, price=b0, ref=ref, k=len(q))
    return low, high

def fill(ex, c):
    spent = qty = 0.0
    for lv in BOOK[ex](c):
        p, q = float(lv[0]), float(lv[1]); t = min(q, (SIZE - spent) / p)
        spent += t * p; qty += t
        if spent >= SIZE - 1e-9: return spent / qty
    return None

def gate_wd(c):
    try:
        ch = get(f"{GA}/spot/currencies/{c}").get("chains") or []
        return "AÇIK" if any(not x.get("withdraw_disabled") for x in ch) else "KAPALI"
    except Exception: return "?"

def tg(msg):
    requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
                  data={"chat_id": os.environ["TG_CHAT"], "text": msg}, timeout=15)

def quiet(st, key, sp):
    last = st.get(key)
    return bool(last and time.time() - last["t"] < QUIET and sp < last["sp"] + 2)

try: st = json.load(open("state.json"))
except Exception: st = {}
al, ah = snap()
time.sleep(GAP)
bl, bh = snap()

for c in al:
    if c not in bl or bl[c]["ex"] != al[c]["ex"]: continue
    ex = bl[c]["ex"]
    try: avg = fill(ex, c)
    except Exception: continue
    if not avg: continue
    sp = (min(al[c]["ref"], bl[c]["ref"]) / avg - 1) * 100
    if sp < T or quiet(st, c + ":low", sp): continue
    extra = f"\nGate çekme: {gate_wd(c)}" if ex == "Gate" else ""
    tg(f"AL ADAYI {c}: {ex}'te {avg:.6g} USDT (50$ dolum)\n"
       f"Diğer borsaların ortası {bl[c]['ref']:.6g} (%{sp:.1f} fark, {bl[c]['k']} borsa){extra}\n"
       f"Aynı isimli farklı token olmadığını ve {ex}'te alım yapabildiğini kontrol et.")
    st[c + ":low"] = dict(t=time.time(), sp=sp)

for c in ah:
    if c not in bh or bh[c]["ex"] != ah[c]["ex"]: continue
    sp = (bh[c]["price"] / bh[c]["ref"] - 1) * 100
    if quiet(st, c + ":high", sp): continue
    tg(f"PAHALI AZINLIK {c}: {bh[c]['ex']} alış {bh[c]['price']:.6g}, diğerlerinin ortası {bh[c]['ref']:.6g} (%{sp:.1f}).\n"
       f"Elinde varsa satış fırsatı. Almak için sinyal değil, yakınsama düşüşle olabilir.")
    st[c + ":high"] = dict(t=time.time(), sp=sp)
json.dump(st, open("state.json", "w"))
