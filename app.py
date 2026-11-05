import secrets
import sqlite3
from contextlib import closing
from datetime import datetime
from io import BytesIO
from math import ceil
from pathlib import Path
from urllib.parse import quote

import click
from flask import Flask, Response, abort, redirect, render_template, request, send_from_directory, session, url_for
from PIL import Image
from werkzeug.exceptions import SecurityError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, template_folder=".")
app.config.update(
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    SESSION_COOKIE_NAME="support_ticket_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    TRUSTED_HOSTS=["127.0.0.1", "localhost"],
)
# Restarting the app signs out existing sessions.
app.secret_key = secrets.token_hex(32)
DATABASE = Path(__file__).with_name("tickets.db")
MAX_IMAGE_SIZE = 5 * 1024 * 1024
STATUS_OPTIONS = ("Open", "In progress", "Resolved")
PAGE_SIZE = 10
SORT_ORDERS = {
    "newest": "created_at DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
    "name": "name COLLATE NOCASE ASC, id ASC",
    "status": "CASE status WHEN 'Open' THEN 0 WHEN 'In progress' THEN 1 ELSE 2 END, created_at DESC, id DESC",
}


@app.template_filter("readable_date")
def readable_date(value):
    return datetime.fromisoformat(value).strftime("%d %b %Y, %I:%M %p")


def query(sql, values=(), one=False):
    # Run SQL, save any changes, and return either one row or a list of rows.
    with closing(sqlite3.connect(DATABASE)) as connection:
        connection.row_factory = sqlite3.Row
        result = connection.execute(sql, values)
        rows = result.fetchone() if one else result.fetchall()
        connection.commit()
        return rows


query("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL DEFAULT '',
        problem TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Open',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        access_token TEXT NOT NULL UNIQUE
    )
""")
query("""
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
    )
""")
query("""
    CREATE TABLE IF NOT EXISTS ticket_images (
        ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
        image BLOB NOT NULL,
        content_type TEXT NOT NULL
    )
