from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from datetime import datetime
from io import BytesIO
import random
import string
import os

app = Flask(__name__)
app.secret_key = "clc-qea-secret-2026"

# ── SUPABASE CONFIG ──────────────────────────────────────────
SUPABASE_URL      = os.environ.get("SUPABASE_URL", "https://awuqqfurmnyqvkfrtehf.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF3dXFxZnVybW55cXZrZnJ0ZWhmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI1ODc4NTgsImV4cCI6MjA4ODE2Mzg1OH0.8A92RyzX22hSUKOJ1xBQ3XkKQ8CmjDfuAkx8E5cWB3g")
STORAGE_BUCKET    = "forms"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ── HELPERS ──────────────────────────────────────────────────
def generate_clc_id():
    now       = datetime.now()
    date_part = now.strftime("%m%d%Y")
    time_part = now.strftime("%H%M")
    suffix    = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{date_part}CLC{time_part}H-{suffix}", suffix


def stamp_pdf(pdf_bytes: bytes):
    unique_id, suffix = generate_clc_id()
    reader     = PdfReader(BytesIO(pdf_bytes))
    first_page = reader.pages[0]
    width      = float(first_page.mediabox.width)
    height     = float(first_page.mediabox.height)

    packet = BytesIO()
    can    = canvas.Canvas(packet, pagesize=(width, height))
    can.setFont("Helvetica-Bold", 10)
    can.drawRightString(width - 30, height - 25, f"ID: {unique_id}")
    can.save()
    packet.seek(0)

    id_layer = PdfReader(packet)
    writer   = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(id_layer.pages[0])
        writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out, suffix, unique_id


def get_authed_client():
    """Return a Supabase client with the user's access token."""
    token = session.get("access_token")
    if not token:
        return None
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.auth.set_session(token, session.get("refresh_token", ""))
    return client


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ── AUTH ROUTES ──────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("browse"))

    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            session["logged_in"]     = True
            session["access_token"]  = res.session.access_token
            session["refresh_token"] = res.session.refresh_token
            session["user_email"]    = res.user.email
            return redirect(url_for("browse"))
        except Exception:
            error = "Incorrect email or password. Please try again."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    session.clear()
    return redirect(url_for("login"))


# ── BROWSE ───────────────────────────────────────────────────
@app.route("/browse")
@login_required
def browse():
    client  = get_authed_client()
    folders = []
    try:
        items   = client.storage.from_(STORAGE_BUCKET).list("FORMS")
        folders = sorted([i["name"] for i in items if i.get("metadata") is None])
    except Exception:
        pass

    active_folder = request.args.get("folder", "")
    search        = request.args.get("search", "").lower()

    all_files = []
    allowed = (".pdf", ".docx")
    try:
        if active_folder:
            items = client.storage.from_(STORAGE_BUCKET).list(f"FORMS/{active_folder}")
            all_files = [(active_folder, i["name"]) for i in items if i["name"].lower().endswith(allowed)]
        else:
            for folder in folders:
                items = client.storage.from_(STORAGE_BUCKET).list(f"FORMS/{folder}")
                for i in items:
                    if i["name"].lower().endswith(allowed):
                        all_files.append((folder, i["name"]))
    except Exception:
        pass

    if search:
        all_files = [(f, n) for f, n in all_files if search in n.lower()]

    return render_template("browse.html",
        folders=folders,
        all_files=all_files,
        active_folder=active_folder,
        search=request.args.get("search", ""),
        user_email=session.get("user_email", "")
    )


# ── DOWNLOAD (stamp PDFs, direct download for DOCX) ──────────
@app.route("/download", methods=["POST"])
@login_required
def download():
    folder   = request.form.get("folder")
    filename = request.form.get("filename")
    client   = get_authed_client()
    ext      = os.path.splitext(filename)[1].lower()

    try:
        file_bytes = client.storage.from_(STORAGE_BUCKET).download(f"FORMS/{folder}/{filename}")

        if ext == ".pdf":
            # Stamp PDF with unique ID
            file_out, code, uid = stamp_pdf(file_bytes)
            new_name = f"{os.path.splitext(filename)[0]} - {code}.pdf"
            mimetype = "application/pdf"
        elif ext == ".docx":
            _, code, uid = generate_clc_id()
            file_out = BytesIO(file_bytes)
            new_name = filename
            mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            return "File type not supported.", 400

        # Log to database
        client.table("usage_logs").insert({
            "folder_name":   folder,
            "form_name":     filename,
            "unique_id":     uid,
            "downloaded_by": session.get("user_email"),
            "downloaded_at": datetime.utcnow().isoformat(),
        }).execute()

        return send_file(
            file_out,
            mimetype=mimetype,
            as_attachment=True,
            download_name=new_name
        )
    except Exception as e:
        return f"Error: {e}", 500


# ── TRACKER ──────────────────────────────────────────────────
@app.route("/tracker")
@login_required
def tracker():
    client = get_authed_client()
    search = request.args.get("search", "").lower()
    logs   = []
    try:
        res  = client.table("usage_logs").select("*").order("downloaded_at", desc=True).execute()
        logs = res.data
    except Exception:
        pass

    if search:
        logs = [r for r in logs if search in r["form_name"].lower()]

    # Group by form name
    grouped = {}
    for r in logs:
        grouped.setdefault(r["form_name"], []).append(r)

    return render_template("tracker.html",
        grouped=grouped,
        all_logs=logs,
        search=request.args.get("search", ""),
        user_email=session.get("user_email", "")
    )


@app.route("/debug")
@login_required
def debug():
    client = get_authed_client()
    result = {}
    try:
        # Try listing root
        root = client.storage.from_(STORAGE_BUCKET).list("")
        result["root"] = [i["name"] for i in root]
    except Exception as e:
        result["root_error"] = str(e)
    try:
        # Try listing FORMS subfolder
        forms = client.storage.from_(STORAGE_BUCKET).list("FORMS")
        result["FORMS"] = [i["name"] for i in forms]
    except Exception as e:
        result["FORMS_error"] = str(e)
    return jsonify(result)



@login_required
def clear_logs():
    client = get_authed_client()
    try:
        client.table("usage_logs").delete().neq("id", 0).execute()
    except Exception as e:
        return f"Error: {e}", 500
    return redirect(url_for("tracker"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
