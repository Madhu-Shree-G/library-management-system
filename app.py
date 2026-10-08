import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from dsa.library import Library

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "books.json"
DB_FILE = DATA_DIR / "library.db"

LOAN_DAYS = 14
FINE_PER_DAY = 5
MAX_BOOKS = 3
PER_PAGE = 20

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)

library = Library()
with DATA_FILE.open(encoding="utf-8") as f:
    catalogue = json.load(f)
for book in catalogue:
    library.add_book(book["title"], book["author"], book["category"])
library.next_id = max((b["id"] for b in library.books), default=0) + 1


def get_db():
    if "db" not in g:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            borrowed_at TEXT NOT NULL,
            due_at TEXT NOT NULL,
            returned_at TEXT,
            fine INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_loans_user_active
        ON loans(user_id, returned_at);
        CREATE INDEX IF NOT EXISTS idx_loans_book_active
        ON loans(book_id, returned_at);
        """
    )
    conn.commit()


def now_local():
    return datetime.now().replace(microsecond=0)


def parse_dt(value):
    return datetime.fromisoformat(value) if value else None


def format_dt(value):
    dt = parse_dt(value) if isinstance(value, str) else value
    return dt.strftime("%d %b %Y • %I:%M %p") if dt else "—"


def late_days(due_at, end=None):
    due = parse_dt(due_at)
    end = end or now_local()
    if end <= due:
        return 0
    seconds = (end - due).total_seconds()
    return max(1, int((seconds + 86399) // 86400))


def calculate_fine(due_at, end=None):
    return late_days(due_at, end) * FINE_PER_DAY


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def book_by_id(book_id):
    return next((b for b in library.books if b["id"] == book_id), None)


def book_available(book_id):
    row = get_db().execute(
        "SELECT 1 FROM loans WHERE book_id = ? AND returned_at IS NULL LIMIT 1", (book_id,)
    ).fetchone()
    return row is None


def enrich_book(book):
    item = dict(book)
    item["available"] = book_available(book["id"])
    return item


def active_loans_for(user_id):
    rows = get_db().execute(
        "SELECT * FROM loans WHERE user_id = ? AND returned_at IS NULL ORDER BY due_at", (user_id,)
    ).fetchall()
    return [
        {
            "loan": row,
            "book": book_by_id(row["book_id"]),
            "fine": calculate_fine(row["due_at"]),
            "late_days": late_days(row["due_at"]),
        }
        for row in rows
    ]


@app.template_filter("dt")
def datetime_filter(value):
    return format_dt(value)


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "fine_per_day": FINE_PER_DAY,
        "loan_days": LOAN_DAYS,
        "max_books": MAX_BOOKS,
        "csrf_token": csrf_token,
    }


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]


@app.before_request
def protect_post():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or sent != session.get("csrf_token"):
            abort(400, description="Invalid form token. Please refresh and try again.")


@app.route("/")
def index():
    total = len(library.books)
    borrowed = get_db().execute(
        "SELECT COUNT(*) AS c FROM loans WHERE returned_at IS NULL"
    ).fetchone()["c"]
    available = total - borrowed
    featured = [enrich_book(b) for b in library.books[:8]]
    return render_template(
        "index.html",
        stats={"total": total, "available": available, "borrowed": borrowed},
        books=featured,
    )


@app.route("/books")
def books():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort = request.args.get("sort", "title")
    results = library.search(query) if query else list(library.books)
    if category:
        results = [b for b in results if b["category"] == category]
    if sort == "author":
        results = sorted(results, key=lambda b: (b["author"].lower(), b["title"].lower()))
    elif sort == "id":
        results = sorted(results, key=lambda b: b["id"])
    else:
        results = sorted(results, key=lambda b: b["title"].lower())

    categories = sorted({b["category"] for b in library.books})
    page = max(request.args.get("page", 1, type=int), 1)
    total_pages = max((len(results) + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(page, total_pages)
    start = (page - 1) * PER_PAGE
    page_books = [enrich_book(b) for b in results[start : start + PER_PAGE]]
    return render_template(
        "books.html",
        books=page_books,
        query=query,
        category=category,
        sort=sort,
        categories=categories,
        page=page,
        total_pages=total_pages,
        total_results=len(results),
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("profile"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(name) < 2:
            flash("Please enter your full name.", "error")
        elif len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
        else:
            try:
                conn = get_db()
                cur = conn.execute(
                    "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                    (name, email, generate_password_hash(password), now_local().isoformat(sep=" ")),
                )
                conn.commit()
                session.clear()
                session["user_id"] = cur.lastrowid
                session["csrf_token"] = secrets.token_urlsafe(24)
                flash("Welcome to Libra! Your account is ready.", "success")
                return redirect(url_for("profile"))
            except sqlite3.IntegrityError:
                flash("An account with that email already exists. Try signing in.", "error")
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("profile"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(24)
            flash("Signed in successfully.", "success")
            destination = request.args.get("next")
            return redirect(destination if destination and destination.startswith("/") else url_for("profile"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.route("/profile")
@login_required
def profile():
    user = current_user()
    active = active_loans_for(user["id"])
    history = get_db().execute(
        "SELECT * FROM loans WHERE user_id = ? ORDER BY id DESC LIMIT 12", (user["id"],)
    ).fetchall()
    history_items = [{"loan": row, "book": book_by_id(row["book_id"])} for row in history]
    total_fines = sum(calculate_fine(row["due_at"], parse_dt(row["returned_at"])) for row in history)
    return render_template("profile.html", user=user, loans=active, history=history_items, total_fines=total_fines)


@app.route("/borrow/<int:book_id>", methods=["POST"])
@login_required
def borrow(book_id):
    user = current_user()
    book = book_by_id(book_id)
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))
    if not book_available(book_id):
        flash("This book is currently borrowed.", "error")
        return redirect(request.referrer or url_for("books"))
    active_count = get_db().execute(
        "SELECT COUNT(*) AS c FROM loans WHERE user_id = ? AND returned_at IS NULL", (user["id"],)
    ).fetchone()["c"]
    if active_count >= MAX_BOOKS:
        flash(f"You can borrow a maximum of {MAX_BOOKS} books at a time.", "error")
        return redirect(request.referrer or url_for("books"))

    borrowed = now_local()
    due = borrowed + timedelta(days=LOAN_DAYS)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO loans(user_id,book_id,borrowed_at,due_at) VALUES(?,?,?,?)",
            (user["id"], book_id, borrowed.isoformat(sep=" "), due.isoformat(sep=" ")),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash("This book was just borrowed by someone else. Please refresh.", "error")
        return redirect(request.referrer or url_for("books"))
    flash(f"{book['title']} borrowed. Due {format_dt(due)}.", "success")
    return redirect(request.referrer or url_for("books"))


@app.route("/return/<int:book_id>", methods=["POST"])
@login_required
def return_book(book_id):
    user = current_user()
    conn = get_db()
    loan = conn.execute(
        "SELECT * FROM loans WHERE user_id = ? AND book_id = ? AND returned_at IS NULL ORDER BY id DESC LIMIT 1",
        (user["id"], book_id),
    ).fetchone()
    if not loan:
        flash("You do not have this book on loan.", "error")
        return redirect(request.referrer or url_for("profile"))
    returned = now_local()
    fine = calculate_fine(loan["due_at"], returned)
    conn.execute(
        "UPDATE loans SET returned_at = ?, fine = ? WHERE id = ?",
        (returned.isoformat(sep=" "), fine, loan["id"]),
    )
    conn.commit()
    if fine:
        flash(f"Book returned. Late fine: ₹{fine} ({late_days(loan['due_at'], returned)} late day(s)).", "error")
    else:
        flash("Book returned on time. No fine.", "success")
    return redirect(request.referrer or url_for("profile"))


@app.route("/rules")
def rules():
    return render_template("rules.html")


@app.route("/favicon.svg")
def favicon():
    return app.send_static_file("favicon.svg")


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=error.description), 400


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="The page you requested could not be found."), 404


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
