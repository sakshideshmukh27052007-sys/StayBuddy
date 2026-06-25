"""
StayBuddy - Flask Application
Helps students find private hostels and PG accommodations near colleges.
"""

import os
import sqlite3
import json
import uuid
from datetime import datetime, date
from functools import wraps
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# App Configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "staybuddy-dev-secret-key-change-in-prod")

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "staybuddy.db"
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads" / "hostels"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_PHOTOS_PER_HOSTEL = 8

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------------------------

def get_db():
    """Open a new database connection for the current request."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables and seed sample data if the DB is empty."""
    conn = get_db()
    c = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    NOT NULL UNIQUE,
            password    TEXT,
            role        TEXT    NOT NULL DEFAULT 'student',
            phone       TEXT,
            avatar_url  TEXT,
            google_id   TEXT    UNIQUE,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Hostels table
    c.execute("""
        CREATE TABLE IF NOT EXISTS hostels (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id         INTEGER NOT NULL REFERENCES users(id),
            name             TEXT    NOT NULL,
            description      TEXT,
            city             TEXT    NOT NULL,
            area             TEXT,
            college_nearby   TEXT,
            monthly_rent     INTEGER NOT NULL,
            vacancy_status   TEXT    NOT NULL DEFAULT 'available',
            gender_pref      TEXT    NOT NULL DEFAULT 'any',
            contact_number   TEXT,
            maps_link        TEXT,
            facilities       TEXT    DEFAULT '[]',
            created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Hostel photos table
    c.execute("""
        CREATE TABLE IF NOT EXISTS hostel_photos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            hostel_id  INTEGER NOT NULL REFERENCES hostels(id) ON DELETE CASCADE,
            filename   TEXT    NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Inquiries table
    c.execute("""
        CREATE TABLE IF NOT EXISTS inquiries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER REFERENCES users(id),
            hostel_id  INTEGER NOT NULL REFERENCES hostels(id) ON DELETE CASCADE,
            name       TEXT    NOT NULL,
            email      TEXT    NOT NULL,
            phone      TEXT,
            message    TEXT    NOT NULL,
            status     TEXT    NOT NULL DEFAULT 'new',
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Messages table (student ↔ owner real-time chat)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id   INTEGER NOT NULL REFERENCES users(id),
            receiver_id INTEGER NOT NULL REFERENCES users(id),
            hostel_id   INTEGER REFERENCES hostels(id),
            content     TEXT    NOT NULL,
            is_read     INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Meeting requests table
    c.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id     INTEGER NOT NULL REFERENCES users(id),
            owner_id       INTEGER NOT NULL REFERENCES users(id),
            hostel_id      INTEGER NOT NULL REFERENCES hostels(id) ON DELETE CASCADE,
            proposed_date  TEXT    NOT NULL,
            proposed_time  TEXT    NOT NULL,
            message        TEXT,
            status         TEXT    NOT NULL DEFAULT 'pending',
            created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    conn.commit()

    # Seed sample data if tables are empty
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        _seed_data(conn)

    conn.close()


def _seed_data(conn):
    """Insert sample owners, hostels, and a test student."""
    c = conn.cursor()

    # Sample student
    c.execute(
        "INSERT INTO users (name, email, password, role, phone) VALUES (?,?,?,?,?)",
        ("Demo Student", "student@demo.com",
         generate_password_hash("student123"), "student", "9876543210")
    )
    student_id = c.lastrowid

    # Sample owners
    owners = [
        ("Ramesh Kumar",  "owner1@demo.com", "owner123", "9811223344"),
        ("Priya Sharma",  "owner2@demo.com", "owner123", "9922334455"),
        ("Amit Verma",    "owner3@demo.com", "owner123", "9733445566"),
    ]
    owner_ids = []
    for name, email, pwd, phone in owners:
        c.execute(
            "INSERT INTO users (name, email, password, role, phone) VALUES (?,?,?,?,?)",
            (name, email, generate_password_hash(pwd), "owner", phone)
        )
        owner_ids.append(c.lastrowid)

    # Sample hostels
    sample_hostels = [
        {
            "owner_id": owner_ids[0],
            "name": "Green Valley PG",
            "description": "A comfortable and affordable PG for boys near Delhi University. Homely atmosphere with all basic amenities.",
            "city": "Delhi",
            "area": "North Campus",
            "college_nearby": "Delhi University",
            "monthly_rent": 7500,
            "vacancy_status": "available",
            "gender_pref": "male",
            "contact_number": "9811223344",
            "maps_link": "https://maps.google.com/?q=Delhi+University+North+Campus",
            "facilities": json.dumps(["WiFi", "Meals Included", "Laundry", "24/7 Security", "Hot Water", "Study Room"]),
        },
        {
            "owner_id": owner_ids[1],
            "name": "Sunrise Girls Hostel",
            "description": "Safe and secure hostel exclusively for girls. Located walking distance from Mumbai University. Spacious rooms with great ventilation.",
            "city": "Mumbai",
            "area": "Santacruz",
            "college_nearby": "Mumbai University",
            "monthly_rent": 10000,
            "vacancy_status": "available",
            "gender_pref": "female",
            "contact_number": "9922334455",
            "maps_link": "https://maps.google.com/?q=Mumbai+University+Santacruz",
            "facilities": json.dumps(["WiFi", "Meals Included", "AC Rooms", "CCTV", "Gym", "Common Hall", "Hot Water"]),
        },
        {
            "owner_id": owner_ids[2],
            "name": "Scholar's Den PG",
            "description": "Affordable PG accommodation for students in Bangalore. Peaceful environment ideal for studying.",
            "city": "Bangalore",
            "area": "Koramangala",
            "college_nearby": "Christ University",
            "monthly_rent": 8500,
            "vacancy_status": "available",
            "gender_pref": "any",
            "contact_number": "9733445566",
            "maps_link": "https://maps.google.com/?q=Koramangala+Bangalore",
            "facilities": json.dumps(["WiFi", "Laundry", "Parking", "24/7 Security", "Fridge", "Study Table"]),
        },
        {
            "owner_id": owner_ids[0],
            "name": "Campus Corner Hostel",
            "description": "Newly built hostel near IIT Delhi with modern amenities. Best-in-class facilities for engineering students.",
            "city": "Delhi",
            "area": "Hauz Khas",
            "college_nearby": "IIT Delhi",
            "monthly_rent": 12000,
            "vacancy_status": "limited",
            "gender_pref": "male",
            "contact_number": "9811223344",
            "maps_link": "https://maps.google.com/?q=IIT+Delhi+Hauz+Khas",
            "facilities": json.dumps(["WiFi", "AC Rooms", "Gym", "Cafeteria", "Library", "Power Backup", "Hot Water"]),
        },
        {
            "owner_id": owner_ids[1],
            "name": "Colaba Student House",
            "description": "Budget-friendly accommodation near Bombay College. Ideal for first-year students.",
            "city": "Mumbai",
            "area": "Colaba",
            "college_nearby": "Bombay College",
            "monthly_rent": 6500,
            "vacancy_status": "full",
            "gender_pref": "any",
            "contact_number": "9922334455",
            "maps_link": "https://maps.google.com/?q=Colaba+Mumbai",
            "facilities": json.dumps(["WiFi", "Meals Included", "Hot Water", "Common Area"]),
        },
        {
            "owner_id": owner_ids[2],
            "name": "Techie's Abode PG",
            "description": "Premium PG near Electronic City for working professionals and students at engineering colleges.",
            "city": "Bangalore",
            "area": "Electronic City",
            "college_nearby": "PES University",
            "monthly_rent": 9500,
            "vacancy_status": "available",
            "gender_pref": "any",
            "contact_number": "9733445566",
            "maps_link": "https://maps.google.com/?q=Electronic+City+Bangalore",
            "facilities": json.dumps(["WiFi", "AC Rooms", "Gym", "Laundry", "CCTV", "Power Backup", "Parking"]),
        },
    ]

    for h in sample_hostels:
        c.execute("""
            INSERT INTO hostels
                (owner_id, name, description, city, area, college_nearby,
                 monthly_rent, vacancy_status, gender_pref, contact_number, maps_link, facilities)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            h["owner_id"], h["name"], h["description"], h["city"],
            h["area"], h["college_nearby"], h["monthly_rent"],
            h["vacancy_status"], h["gender_pref"], h["contact_number"],
            h["maps_link"], h["facilities"]
        ))

    conn.commit()


