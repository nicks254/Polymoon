
# -*- coding: utf-8 -*-

import os
import time
import random
import itertools
import json
import math
from collections import deque
from datetime import datetime, timezone, timedelta

import requests
from termcolor import colored

# =========================
# ACCOUNT CONFIG
# =========================
FUNDER_ADDRESS = "0xf67474ad72942f72fa018a70e9967ac1cc94f14a"
PRIVATE_KEY = "0xd02daa5c338fc0f047c56ba3b6d9e0464bff1ea9df4b3bfcc7d49bea8854254c"
SIGNATURE_TYPE = 1

# =========================
# TRADING CONFIG
# =========================
BET_AMOUNT = 1.0              # USDC amount for market buy
MIN_PRICE = 0.80              # Minimum bid price on the decided side to consider entry
MIN_PRICE_GAP = 55.0          # $20+ BTC price gap required before executing
ENTRY_WINDOW_SEC = 80
STOP_THRESHOLD_SEC = 5
ORDER_UPDATE_INTERVAL = 3
PRICE_HOLD_TOLERANCE = 0.005
MARKET_DURATION = 300
DRY_RUN = False

# =========================
# APIs
# =========================
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
PROFILE_API = "https://gamma-api.polymarket.com"
PYTH_BTC_ID = "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43"

# =========================
# DEBUG
# =========================
DEBUG_BOOK_PAYLOAD = False
DEBUG_TOKEN_MAPPING = True
DEBUG_SDK_METHODS = False

# =========================
# SDK SETUP
# =========================
client = None
SDK_AVAILABLE = False

try:
    from py_clob_client_v2 import ClobClient, MarketOrderArgs, Side, OrderType, PartialCreateOrderOptions
    SDK_AVAILABLE = True
except ImportError:
    print(colored("⚠️ pip install py-clob-client-v2", "red"))


