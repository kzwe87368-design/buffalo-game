from app import app, connect
from flask import session, jsonify, request
from datetime import date

MISSIONS = {
    "login": {"title": "Daily Login", "target": 1, "reward": 1000},
    "buffalo_spin": {"title": "BUFFALO Slot", "target": 10, "reward": 2000},
    "shan_round": {"title": "Shan Koe Mee", "target": 3, "reward": 3000},
}

def today():
    return date.today().isoformat()

def ensure_daily_missions(uid):
    with connect() as db:
        for key in MISSIONS:
            db.execute(
                """INSERT OR IGNORE INTO daily_missions
                   (user_id, mission_date, mission_key, progress, claimed)
                   VALUES (?, ?, ?, 0, 0)""",
                (uid, today(), key)
            )
        db.execute(
            """UPDATE daily_missions SET progress=1
               WHERE user_id=? AND mission_date=? AND mission_key='login'
               AND progress < 1""",
            (uid, today())
        )

def add_mission_progress(uid, mission_key, amount=1):
    if mission_key not in MISSIONS or amount <= 0:
        return
    ensure_daily_missions(uid)
    with connect() as db:
        db.execute(
            """UPDATE daily_missions
               SET progress=MIN(progress + ?, ?)
               WHERE user_id=? AND mission_date=? AND mission_key=?""",
            (amount, MISSIONS[mission_key]["target"], uid, today(), mission_key)
        )

@app.get("/api/missions")
def get_missions():
    uid = session.get("user_id")
    if not uid:
        return jsonify(error="Please login"), 401

    ensure_daily_missions(uid)
    with connect() as db:
        rows = db.execute(
            """SELECT mission_key, progress, claimed
               FROM daily_missions
               WHERE user_id=? AND mission_date=?""",
            (uid, today())
        ).fetchall()
        user = db.execute("SELECT coins FROM users WHERE id=?", (uid,)).fetchone()

    result = []
    for row in rows:
        key = row["mission_key"]
        info = MISSIONS[key]
        progress = row["progress"]
        result.append({
            "key": key,
            "title": info["title"],
            "target": info["target"],
            "reward": info["reward"],
            "progress": progress,
            "completed": progress >= info["target"],
            "claimed": bool(row["claimed"])
        })
    return jsonify(missions=result, coins=user["coins"] if user else 0)

@app.post("/api/missions/claim")
def claim_mission():
    uid = session.get("user_id")
    if not uid:
        return jsonify(error="Please login"), 401

    data = request.get_json(silent=True) or {}
    key = str(data.get("mission_key", ""))
    if key not in MISSIONS:
        return jsonify(error="Invalid mission"), 400

    ensure_daily_missions(uid)
    info = MISSIONS[key]

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            """UPDATE daily_missions SET claimed=1
               WHERE user_id=? AND mission_date=? AND mission_key=?
               AND progress>=? AND claimed=0""",
            (uid, today(), key, info["target"])
        ).rowcount

        if changed != 1:
            db.rollback()
            return jsonify(error="Mission incomplete or already claimed"), 409

        db.execute(
            "UPDATE users SET coins=coins+? WHERE id=?",
            (info["reward"], uid)
        )
        user = db.execute("SELECT coins FROM users WHERE id=?", (uid,)).fetchone()

    return jsonify(message="Mission reward claimed", reward=info["reward"], coins=user["coins"])

def setup_missions():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS daily_missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mission_date TEXT NOT NULL,
                mission_key TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                claimed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, mission_date, mission_key)
            )
        """)

setup_missions()