# ---------------------------------------------------------------------------
# Auth Helpers
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator: redirect to login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated


def owner_required(f):
    """Decorator: redirect if user is not an owner."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "owner":
            flash("This area is for hostel owners only.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def current_user():
    """Return the logged-in user row or None."""
    if "user_id" not in session:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return user


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Context Processors
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "now": datetime.now(),
    }


# ---------------------------------------------------------------------------
# Public Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Home page with search bar and featured hostels."""
    conn = get_db()
    featured = conn.execute("""
        SELECT h.*, u.name AS owner_name,
               (SELECT filename FROM hostel_photos WHERE hostel_id=h.id AND is_primary=1 LIMIT 1) AS primary_photo
        FROM hostels h JOIN users u ON h.owner_id=u.id
        WHERE h.vacancy_status != 'full'
        ORDER BY h.created_at DESC LIMIT 6
    """).fetchall()
    cities = conn.execute("SELECT DISTINCT city FROM hostels ORDER BY city").fetchall()
    conn.close()
    return render_template("index.html", featured=featured, cities=cities)


@app.route("/search")
def search():
    """Search hostels by city, college, or area."""
    q       = request.args.get("q", "").strip()
    city    = request.args.get("city", "").strip()
    gender  = request.args.get("gender", "").strip()
    max_rent = request.args.get("max_rent", "").strip()

    conn = get_db()
    query = """
        SELECT h.*, u.name AS owner_name,
               (SELECT filename FROM hostel_photos WHERE hostel_id=h.id AND is_primary=1 LIMIT 1) AS primary_photo
        FROM hostels h JOIN users u ON h.owner_id=u.id
        WHERE 1=1
    """
    params = []

    if q:
        query += " AND (h.name LIKE ? OR h.city LIKE ? OR h.area LIKE ? OR h.college_nearby LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like, like]
    if city:
        query += " AND h.city=?"
        params.append(city)
    if gender and gender != "any":
        query += " AND (h.gender_pref=? OR h.gender_pref='any')"
        params.append(gender)
    if max_rent:
        query += " AND h.monthly_rent<=?"
        params.append(int(max_rent))

    query += " ORDER BY h.created_at DESC"
    hostels = conn.execute(query, params).fetchall()
    cities  = conn.execute("SELECT DISTINCT city FROM hostels ORDER BY city").fetchall()
    conn.close()
    return render_template("search.html", hostels=hostels, cities=cities,
                           q=q, city=city, gender=gender, max_rent=max_rent)


