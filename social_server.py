from flask import request, jsonify, session
from app import app, connect
import sqlite3
import time

def setup_social():
    with connect() as db:
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(users)")
        }
        if "last_seen" not in columns:
            db.execute(
                "ALTER TABLE users ADD COLUMN last_seen REAL NOT NULL DEFAULT 0"
            )

        db.execute("""
            CREATE TABLE IF NOT EXISTS friend_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                UNIQUE(sender_id, receiver_id)
            )
        """)

setup_social()


def current_user():
    return session.get("user_id")


@app.post("/api/social/ping")
def social_ping():
    uid = current_user()
    if not uid:
        return jsonify(error="Please login"), 401

    with connect() as db:
        db.execute(
            "UPDATE users SET last_seen=? WHERE id=?",
            (time.time(), uid)
        )
    return jsonify(message="Online status updated")


@app.get("/api/social")
def social_overview():
    uid = current_user()
    if not uid:
        return jsonify(error="Please login"), 401

    now = time.time()

    with connect() as db:
        friends = db.execute("""
            SELECT u.id, u.username,
                   COALESCE(NULLIF(u.display_name,''),u.username) AS display_name,
                   u.avatar, u.level, u.last_seen
            FROM friend_requests f
            JOIN users u ON u.id =
                CASE WHEN f.sender_id=? THEN f.receiver_id ELSE f.sender_id END
            WHERE f.status='accepted'
              AND (f.sender_id=? OR f.receiver_id=?)
            ORDER BY u.username
        """, (uid, uid, uid)).fetchall()

        incoming = db.execute("""
            SELECT f.id AS request_id, u.username,
                   COALESCE(NULLIF(u.display_name,''),u.username) AS display_name,
                   u.avatar, u.level
            FROM friend_requests f
            JOIN users u ON u.id=f.sender_id
            WHERE f.receiver_id=? AND f.status='pending'
            ORDER BY f.created_at DESC
        """, (uid,)).fetchall()

        online = db.execute("""
            SELECT id, username,
                   COALESCE(NULLIF(display_name,''),username) AS display_name,
                   avatar, level
            FROM users
            WHERE id!=? AND last_seen>?
            ORDER BY last_seen DESC
            LIMIT 20
        """, (uid, now - 120)).fetchall()

        ranking = db.execute("""
            SELECT id, username,
                   COALESCE(NULLIF(display_name,''),username) AS display_name,
                   avatar, level, xp
            FROM users
            ORDER BY level DESC, xp DESC, id ASC
            LIMIT 10
        """).fetchall()

    return jsonify(
        friends=[dict(x, online=(x["last_seen"] > now - 120)) for x in friends],
        incoming=[dict(x) for x in incoming],
        online_players=[dict(x) for x in online],
        ranking=[dict(x) for x in ranking]
    )


@app.get("/api/social/search")
def social_search():
    uid = current_user()
    if not uid:
        return jsonify(error="Please login"), 401

    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify(players=[])

    with connect() as db:
        rows = db.execute("""
            SELECT id, username,
                   COALESCE(NULLIF(display_name,''),username) AS display_name,
                   avatar, level
            FROM users
            WHERE id!=? AND username LIKE ?
            ORDER BY username
            LIMIT 20
        """, (uid, "%" + q + "%")).fetchall()

    return jsonify(players=[dict(x) for x in rows])


@app.post("/api/social/request")
def social_request():
    uid = current_user()
    if not uid:
        return jsonify(error="Please login"), 401

    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()

    with connect() as db:
        target = db.execute(
            "SELECT id FROM users WHERE username=?",
            (username,)
        ).fetchone()

        if not target:
            return jsonify(error="Player not found"), 404

        target_id = target["id"]
        if target_id == uid:
            return jsonify(error="You cannot add yourself"), 400

        existing = db.execute("""
            SELECT status FROM friend_requests
            WHERE (sender_id=? AND receiver_id=?)
               OR (sender_id=? AND receiver_id=?)
        """, (uid, target_id, target_id, uid)).fetchone()

        if existing:
            return jsonify(error="Request or friendship already exists"), 409

        db.execute("""
            INSERT INTO friend_requests(sender_id,receiver_id,status,created_at)
            VALUES(?,?,'pending',?)
        """, (uid, target_id, time.time()))

    return jsonify(message="Friend request sent"), 201


@app.post("/api/social/respond")
def social_respond():
    uid = current_user()
    if not uid:
        return jsonify(error="Please login"), 401

    data = request.get_json(silent=True) or {}
    try:
        request_id = int(data.get("request_id", 0))
    except (TypeError, ValueError):
        return jsonify(error="Invalid request ID"), 400

    action = data.get("action")
    if action not in ("accept", "reject"):
        return jsonify(error="Invalid action"), 400

    with connect() as db:
        row = db.execute("""
            SELECT id FROM friend_requests
            WHERE id=? AND receiver_id=? AND status='pending'
        """, (request_id, uid)).fetchone()

        if not row:
            return jsonify(error="Friend request not found"), 404

        status = "accepted" if action == "accept" else "rejected"
        db.execute(
            "UPDATE friend_requests SET status=? WHERE id=?",
            (status, request_id)
        )

    return jsonify(message="Friend request " + status)
