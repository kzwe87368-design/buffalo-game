from flask import Flask, request, jsonify, session, send_file, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, re, os, hmac

app = Flask(__name__)
app.secret_key = os.environ.get("BUFFALO_SECRET", os.urandom(32))

DB = "database/buffalo.db"

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def setup():
    os.makedirs("database", exist_ok=True)
    with connect() as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            coins INTEGER NOT NULL DEFAULT 10000,
            role TEXT NOT NULL DEFAULT 'user',
            free_spins INTEGER NOT NULL DEFAULT 0,
            pending_scatter INTEGER NOT NULL DEFAULT 0,
            spin_started_at REAL
        )
        """)

@app.get("/")
def home():
    return send_file("login.html")

@app.get("/lobby")
def lobby():
    if "user_id" not in session:
        return jsonify(error="Please login"), 401
    return send_file("lobby.html")

@app.get("/game")
def game():
    if "user_id" not in session:
        return jsonify(error="Please login"), 401
    return send_file("index.html")

@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory("assets", filename)

@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not re.fullmatch(r"[a-zA-Z0-9_]{3,20}", username):
        return jsonify(error="Username must be 3-20 characters"), 400

    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters"), 400

    try:
        with connect() as db:
            db.execute(
                "INSERT INTO users(username,password) VALUES(?,?)",
                (username, generate_password_hash(password))
            )
        return jsonify(message="Account created", coins=10000), 201
    except sqlite3.IntegrityError:
        return jsonify(error="Username already exists"), 409

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    with connect() as db:
        user = db.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

    if not user or not check_password_hash(user["password"], password):
        return jsonify(error="Invalid username or password"), 401

    session.clear()
    session["user_id"] = user["id"]
    return jsonify(message="Login successful", username=user["username"])

@app.get("/api/me")
def me():
    if "user_id" not in session:
        return jsonify(error="Please login"), 401

    with connect() as db:
        user = db.execute(
            "SELECT id,username,coins,free_spins,pending_scatter,role FROM users WHERE id=?",
            (session["user_id"],)
        ).fetchone()

    if not user:
        session.clear()
        return jsonify(error="Account not found"), 404

    result = dict(user)
    result["is_owner"] = (user["role"] == "owner")
    result.pop("role", None)
    return jsonify(result)

@app.post("/api/owner/activate")
def activate_owner():
    expected = os.environ.get("BUFFALO_OWNER_ACTIVATION_KEY", "")
    supplied = request.headers.get("X-Owner-Activation-Key", "")

    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify(error="Unauthorized"), 403

    with connect() as db:
        user = db.execute(
            "SELECT id FROM users WHERE username='BUFFALO_OWNER'"
        ).fetchone()

        if not user:
            return jsonify(error="Owner account not found"), 404

        db.execute(
            "UPDATE users SET role='owner' WHERE id=?", (user["id"],)
        )

    return jsonify(message="Owner activated")


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(message="Logged out")

import sys
sys.modules["app"] = sys.modules[__name__]

setup()
import admin_server
import game_api
import shan_api

@app.get("/shan")
def shan_game():
    if "user_id" not in session:
        return jsonify(error="Please login"), 401
    return send_file("shan.html")


@app.get("/sw.js")
def service_worker():
    response = send_from_directory("static", "sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