@app.route("/hostel/<int:hostel_id>")
def hostel_detail(hostel_id):
    """Hostel detail page."""
    conn = get_db()
    hostel = conn.execute("""
        SELECT h.*, u.name AS owner_name, u.phone AS owner_phone, u.id AS owner_user_id
        FROM hostels h JOIN users u ON h.owner_id=u.id
        WHERE h.id=?
    """, (hostel_id,)).fetchone()
    if not hostel:
        abort(404)
    photos  = conn.execute("SELECT * FROM hostel_photos WHERE hostel_id=? ORDER BY is_primary DESC", (hostel_id,)).fetchall()
    similar = conn.execute("""
        SELECT h.*,
               (SELECT filename FROM hostel_photos WHERE hostel_id=h.id AND is_primary=1 LIMIT 1) AS primary_photo
        FROM hostels h
        WHERE h.city=? AND h.id!=? LIMIT 3
    """, (hostel["city"], hostel_id)).fetchall()
    conn.close()
    facilities = json.loads(hostel["facilities"] or "[]")
    return render_template("hostel_detail.html", hostel=hostel, photos=photos,
                           facilities=facilities, similar=similar)


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn     = get_db()
        user     = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and user["password"] and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["role"]    = user["role"]
            session["name"]    = user["name"]
            flash(f"Welcome back, {user['name']}!", "success")
            next_url = request.args.get("next")
            if next_url:
                return redirect(next_url)
            return redirect(url_for("owner_dashboard") if user["role"] == "owner" else url_for("index"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role     = request.form.get("role", "student")
        phone    = request.form.get("phone", "").strip()

        if not all([name, email, password]):
            flash("All fields are required.", "danger")
            return render_template("auth/register.html")

        conn = get_db()
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            conn.close()
            flash("An account with this email already exists.", "danger")
            return render_template("auth/register.html")

        conn.execute(
            "INSERT INTO users (name, email, password, role, phone) VALUES (?,?,?,?,?)",
            (name, email, generate_password_hash(password), role, phone)
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        session["user_id"] = user["id"]
        session["role"]    = user["role"]
        session["name"]    = user["name"]
        flash("Account created successfully! Welcome to StayBuddy.", "success")
        return redirect(url_for("owner_dashboard") if role == "owner" else url_for("index"))
    return render_template("auth/register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Inquiry Routes
# ---------------------------------------------------------------------------

@app.route("/inquiry/<int:hostel_id>", methods=["POST"])
def submit_inquiry(hostel_id):
    """Student submits an inquiry for a hostel."""
    name    = request.form.get("name", "").strip()
    email   = request.form.get("email", "").strip()
    phone   = request.form.get("phone", "").strip()
    message = request.form.get("message", "").strip()

    if not all([name, email, message]):
        flash("Please fill in all required fields.", "danger")
        return redirect(url_for("hostel_detail", hostel_id=hostel_id))

    student_id = session.get("user_id")
    conn = get_db()
    conn.execute("""
        INSERT INTO inquiries (student_id, hostel_id, name, email, phone, message)
        VALUES (?,?,?,?,?,?)
    """, (student_id, hostel_id, name, email, phone, message))
    conn.commit()
    conn.close()
    flash("Your inquiry has been sent! The owner will contact you soon.", "success")
    return redirect(url_for("hostel_detail", hostel_id=hostel_id))


# ---------------------------------------------------------------------------
# Messaging Routes
# ---------------------------------------------------------------------------

@app.route("/messages")
@login_required
def messages():
    """Inbox: list all conversations for the current user."""
    conn = get_db()
    user_id = session["user_id"]

    # Get unique conversation partners
    conversations = conn.execute("""
        SELECT
            CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END AS partner_id,
            u.name AS partner_name,
            h.id AS hostel_id,
            h.name AS hostel_name,
            m.content AS last_message,
            m.created_at AS last_at,
            SUM(CASE WHEN m.receiver_id=? AND m.is_read=0 THEN 1 ELSE 0 END) AS unread_count
        FROM messages m
        JOIN users u ON u.id = CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END
        LEFT JOIN hostels h ON h.id=m.hostel_id
        WHERE m.sender_id=? OR m.receiver_id=?
        GROUP BY partner_id, h.id
        ORDER BY last_at DESC
    """, (user_id, user_id, user_id, user_id, user_id)).fetchall()
    conn.close()
    return render_template("student/messages.html", conversations=conversations)


@app.route("/messages/<int:partner_id>")
@login_required
def conversation(partner_id):
    """View conversation with a specific user, optionally about a hostel."""
    hostel_id = request.args.get("hostel_id")
    conn = get_db()
    user_id = session["user_id"]

    partner = conn.execute("SELECT * FROM users WHERE id=?", (partner_id,)).fetchone()
    if not partner:
        abort(404)

    # Build query for thread
    if hostel_id:
        thread = conn.execute("""
            SELECT m.*, u.name AS sender_name FROM messages m JOIN users u ON u.id=m.sender_id
            WHERE ((m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?))
              AND m.hostel_id=?
            ORDER BY m.created_at ASC
        """, (user_id, partner_id, partner_id, user_id, hostel_id)).fetchall()
        hostel = conn.execute("SELECT * FROM hostels WHERE id=?", (hostel_id,)).fetchone()
    else:
        thread = conn.execute("""
            SELECT m.*, u.name AS sender_name FROM messages m JOIN users u ON u.id=m.sender_id
            WHERE (m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?)
            ORDER BY m.created_at ASC
        """, (user_id, partner_id, partner_id, user_id)).fetchall()
        hostel = None

    # Mark incoming as read
    conn.execute("""
        UPDATE messages SET is_read=1
        WHERE receiver_id=? AND sender_id=? AND is_read=0
    """, (user_id, partner_id))
    conn.commit()

    # All conversations for sidebar
    conversations = conn.execute("""
        SELECT
            CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END AS partner_id,
            u.name AS partner_name,
            h.id AS hostel_id,
            h.name AS hostel_name,
            m.content AS last_message,
            m.created_at AS last_at,
            SUM(CASE WHEN m.receiver_id=? AND m.is_read=0 THEN 1 ELSE 0 END) AS unread_count
        FROM messages m
        JOIN users u ON u.id = CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END
        LEFT JOIN hostels h ON h.id=m.hostel_id
        WHERE m.sender_id=? OR m.receiver_id=?
        GROUP BY partner_id, h.id
        ORDER BY last_at DESC
    """, (user_id, user_id, user_id, user_id, user_id)).fetchall()
    conn.close()
    return render_template("student/messages.html",
                           partner=partner, thread=thread, hostel=hostel,
                           conversations=conversations,
                           hostel_id=hostel_id)


@app.route("/messages/send", methods=["POST"])
@login_required
def send_message():
    """Send a message to another user."""
    receiver_id = int(request.form.get("receiver_id"))
    content     = request.form.get("content", "").strip()
    hostel_id   = request.form.get("hostel_id") or None
    if not content:
        flash("Message cannot be empty.", "danger")
        return redirect(request.referrer or url_for("messages"))

    conn = get_db()
    conn.execute("""
        INSERT INTO messages (sender_id, receiver_id, hostel_id, content)
        VALUES (?,?,?,?)
    """, (session["user_id"], receiver_id, hostel_id, content))
    conn.commit()
    conn.close()

    redir = url_for("conversation", partner_id=receiver_id)
    if hostel_id:
        redir += f"?hostel_id={hostel_id}"
    return redirect(redir)


# ---------------------------------------------------------------------------
# Meeting Request Routes
# ---------------------------------------------------------------------------

@app.route("/meetings")
@login_required
def meetings():
    """Student: view sent meeting requests."""
    conn = get_db()
    user_id = session["user_id"]
    if session["role"] == "student":
        rows = conn.execute("""
            SELECT mt.*, h.name AS hostel_name, u.name AS owner_name
            FROM meetings mt
            JOIN hostels h ON h.id=mt.hostel_id
            JOIN users u ON u.id=mt.owner_id
            WHERE mt.student_id=?
            ORDER BY mt.created_at DESC
        """, (user_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT mt.*, h.name AS hostel_name, u.name AS student_name
            FROM meetings mt
            JOIN hostels h ON h.id=mt.hostel_id
            JOIN users u ON u.id=mt.student_id
            WHERE mt.owner_id=?
            ORDER BY mt.created_at DESC
        """, (user_id,)).fetchall()
    conn.close()
    return render_template("student/meetings.html", meetings=rows)


@app.route("/meetings/request/<int:hostel_id>", methods=["POST"])
@login_required
def request_meeting(hostel_id):
    """Student requests a visit/meeting with owner."""
    if session["role"] != "student":
        flash("Only students can request meetings.", "danger")
        return redirect(url_for("hostel_detail", hostel_id=hostel_id))

    proposed_date = request.form.get("proposed_date")
    proposed_time = request.form.get("proposed_time")
    message       = request.form.get("message", "").strip()

    if not proposed_date or not proposed_time:
        flash("Please select a date and time.", "danger")
        return redirect(url_for("hostel_detail", hostel_id=hostel_id))

    conn = get_db()
    hostel = conn.execute("SELECT * FROM hostels WHERE id=?", (hostel_id,)).fetchone()
    conn.execute("""
        INSERT INTO meetings (student_id, owner_id, hostel_id, proposed_date, proposed_time, message)
        VALUES (?,?,?,?,?,?)
    """, (session["user_id"], hostel["owner_id"], hostel_id, proposed_date, proposed_time, message))
    conn.commit()
    conn.close()
    flash("Meeting request sent! The owner will confirm soon.", "success")
    return redirect(url_for("hostel_detail", hostel_id=hostel_id))


@app.route("/meetings/<int:meeting_id>/update", methods=["POST"])
@login_required
def update_meeting(meeting_id):
    """Owner: confirm or reject a meeting request."""
    status = request.form.get("status")
    if status not in ("confirmed", "rejected"):
        flash("Invalid status.", "danger")
        return redirect(url_for("meetings"))
    conn = get_db()
    conn.execute("UPDATE meetings SET status=? WHERE id=? AND owner_id=?",
                 (status, meeting_id, session["user_id"]))
    conn.commit()
    conn.close()
    flash(f"Meeting {status}.", "success")
    return redirect(url_for("meetings"))


# ---------------------------------------------------------------------------
# Owner Routes
# ---------------------------------------------------------------------------

@app.route("/owner/dashboard")
@owner_required
def owner_dashboard():
    """Owner dashboard: stats + own hostels."""
    conn = get_db()
    owner_id = session["user_id"]
    hostels  = conn.execute("""
        SELECT h.*,
               (SELECT filename FROM hostel_photos WHERE hostel_id=h.id AND is_primary=1 LIMIT 1) AS primary_photo,
               (SELECT COUNT(*) FROM inquiries WHERE hostel_id=h.id) AS inquiry_count,
               (SELECT COUNT(*) FROM inquiries WHERE hostel_id=h.id AND status='new') AS new_inquiries,
               (SELECT COUNT(*) FROM meetings WHERE hostel_id=h.id AND status='pending') AS pending_meetings
        FROM hostels h WHERE h.owner_id=?
        ORDER BY h.created_at DESC
    """, (owner_id,)).fetchall()
    total_inquiries = conn.execute(
        "SELECT COUNT(*) FROM inquiries i JOIN hostels h ON h.id=i.hostel_id WHERE h.owner_id=? AND i.status='new'",
        (owner_id,)).fetchone()[0]
    unread_messages = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE receiver_id=? AND is_read=0",
        (owner_id,)).fetchone()[0]
    conn.close()
    return render_template("owner/dashboard.html", hostels=hostels,
                           total_inquiries=total_inquiries,
                           unread_messages=unread_messages)


@app.route("/owner/add", methods=["GET", "POST"])
@owner_required
def add_hostel():
    """Owner: add a new hostel listing."""
    if request.method == "POST":
        name        = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        city        = request.form.get("city", "").strip()
        area        = request.form.get("area", "").strip()
        college     = request.form.get("college_nearby", "").strip()
        rent        = int(request.form.get("monthly_rent", 0))
        vacancy     = request.form.get("vacancy_status", "available")
        gender_pref = request.form.get("gender_pref", "any")
        contact     = request.form.get("contact_number", "").strip()
        maps_link   = request.form.get("maps_link", "").strip()
        facilities  = request.form.getlist("facilities")

        conn = get_db()
        conn.execute("""
            INSERT INTO hostels
                (owner_id, name, description, city, area, college_nearby,
                 monthly_rent, vacancy_status, gender_pref, contact_number, maps_link, facilities)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (session["user_id"], name, description, city, area, college,
              rent, vacancy, gender_pref, contact, maps_link, json.dumps(facilities)))
        conn.commit()
        hostel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Handle photo uploads
        photos = request.files.getlist("photos")
        _save_photos(conn, hostel_id, photos)
        conn.commit()
        conn.close()
        flash("Hostel listed successfully!", "success")
        return redirect(url_for("owner_dashboard"))
    return render_template("owner/add_hostel.html")


@app.route("/owner/edit/<int:hostel_id>", methods=["GET", "POST"])
@owner_required
def edit_hostel(hostel_id):
    """Owner: edit an existing hostel."""
    conn = get_db()
    hostel = conn.execute(
        "SELECT * FROM hostels WHERE id=? AND owner_id=?",
        (hostel_id, session["user_id"])).fetchone()
    if not hostel:
        conn.close()
        abort(403)

    if request.method == "POST":
        name        = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        city        = request.form.get("city", "").strip()
        area        = request.form.get("area", "").strip()
        college     = request.form.get("college_nearby", "").strip()
        rent        = int(request.form.get("monthly_rent", 0))
        vacancy     = request.form.get("vacancy_status", "available")
        gender_pref = request.form.get("gender_pref", "any")
        contact     = request.form.get("contact_number", "").strip()
        maps_link   = request.form.get("maps_link", "").strip()
        facilities  = request.form.getlist("facilities")

        conn.execute("""
            UPDATE hostels SET name=?, description=?, city=?, area=?, college_nearby=?,
            monthly_rent=?, vacancy_status=?, gender_pref=?, contact_number=?, maps_link=?, facilities=?
            WHERE id=? AND owner_id=?
        """, (name, description, city, area, college, rent, vacancy, gender_pref,
              contact, maps_link, json.dumps(facilities), hostel_id, session["user_id"]))
        conn.commit()

        # Handle new photo uploads
        photos = request.files.getlist("photos")
        _save_photos(conn, hostel_id, photos)
        conn.commit()
        conn.close()
        flash("Hostel updated successfully!", "success")
        return redirect(url_for("owner_dashboard"))

    photos     = conn.execute("SELECT * FROM hostel_photos WHERE hostel_id=?", (hostel_id,)).fetchall()
    facilities = json.loads(hostel["facilities"] or "[]")
    conn.close()
    return render_template("owner/edit_hostel.html", hostel=hostel,
                           photos=photos, facilities=facilities)


@app.route("/owner/delete-photo/<int:photo_id>", methods=["POST"])
@owner_required
def delete_photo(photo_id):
    """Owner: delete a single photo."""
    conn = get_db()
    photo = conn.execute("""
        SELECT p.* FROM hostel_photos p
        JOIN hostels h ON h.id=p.hostel_id
        WHERE p.id=? AND h.owner_id=?
    """, (photo_id, session["user_id"])).fetchone()
    if photo:
        path = UPLOAD_FOLDER / photo["filename"]
        if path.exists():
            path.unlink()
        conn.execute("DELETE FROM hostel_photos WHERE id=?", (photo_id,))
        conn.commit()
        flash("Photo deleted.", "success")
    conn.close()
    return redirect(request.referrer or url_for("owner_dashboard"))


@app.route("/owner/delete/<int:hostel_id>", methods=["POST"])
@owner_required
def delete_hostel(hostel_id):
    """Owner: delete a hostel listing."""
    conn = get_db()
    hostel = conn.execute(
        "SELECT * FROM hostels WHERE id=? AND owner_id=?",
        (hostel_id, session["user_id"])).fetchone()
    if hostel:
        # Delete photos from disk
        photos = conn.execute("SELECT filename FROM hostel_photos WHERE hostel_id=?", (hostel_id,)).fetchall()
        for p in photos:
            path = UPLOAD_FOLDER / p["filename"]
            if path.exists():
                path.unlink()
        conn.execute("DELETE FROM hostels WHERE id=?", (hostel_id,))
        conn.commit()
        flash("Hostel deleted.", "success")
    conn.close()
    return redirect(url_for("owner_dashboard"))


@app.route("/owner/inquiries")
@owner_required
def owner_inquiries():
    """Owner: view all inquiries for their hostels."""
    conn = get_db()
    owner_id = session["user_id"]
    hostel_filter = request.args.get("hostel_id")

    query = """
        SELECT i.*, h.name AS hostel_name
        FROM inquiries i JOIN hostels h ON h.id=i.hostel_id
        WHERE h.owner_id=?
    """
    params = [owner_id]
    if hostel_filter:
        query += " AND h.id=?"
        params.append(hostel_filter)
    query += " ORDER BY i.created_at DESC"

    inquiries = conn.execute(query, params).fetchall()
    hostels   = conn.execute("SELECT id, name FROM hostels WHERE owner_id=?", (owner_id,)).fetchall()

    # Mark viewed inquiries as 'seen'
    conn.execute("""
        UPDATE inquiries SET status='seen'
        WHERE status='new' AND hostel_id IN (SELECT id FROM hostels WHERE owner_id=?)
    """, (owner_id,))
    conn.commit()
    conn.close()
    return render_template("owner/inquiries.html", inquiries=inquiries,
                           hostels=hostels, hostel_filter=hostel_filter)


# ---------------------------------------------------------------------------
# Photo Upload Helper
# ---------------------------------------------------------------------------

def _save_photos(conn, hostel_id, photo_files):
    """Save uploaded photos to disk and insert DB records."""
    existing_count = conn.execute(
        "SELECT COUNT(*) FROM hostel_photos WHERE hostel_id=?", (hostel_id,)).fetchone()[0]
    has_primary = conn.execute(
        "SELECT COUNT(*) FROM hostel_photos WHERE hostel_id=? AND is_primary=1", (hostel_id,)).fetchone()[0]

    for i, photo in enumerate(photo_files):
        if photo and photo.filename and allowed_file(photo.filename):
            if existing_count >= MAX_PHOTOS_PER_HOSTEL:
                break
            ext      = secure_filename(photo.filename).rsplit(".", 1)[-1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            photo.save(UPLOAD_FOLDER / filename)
            is_primary = 1 if (not has_primary and i == 0) else 0
            conn.execute(
                "INSERT INTO hostel_photos (hostel_id, filename, is_primary) VALUES (?,?,?)",
                (hostel_id, filename, is_primary)
            )
            has_primary = True
            existing_count += 1


# ---------------------------------------------------------------------------
# Uploaded files
# ---------------------------------------------------------------------------

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html", message="Access denied."), 403


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

# Always initialise DB regardless of how the app is started (direct or WSGI)
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("NODE_ENV") != "production"
    app.run(host="0.0.0.0", port=port, debug=debug)
