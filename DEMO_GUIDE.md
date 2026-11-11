# Flask support ticket: defence rehearsal

This is the Flask project in the GitHub repository. It uses HTML forms, Python routes and SQLite. The separate `support-ticket-demo` directory is a later Streamlit conversation prototype; describe it as an extension, not as a feature already present here.

## Prepare a separate demonstration

Use Python 3.11 or newer. From this project directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python demo_setup.py
export SUPPORT_TICKET_DB="$PWD/.demo/tickets.db"
.venv/bin/flask --app app create-staff
.venv/bin/python app.py
```

Choose your own staff username and password when prompted. The password is hidden and stored as a hash. Keep that terminal open. Open `http://127.0.0.1:5001` and `http://127.0.0.1:5001/desk/login` in the browser. Stop the server with Ctrl+C.

The rehearsal database already prepared on this laptop contains 12 made-up tickets and one generated PNG. Skip `demo_setup.py` when reusing it. The script refuses to overwrite any existing database. For a fresh rehearsal use `--database .demo/rehearsal-2.db`, then set `SUPPORT_TICKET_DB` to that same path before the staff and server commands. The environment variable applies to each new terminal separately.

The normal `tickets.db` is separate. SQLite files, environments and local staff-login notes are ignored by Git. Images are inside the database, not a public uploads directory. Bootstrap CSS is bundled locally, so the running app needs no internet. Installing dependencies and opening GitHub do need internet if not already available.

## Five-minute live demonstration

| Time | Do this | Say this in your own words |
| --- | --- | --- |
| 0:00–0:30 | Show the customer form. | “I built a small service-desk application to record support requests and let staff track their progress.” |
| 0:30–1:15 | Submit a made-up name, `demo@example.invalid`, and “Training-room printer is offline.” | “The browser sends a POST request. Python validates the fields and saves the request in SQLite. The confirmation includes a reference and status.” |
| 1:15–2:00 | Show the confirmation URL. Reload it. | “This is a GET page after a 303 redirect. Reloading reads the saved record instead of submitting another ticket. The long random token identifies the customer's view.” |
| 2:00–3:00 | Sign in to the staff desk. Search `Printer`, reset, show Next, then open the seeded `ST-1` image. | “Staff access requires login. Search is case-insensitive, pagination shows ten records per page, and images are checked by their contents.” |
| 3:00–3:40 | Update the new ticket to In progress, then Resolved. Reload its customer confirmation. | “The update is saved in the database. The customer view reads the same record, so it shows the new status.” |
| 3:40–4:10 | Point to Email customer. No email needs to be sent. | “This generates a mailto link with the address and ticket reference. It opens an email program; this application does not send email.” |
| 4:10–5:00 | Show the code route and Git history. | “The work is divided between templates, Flask routes and database tables. Git records changes locally; GitHub hosts the repository.” |

If restarting to prove persistence, stop and run the same server command with the same database variable. Tickets remain; the randomly generated session secret means staff must sign in again.

## Trace one real request through the source

Line numbers below refer to the accompanying `app.py`; search the named function if they move.

1. `index.html` has `<form action="/submit" method="post" enctype="multipart/form-data">`. Field `name` attributes become keys in `request.form`; the optional file appears in `request.files`.
2. `check_access_and_form()` (`app.py:105`) runs before a route. It protects `/desk` paths and compares the posted CSRF token with the token in the browser session. A missing or wrong token rejects the POST.
3. `submit_ticket()` (`app.py:217`) strips surrounding spaces and checks required values, lengths and the email format. Client-side `required` helps the user, but Python performs the decisive checks. Invalid input returns HTTP 400 without inserting a ticket.
4. `read_image()` (`app.py:201`) reads at most 5 MB plus one byte, opens actual JPG/PNG content with Pillow and checks the 20-megapixel limit. Renaming a text file to `.png` does not make it valid.
5. `submit_ticket()` inserts into SQLite using `VALUES (?, ?, ?, ?)` and a separate values tuple (`app.py:246`). Input is treated as data, not SQL instructions. The ticket and optional image are committed together; an attachment failure rolls both back.
6. The database assigns a numeric ID. `secrets.token_urlsafe(32)` creates a separate random customer-view token. The route returns a 303 redirect (`app.py:255`) to `view_ticket()` (`app.py:306`), which reads the saved row and renders the confirmation.
7. `staff_login()` (`app.py:139`) looks up a username with a placeholder, checks its password hash and records login state in the Flask session. `support_desk()` (`app.py:270`) searches saved tickets. Sort SQL comes from the fixed `SORT_ORDERS` dictionary, not from arbitrary URL text.
8. `manage_ticket()` (`app.py:329`) allows only Open, In progress or Resolved, runs a parameterised UPDATE, then redirects. `ticket_image()` (`app.py:316`) serves the saved image only through the protected staff path.

