from flask import Flask, render_template,render_template_string, request, redirect, url_for, session, send_file, flash
import folium
from folium.plugins import MarkerCluster, Fullscreen
import pandas as pd
import os
import sqlite3
import hashlib
import threading
import io
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'rahasia-super-aman'  # for production, generate a secure secret

# ----------------- DATABASE -----------------
def get_db_path():
    folder = os.path.join(os.path.expanduser("~"), "Documents", "DataKasus")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "data.db")

DB_PATH = get_db_path()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kasus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL,
            longitude REAL,
            nama TEXT,
            lokasi TEXT,
            jaringan TEXT,
            waktu TEXT
        )
    """)
    conn.commit()
    conn.close()

def update_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(kasus)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'jaringan' not in columns:
        cursor.execute("ALTER TABLE kasus ADD COLUMN jaringan TEXT")
    if 'waktu' not in columns:
        cursor.execute("ALTER TABLE kasus ADD COLUMN waktu TEXT")
    conn.commit()
    conn.close()

def save_data(latitude, longitude, nama, lokasi, jaringan, waktu):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO kasus (latitude, longitude, nama, lokasi, jaringan, waktu) VALUES (?, ?, ?, ?, ?, ?)",
                   (latitude, longitude, nama, lokasi, jaringan, waktu))
    conn.commit()
    conn.close()

def update_data(id, latitude, longitude, nama, lokasi, jaringan, waktu):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE kasus SET latitude=?, longitude=?, nama=?, lokasi=?, jaringan=?, waktu=? WHERE id=?",
                   (latitude, longitude, nama, lokasi, jaringan, waktu, id))
    conn.commit()
    conn.close()

def delete_data(id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kasus WHERE id=?", (id,))
    conn.commit()
    conn.close()

def load_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    rows = cursor.execute("SELECT id, latitude, longitude, nama, lokasi, jaringan, waktu FROM kasus").fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame(columns=["id","latitude","longitude","nama","lokasi","jaringan","waktu"])
    return pd.DataFrame(rows, columns=["id", "latitude", "longitude", "nama", "lokasi", "jaringan", "waktu"])

def get_color_by_name(name):
    colors = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred',
              'beige', 'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'white',
              'pink', 'lightblue', 'lightgreen', 'gray', 'black', 'lightgray']
    index = int(hashlib.sha256(str(name).encode('utf-8')).hexdigest(), 16) % len(colors)
    return colors[index]

init_db()
update_schema()

# ----------------- AUTH (simple) -----------------
def check_login():
    return session.get("logged_in")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if "shutdown" in request.form:
            return redirect(url_for("shutdown"))
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        # basic creds -- replace with proper auth in production
        if username == "admin" and password == "1234":
            session["logged_in"] = True
            flash("Login berhasil", "success")
            return redirect(url_for("index"))
        flash("Login gagal", "danger")
    return render_template("login.html")

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("Anda telah logout", "info")
    return redirect(url_for("login"))

# ----------------- HOME / MAP -----------------
@app.route("/", methods=["GET"])
def index():
    if not check_login():
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip().lower()
    df = load_data()

    # filter by multiple keywords across nama/lokasi/jaringan
    if query:
        keywords = [k for k in query.split() if k]
        if keywords:
            def match_row(row):
                text = " ".join([str(row.get(c,"")) for c in ["nama","lokasi","jaringan"]]).lower()
                return all(k in text for k in keywords)
            df = df[df.apply(match_row, axis=1)]

    # drop rows missing coords
    df = df.dropna(subset=["latitude","longitude"])

    # build folium map
    if df.empty:
        # fallback location if no data
        center = [-6.200000, 106.816666]  # Jakarta center as default
    else:
        center = [df["latitude"].mean(), df["longitude"].mean()]

    m = folium.Map(location=center, zoom_start=13)
    Fullscreen().add_to(m)
    marker_cluster = MarkerCluster().add_to(m)

    for _, row in df.iterrows():
        # URL to lihat_data filtered by name (opens full window)
        lihat_data_url = url_for("lihat_data", nama=row["nama"])
        popup_html = f"""
        <div style="min-width:200px">
          <strong>{row['nama']}</strong><br>
          <small>{row['lokasi']}</small><br>
          <small>Jaringan: {row['jaringan']}</small><br>
          <small>Waktu: {row['waktu']}</small><br><br>
          <a href="{url_for('edit_data', id=int(row['id']))}" class="btn btn-sm btn-primary" target="_top">Edit</a>
          <a href="{url_for('hapus_data', id=int(row['id']))}" class="btn btn-sm btn-danger" target="_top" onclick="return confirm('Yakin ingin menghapus?')">Hapus</a>
          <a href="#" onclick="window.top.location.href='{lihat_data_url}';" class="btn btn-sm btn-warning">Lihat Semua Data</a>
        </div>
        """
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color=get_color_by_name(row["nama"]), icon="info-sign")
        ).add_to(marker_cluster)

    map_html = m._repr_html_()

    return render_template("index.html", map_html=map_html, query=query, total=len(df))

# ----------------- LIHAT DATA -----------------
@app.route("/lihat_data")
def lihat_data():
    if not check_login():
        return redirect(url_for("login"))

    nama = request.args.get("nama", type=str)
    df = load_data()
    if nama:
        df = df[df["nama"] == nama]
    # render nicer table
    table_html = df.to_html(classes="table table-striped table-hover table-bordered", index=False, escape=False)
    return render_template("lihat_data.html", table_html=table_html, nama=nama, count=len(df))

# ----------------- DOWNLOAD EXCEL / CSV -----------------
@app.route("/download_excel")
def download_excel():
    if not check_login():
        return redirect(url_for("login"))
    df = load_data()
    if df.empty:
        flash("Tidak ada data untuk diunduh.", "warning")
        return redirect(url_for("lihat_data"))
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="DataKasus")
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="data_kasus.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/download_csv")
def download_csv():
    if not check_login():
        return redirect(url_for("login"))
    df = load_data()
    if df.empty:
        flash("Tidak ada data untuk diunduh.", "warning")
        return redirect(url_for("lihat_data"))
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), as_attachment=True, download_name="data_kasus.csv",
                     mimetype="text/csv")

# ----------------- TAMBAH DATA -----------------
@app.route("/tambah", methods=["GET", "POST"])
def tambah_data():
    if not check_login():
        return redirect(url_for("login"))
    if request.method == "POST":
        try:
            nama = request.form["nama"].strip()
            lokasi = request.form["lokasi"].strip()
            jaringan = request.form.get("jaringan","").strip()
            waktu = request.form.get("waktu","")
            koordinat = request.form.get("koordinat","").strip()
            lat, lon = map(str.strip, koordinat.split(","))
            # try to normalize waktu: if empty, use now
            if not waktu:
                waktu = datetime.now().isoformat(sep=" ", timespec="seconds")
            save_data(float(lat), float(lon), nama, lokasi, jaringan, waktu)
            flash("Data berhasil disimpan.", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Gagal menyimpan data: {e}", "danger")
    return render_template("tambah.html")

# ----------------- EDIT & HAPUS -----------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_data(id):
    if not check_login():
        return redirect(url_for("login"))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if request.method == "POST":
        try:
            nama = request.form["nama"].strip()
            lokasi = request.form["lokasi"].strip()
            jaringan = request.form.get("jaringan","").strip()
            waktu = request.form.get("waktu","")
            koordinat = request.form.get("koordinat","").strip()
            lat, lon = map(str.strip, koordinat.split(","))
            update_data(id, float(lat), float(lon), nama, lokasi, jaringan, waktu)
            flash("Data berhasil diupdate.", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Error saat edit: {e}", "danger")
    row = cursor.execute("SELECT nama, lokasi, latitude, longitude, jaringan, waktu FROM kasus WHERE id=?", (id,)).fetchone()
    conn.close()
    if not row:
        flash("Data tidak ditemukan.", "warning")
        return redirect(url_for("index"))
    nama, lokasi, latitude, longitude, jaringan, waktu = row
    koordinat = f"{latitude}, {longitude}"
    return render_template("edit.html", nama=nama, lokasi=lokasi, jaringan=jaringan, waktu=waktu, koordinat=koordinat, id=id)

@app.route("/hapus/<int:id>")
def hapus_data(id):
    if not check_login():
        return redirect(url_for("login"))
    delete_data(id)
    flash("Data dihapus.", "info")
    return redirect(url_for("index"))

# ----------------- STATIC CHECK & SHUTDOWN -----------------
@app.route("/cek-static")
def cek_static():
    try:
        path = os.path.join(os.path.dirname(__file__), "static")
        files = os.listdir(path)
        return render_template_string ("<h3>Isi folder static:</h3><ul>" + "".join(f"<li>{f}</li>" for f in files) + "</ul>")
    except Exception as e:
        return f"<h3>Error saat membaca folder static:</h3><pre>{e}</pre>"

@app.route("/shutdown", methods=["GET", "POST"])
def shutdown():
    if request.method == "GET" and not check_login():
        return redirect(url_for("login"))
    def shutdown_server():
        os._exit(0)
    threading.Timer(1.0, shutdown_server).start()
    return """
    <h3>Aplikasi telah ditutup.</h3>
    <script>setTimeout(()=>{ window.open('', '_self'); window.close(); },1000);</script>
    """

# ----------------- CEK KOLOM -----------------
@app.route("/cek-kolom")
def cek_kolom():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(kasus)")
    hasil = cursor.fetchall()
    conn.close()
    return "<h3>Kolom tabel:</h3><pre>" + "\n".join(str(row) for row in hasil) + "</pre>"

# ----------------- RUN -----------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)  
