from app import app, connect
from flask import session, jsonify, send_file, request

def is_owner():
    uid = session.get("user_id")
    if not uid:
        return False
    with connect() as db:
        user = db.execute(
            "SELECT role FROM users WHERE id=?", (uid,)
        ).fetchone()
    return bool(user and user["role"] == "owner")

@app.get("/admin")
def admin():
    if not is_owner():
        return "Owner access only", 403
    return send_file("admin.html")

@app.get("/api/admin/users")
def admin_users():
    if not is_owner():
        return jsonify(error="Owner access only"), 403
    with connect() as db:
        users = db.execute(
            "SELECT id, username, coins, role FROM users ORDER BY id"
        ).fetchall()
    return jsonify(users=[dict(u) for u in users])

@app.post("/api/admin/coins")
def admin_coins():
    if not is_owner():
        return jsonify(error="Owner access only"), 403
    data = request.get_json(silent=True) or {}
    try:
        uid = int(data.get("id"))
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify(error="Invalid values"), 400
    if amount == 0 or abs(amount) > 1000000:
        return jsonify(error="Invalid amount"), 400
    with connect() as db:
        user = db.execute(
            "SELECT coins FROM users WHERE id=?", (uid,)
        ).fetchone()
        if not user or user["coins"] + amount < 0:
            return jsonify(error="User not found or insufficient coins"), 400
        db.execute(
            "UPDATE users SET coins=coins+? WHERE id=?", (amount, uid)
        )
    return jsonify(message="Virtual coins updated")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
