# Support ticket

A small support-ticket application built with Python, Flask, SQLite, HTML and Bootstrap CSS.

Customers submit their name, email, problem and an optional JPG or PNG image. Staff sign in to search and sort tickets, view attachments, and update the ticket status. The email button opens the staff member's email application.

## Run locally

Use Python 3.11 or newer. From the project folder on macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/flask --app app create-staff
.venv/bin/python app.py
```

Open http://127.0.0.1:5001 for the customer form, or http://127.0.0.1:5001/desk/login for staff login.

Run the `create-staff` command again for each additional staff account. Usernames must be unique. All staff use the same support desk.

Press Ctrl+C to stop the server. Restart it after changing Python or HTML templates. Restarting signs staff out.

## Files

- `app.py`: routes, validation, staff login and database operations.
- `index.html`: ticket form and customer confirmation.
- `login.html`: staff login.
- `desk.html`: ticket search, sorting and pagination.
- `desk_ticket.html`: ticket details, image and status controls.
- `style.css`: custom colours, spacing and layout.
- `static/bootstrap.min.css`: Bootstrap 5.3.8 styles, stored locally for offline use.

The app creates `tickets.db` automatically. It stores tickets, image attachments and staff password hashes. The database and virtual environment are excluded from Git, so a new checkout starts with no accounts or tickets.

The form accepts one JPG or PNG up to 5 MB and 20 megapixels. Dates are displayed in UTC. Replies happen in the email application; the support app does not send or receive email itself.

Bootstrap is distributed under the MIT license; see `static/bootstrap.LICENSE.txt`.

For synthetic rehearsal data, automated checks, a five-minute presentation and code questions, see [DEMO_GUIDE.md](DEMO_GUIDE.md). Set `SUPPORT_TICKET_DB` before starting Python to use a separate database path; the default remains `tickets.db` beside `app.py`.
