from app import app, connect
from flask import session, jsonify, request
from datetime import date
import random
import time

# Database migration
with connect() as db:
    columns = [r["name"] for r in db.execute(
        "PRAGMA table_info(users)"
    ).fetchall()]

    if "free_spins" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN free_spins INTEGER NOT NULL DEFAULT 0")

    if "pending_scatter" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN pending_scatter INTEGER NOT NULL DEFAULT 0")

    if "spin_started_at" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN spin_started_at REAL")

    db.execute("""
        CREATE TABLE IF NOT EXISTS jp_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("INSERT OR IGNORE INTO jp_stats (id, total) VALUES (1, 0)")


@app.get("/api/jp")
def get_jp():
    with connect() as db:
        row = db.execute("SELECT total FROM jp_stats WHERE id=1").fetchone()
    return jsonify(jp_total=row["total"] if row else 0)


@app.post("/api/bonus")
def daily_bonus():
    uid = session.get("user_id")
    if not uid:
        return jsonify(error="Please login"), 401

    today = date.today().isoformat()

    with connect() as db:
        try:
            db.execute(
                "INSERT INTO daily_bonus(user_id,bonus_date,amount) VALUES(?,?,?)",
                (uid, today, 5000)
            )
        except Exception:
            return jsonify(error="Today's bonus already claimed"), 409

        db.execute("UPDATE users SET coins=coins+5000 WHERE id=?", (uid,))
        user = db.execute(
            "SELECT coins FROM users WHERE id=?", (uid,)
        ).fetchone()

    return jsonify(bonus=5000, coins=user["coins"])


@app.post("/api/collect")
def collect_scatter():
    return jsonify(error="Scatter rewards are credited automatically"), 400


@app.post("/api/spin")
def play_spin():
    uid = session.get("user_id")
    if not uid:
        return jsonify(error="Please login"), 401

    data = request.get_json(silent=True) or {}

    try:
        bet = int(data.get("bet", 0))
    except (TypeError, ValueError):
        return jsonify(error="Invalid bet"), 400

    if bet < 80 or bet > 80000 or bet % 80 != 0:
        return jsonify(error="Invalid bet level"), 400

    use_free = bool(data.get("free_spin", False))

    symbols = [
        "elephant_green.png", "deer_white.png",
        "buffalo_redbrown.png", "lion_red.png",
        "zebra_blue.png", "A.png", "K.png",
        "Q.png", "10.png", "9.png"
    ]

    paytable = {
        "buffalo_redbrown.png": 30,
        "lion_red.png": 25,
        "elephant_green.png": 20,
        "deer_white.png": 15,
        "zebra_blue.png": 10,
        "A.png": 10,
        "K.png": 9,
        "Q.png": 8,
        "9.png": 7,
        "10.png": 5
    }

    with connect() as db:
        user = db.execute(
            "SELECT coins,free_spins,role,spin_started_at FROM users WHERE id=?", (uid,)
        ).fetchone()

        if not user:
            return jsonify(error="Account not found"), 404

        # Start the 20-minute timer on the first spin
        now = time.time()
        spin_started_at = user["spin_started_at"]
        if spin_started_at is None:
            spin_started_at = now
            db.execute(
                "UPDATE users SET spin_started_at=? WHERE id=?",
                (spin_started_at, uid)
            )
        scatter_unlocked = now - float(spin_started_at) >= 1200

        is_owner = user["role"] == "owner"
        free_spins = user["free_spins"]

        if use_free and free_spins <= 0:
            return jsonify(error="No free spins"), 400

        if not is_owner and not use_free and user["coins"] < bet:
            return jsonify(error="Not enough credits"), 400

        results = [
            [random.choices(symbols, weights=[1, 1, 1.3, 1, 1, 1, 1, 1, 1, 1], k=1)[0] for _ in range(4)]
            for _ in range(5)
        ]

        # SCATTER stays locked for the first 20 minutes
        scatter_count = 0
        if scatter_unlocked:
            roll = random.random()
            if roll < 0.0002:
                scatter_count = 5
            elif roll < 0.0012:
                scatter_count = 4
            elif roll < 0.0062:
                scatter_count = 3
            elif roll < 0.1062:
                scatter_count = 2
            elif roll < 0.3062:
                scatter_count = 1

        scatter_reward = 0
        triggered = 0

        if use_free:
            triggered = {2: 4, 3: 8, 4: 12, 5: 20}.get(scatter_count, 0)
            if scatter_count == 3:
                scatter_reward = bet * 2
            elif scatter_count == 4:
                scatter_reward = bet * 5
            elif scatter_count == 5:
                scatter_reward = bet * 8
        else:
            if scatter_count == 3:
                scatter_reward = bet * 2
                triggered = 8
            elif scatter_count == 4:
                scatter_reward = bet * 5
                triggered = 12
            elif scatter_count == 5:
                scatter_reward = bet * 8
                triggered = 20

        # At most one SCATTER on each selected reel
        if scatter_count:
            selected_reels = random.sample(range(5), scatter_count)
            for column in selected_reels:
                row = random.randrange(4)
                results[column][row] = "SCATTER"

        # WILD: 50% chance per spin, 1 to 6 wilds on reels 3-5
        if random.random() < 0.10:
            available = [
                (col, row)
                for col in range(1, 4)
                for row in range(4)
                if results[col][row] != "SCATTER"
            ]
            wild_count = random.randint(1, min(6, len(available)))
            for col, row in random.sample(available, wild_count):
                results[col][row] = "wild.png"

        # WILD payout: first 3 reels must match, then continue right
        symbol_win = 0
        win_details = []

        wild_multipliers = {
            (col, row): 3
            for col in range(5)
            for row in range(4)
            if results[col][row] == "wild.png"
        }

        for symbol, base_value in paytable.items():
            counts = []
            for column in range(5):
                count = (
                    results[column].count(symbol)
                    + results[column].count("wild.png")
                )
                if count == 0:
                    break
                counts.append(count)

            matched_reels = len(counts)
            if matched_reels < 3:
                continue

            payout_units = 0
            ways = 1

            for col in range(matched_reels):
                payout_units += results[col].count(symbol)
                ways *= counts[col]

                for row, item in enumerate(results[col]):
                    if item == "wild.png":
                        payout_units += wild_multipliers[(col, row)]

            amount = max(1, round(
                base_value * (bet / 80) * payout_units
            ))
            symbol_win += amount

            win_details.append({
                "symbol": symbol,
                "reels": matched_reels,
                "ways": ways,
                "amount": amount
            })

        if use_free:
            free_spins -= 1

        free_spins += triggered

        total_win = symbol_win + scatter_reward
        new_coins = user["coins"] + (0 if is_owner or use_free else -bet) + total_win

        if total_win >= bet * 20:
            win_type = "EPIC WIN"
        elif total_win >= bet * 10:
            win_type = "MEGA WIN"
        elif total_win >= bet * 5:
            win_type = "BIG WIN"
        elif total_win > 0:
            win_type = "WIN"
        else:
            win_type = "NONE"

        db.execute(
            """UPDATE users
               SET coins=?, free_spins=?, pending_scatter=0
               WHERE id=?""",
            (new_coins, free_spins, uid)
        )

        if not use_free:
            db.execute(
                "UPDATE jp_stats SET total = total + ? WHERE id=1",
                (bet,)
            )

        jp_row = db.execute(
            "SELECT total FROM jp_stats WHERE id=1"
        ).fetchone()
        jp_total = jp_row["total"] if jp_row else 0

    return jsonify(
        jp_total=jp_total,
        results=results,
        bet=bet,
        win=total_win,
        symbol_win=symbol_win,
        coins=new_coins,
        free_spins=free_spins,
        triggered_free_spins=triggered,
        scatter_count=scatter_count,
        scatter_reward=scatter_reward,
        pending_scatter=0,
        win_details=win_details,
        win_type=win_type,
        used_free_spin=use_free
    )