def _as_dict(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return dict(obj.__dict__)
        except Exception:
            pass
    return None


if SDK_AVAILABLE and PRIVATE_KEY and FUNDER_ADDRESS and "YOUR_" not in PRIVATE_KEY:
    try:
        clean_key = PRIVATE_KEY[2:] if PRIVATE_KEY.startswith("0x") else PRIVATE_KEY
        client = ClobClient(
            host=CLOB_API,
            key=clean_key,
            chain_id=137,
            signature_type=SIGNATURE_TYPE,
            funder=FUNDER_ADDRESS,
        )
        try:
            creds = client.create_or_derive_api_key()
            client.set_api_creds(creds)
            print(colored("✅ Polymarket L2 ready", "green"))
        except Exception:
            creds = client.derive_api_key()
            client.set_api_creds(creds)
            print(colored("✅ Using derived API key", "green"))

        if DEBUG_SDK_METHODS and client:
            cancels = [m for m in dir(client) if "cancel" in m.lower()]
            posts = [m for m in dir(client) if "post" in m.lower() or "create" in m.lower()]
            print(colored(f"SDK cancel methods: {cancels}", "yellow"))
            print(colored(f"SDK order methods:  {[m for m in posts if 'order' in m.lower()]}", "yellow"))

    except Exception as e:
        print(colored(f"⚠️ Client init issue: {e}", "yellow"))
        client = None

# =========================
# SESSION STATE
# =========================
SESSION_ENTRIES = 0
SESSION_SKIPS = 0
SESSION_ATTEMPTS = 0
SESSION_START = time.time()

HYPE_MESSAGES = [
    "LFG Moon Dev! 🚀",
    "5% every 5 minutes 💸",
    "We don't chase, we market buy 🛒",
    "Only the decided ones, only 75c+ 🎯",
    "Patience pays the bills 🏦",
    "Market orders. Instant fill. 🚀",
    "Sniping the last nickel 🦾",
    "Let the gamblers fight at 50c ⚔️",
    "Decided = our zone 🚧",
    "Sit. Wait. Fire. Hold. 🧘",
    "The market is our friend 🤝",
    "Built different 🧬",
    "Cook mode: PATIENT 👨‍🍳",
    "Moon Dev = the closer 🔒",
]

SPINNER_FRAMES = itertools.cycle(["◐", "◓", "◑", "◒"])
ROCKET_FRAMES = itertools.cycle(["🚀", " 🚀", "  🚀", "   🚀"])
BANNER_COLORS = itertools.cycle(["cyan", "magenta", "yellow", "green", "blue", "red"])
EVENT_LOG = deque(maxlen=6)


def log_event(msg, color="white"):
    ts = datetime.now().strftime("%H:%M:%S")
    EVENT_LOG.append((ts, msg, color))


def short_id(x):
    if not x:
        return "None"
    s = str(x)
    return s[:8] + "..." + s[-4:] if len(s) > 12 else s


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def format_market_interval(market_info):
    if not market_info:
        return "Unknown interval"
    st = market_info.get("start_time")
    et = market_info.get("end_time")
    if isinstance(st, datetime) and isinstance(et, datetime):
        return f"{st.strftime('%H:%M')} -> {et.strftime('%H:%M')} UTC"
    return "Unknown interval"


# =========================
# PRICE TRACKING (PYTH NETWORK)
# =========================
def get_live_pyth_price():
    try:
        url = "https://hermes.pyth.network/v2/updates/price/latest"
        r = requests.get(url, params={"ids[]": PYTH_BTC_ID}, timeout=3)
        r.raise_for_status()
        data = r.json()
        parsed = data.get("parsed", [])
        if not parsed:
            return None

        entry = parsed[0]
        price_info = entry.get("price", {}) or {}

        raw_price = int(price_info.get("price", 0))
        expo = int(price_info.get("expo", 0))

        raw_conf = price_info.get("conf", None)
        conf_val = None
        if raw_conf is not None:
            conf_val = int(raw_conf)

        publish_time = entry.get("publish_time") or entry.get("publishTime") or price_info.get("publish_time")

        price = raw_price * (10 ** expo)
        conf = conf_val * (10 ** expo) if conf_val is not None else None

        return {
            "price": float(price),
            "confidence": float(conf) if conf is not None else None,
            "publish_time": int(publish_time) if publish_time is not None else None,
        }
    except Exception:
        return None


def get_exact_pyth_price_before(ts, max_search_back_sec=30):
    try:
        ts = int(ts)

        for delta in range(0, max_search_back_sec + 1):
            t = ts - delta
            url = f"https://hermes.pyth.network/v2/updates/price/{t}"
            r = requests.get(url, params={"ids[]": PYTH_BTC_ID}, timeout=4)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.json()

            parsed = data.get("parsed", [])
            if not parsed:
                continue

            entry = parsed[0]
            price_info = entry.get("price", {}) or {}

            publish_time = entry.get("publish_time") or entry.get("publishTime") or price_info.get("publish_time")
            if publish_time is None:
                publish_time_int = None
            else:
                publish_time_int = int(publish_time)

            if publish_time_int is not None and publish_time_int > ts:
                continue

            raw_price = int(price_info.get("price", 0))
            expo = int(price_info.get("expo", 0))

            raw_conf = price_info.get("conf", None)
            conf_val = int(raw_conf) if raw_conf is not None else None

            price = raw_price * (10 ** expo)
            conf = conf_val * (10 ** expo) if conf_val is not None else None

            return {
                "price": float(price),
                "confidence": float(conf) if conf is not None else None,
                "publish_time": publish_time_int if publish_time_int is not None else t,
                "queried_time": t,
            }

        return None
    except Exception as e:
        log_event(f"Pyth exact fetch err: {str(e)[:60]}", "red")
        return None


def extract_strike_price(market_info):
    if not market_info:
        return None

    start_time = market_info.get("start_time")
    if not start_time:
        return None

    start_ts = int(start_time.timestamp())
    strike_data = get_exact_pyth_price_before(start_ts)

    if not strike_data:
        return None

    strike_price = strike_data["price"]
    publish_time = strike_data["publish_time"]

    log_event(
        f"🎯 Strike from Pyth @ {publish_time} (Δ {start_ts - publish_time}s) = ${strike_price:,.2f}",
        "cyan",
    )
    return float(strike_price)


def predict_resolution(strike_price, live_data):
    if not strike_price or not live_data:
        return None

    price = live_data.get("price")
    if price is None:
        return None

    diff = price - strike_price
    if diff > 0:
        winner = "UP"
    elif diff < 0:
        winner = "DOWN"
    else:
        winner = "TIE"

    conf = live_data.get("confidence")
    inside_conf = False
    if conf is not None:
        inside_conf = abs(diff) <= conf

    return {"winner": winner, "diff": diff, "inside_conf": inside_conf}


def detect_ui_mismatch(strike_price, live_data):
    if not strike_price or not live_data:
        return None

    oracle_price = live_data.get("price")
    if oracle_price is None:
        return None

    diff = abs(oracle_price - strike_price)
    if diff > 50:
        return f"⚠️ Large oracle deviation from strike: ${diff:,.2f}"
    return None


def draw_price_tracker(live_data, strike_price, favored_side):
    if not live_data:
        print(colored(" 💰 BTC PRICE TRACKER: Loading from Pyth Network...", "cyan", attrs=["bold"]))
        return

    price = live_data.get("price")
    conf = live_data.get("confidence")
    publish_time = live_data.get("publish_time")

    if price is None:
        print(colored(" 💰 BTC PRICE TRACKER: Loading from Pyth Network...", "cyan", attrs=["bold"]))
        return

    price_str = f"${price:,.2f}"

    print(colored(" ═══════════════════════════════════════════════════════════════", "white", attrs=["bold"]))
    print(colored(" 💰 BTC PRICE TRACKER (PYTH ORACLE)", "cyan", attrs=["bold"]))
    print(colored(" ─────────────────────────────────────────────────────────────────", "white"))
    print(colored(f" 📊 Current BTC:    {price_str}", "cyan", attrs=["bold"]))

    if publish_time is not None:
        print(colored(f" 📡 Pyth Publish:  {publish_time}", "white"))
    if conf is not None:
        print(colored(f" 📏 Confidence:    ±${conf:,.2f}", "yellow"))
    else:
        print(colored(f" 📏 Confidence:    [unavailable]", "yellow"))

    if strike_price is None:
        print(colored(" 🎯 Price to Beat:  [Waiting for Start Time / Resolving...]", "yellow"))
        print(colored(" ═══════════════════════════════════════════════════════════════", "white", attrs=["bold"]))
        return

    diff = price - strike_price
    diff_pct = (diff / strike_price) * 100 if strike_price else 0.0

    if diff > 0:
        position, position_color, symbol = "ABOVE", "green", "📈"
    elif diff < 0:
        position, position_color, symbol = "BELOW", "red", "📉"
    else:
        position, position_color, symbol = "AT", "yellow", "➡️"

    winning = False
    if favored_side == "UP" and diff > 0:
        winning = True
    elif favored_side == "DOWN" and diff < 0:
        winning = True

    strike_str = f"${strike_price:,.2f}"
    print(colored(f" 🎯 Price to Beat:  {strike_str}", "yellow", attrs=["bold"]))

    diff_str = f"${abs(diff):,.2f}"
    diff_display = f"+{diff_str}" if diff > 0 else f"-{diff_str}"
    pct_display = f"({diff_pct:+.2f}%)"

    print(
        colored(f" {symbol} Position: {position} by ", position_color, attrs=["bold"]) +
        colored(f"{diff_display} {pct_display}", position_color, attrs=["bold"])
    )

    if favored_side:
        if winning:
            print(colored(f" ✅ {favored_side} position is WINNING! 🎉", "green", attrs=["bold"]))
        else:
            print(colored(f" ⚠️ {favored_side} position currently losing", "red"))

    prediction = predict_resolution(strike_price, live_data)
    if prediction:
        win_color = "green" if prediction["winner"] == "UP" else "red"
        print(colored(f" 🔮 Predicted Winner: {prediction['winner']}", win_color, attrs=["bold"]))
        if prediction.get("inside_conf"):
            print(colored(" ⚠️ Inside confidence band — HIGH RISK ZONE", "yellow", attrs=["bold"]))

    mismatch = detect_ui_mismatch(strike_price, live_data)
    if mismatch:
        print(colored(f" {mismatch}", "red", attrs=["bold"]))

    bar_width = 50
    if strike_price > 0:
        ratio = price / strike_price
        if ratio > 1.002:
            ratio = 1.002
        elif ratio < 0.998:
            ratio = 0.998

        center_pos = int(bar_width / 2)
        current_pos = int((ratio - 0.998) / 0.004 * (bar_width - 1))
        current_pos = max(0, min(bar_width - 1, current_pos))

        bar = list("─" * bar_width)
        bar[center_pos] = "┃"
        bar[current_pos] = "●"

        bar_str = "".join(bar)
        print(colored(f" │{bar_str}│", position_color))
        print(colored(f" └{'Below':<{center_pos}}{'Target':^10}{'Above':>{bar_width-center_pos-10}}┘", "white"))

    print(colored(" ═══════════════════════════════════════════════════════════════", "white", attrs=["bold"]))


def draw_banner(hype_msg):
    color = next(BANNER_COLORS)
    print(
        colored(
            r"""
 __ __ ____ ____ _ _ _____ ________ __
| \/ |/ __ \ / __ \| \ | | | __ \| ____\ \ / /
| \ / | | | | | | | \| | | | | | |__ \ \ / /
| |\/| | | | | | | | . ` | | | | | __| \ \/ /
| | | | |__| | |__| | |\ | | |____| | |____ \ /
|_| |_|\____/ \____/|_| \_| |_____/|______| \/
""",
            color,
            attrs=["bold"],
        )
    )
    print(colored(" 🛰️  5-MIN MARKET SNIPER -- Decided Side • Instant Fill", "white", attrs=["bold"]))
    print(colored(f" {next(ROCKET_FRAMES)} {hype_msg}", "magenta", attrs=["bold"]))
    print()


def draw_scoreboard():
    uptime_min = (time.time() - SESSION_START) / 60
    print(colored(f" 🏆 {' SESSION SCOREBOARD ':=^54} 🏆", "yellow", attrs=["bold"]))
    print(
        colored(" │ ", "yellow")
        + colored(f"📈 Entries: {SESSION_ENTRIES:<4}", "green", attrs=["bold"])
        + " "
        + colored(f"🎯 Attempts: {SESSION_ATTEMPTS:<4}", "cyan")
        + " "
        + colored(f"⏩ Skips: {SESSION_SKIPS:<4}", "white")
        + " "
        + colored(f"🕒 Up: {uptime_min:.1f}m", "magenta")
        + colored(" │", "yellow")
    )
    print(
        colored(" │ ", "yellow")
        + colored(
            f"👤 Acct: {FUNDER_ADDRESS[:8]}...{FUNDER_ADDRESS[-4:] if len(FUNDER_ADDRESS) > 12 else ''}",
            "cyan",
            attrs=["bold"],
        )
        + " "
        + colored(f"💰 ${BET_AMOUNT:.1f}", "green")
        + " "
        + colored(f"🎯 @{MIN_PRICE:.2f}", "white")
        + colored(" │", "yellow")
    )
    print(colored(f" └{'─' * 56}┘", "yellow", attrs=["bold"]))


def draw_timer(time_left, market_info=None):
    mins = max(0, int(time_left // 60))
    secs = max(0, int(time_left % 60))
    pct = max(0.0, min(1.0, time_left / MARKET_DURATION))
    bar_width = 50
    filled = int(bar_width * pct)
    bar = "█" * filled + "░" * (bar_width - filled)

    if time_left > 20:
        color, label = "yellow", " WAITING FOR WINDOW... 🕒"
    elif time_left > STOP_THRESHOLD_SEC:
        color, label = "green", " 🎯 SNIPE WINDOW OPEN 🎯"
    else:
        color, label = "red", " 🏁 FINAL STRETCH 🏁"

    interval = format_market_interval(market_info)
    print()
    print(colored(f" ⏳ TIME LEFT: {mins:02d}:{secs:02d} {label}", color, attrs=["bold"]))
    print(colored(f" 📅 MARKET: {interval}", "cyan", attrs=["bold"]))
    print(colored(f" ├─ {bar} ─┤", color))


def draw_books(market_info, up_book, down_book, favored_side):
    if not market_info:
        return

    print()
    print(colored(f" 💬 {market_info.get('question', 'Market')}", "white", attrs=["bold"]))
    print(colored(f" 📅 WINDOW: {format_market_interval(market_info)}", "cyan", attrs=["bold"]))
    print(colored(f" 🔎 UP TOKEN:   {short_id(market_info.get('up_token_id'))}", "white"))
    print(colored(f" 🔎 DOWN TOKEN: {short_id(market_info.get('down_token_id'))}", "white"))

    def row(label, book, is_favored, base_color):
        if not book:
            print(colored(f" {label} | No book", base_color))
            return

        tag = ""
        if book.get("best_bid", 0) >= MIN_PRICE:
            tag = colored(" -- decided", "yellow")
        if is_favored:
            tag = colored(" 👈 DECIDED - TARGET", "yellow", attrs=["bold"])

        tick = book.get("tick_size")
        tick_txt = f" | tick {tick:g}" if tick else ""

        line = (
            colored(f" {label} | ", base_color, attrs=["bold"])
            + colored(f"Bid: ${book.get('best_bid', 0):.4f}", base_color, attrs=["bold"])
            + colored(" | ", "white")
            + colored(f"Ask: ${book.get('best_ask', 0):.4f}", base_color)
            + colored(tick_txt, "white")
            + tag
        )
        print(line)

    row("🟢 UP ", up_book, favored_side == "UP", "green")
    row("🔴 DOWN", down_book, favored_side == "DOWN", "red")


def draw_status(state, time_left):
    print(colored(" ─────────────────────────────────────────────────────────────────────", "white"))
    if state["entered"]:
        print(colored(" 🏆 FILLED - HOLDING TO EXPIRY 🏆", "green", attrs=["bold"]))
        return

    spin = next(SPINNER_FRAMES)
    if time_left > ENTRY_WINDOW_SEC:
        wait = int(time_left - ENTRY_WINDOW_SEC)
        print(colored(f" {spin} CHILLIN' -- {wait}s until snipe window", "white"))
        return

    if state["favored_side"] is None:
        print(colored(f" {spin} HUNTING FOR DECIDED SIDE...", "yellow", attrs=["bold"]))
        return

    side_color = "green" if state["favored_side"] == "UP" else "red"
    print(colored(f" {spin} LOCKED ON: ", "magenta", attrs=["bold"]) + colored(state["favored_side"], side_color, attrs=["bold"]))
    if state["open_order_id"]:
        print(colored(f" 📥 MARKET ORDER PENDING: {short_id(state['open_order_id'])}", "cyan", attrs=["bold"]))


def draw_event_log():
    print(colored(" 📜 RECENT EVENTS", "white", attrs=["bold"]))
    for ts, msg, color in list(EVENT_LOG):
        print(colored(f" {ts} | {msg}", color))


def draw_footer():
    print(colored(" ─────────────────────────────────────────────────────────────────────", "white"))
    print(colored(" Moon Dev 🌙 | Patience = Edge | One bullet per market", "magenta", attrs=["bold"]))


def draw_dashboard(state, time_left, up_book, down_book, hype_msg, live_data, strike_price):
    clear_screen()
    draw_banner(hype_msg)
    draw_scoreboard()
    draw_price_tracker(live_data, strike_price, state.get("favored_side"))
    draw_timer(time_left, state.get("market_info"))
    draw_books(state.get("market_info"), up_book, down_book, state.get("favored_side"))
    draw_status(state, time_left)
    draw_event_log()
    draw_footer()


# =========================
# TIME HELPERS
# =========================
def get_current_market_timestamp():
    now = datetime.now(timezone.utc)
    minutes = (now.minute // 5) * 5
    return now.replace(minute=minutes, second=0, microsecond=0).timestamp()


def get_time_remaining(market_ts):
    return max(0.0, market_ts + MARKET_DURATION - time.time())


# =========================
# MARKET PARSING
# =========================
def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def slug_start(ts):
    return int(ts // MARKET_DURATION) * MARKET_DURATION


def fetch_event_by_slug(slug):
    r = requests.get(f"{PROFILE_API}/events", params={"slug": slug}, timeout=8)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        if data.get("events"):
            return data["events"][0] if data["events"] else None
        return data
    return None


def parse_token_entries(market):
    entries = []

    def add_entry(tid, label):
        if tid is None:
            return
        tid = str(tid)
        lbl = str(label).lower() if label else ""
        entries.append({"token_id": tid, "label": lbl})

    fields = (
        "tokens",
        "clobTokenIds",
        "clob_token_ids",
        "outcomeTokens",
        "outcome_tokens",
    )

    for field in fields:
        raw = market.get(field)
        if raw is None:
            continue

        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                pass

        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    tid = (
                        item.get("token_id")
                        or item.get("tokenId")
                        or item.get("clobTokenId")
                        or item.get("id")
                    )
                    label = (
                        item.get("outcome")
                        or item.get("name")
                        or item.get("side")
                        or item.get("label")
                        or item.get("title")
                    )
                    add_entry(tid, label)
                elif item is not None:
                    add_entry(item, None)

        if len(entries) >= 2:
            break

    seen = set()
    uniq = []
    for e in entries:
        tid = e["token_id"]
        if tid not in seen:
            seen.add(tid)
            uniq.append(e)

    return uniq if len(uniq) >= 2 else None


def resolve_up_down_tokens(market):
    token_rows = parse_token_entries(market)
    if not token_rows or len(token_rows) < 2:
        return None, None

    up_id = None
    down_id = None

    for row in token_rows:
        label = (row.get("label") or "").lower()
        tid = row.get("token_id")
        if not tid:
            continue

        if any(k in label for k in ("up", "yes", "bull", "higher", "above")):
            if up_id is None:
                up_id = tid
        elif any(k in label for k in ("down", "no", "bear", "lower", "below")):
            if down_id is None:
                down_id = tid

    if up_id is None:
        up_id = token_rows[0]["token_id"]
    if down_id is None:
        down_id = token_rows[1]["token_id"]

    if up_id == down_id:
        return None, None

    return up_id, down_id


def extract_best_market(event):
    markets = event.get("markets") or []
    for m in markets:
        if not m.get("active", False):
            continue

        q = (m.get("question") or event.get("title") or "").lower()
        if "bitcoin" in q or "btc" in q:
            up_token, down_token = resolve_up_down_tokens(m)
            if up_token and down_token:
                end_dt = parse_dt(m.get("endDate") or m.get("end_date"))
                start_dt = None
                if end_dt:
                    start_dt = end_dt - timedelta(seconds=MARKET_DURATION)
                else:
                    start_dt = parse_dt(m.get("startDate") or m.get("start_date"))
                    if start_dt and not end_dt:
                        end_dt = start_dt + timedelta(seconds=MARKET_DURATION)

                if not start_dt or not end_dt:
                    return None

                return {
                    "question": m.get("question", event.get("title", "Market")),
                    "description": event.get("description", ""),
                    "up_token_id": up_token,
                    "down_token_id": down_token,
                    "slug": m.get("slug") or event.get("slug"),
                    "event_slug": event.get("slug"),
                    "event_id": event.get("id"),
                    "market_id": m.get("id"),
                    "start_time": start_dt,
                    "end_time": end_dt,
                    "metadata": m,
                }
    return None


def get_market_info():
    base = slug_start(time.time())
    candidates = [base, base - MARKET_DURATION, base + MARKET_DURATION]

    for start in candidates:
        slug = f"btc-updown-5m-{start}"
        try:
            event = fetch_event_by_slug(slug)
            if event:
                market = extract_best_market(event)
                if market:
                    print(colored(f"✅ Watching BTC 5m: {format_market_interval(market)}", "green"))
                    if DEBUG_TOKEN_MAPPING:
                        print(colored(f"   UP:   {short_id(market.get('up_token_id'))}", "white"))
                        print(colored(f"   DOWN: {short_id(market.get('down_token_id'))}", "white"))
                    return market
        except Exception:
            continue

    try:
        r = requests.get(
            f"{PROFILE_API}/events",
            params={"active": "true", "closed": "false", "limit": 100},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("events") if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = data.get("data", []) if isinstance(data, dict) else []

        for event in items:
            market = extract_best_market(event)
            if market:
                print(colored(f"✅ Watching BTC 5m: {format_market_interval(market)}", "green"))
                if DEBUG_TOKEN_MAPPING:
                    print(colored(f"   UP:   {short_id(market.get('up_token_id'))}", "white"))
                    print(colored(f"   DOWN: {short_id(market.get('down_token_id'))}", "white"))
                return market
    except Exception as e:
        print(colored(f"Market fetch error: {e}", "red"))

    return None


# =========================
# ORDER BOOK PARSING
# =========================
def extract_price_size(level):
    if level is None:
        return None, None

    if isinstance(level, dict):
        price = level.get("price", level.get("p"))
        size = level.get("size", level.get("s"))
        try:
            price = float(price) if price is not None else None
        except Exception:
            price = None
        try:
            size = float(size) if size is not None else None
        except Exception:
            size = None
        return price, size

    if isinstance(level, (list, tuple)) and len(level) >= 1:
        nums = []
        for x in level[:2]:
            try:
                nums.append(float(x))
            except Exception:
                nums.append(None)

        if len(nums) == 1:
            return nums[0], None

        a, b = nums[0], nums[1]

        a_ok = a is not None and 0.0 <= a <= 1.5
        b_ok = b is not None and 0.0 <= b <= 1.5

        if a_ok and not b_ok:
            return a, b
        if b_ok and not a_ok:
            return b, a

        return a, b

    return None, None


def find_book_levels(payload):
    if payload is None:
        return [], []

    if isinstance(payload, dict):
        if "bids" in payload or "asks" in payload:
            return payload.get("bids", []) or [], payload.get("asks", []) or []

        for key in ("data", "book", "orderbook", "order_book", "result", "payload"):
            if key in payload:
                bids, asks = find_book_levels(payload[key])
                if bids or asks:
                    return bids, asks

    return [], []


def best_level_price(levels, side):
    parsed = []
    for lvl in levels or []:
        price, size = extract_price_size(lvl)
        if price is not None:
            parsed.append((price, size))

    if not parsed:
        return None, None, []

    if side == "bid":
        best = max(parsed, key=lambda x: x[0])
    else:
        best = min(parsed, key=lambda x: x[0])

    prices = [p for p, _ in parsed]
    return round(float(best[0]), 4), best[1], prices


def _snap_tick(raw_tick: float | None) -> float:
    if not raw_tick or raw_tick <= 0:
        return 0.01
    common = [0.0001, 0.001, 0.01]
    return min(common, key=lambda x: abs(x - raw_tick))


def estimate_tick_size(bid_prices, ask_prices):
    prices = []
    for p in (bid_prices or [])[:15]:
        if p is not None:
            prices.append(round(float(p), 6))
    for p in (ask_prices or [])[:15]:
        if p is not None:
            prices.append(round(float(p), 6))

    prices = sorted(set(prices))
    if len(prices) < 3:
        return 0.01

    diffs = []
    for i in range(len(prices) - 1):
        d = round(prices[i + 1] - prices[i], 6)
        if d > 0:
            diffs.append(d)

    if not diffs:
        return 0.01

    return _snap_tick(min(diffs))


def get_order_book(token_id):
    if not token_id:
        return None

    token_id = str(token_id)

    if SDK_AVAILABLE and client is not None:
        try:
            book = client.get_order_book(token_id)
            book = _as_dict(book)
            if book:
                bids, asks = find_book_levels(book)
                best_bid, _, bid_prices = best_level_price(bids, "bid")
                best_ask, _, ask_prices = best_level_price(asks, "ask")
                tick = estimate_tick_size(bid_prices, ask_prices)

                if best_bid is not None or best_ask is not None:
                    return {
                        "token_id": token_id,
                        "best_bid": best_bid if best_bid is not None else 0.0,
                        "best_ask": best_ask if best_ask is not None else 1.0,
                        "tick_size": tick,
                    }
        except Exception:
            pass

    try:
        url = f"{CLOB_API}/book?token_id={token_id}"
        r = requests.get(url, timeout=8)

        if r.status_code == 404:
            return None

        r.raise_for_status()
        data = r.json()

        if DEBUG_BOOK_PAYLOAD:
            log_event(f"RAW {token_id[:8]}: {str(data)[:80]}", "white")

        bids, asks = find_book_levels(data)
        best_bid, _, bid_prices = best_level_price(bids, "bid")
        best_ask, _, ask_prices = best_level_price(asks, "ask")
        tick = estimate_tick_size(bid_prices, ask_prices)

        if best_bid is None:
            best_bid = 0.0
        if best_ask is None:
            best_ask = 1.0

        return {
            "token_id": token_id,
            "best_bid": round(best_bid, 4),
            "best_ask": round(best_ask, 4),
            "tick_size": tick,
        }
    except Exception as e:
        if "404" not in str(e):
            log_event(f"Book REST error: {str(e)[:48]}", "red")
        return None


# =========================
# TRADING LOGIC (MARKET ORDERS)
# =========================
def pick_decided_side(up_book, down_book):
    """Decide based on stronger bid, not ask."""
    if not up_book or not down_book:
        return None, None

    up_bid = up_book.get("best_bid", 0.0)
    down_bid = down_book.get("best_bid", 0.0)

    if up_bid >= MIN_PRICE and up_bid > down_bid:
        return "UP", up_book
    if down_bid >= MIN_PRICE and down_bid > up_bid:
        return "DOWN", down_book

    return None, None


def check_order_fill(state):
    """Check if market order got filled. Returns True if filled."""
    if DRY_RUN or not client or not state["last_order_id"]:
        return False

    try:
        oid = state["last_order_id"]

        if hasattr(client, "get_order"):
            order = client.get_order(oid)
        else:
            return False

        order = _as_dict(order)
        if not order:
            return False

        status = (order.get("status") or order.get("state") or "").upper()

        if status == "FILLED":
            state["entered"] = True
            state["entry_fill_price"] = float(order.get("price", 0.0))
            global SESSION_ENTRIES
            SESSION_ENTRIES += 1
            log_event(f"💰 FILLED @ ${state['entry_fill_price']:.3f}!", "green")
            return True

        if status in ["CANCELLED", "CANCELED", "EXPIRED"]:
            log_event(f"Order {status}", "yellow")
            state["open_order_id"] = None
            state["last_order_id"] = None
            return False

    except Exception as e:
        log_event(f"Fill check err: {str(e)[:60]}", "red")

    return False


def _place_market_order(state, token_id, amount):
    """
    Place a market order using MarketOrderArgs.
    amount = USDC dollars (for BUY side)
    Uses FOK (Fill-or-Kill) for immediate full execution.
    """
    global SESSION_ATTEMPTS
    SESSION_ATTEMPTS += 1

    if DRY_RUN:
        print(colored(f"🔒 DRY RUN: Market Buy ${amount:.2f} USDC", "yellow"))
        state["open_order_id"] = f"dry_{int(time.time())}"
        state["last_order_id"] = state["open_order_id"]
        return True

    if not client:
        log_event("No client. Cannot place live order.", "red")
        return False

    try:
        market_order = MarketOrderArgs(
            token_id=str(token_id),
            amount=float(amount),  # USDC for BUY
            side=Side.BUY,
            order_type=OrderType.FOK,
        )

        resp = client.create_and_post_market_order(
            order_args=market_order,
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.FOK,
        )

        resp = _as_dict(resp) or {}
        state["last_order_id"] = resp.get("orderID") or resp.get("order_id") or resp.get("id")
        state["open_order_id"] = state["last_order_id"]
        log_event(f"✅ Market buy placed ${amount:.2f} USDC", "cyan")
        return True

    except Exception as e:
        log_event(f"Market order failed: {str(e)[:90]}", "red")
        return False


# =========================
# MAIN LOOP
# =========================
def main():
    global SESSION_SKIPS

    state = {
        "market_ts": None,
        "market_info": None,
        "favored_side": None,
        "favored_token_id": None,
        "favored_tick_size": 0.01,
        "open_order_id": None,
        "entered": False,
        "entry_fill_price": None,
        "last_order_id": None,
        "last_book_fetch": 0.0,
        "last_order_update": 0.0,
        "last_fill_check": 0.0,
        "last_event_update": 0.0,
    }

    last_draw = 0
    last_hype_change = 0
    last_price_fetch = 0
    hype_msg = random.choice(HYPE_MESSAGES)
    up_book = None
    down_book = None
    live_data = None
    strike_price = None

    print(colored("🚀 Moon Dev 5min Market Sniper Started", "green"))
    print(colored("🔒 LIVE MODE" if not DRY_RUN else "🔒 DRY RUN MODE", "yellow", attrs=["bold"]))
    if client:
        print(colored("✅ CLOB Client: CONNECTED", "green"))
    else:
        print(colored("⚠️ CLOB Client: NOT CONNECTED - Orders will fail", "red"))

    while True:
        now = time.time()
        market_ts = get_current_market_timestamp()
        time_left = get_time_remaining(market_ts)

        if now - last_hype_change > 12:
            hype_msg = random.choice(HYPE_MESSAGES)
            last_hype_change = now

        # Fetch latest Pyth BTC price every 3 seconds
        if now - last_price_fetch > 3:
            live_data = get_live_pyth_price()
            last_price_fetch = now

            # Retrieve missing strike_price once the market officially starts via Pyth timestamp
            if strike_price is None and state["market_info"]:
                if now >= state["market_info"]["start_time"].timestamp():
                    strike_price = extract_strike_price(state["market_info"])
                    if strike_price:
                        log_event(f"🎯 Pyth Oracle Strike locked: ${strike_price:,.2f}", "cyan")

            # Continuously check Polymarket API for overriding InitialValue
            if state["market_info"]:
                market_start = state["market_info"]["start_time"].timestamp()
                if now >= market_start:
                    if now - state["last_event_update"] > 10:
                        try:
                            event = fetch_event_by_slug(state["market_info"]["event_slug"])
                            if event:
                                updated_market = extract_best_market(event)
                                if updated_market:
                                    state["market_info"] = updated_market
                                    if isinstance(updated_market.get("metadata"), dict):
                                        meta = updated_market["metadata"]
                                        for key in ["strike", "strikePrice", "strike_price", "target", "targetPrice", "initialValue"]:
                                            if key in meta:
                                                try:
                                                    api_strike = float(meta[key])
                                                    if api_strike != strike_price:
                                                        strike_price = api_strike
                                                        log_event(f"🎯 Official API Strike updated: ${strike_price:,.2f}", "cyan")
                                                except (ValueError, TypeError):
                                                    pass
                        except Exception:
                            pass
                        state["last_event_update"] = now

        if state["market_info"] is None:
            state["market_info"] = get_market_info()
            if state["market_info"]:
                state["market_ts"] = state["market_info"]["start_time"].timestamp()
                strike_price = extract_strike_price(state["market_info"])
                if strike_price:
                    log_event(f"🎯 Price to Beat (Strike): ${strike_price:,.2f}", "cyan")
        else:
            market_end = state["market_info"]["end_time"].timestamp()
            if now > market_end + 5:
                log_event("Market expired, finding next...", "yellow")
                state["market_info"] = None
                state["favored_side"] = None
                state["favored_token_id"] = None
                state["favored_tick_size"] = 0.01
                state["entered"] = False
                state["open_order_id"] = None
                state["last_order_id"] = None
                strike_price = None
                continue

        if state["market_info"] and now - state["last_book_fetch"] > 2:
            up_book = get_order_book(state["market_info"].get("up_token_id"))
            down_book = get_order_book(state["market_info"].get("down_token_id"))
            state["last_book_fetch"] = now

        if state["last_order_id"] and not state["entered"] and now - state["last_fill_check"] > 1.5:
            check_order_fill(state)
            state["last_fill_check"] = now

        if state["market_info"] and not state["entered"]:
            market_end_ts = state["market_info"]["end_time"].timestamp()
            market_time_left = max(0.0, market_end_ts - now)

            if ENTRY_WINDOW_SEC >= market_time_left > STOP_THRESHOLD_SEC:
                if now - state["last_order_update"] >= ORDER_UPDATE_INTERVAL:
                    state["last_order_update"] = now

                    if state["favored_side"] is None:
                        side, favored_book = pick_decided_side(up_book, down_book)
                        if side:
                            state["favored_side"] = side
                            state["favored_token_id"] = (
                                state["market_info"]["up_token_id"] if side == "UP" else state["market_info"]["down_token_id"]
                            )
                            state["favored_tick_size"] = (favored_book or {}).get("tick_size") or 0.01
                            log_event(f"🎯 LOCKED {side} {market_time_left:.0f}s left", "magenta")

                    if state["favored_side"]:
                        token_id = state["favored_token_id"]

                        # --- Ensure there is at least a $20 difference before executing ---
                        has_enough_gap = False
                        btc_price_val = live_data.get("price") if live_data else None

                        if btc_price_val is not None and strike_price is not None:
                            if abs(btc_price_val - strike_price) >= MIN_PRICE_GAP:
                                has_enough_gap = True

                        if has_enough_gap:
                            # Market order: only fire once per window (no price tracking needed)
                            if not state["open_order_id"]:
                                _place_market_order(state, token_id=token_id, amount=BET_AMOUNT)
                        else:
                            if state["open_order_id"]:
                                log_event(f"Gap < ${MIN_PRICE_GAP}, skipped", "yellow")
                            else:
                                SESSION_SKIPS += 1

            elif market_time_left <= STOP_THRESHOLD_SEC:
                if state["open_order_id"] and not state["entered"]:
                    check_order_fill(state)
                    if not state["entered"]:
                        log_event("Window closed, order did not fill", "yellow")

        if now - last_draw >= 0.5:
            last_draw = now
            market_time_left = (
                state["market_info"]["end_time"].timestamp() - now
                if state["market_info"]
                else time_left
            )
            draw_dashboard(state, market_time_left, up_book, down_book, hype_msg, live_data, strike_price)

        time.sleep(0.3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(colored("\n👋 Moon Dev shutdown", "yellow"))
    except Exception as e:
        print(colored(f"\n💥 Error: {e}", "red"))
