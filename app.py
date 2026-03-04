from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from datetime import datetime, timezone, timedelta

PHT = timezone(timedelta(hours=8))

def get_pht_now():
    return datetime.now(PHT)
from io import BytesIO
from functools import wraps
import random
import string
import os

app = Flask(__name__)
app.secret_key = "clc-qea-secret-2026"

SUPABASE_URL      = os.environ.get("SUPABASE_URL", "https://awuqqfurmnyqvkfrtehf.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF3dXFxZnVybW55cXZrZnJ0ZWhmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI1ODc4NTgsImV4cCI6MjA4ODE2Mzg1OH0.8A92RyzX22hSUKOJ1xBQ3XkKQ8CmjDfuAkx8E5cWB3g")
STORAGE_BUCKET    = "FORMS"
FORMS_FOLDER      = "FORMS"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def generate_clc_id():
    """Returns a single unique ID string: 03042026CLC2040H-XXXXXX"""
    now       = get_pht_now()
    date_part = now.strftime("%m%d%Y")
    time_part = now.strftime("%H%M")
    suffix    = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{date_part}CLC{time_part}H-{suffix}"


def stamp_pdf(pdf_bytes, unique_id):
    """Stamp unique_id onto first page of PDF. Returns BytesIO."""
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
    return out


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


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


@app.route("/debug")
@login_required
def debug():
    result = {}
    try:
        root = supabase.storage.from_(STORAGE_BUCKET).list("")
        result["root"] = [i["name"] for i in root]
    except Exception as e:
        result["root_error"] = str(e)
    try:
        forms = supabase.storage.from_(STORAGE_BUCKET).list(FORMS_FOLDER)
        result["FORMS_folder"] = [i["name"] for i in forms]
    except Exception as e:
        result["FORMS_error"] = str(e)
    return jsonify(result)


@app.route("/browse")
@login_required
def browse():
    folders   = []
    all_files = []
    allowed   = (".pdf", ".docx")

    try:
        items   = supabase.storage.from_(STORAGE_BUCKET).list(FORMS_FOLDER)
        folders = sorted([i["name"] for i in items if i.get("metadata") is None])
    except Exception:
        pass

    active_folder = request.args.get("folder", "")
    search        = request.args.get("search", "").lower()

    try:
        if active_folder:
            items     = supabase.storage.from_(STORAGE_BUCKET).list(f"{FORMS_FOLDER}/{active_folder}")
            all_files = [(active_folder, i["name"]) for i in items if i["name"].lower().endswith(allowed)]
        else:
            for folder in folders:
                items = supabase.storage.from_(STORAGE_BUCKET).list(f"{FORMS_FOLDER}/{folder}")
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


@app.route("/download", methods=["POST"])
@login_required
def download():
    folder   = request.form.get("folder")
    filename = request.form.get("filename")
    ext      = os.path.splitext(filename)[1].lower()
    base     = os.path.splitext(filename)[0]

    try:
        # Download file from Supabase Storage
        file_bytes = supabase.storage.from_(STORAGE_BUCKET).download(
            f"{FORMS_FOLDER}/{folder}/{filename}"
        )

        # Generate unique ID
        unique_id = generate_clc_id()

        # Process based on file type
        if ext == ".pdf":
            file_out = stamp_pdf(file_bytes, unique_id)
            new_name = f"{base} - {unique_id}.pdf"
            mimetype = "application/pdf"
        elif ext == ".docx":
            file_out = BytesIO(file_bytes)
            new_name = f"{base} - {unique_id}.docx"
            mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            return "File type not supported.", 400

        # Log download
        try:
            supabase.table("usage_logs").insert({
                "folder_name":   folder,
                "form_name":     filename,
                "unique_id":     unique_id,
                "downloaded_by": session.get("user_email"),
                "downloaded_at": get_pht_now().isoformat(),
            }).execute()
        except Exception:
            pass

        return send_file(file_out, mimetype=mimetype, as_attachment=True, download_name=new_name)

    except Exception as e:
        return f"Error: {e}", 500


@app.route("/tracker")
@login_required
def tracker():
    search = request.args.get("search", "").lower()
    logs   = []
    try:
        res  = supabase.table("usage_logs").select("*").order("downloaded_at", desc=True).execute()
        logs = res.data
    except Exception:
        pass

    if search:
        logs = [r for r in logs if search in r["form_name"].lower()]

    grouped = {}
    for r in logs:
        grouped.setdefault(r["form_name"], []).append(r)

    return render_template("tracker.html",
        grouped=grouped,
        all_logs=logs,
        search=request.args.get("search", ""),
        user_email=session.get("user_email", "")
    )


@app.route("/tracker/export")
@login_required
def export_logs():
    import csv
    search = request.args.get("search", "").lower()
    logs   = []
    try:
        res  = supabase.table("usage_logs").select("*").order("downloaded_at", desc=True).execute()
        logs = res.data
    except Exception:
        pass

    if search:
        logs = [r for r in logs if search in r["form_name"].lower()]

    output = BytesIO()
    import io
    text_output = io.StringIO()
    writer = csv.writer(text_output)
    writer.writerow(["Form Name", "Folder", "Downloaded By", "Downloaded At", "Unique ID"])
    for r in logs:
        writer.writerow([
            r["form_name"],
            r["folder_name"],
            r.get("downloaded_by", ""),
            r["downloaded_at"][:19].replace("T", " "),
            r["unique_id"],
        ])
    output = BytesIO(text_output.getvalue().encode("utf-8-sig"))
    output.seek(0)
    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"CLC_Download_Log_{get_pht_now().strftime('%m%d%Y_%H%M')}.csv"
    )


@app.route("/tracker/clear", methods=["POST"])
@login_required
def clear_logs():
    try:
        supabase.table("usage_logs").delete().neq("id", 0).execute()
    except Exception as e:
        return f"Error: {e}", 500
    return redirect(url_for("tracker"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
