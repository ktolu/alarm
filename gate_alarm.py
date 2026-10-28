import os, json, time, statistics, requests

T, MAX_SP, SIZE, GAP, QUIET, MIN_EX = 5.0, 40.0, 100.0, 30, 300, 5
NET_MIN, FEE, MAX_ROWS = 3.0, 0.001, 15
SHOW_PAHALI = False
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
    "CryptoCom": ("https://api.crypto.com/exchange/v1/public/get-tickers",
                  lambda d: {x["i"][:-5]: (fl(x.get("b")), fl(x.get("k"))) for x in d["result"]["data"] if x["i"].endswith("_USDT")}),
    "Kraken": ("https://api.kraken.com/0/public/Ticker", kr),
}

def ab(d): return d["asks"], d["bids"]

BOOK = {
    "MEXC": lambda c: ab(get(f"https://api.mexc.com/api/v3/depth?symbol={c}USDT&limit=50")),
    "Binance": lambda c: ab(get(f"https://data-api.binance.vision/api/v3/depth?symbol={c}USDT&limit=50")),
    "OKX": lambda c: ab(get(f"https://www.okx.com/api/v5/market/books?instId={c}-USDT&sz=50")["data"][0]),
    "KuCoin": lambda c: ab(get(f"https://api.kucoin.com/api/v1/market/orderbook/level2_100?symbol={c}-USDT")["data"]),
    "Bybit": lambda c: (lambda r: (r["a"], r["b"]))(get(f"https://api.bybit.com/v5/market/orderbook?category=spot&symbol={c}USDT&limit=50")["result"]),
    "Gate": lambda c: ab(get(f"{GA}/spot/order_book?currency_pair={c}_USDT&limit=50")),
    "Bitget": lambda c: ab(get(f"https://api.bitget.com/api/v2/spot/market/orderbook?symbol={c}USDT&type=step0&limit=50")["data"]),
    "CryptoCom": lambda c: ab(get(f"https://api.crypto.com/exchange/v1/public/get-book?instrument_name={c}_USDT&depth=50")["result"]["data"][0]),
    "Kraken": lambda c: ab(list(get(f"https://api.kraken.com/0/public/Depth?pair={RK.get(c, c)}USDT&count=50")["result"].values())[0]),
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
            lon = {x[0] for x in lo}
            ref = statistics.median([b for n, b, a in q if n not in lon])
            sp = (ref / a0 - 1) * 100
            if T <= sp <= MAX_SP:
                low[c] = dict(ex=n0, sp=sp, k=len(q), others=[n for n, b, a in q if n not in lon])
        if SHOW_PAHALI and 1 <= len(hi) <= 2:
            n0, b0, a0 = max(hi, key=lambda x: x[1])
            hin = {x[0] for x in hi}
            ref = statistics.median([a for n, b, a in q if n not in hin])
            if T <= (b0 / ref - 1) * 100 <= MAX_SP:
                high[c] = dict(ex=n0, price=b0, ref=ref, k=len(q))
    return low, high

def buy_fill(asks):
    spent = qty = 0.0
    for lv in sorted(asks, key=lambda x: float(x[0])):
        p, q = float(lv[0]), float(lv[1]); t = min(q, (SIZE - spent) / p)
        spent += t * p; qty += t
        if spent >= SIZE - 1e-9: return spent / qty, qty
    return None

def sell_fill(bids, qty):
    got, left = 0.0, qty
    for lv in sorted(bids, key=lambda x: -float(x[0])):
        p, q = float(lv[0]), float(lv[1]); t = min(q, left)
        got += t * p; left -= t
        if left <= qty * 1e-9: return got / qty
    return None

def gate_wd(c):
    try:
        ch = get(f"{GA}/spot/currencies/{c}").get("chains") or []
        return "AÇIK" if any(not x.get("withdraw_disabled") for x in ch) else "KAPALI"
    except Exception: return "?"

def tg(msg):
    try:
        r = requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
                      data={"chat_id": os.environ["TG_CHAT"], "text": msg[:3900]}, timeout=15)
        print(f"TG yanıt: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"TG hata: {e}")

def quiet(st, key, sp):
    last = st.get(key)
    return bool(last and time.time() - last["t"] < QUIET and sp < last["sp"] + 2)

try: st = json.load(open("state.json"))
except Exception: st = {}
al, ah = snap()
time.sleep(GAP)
bl, bh = snap()

rows = []
for c in sorted(al, key=lambda x: -al[x]["sp"]):
    if len(rows) >= MAX_ROWS: break
    if c not in bl or bl[c]["ex"] != al[c]["ex"]: continue
    ex = bl[c]["ex"]
    row = dict(c=c, ex=ex, ok=False, net=None, why="")
    rows.append(row)
    try:
        asks, _ = BOOK[ex](c)
        r = buy_fill(asks)
    except Exception:
        row["why"] = "kitap alınamadı"; continue
    if not r:
        row["why"] = f"{ex} kitabı {SIZE:.0f}$'ı karşılamıyor"; continue
    avg, qty = r
    row["avg"] = avg
    row["slip"] = (avg / min(float(x[0]) for x in asks) - 1) * 100
    sells = []
    for n in bl[c]["others"]:
        try:
            s = sell_fill(BOOK[n](c)[1], qty)
            if s: sells.append(s)
        except Exception: pass
    if len(sells) < 2:
        row["why"] = f"satış kitabı yetersiz ({len(sells)} borsa)"; continue
    ref = statistics.median(sells)
    row["ref"], row["n"] = ref, len(sells)
    row["net"] = (ref * (1 - FEE) / (avg * (1 + FEE)) - 1) * 100
    row["ok"] = row["net"] >= NET_MIN
    if not row["ok"]: row["why"] = "net düşük"

def key_sp(r): return r["net"] if r["net"] is not None else 0.0

if any(not quiet(st, r["c"] + ":low", key_sp(r)) for r in rows):
    rows.sort(key=lambda r: (not r["ok"], -key_sp(r)))
    lines = [f"Aday {len(rows)}, filtreyi geçen {sum(r['ok'] for r in rows)} ({SIZE:.0f}$ işlem)"]
    for r in rows:
        if r["net"] is None:
            lines.append(f"▫️ {r['c']} ({r['ex']}): {r['why']}")
        else:
            extra = f" | Gate çekme: {gate_wd(r['c'])}" if r["ok"] and r["ex"] == "Gate" else ""
            lines.append(f"{'✅' if r['ok'] else '▫️'} {r['c']} {r['ex']}: alış {r['avg']:.6g} (kayma %{r['slip']:.1f}), "
                         f"satış ort. {r['ref']:.6g} ({r['n']} borsa), net %{r['net']:.1f}"
                         + (f" [{r['why']}]" if r["why"] else "") + extra)
    lines.append("Aynı isimli farklı token olmadığını ve ucuz borsada alım yapabildiğini kontrol et.")
    tg("\n".join(lines))
    for r in rows:
        st[r["c"] + ":low"] = dict(t=time.time(), sp=key_sp(r))

for c in ah:
    if c not in bh or bh[c]["ex"] != ah[c]["ex"]: continue
    sp = (bh[c]["price"] / bh[c]["ref"] - 1) * 100
    if quiet(st, c + ":high", sp): continue
    tg(f"PAHALI AZINLIK {c}: {bh[c]['ex']} alış {bh[c]['price']:.6g}, diğerlerinin ortası {bh[c]['ref']:.6g} (%{sp:.1f}).")
    st[c + ":high"] = dict(t=time.time(), sp=sp)

json.dump(st, open("state.json", "w"))
tg(f"çalıştı {time.strftime('%H:%M')} UTC, aday {len(rows)}")
