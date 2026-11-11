"""Integration proof with temporary databases; no user tickets or passwords are read."""

from io import BytesIO
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash

# Importing the application initializes tables. Redirect that first initialization
# too, so merely collecting tests cannot create or open the user's tickets.db.
with tempfile.TemporaryDirectory() as import_directory:
    with patch.dict(os.environ, {"SUPPORT_TICKET_DB": str(Path(import_directory) / "import.db")}):
        import app as ticket_app


class TicketAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_db = ticket_app.DATABASE
        ticket_app.DATABASE = Path(self.directory.name) / "test.db"
        ticket_app.initialize_database()
        ticket_app.app.config["TESTING"] = True
        self.client = ticket_app.app.test_client()
        # Synthetic credentials exist only inside this disposable database.
        self.password = "temporary-test-password"
        ticket_app.query("INSERT INTO staff (username, password_hash) VALUES (?, ?)",
                         ("demo_staff", generate_password_hash(self.password)))

    def tearDown(self):
        ticket_app.DATABASE = self.original_db
        self.directory.cleanup()

    def csrf(self, client=None, path="/"):
        client = client or self.client
        client.get(path)
        with client.session_transaction() as session:
            return session["csrf_token"]

    def submit(self, **changes):
        fields = {"csrf_token": self.csrf(), "name": "Demo Customer",
                  "email": "demo@example.invalid", "problem": "Printer is offline."}
        fields.update(changes)
        response = self.client.post("/submit", data=fields)
        self.addCleanup(response.close)
        self.addCleanup(response.request.input_stream.close)
        return response

    def login(self):
        return self.client.post("/desk/login", data={
            "csrf_token": self.csrf(path="/desk/login"),
            "username": "demo_staff", "password": self.password})

    def count(self):
        return ticket_app.query("SELECT COUNT(*) FROM tickets", one=True)[0]

    def image(self, format="PNG"):
        image = BytesIO()
        Image.new("RGB", (8, 8), "blue").save(image, format=format)
        return image.getvalue()

    def test_submit_redirects_to_private_reference_and_persists(self):
        response = self.submit(name="  Demo Customer  ")
        self.assertEqual(response.status_code, 303)
        self.assertRegex(response.location, r"^/tickets/[A-Za-z0-9_-]{40,}$")
        page = self.client.get(response.location)
        self.assertIn(b"Ticket Created", page.data)
        self.assertIn(b"ST-1", page.data)
        self.assertIn(b"Printer is offline.", page.data)
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        ticket_app.initialize_database()
        # A fresh SQL connection and a fresh browser session read saved data.
        with closing(sqlite3.connect(ticket_app.DATABASE)) as connection:
            self.assertEqual(connection.execute("SELECT name, status FROM tickets").fetchone(),
                             ("Demo Customer", "Open"))
        self.assertIn(b"Printer is offline.", ticket_app.app.test_client().get(response.location).data)

    def test_validation_rejects_missing_long_and_invalid_values_without_saving(self):
        for changes in ({"name": " "}, {"email": "bad"}, {"email": "a@@example.invalid"},
                        {"problem": " "}, {"name": "x" * 81}, {"problem": "x" * 1001}):
            with self.subTest(changes=changes):
                self.assertEqual(self.submit(**changes).status_code, 400)
        self.assertEqual(self.count(), 0)

    def test_csrf_rejects_absent_forged_and_other_session_tokens(self):
        token = self.csrf()
        other = ticket_app.app.test_client()
        for client, token_value in ((self.client, ""), (self.client, "forged"), (other, token)):
            self.assertEqual(client.post("/submit", data={"csrf_token": token_value}).status_code, 400)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.client.post("/desk/login", data={}).status_code, 400)

    def test_staff_routes_and_images_require_login(self):
        self.submit()
        for route in ("/desk", "/desk/tickets/1", "/desk/tickets/1/image"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.location, "/desk/login")
        self.assertEqual(self.client.post("/desk/tickets/1", data={"status": "Resolved"}).status_code, 303)
        self.assertEqual(ticket_app.query("SELECT status FROM tickets", one=True)[0], "Open")
        self.assertEqual(self.client.get("/tickets/not-a-real-token").status_code, 404)
        self.assertEqual(self.client.get("/tickets/1").status_code, 404)

    def test_login_hash_checks_session_and_logout(self):
        response = self.client.post("/desk/login", data={"csrf_token": self.csrf(path="/desk/login"),
                                   "username": "demo_staff", "password": "incorrect"})
        self.assertEqual(response.status_code, 401)
        stored = ticket_app.query("SELECT password_hash FROM staff", one=True)[0]
        self.assertNotEqual(stored, self.password)
        self.assertTrue(check_password_hash(stored, self.password))
        self.assertEqual(self.login().status_code, 303)
        self.assertEqual(self.client.get("/desk").status_code, 200)
        self.assertEqual(self.client.post("/desk/logout", data={"csrf_token": self.csrf(path="/desk")}).status_code, 303)
        self.assertEqual(self.client.get("/desk").status_code, 303)

    def test_status_validation_csrf_and_customer_view(self):
        location = self.submit().location
        self.login()
        self.assertEqual(self.client.post("/desk/tickets/1", data={"status": "Resolved"}).status_code, 400)
        token = self.csrf(path="/desk/tickets/1")
        self.assertEqual(self.client.post("/desk/tickets/1", data={"csrf_token": token, "status": "Deleted"}).status_code, 400)
        self.assertEqual(ticket_app.query("SELECT status FROM tickets", one=True)[0], "Open")
        for status in ("In progress", "Resolved"):
            response = self.client.post("/desk/tickets/1", data={"csrf_token": token, "status": status})
            self.assertEqual(response.status_code, 303)
            self.assertIn(status.encode(), self.client.get(location).data)
        self.assertEqual(self.client.get("/desk/tickets/999").status_code, 404)

    def test_search_sort_and_pagination(self):
        for index in range(12):
            self.submit(name=f"Customer {index:02d}", problem=f"Training issue {index:02d}")
        self.login()
        first = self.client.get("/desk?sort=oldest").get_data(as_text=True)
        self.assertIn("Showing 1–10 of 12", first)
        second = self.client.get("/desk?sort=oldest&page=2").get_data(as_text=True)
        self.assertIn("Showing 11–12 of 12", second)
        self.assertIn("Customer 11", second)
        for term in ("CUSTOMER 11", "Training issue 11", "ST-12"):
            page = self.client.get("/desk", query_string={"q": term}).get_data(as_text=True)
            self.assertIn("Customer 11", page)
            self.assertIn("Showing 1–1 of 1", page)
        self.assertIn("Page 2 of 2", self.client.get("/desk?page=999&sort=unsafe").get_data(as_text=True))
        self.assertIn("Page 1 of 2", self.client.get("/desk?page=bad").get_data(as_text=True))

    def test_parameterised_sql_and_html_escaping(self):
        name = "'); DROP TABLE tickets; --"
        problem = '<script>alert("demo")</script>'
        response = self.submit(name=name, problem=problem)
        page = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertEqual(ticket_app.query("SELECT problem FROM tickets", one=True)[0], problem)
        self.login()
        self.assertEqual(self.client.get("/desk", query_string={"q": "' OR 1=1 --"}).status_code, 200)
        self.assertEqual(self.count(), 1)

    def test_png_and_jpeg_are_checked_by_content_and_only_staff_can_fetch(self):
        for format in ("PNG", "JPEG"):
            data = self.image(format)
            response = self.submit(image=(BytesIO(data), "misleading-name.txt"))
            self.assertEqual(response.status_code, 303)
        self.login()
        for ticket_id, mime in ((1, "image/png"), (2, "image/jpeg")):
            response = self.client.get(f"/desk/tickets/{ticket_id}/image")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, mime)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn(f"ticket-{ticket_id}", response.headers["Content-Disposition"])
        self.assertEqual(self.client.get("/desk/tickets/999/image").status_code, 404)

    def test_invalid_attachment_does_not_leave_a_ticket(self):
        for data, filename in ((b"not an image", "fake.png"), (self.image("GIF"), "fake.jpg"),
                               (b"x" * (ticket_app.MAX_IMAGE_SIZE + 1), "large.png")):
            self.assertEqual(self.submit(image=(BytesIO(data), filename)).status_code, 400)
        self.assertEqual(self.count(), 0)

    def test_request_over_six_megabytes_redirects_without_saving(self):
        response = self.submit(image=(BytesIO(b"x" * (7 * 1024 * 1024)), "large.png"))
        self.assertEqual(response.status_code, 303)
        self.assertIn("upload_error=1", response.location)
        self.assertIn(b"upload was too large", self.client.get(response.location).data)
        self.assertEqual(self.count(), 0)

    def test_ticket_and_attachment_insert_are_atomic(self):
        ticket_app.query("""CREATE TRIGGER simulate_image_failure BEFORE INSERT ON ticket_images
                            BEGIN SELECT RAISE(ABORT, 'simulated attachment failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.submit(image=(BytesIO(self.image()), "demo.png"))
        self.assertEqual(self.count(), 0)

    def test_offline_styles_email_link_and_trusted_hosts(self):
        self.submit(email="demo+training@example.invalid")
        self.login()
        page = self.client.get("/desk/tickets/1").get_data(as_text=True)
        self.assertIn("mailto:demo%2Btraining@example.invalid?subject=Support%20ticket%20ST-1", page)
        self.assertNotRegex(page, r'(?:src|href)="https?://')
        for path in ("/static/bootstrap.min.css", "/style.css"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/", headers={"Host": "untrusted.invalid"}).status_code, 400)

    def test_demo_setup_creates_synthetic_data_and_refuses_existing_database(self):
        target = Path(self.directory.name) / "synthetic.db"
        command = [sys.executable, str(Path(ticket_app.__file__).with_name("demo_setup.py")), "--database", str(target)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 12)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ticket_images").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM staff").fetchone()[0], 0)
        before = target.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
