from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from datetime import datetime, timezone, timedelta
from io import BytesIO
from functools import wraps
import random
import string
import os

PHT = timezone(timedelta(hours=8))

def get_pht_now():
    return datetime.now(PHT)

app = Flask(__name__)
app.secret_key = "clc-qea-secret-2026"

SUPABASE_URL      = os.environ.get("SUPABASE_URL", "https://awuqqfurmnyqvkfrtehf.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF3dXFxZnVybW55cXZrZnJ0ZWhmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI1ODc4NTgsImV4cCI6MjA4ODE2Mzg1OH0.8A92RyzX22hSUKOJ1xBQ3XkKQ8CmjDfuAkx8E5cWB3g")
STORAGE_BUCKET    = "FORMS"
FORMS_FOLDER      = "FORMS"

ADMIN_EMAIL    = "jmr.tibon@clcqea.com"
ADMIN_PASSWORD = "clcqea12345"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def generate_clc_id():
    now       = get_pht_now()
    date_part = now.strftime("%m%d%Y")
    time_part = now.strftime("%H%M")
    suffix    = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{date_part}CLC{time_part}H-{suffix}"


def stamp_pdf(pdf_bytes, unique_id):
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


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            return redirect(url_for("browse"))
        return f(*args, **kwargs)
    return decorated


# ============================================================
# LOGIN / LOGOUT
# ============================================================
@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("browse"))

    error         = None
    selected_role = request.form.get("role", "regular")

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        role     = request.form.get("role", "regular")

        if role == "admin":
            if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    session["access_token"]  = res.session.access_token
                    session["refresh_token"] = res.session.refresh_token
                except Exception:
                    pass
                session["logged_in"]  = True
                session["user_email"] = ADMIN_EMAIL
                session["is_admin"]   = True
                return redirect(url_for("browse"))
            else:
                error = "Incorrect admin credentials. Please try again."
        else:
            if email == ADMIN_EMAIL:
                error = "Please use the Admin tab to log in with that account."
            else:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    session["logged_in"]     = True
                    session["access_token"]  = res.session.access_token
                    session["refresh_token"] = res.session.refresh_token
                    session["user_email"]    = res.user.email
                    session["is_admin"]      = False
                    return redirect(url_for("browse"))
                except Exception:
                    error = "Incorrect email or password. Please try again."

    return render_template("login.html",
        error=error,
        selected_role=selected_role,
        reg_error=None,
        reg_success=None,
    )


# ============================================================
# REGISTER
# ============================================================
@app.route("/register", methods=["POST"])
def register():
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    confirm  = request.form.get("confirm", "").strip()

    # Block admin email from registering
    if email == ADMIN_EMAIL:
        return render_template("login.html",
            error=None,
            selected_role="regular",
            reg_error="That email cannot be used for registration.",
            reg_success=None,
        )

    # Password match check
    if password != confirm:
        return render_template("login.html",
            error=None,
            selected_role="regular",
            reg_error="Passwords do not match. Please try again.",
            reg_success=None,
        )

    # Password length check
    if len(password) < 6:
        return render_template("login.html",
            error=None,
            selected_role="regular",
            reg_error="Password must be at least 6 characters.",
            reg_success=None,
        )

    try:
        supabase.auth.sign_up({"email": email, "password": password})
        return render_template("login.html",
            error=None,
            selected_role="regular",
            reg_error=None,
            reg_success=f"✅ Account created! A confirmation email has been sent to {email}. Please confirm your email before logging in.",
        )
    except Exception as e:
        err_msg = str(e)
        if "already registered" in err_msg.lower() or "already exists" in err_msg.lower():
            friendly = "That email is already registered. Please sign in instead."
        else:
            friendly = "Registration failed. Please try again."
        return render_template("login.html",
            error=None,
            selected_role="regular",
            reg_error=friendly,
            reg_success=None,
        )


@app.route("/logout")
def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# DEBUG
# ============================================================
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


# ============================================================
# BROWSE
# ============================================================
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

    success_msg = request.args.get("success", "")
    error_msg   = request.args.get("error", "")

    return render_template("browse.html",
        folders=folders,
        all_files=all_files,
        active_folder=active_folder,
        search=request.args.get("search", ""),
        user_email=session.get("user_email", ""),
        is_admin=session.get("is_admin", False),
        success_msg=success_msg,
        error_msg=error_msg,
    )


# ============================================================
# DOWNLOAD
# ============================================================
@app.route("/download", methods=["POST"])
@login_required
def download():
    folder   = request.form.get("folder")
    filename = request.form.get("filename")
    ext      = os.path.splitext(filename)[1].lower()
    base     = os.path.splitext(filename)[0]

    try:
        file_bytes = supabase.storage.from_(STORAGE_BUCKET).download(
            f"{FORMS_FOLDER}/{folder}/{filename}"
        )
        unique_id = generate_clc_id()

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


# ============================================================
# ADMIN — UPLOAD
# ============================================================
@app.route("/admin/upload", methods=["POST"])
@admin_required
def admin_upload():
    folder = request.form.get("folder", "").strip()
    file   = request.files.get("file")

    if not folder or not file or file.filename == "":
        return redirect(url_for("browse", error="Please select a folder and file."))

    filename = file.filename
    if not filename.lower().endswith((".pdf", ".docx")):
        return redirect(url_for("browse", error="Only PDF and DOCX files are allowed."))

    try:
        file_bytes = file.read()
        ext        = os.path.splitext(filename)[1].lower()
        mime       = "application/pdf" if ext == ".pdf" else \
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        path       = f"{FORMS_FOLDER}/{folder}/{filename}"
        supabase.storage.from_(STORAGE_BUCKET).upload(path, file_bytes, {"content-type": mime})
        return redirect(url_for("browse", folder=folder,
                                success=f"'{filename}' uploaded to {folder}."))
    except Exception as e:
        return redirect(url_for("browse", error=f"Upload failed: {e}"))


