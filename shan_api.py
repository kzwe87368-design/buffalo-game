from app import app, connect
from flask import session, jsonify, request
import secrets
import json
import uuid
import time

# SHAN round storage
with connect() as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS shan_rounds (
            round_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            bet INTEGER NOT NULL,
            hands TEXT NOT NULL,
            remaining_deck TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)


@app.post("/api/shan/deal")
def shan_deal():
    uid = session.get("user_id")
    if not uid:
        return jsonify(error="Please login"), 401

    data = request.get_json(silent=True) or {}

    try:
        bet = int(data.get("bet", 0))
    except (TypeError, ValueError):
        return jsonify(error="Invalid bet"), 400

    if bet < 1000 or bet > 50000:
        return jsonify(error="Bet must be 1,000 to 50,000"), 400

    seats = [
        "AI DEALER", "AI 1", "AI 2", "AI 3",
        "AI 4", "AI 5", "AI 6", "YOU"
    ]

    ranks = ["A", "2", "3", "4", "5", "6", "7",
             "8", "9", "10", "J", "Q", "K"]
    suits = ["♠", "♥", "♦", "♣"]

    deck = [rank + suit for suit in suits for rank in ranks]
    secrets.SystemRandom().shuffle(deck)

    hands = {seat: [] for seat in seats}

    # Deal two cards to every seat, without replacement
    for _ in range(2):
        for seat in seats:
            hands[seat].append(deck.pop())

    round_id = uuid.uuid4().hex

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")

        user = db.execute(
            "SELECT coins, role FROM users WHERE id=?", (uid,)
        ).fetchone()

        if not user:
            return jsonify(error="Account not found"), 404

        is_owner = user["role"] == "owner"

        if not is_owner and user["coins"] < bet:
            return jsonify(error="Not enough credits"), 400

        active = db.execute(
            "SELECT round_id FROM shan_rounds "
            "WHERE user_id=? AND status='dealt' LIMIT 1",
            (uid,)
        ).fetchone()

        if active:
            return jsonify(error="Please finish the previous round"), 409

        new_coins = user["coins"] if is_owner else user["coins"] - bet

        db.execute(
            "UPDATE users SET coins=? WHERE id=?",
            (new_coins, uid)
        )

        db.execute("""
            INSERT INTO shan_rounds
            (round_id,user_id,bet,hands,remaining_deck,status,created_at)
            VALUES(?,?,?,?,?,'dealt',?)
        """, (
            round_id, uid, bet,
            json.dumps(hands),
            json.dumps(deck),
            time.time()
        ))

    return jsonify(
        round_id=round_id,
        seats=seats,
        hands=hands,
        bet=bet,
        coins=new_coins,
        cards_remaining=len(deck),
        message="Cards dealt successfully"
    )

# SHAN KOE MEE RULE ENGINE
SUIT_POWER = {"♣": 1, "♦": 2, "♥": 3, "♠": 4}
RANK_POWER = {
    "A": 1, "2": 2, "3": 3, "4": 4, "5": 5,
    "6": 6, "7": 7, "8": 8, "9": 9,
    "10": 10, "J": 11, "Q": 12, "K": 13
}


def card_value(card):
    rank = card[:-1]
    return 1 if rank == "A" else (
        int(rank) if rank in "23456789" else 0
    )


def hand_score(hand):
    return sum(card_value(c) for c in hand) % 10


def is_auto_shan(hand):
    return len(hand) == 2 and hand_score(hand) in (8, 9)


def hand_power(hand):
    score = hand_score(hand)
    strongest = max(
        hand,
        key=lambda c: (SUIT_POWER[c[-1]], RANK_POWER[c[:-1]])
    )
    return (
        1 if is_auto_shan(hand) else 0,
        score,
        SUIT_POWER[strongest[-1]],
        RANK_POWER[strongest[:-1]]
    )


def player_draw(hand):
    return len(hand) == 2 and not is_auto_shan(hand) and hand_score(hand) <= 5


def banker_draw(banker, players):
    score = hand_score(banker)

    if len(banker) != 2 or is_auto_shan(banker):
        return False
    if score <= 2:
        return True
    if score >= 7:
        return False

    third_cards = [
        hand[2] for hand in players.values() if len(hand) == 3
    ]

    if score == 3:
        return any(c[:-1] != "8" for c in third_cards)
    if score == 4:
        return any(2 <= card_value(c) <= 7 for c in third_cards)
    if score == 5:
        return any(4 <= card_value(c) <= 7 for c in third_cards)
    if score == 6:
        return any(6 <= card_value(c) <= 7 for c in third_cards)

    return False


@app.post("/api/shan/play")
def shan_play():
    uid = session.get("user_id")
    if not uid:
        return jsonify(error="Please login"), 401

    data = request.get_json(silent=True) or {}
    round_id = data.get("round_id")

    if not round_id:
        return jsonify(error="Round ID required"), 400

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")

        row = db.execute(
            "SELECT * FROM shan_rounds WHERE round_id=? AND user_id=?",
            (round_id, uid)
        ).fetchone()

        if not row:
            return jsonify(error="Round not found"), 404

        if row["status"] != "dealt":
            return jsonify(error="Round already finished"), 409

        hands = json.loads(row["hands"])
        deck = json.loads(row["remaining_deck"])
        banker = hands["AI DEALER"]

        players = {
            name: hand for name, hand in hands.items()
            if name != "AI DEALER"
        }

        # Players take their third card when required
        for hand in players.values():
            if player_draw(hand):
                hand.append(deck.pop())

        # Banker decides after seeing players' third cards
        if banker_draw(banker, players):
            banker.append(deck.pop())

        results = {}
        for name, hand in hands.items():
            results[name] = {
                "cards": hand,
                "score": hand_score(hand),
                "auto_shan": is_auto_shan(hand),
                "power": hand_power(hand)
            }

        user_hand = hands["YOU"]
        banker_wins = hand_power(banker) > hand_power(user_hand)
        user_wins = hand_power(user_hand) > hand_power(banker)

        user = db.execute(
            "SELECT coins, role FROM users WHERE id=?", (uid,)
        ).fetchone()

        bet = row["bet"]
        is_owner = user["role"] == "owner"

        if user_wins:
            multiplier = 3 if is_auto_shan(user_hand) else 2
            credit = bet * (multiplier - 1) if is_owner else bet * multiplier
            message = "YOU WIN"
        elif banker_wins:
            credit = 0
            message = "DEALER WINS"
        else:
            credit = 0
            message = "RESULT ERROR"

        new_coins = user["coins"] + credit

        db.execute(
            "UPDATE users SET coins=? WHERE id=?",
            (new_coins, uid)
        )

        db.execute(
            "UPDATE shan_rounds SET hands=?, remaining_deck=?, status='finished' "
            "WHERE round_id=?",
            (json.dumps(hands), json.dumps(deck), round_id)
        )

    from mission_server import add_mission_progress
    add_mission_progress(uid, "shan_round")

    return jsonify(
        results=results,
        winner="YOU" if user_wins else "AI DEALER",
        message=message,
        bet=bet,
        credit=credit,
        coins=new_coins,
        suit_order=["♠", "♥", "♦", "♣"]
    )