""")


@app.cli.command("create-staff")
def create_staff():
    username = click.prompt("Staff username", default="staff").strip()
    if not username or len(username) > 80:
        raise click.ClickException("Use a username between 1 and 80 characters.")
    if query("SELECT id FROM staff WHERE username = ?", (username,), one=True):
        raise click.ClickException("That username already exists. Choose another username.")

    password = click.prompt("Staff password", hide_input=True, confirmation_prompt=True)
    if not 8 <= len(password) <= 128:
        raise click.ClickException("Use a password between 8 and 128 characters.")

    query("INSERT INTO staff (username, password_hash) VALUES (?, ?)",
          (username, generate_password_hash(password)))
    click.echo("Staff account created. Sign in at http://127.0.0.1:5001/desk/login")


@app.before_request
def check_access_and_form():
    if isinstance(request.routing_exception, SecurityError):
        raise request.routing_exception

    staff_page = request.path == "/desk" or request.path.startswith("/desk/")
    if staff_page and request.endpoint != "staff_login" and not session.get("staff_logged_in"):
        return redirect(url_for("staff_login"), code=303)

    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    # Displaying a page is fine; submitting a form needs a valid token.
    if request.method != "POST":
        return
    token = request.form.get("csrf_token", "")
    if token.isascii() and secrets.compare_digest(session["csrf_token"], token):
        return
    if request.endpoint == "submit_ticket":
        return render_template(
            "index.html", submitted=False,
            error="The form was refreshed. Please submit your ticket again.",
        ), 400
    abort(400, description="This form has expired. Reload the page and try again.")


@app.after_request
def protect_private_responses(response):
    if request.path in ("/", "/desk", "/submit") or request.path.startswith(("/desk/", "/tickets/")):
        response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.route("/desk/login", methods=["GET", "POST"])
def staff_login():
    if session.get("staff_logged_in"):
        return redirect(url_for("support_desk"), code=303)

    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        staff = query("SELECT * FROM staff WHERE username = ?", (username,), one=True)

        if staff and check_password_hash(staff["password_hash"], password):
            session.clear()
            session["staff_logged_in"] = True
            session["staff_username"] = staff["username"]
            return redirect(url_for("support_desk"), code=303)
        error = "Incorrect username or password."

    return render_template("login.html", error=error, username=username), 401 if error else 200


@app.post("/desk/logout")
def staff_logout():
    session.clear()
    return redirect(url_for("staff_login"), code=303)


@app.get("/")
def home():
    error = None
    if request.args.get("upload_error"):
        error = "The upload was too large. Use an image up to 5 MB and fill in the form again."
    return render_template("index.html", error=error, submitted=False)


@app.errorhandler(413)
def upload_too_large(error):
    return redirect(url_for("home", upload_error=1), code=303)


@app.get("/style.css")
def stylesheet():
    return send_from_directory(app.root_path, "style.css")


def valid_email(email):
    if len(email) > 254 or not email.isascii() or email.count("@") != 1:
        return False
    name, domain = email.split("@")
    if not name or "." not in domain:
        return False
    if name.startswith(".") or name.endswith(".") or ".." in name:
        return False
    for character in name:
        if not character.isalnum() and character not in "._+-":
            return False
    for part in domain.split("."):
        if not part or not part.replace("-", "").isalnum():
            return False
    return True


def read_image(upload):
    # Check the actual image, not just its filename.
    data = upload.read(MAX_IMAGE_SIZE + 1)
    if len(data) > MAX_IMAGE_SIZE:
        raise ValueError("Choose an image up to 5 MB.")
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG")) as picture:
            if picture.width * picture.height > 20_000_000:
                raise ValueError("Use an image of 20 megapixels or less.")
            picture.load()
            return data, Image.MIME[picture.format]
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError("Choose a valid JPG or PNG image.") from error


@app.post("/submit")
def submit_ticket():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    problem = request.form.get("problem", "").strip()

    error = None
    if not name or not email or not problem:
        error = "Please enter your name, email address, and problem."
    elif len(name) > 80 or len(problem) > 1000:
        error = "Use up to 80 characters for your name and 1,000 for the problem."
    elif not valid_email(email):
        error = "Please enter a valid email address, such as name@example.com."

    image_data = None
    content_type = None
    upload = request.files.get("image")
    if not error and upload and upload.filename:
        try:
            image_data, content_type = read_image(upload)
        except ValueError as image_error:
            error = str(image_error)

    if error:
        return render_template("index.html", error=error, submitted=False), 400

    access_token = secrets.token_urlsafe(32)
    # Save the ticket and its optional image together.
    with closing(sqlite3.connect(DATABASE)) as connection:
        with connection:
            ticket_id = connection.execute(
                "INSERT INTO tickets (name, email, problem, access_token) VALUES (?, ?, ?, ?)",
                (name, email, problem, access_token),
            ).lastrowid
            if image_data is not None:
                connection.execute(
                    "INSERT INTO ticket_images (ticket_id, image, content_type) VALUES (?, ?, ?)",
                    (ticket_id, image_data, content_type),
                )
    return redirect(url_for("view_ticket", access_token=access_token), code=303)


def desk_filters():
    # Read the search, sort, and page values from the URL.
    search = request.args.get("q", "").strip()[:100]
    sort = request.args.get("sort", "newest")
    if sort not in SORT_ORDERS:
        sort = "newest"

    page = max(1, request.args.get("page", 1, type=int))
    return search, sort, page


@app.get("/desk")
def support_desk():
    search, sort, page = desk_filters()
    order_by = SORT_ORDERS[sort]
    # instr finds text inside a field; lower makes the search ignore letter case.
    # An empty search matches every ticket.
    where_clause = """
        WHERE instr(lower(name), lower(?)) > 0
           OR instr(lower(email), lower(?)) > 0
           OR instr(lower(problem), lower(?)) > 0
           OR instr(lower('ST-' || id), lower(?)) > 0
    """
    parameters = [search, search, search, search]

    total = query("SELECT COUNT(*) FROM tickets " + where_clause, parameters, one=True)[0]
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE
    tickets = query(
        "SELECT id, name, email, status, created_at FROM tickets " + where_clause
        + " ORDER BY " + order_by + " LIMIT ? OFFSET ?",
        parameters + [PAGE_SIZE, offset],
    )

    first_result = 0
    if total > 0:
        first_result = offset + 1
    last_result = offset + len(tickets)

    return render_template(
        "desk.html", tickets=tickets, search=search, sort=sort,
        page=page, total_pages=total_pages, total=total,
        first_result=first_result, last_result=last_result,
    )


@app.get("/tickets/<access_token>")
def view_ticket(access_token):
    ticket = query("SELECT * FROM tickets WHERE access_token = ?", (access_token,), one=True)
    if ticket is None:
        abort(404)

    image_attached = query("SELECT ticket_id FROM ticket_images WHERE ticket_id = ?", (ticket["id"],), one=True)
    return render_template("index.html", ticket=ticket, submitted=True, image_attached=image_attached)


@app.get("/desk/tickets/<int:ticket_id>/image")
def ticket_image(ticket_id):
    attachment = query("SELECT * FROM ticket_images WHERE ticket_id = ?", (ticket_id,), one=True)
    if attachment is None:
        abort(404)
    return Response(attachment["image"], mimetype=attachment["content_type"],
                    headers={"X-Content-Type-Options": "nosniff"})


@app.route("/desk/tickets/<int:ticket_id>", methods=["GET", "POST"])
def manage_ticket(ticket_id):
    ticket = query("SELECT * FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if ticket is None:
        abort(404)
    search, sort, page = desk_filters()
    error = None

    if request.method == "POST":
        status = request.form.get("status", "")
        if status not in STATUS_OPTIONS:
            error = "Choose Open, In progress, or Resolved."
        else:
            query("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
            return redirect(url_for(
                "manage_ticket", ticket_id=ticket_id,
                q=search, sort=sort, page=page, saved=1,
            ), code=303)

    email_link = None
    if ticket["email"]:
        # Encode the address and subject so symbols work correctly in the link.
        recipient = quote(ticket["email"], safe="@")
        subject = quote(f"Support ticket ST-{ticket_id}", safe="")
        email_link = f"mailto:{recipient}?subject={subject}"
    image_attached = query("SELECT ticket_id FROM ticket_images WHERE ticket_id = ?", (ticket_id,), one=True)
    return render_template(
        "desk_ticket.html", ticket=ticket, status_options=STATUS_OPTIONS,
        error=error, saved=request.method == "GET" and request.args.get("saved") == "1",
        email_link=email_link, search=search, sort=sort, page=page, image_attached=image_attached,
    ), 400 if error else 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001)