# ============================================================
# ADMIN — DELETE FILE
# ============================================================
@app.route("/admin/delete", methods=["POST"])
@admin_required
def admin_delete():
    folder   = request.form.get("folder")
    filename = request.form.get("filename")
    try:
        supabase.storage.from_(STORAGE_BUCKET).remove([f"{FORMS_FOLDER}/{folder}/{filename}"])
        supabase.table("usage_logs").delete().eq("form_name", filename).execute()
        return redirect(url_for("browse", folder=folder,
                                success=f"'{filename}' and its logs were deleted."))
    except Exception as e:
        return redirect(url_for("browse", error=f"Delete failed: {e}"))


# ============================================================
# ADMIN — RENAME
# ============================================================
@app.route("/admin/rename", methods=["POST"])
@admin_required
def admin_rename():
    folder   = request.form.get("folder")
    old_name = request.form.get("old_name")
    new_name = request.form.get("new_name", "").strip()

    if not new_name:
        return redirect(url_for("browse", error="New filename cannot be empty."))

    old_ext = os.path.splitext(old_name)[1].lower()
    if not new_name.lower().endswith(old_ext):
        new_name += old_ext

    if new_name == old_name:
        return redirect(url_for("browse", folder=folder))

    try:
        mime       = "application/pdf" if old_ext == ".pdf" else \
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        old_path   = f"{FORMS_FOLDER}/{folder}/{old_name}"
        new_path   = f"{FORMS_FOLDER}/{folder}/{new_name}"
        file_bytes = supabase.storage.from_(STORAGE_BUCKET).download(old_path)
        supabase.storage.from_(STORAGE_BUCKET).upload(new_path, file_bytes, {"content-type": mime})
        supabase.storage.from_(STORAGE_BUCKET).remove([old_path])
        supabase.table("usage_logs").update({"form_name": new_name}).eq("form_name", old_name).execute()
        return redirect(url_for("browse", folder=folder,
                                success=f"'{old_name}' renamed to '{new_name}'."))
    except Exception as e:
        return redirect(url_for("browse", error=f"Rename failed: {e}"))


# ============================================================
# TRACKER — all logged-in users
# ============================================================
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
        user_email=session.get("user_email", ""),
        is_admin=session.get("is_admin", False),
    )


@app.route("/tracker/export")
@login_required
def export_logs():
    import csv, io
    search = request.args.get("search", "").lower()
    logs   = []
    try:
        res  = supabase.table("usage_logs").select("*").order("downloaded_at", desc=True).execute()
        logs = res.data
    except Exception:
        pass

    if search:
        logs = [r for r in logs if search in r["form_name"].lower()]

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
    return send_file(output, mimetype="text/csv", as_attachment=True,
                     download_name=f"CLC_Download_Log_{get_pht_now().strftime('%m%d%Y_%H%M')}.csv")


@app.route("/tracker/clear", methods=["POST"])
@admin_required
def clear_logs():
    try:
        supabase.table("usage_logs").delete().neq("id", 0).execute()
    except Exception as e:
        return f"Error: {e}", 500
    return redirect(url_for("tracker"))


# ============================================================
# CHAT — all logged-in users
# ============================================================
@app.route("/chat")
@login_required
def chat():
    _heartbeat()
    return render_template("chat.html",
        user_email=session.get("user_email", ""),
        is_admin=session.get("is_admin", False),
    )


@app.route("/chat/messages")
@login_required
def chat_messages():
    _heartbeat()
    try:
        res  = supabase.table("chat_messages").select("*") \
                       .order("sent_at", desc=False).limit(100).execute()
        msgs = res.data
    except Exception:
        msgs = []
    return jsonify(msgs)


@app.route("/chat/send", methods=["POST"])
@login_required
def chat_send():
    body    = request.json or {}
    message = body.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400
    if len(message) > 1000:
        return jsonify({"error": "Message too long"}), 400

    try:
        supabase.table("chat_messages").insert({
            "sender":   session.get("user_email"),
            "message":  message,
            "sent_at":  get_pht_now().isoformat(),
            "is_admin": session.get("is_admin", False),
        }).execute()
        _heartbeat()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat/delete/<int:msg_id>", methods=["POST"])
@admin_required
def chat_delete(msg_id):
    try:
        supabase.table("chat_messages").delete().eq("id", msg_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat/online")
@login_required
def chat_online():
    _heartbeat()
    cutoff = (get_pht_now() - timedelta(minutes=2)).isoformat()
    try:
        res   = supabase.table("chat_presence").select("email") \
                        .gte("last_seen", cutoff).execute()
        users = [r["email"] for r in res.data]
    except Exception:
        users = []
    return jsonify(users)


def _heartbeat():
    email = session.get("user_email")
    if not email:
        return
    try:
        supabase.table("chat_presence").upsert({
            "email":     email,
            "last_seen": get_pht_now().isoformat(),
        }, on_conflict="email").execute()
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)