The three tables are `tickets` (request and current status), `staff` (username and password hash), and `ticket_images` (image bytes and MIME type linked by ticket ID). A SQLite database is a local file; it does not require a separate database server.

## Likely questions

| Lecturer asks | Answer grounded in this project |
| --- | --- |
| Why Flask? | It maps URLs and HTTP methods to small Python functions and renders HTML templates. It suits this small form and staff dashboard. |
| What is the difference between frontend and backend? | HTML, Bootstrap and `style.css` present the forms. Flask validates requests and runs database operations. SQLite stores records. |
| What does POST mean? | A submission that can change server data. GET reads a page or performs the desk search. |
| Why redirect after saving? | The browser reaches a GET confirmation page. Reloading that page does not repeat the previous POST. |
| How do you stop SQL injection? | User values go through `?` placeholders. The variable ORDER BY expression is selected from a fixed whitelist. |
| How do you stop script text from running? | Jinja escapes user text in the HTML templates. The test submits script-looking text and checks that it is escaped. |
| Are passwords encrypted? | They are hashed, not encrypted. Encryption is reversible with a key. Password verification checks a one-way salted hash; the application does not recover the original password. Ticket descriptions and images are not encrypted by this code. |
| What does CSRF protection do? | It requires a session-specific token on POST forms, helping reject a forged submission from another site. It does not replace input validation or staff login. |
| Can customers see one another's tickets? | There is no customer login here. A customer needs the long random view link; anyone who receives that link can read that ticket's details. Staff access uses login. Images are staff-only. |
| What can staff do? | All staff share the same desk, search/sort/page tickets, inspect images and set any of the three allowed statuses. There are no separate administrator roles or enforced progression between statuses here. |
| Does Resolved mean the customer accepted? | In this Flask version staff select Resolved. Customer acceptance and conversation history belong to the separate Streamlit extension. |
| What does the email button do? | It opens the installed email client using a mailto link. There is no SMTP integration and no email-delivery confirmation in this app. |
| What happens after closing the browser? | SQLite records persist on disk. The session tracks login separately. Restarting the app invalidates existing staff sessions. |
| What are the current limits? | It is a local demonstration: no public deployment, password-reset flow, email delivery, login rate limiting or status audit history. The email check is a simple format check, not proof an inbox exists. |
| What would you improve next? | Choose a requirement: for example customer accounts and conversation history, which the separate prototype explores. Public deployment would need its own server and authentication configuration. |
| What did you personally do? | Describe only your actual work and understanding. A commit's author label or an app running on your laptop does not prove who wrote every line. |

## Run the proof

```sh
.venv/bin/python -m unittest discover -s tests -v
git status -sb
git log --oneline -5
git remote -v
git ls-files '*.db' '*.sqlite*' '*LOGIN*' '.env*'
```

The 14 integration tests use new temporary databases, including during module import. They cover valid and invalid submissions, CSRF, staff login/logout and access, allowed statuses, search and pagination, HTML escaping, SQL-looking text, attachments, oversized requests, persistence and rollback. They also verify the demo script refuses an existing database. They do not start a listening web server.

The repository's existing history is `4a41c47` (add app), `7dd9880` (attachment filename fix), then `0ae93aa` (ignore local staff-login notes), on `main` tracking `origin/main`. Origin is `https://github.com/TobyObiwole/support-ticket-1.git`. Rehearsal additions may appear as local uncommitted changes. No commit or push is needed to run them. `git status` shows the working tree; `git log` shows committed snapshots; `git remote -v` shows the configured GitHub destination. These commands do not prove current GitHub network availability.
