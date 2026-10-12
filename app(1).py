# 1. Import library dan konfigurasi halaman.
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
from uuid import uuid4
import getpass
import hashlib
import hmac
import re
import secrets
import sys
import time
import streamlit as st
from cloud_setup import siapkan_pemilik_cloud
HARGA = {"Cuci kering": 5000, "Cuci setrika": 7000, "Express": 10000}
STATUS = ["Baru", "Dijemput", "Diproses", "Siap diantar", "Selesai"]
DB = Path(__file__).with_name("laundrykost.db")
ITERASI_HASH = 600_000
BATAS_SESI = 30 * 60  # Logout setelah 30 menit tanpa aktivitas.

# 2. Fungsi pembantu untuk format harga, nomor telepon, dan database.
def rupiah(angka):
    return "Rp" + f"{angka:,.0f}".replace(",", ".")


def bersihkan_nomor(nomor):
    nomor = nomor.replace(" ", "").replace("-", "")
    if nomor.startswith("+62"):
        nomor = "0" + nomor[3:]
    elif nomor.startswith("62"):
        nomor = "0" + nomor[2:]
    return nomor


def query(sql, parameter=(), baca=False):
    with closing(sqlite3.connect(DB)) as koneksi:
        koneksi.execute("PRAGMA foreign_keys = ON")
        koneksi.row_factory = sqlite3.Row
        hasil = koneksi.execute(sql, parameter)
        if baca:
            return [dict(baris) for baris in hasil.fetchall()]
        koneksi.commit()


# 3. Akun dan migrasi: pesanan versi lama tetap ada di database.
def siapkan_database():
    with closing(sqlite3.connect(DB)) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS akun (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            nama TEXT NOT NULL, nomor TEXT NOT NULL,
            salt TEXT NOT NULL, password_hash TEXT NOT NULL,
            peran TEXT NOT NULL CHECK(peran IN ('pelanggan', 'pemilik'))
        )""")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS satu_pemilik
                    ON akun(peran) WHERE peran = 'pemilik'""")
        db.execute("""CREATE TABLE IF NOT EXISTS percobaan_login (
            username TEXT PRIMARY KEY, gagal INTEGER NOT NULL,
            terakhir REAL NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS pesanan (
            id TEXT PRIMARY KEY, nama TEXT NOT NULL, nomor TEXT NOT NULL,
            alamat TEXT NOT NULL, layanan TEXT NOT NULL, berat REAL NOT NULL,
            tanggal TEXT NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL,
            pelanggan_id TEXT REFERENCES akun(id)
        )""")
        kolom = [baris[1] for baris in db.execute("PRAGMA table_info(pesanan)")]
        if "pelanggan_id" not in kolom:
            db.execute("ALTER TABLE pesanan ADD COLUMN pelanggan_id TEXT REFERENCES akun(id)")
        db.commit()


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               bytes.fromhex(salt), ITERASI_HASH).hex()


def buat_akun(username, nama, nomor, password, konfirmasi, peran="pelanggan"):
    username = username.strip().lower()
    nomor = bersihkan_nomor(nomor.strip())
    if not re.fullmatch(r"[a-z0-9_]{3,30}", username):
        raise ValueError("Username: 3–30 huruf kecil, angka, atau underscore; tanpa spasi.")
    if not nama.strip() or len(nama.strip()) > 80:
        raise ValueError("Nama wajib diisi, maksimal 80 karakter.")
    if not nomor.isascii() or not nomor.isdigit() or not 10 <= len(nomor) <= 15:
        raise ValueError("Nomor WhatsApp harus berisi 10–15 digit.")
    if not 8 <= len(password) <= 128:
        raise ValueError("Password harus berisi 8–128 karakter.")
    if password != konfirmasi:
        raise ValueError("Konfirmasi password belum sama.")
    if peran not in ("pelanggan", "pemilik"):
        raise ValueError("Peran tidak valid.")
    salt = secrets.token_hex(16)
    try:
        query("""INSERT INTO akun
              (id, username, nama, nomor, salt, password_hash, peran)
              VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (uuid4().hex, username, nama.strip(), nomor, salt,
               hash_password(password, salt), peran))
    except sqlite3.IntegrityError:
        raise ValueError("Username sudah digunakan atau akun pemilik sudah tersedia.") from None


def login(username, password):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,30}", username) or len(password) > 128:
        raise ValueError("Username atau password salah.")
    # Transaksi menyatukan pemeriksaan dan pencatatan batas percobaan login.
    with closing(sqlite3.connect(DB)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        sekarang = time.time()
        percobaan = db.execute("SELECT * FROM percobaan_login WHERE username = ?",
                              (username,)).fetchone()
        gagal = 0
        if percobaan and sekarang - percobaan["terakhir"] < 300:
            gagal = percobaan["gagal"]
        if gagal >= 5:
            raise ValueError("Terlalu banyak percobaan. Tunggu 5 menit lalu coba lagi.")
        akun = db.execute("SELECT * FROM akun WHERE username = ?", (username,)).fetchone()
        # Akun tidak ditemukan juga melewati proses hash sebelum ditolak.
        salt = akun["salt"] if akun else "00" * 16
        pembanding = akun["password_hash"] if akun else "00" * 32
        cocok = hmac.compare_digest(hash_password(password, salt), pembanding)
        if not akun or not cocok:
            db.execute("""INSERT INTO percobaan_login VALUES (?, ?, ?)
                          ON CONFLICT(username) DO UPDATE SET
                          gagal = excluded.gagal, terakhir = excluded.terakhir""",
                       (username, gagal + 1, sekarang))
            db.commit()
            raise ValueError("Username atau password salah.")
        db.execute("DELETE FROM percobaan_login WHERE username = ?", (username,))
        db.commit()
        return akun["id"]


def akun_aktif():
    identitas = st.session_state.get("akun_id")
    if not identitas:
        return None
    if time.time() - st.session_state.get("aktivitas", 0) > BATAS_SESI:
        st.session_state.clear()
        return None
    data = query("SELECT id, username, nama, nomor, peran FROM akun WHERE id = ?",
                 (identitas,), baca=True)
    if not data:
        st.session_state.clear()
        return None
    st.session_state["aktivitas"] = time.time()
    return data[0]


def wajib_peran(peran):
    akun = akun_aktif()
    if not akun or akun["peran"] != peran:
        st.error("Akses ditolak. Silakan login dengan akun yang sesuai.")
        st.stop()
    return akun


siapkan_database()

# Pemilik dibuat lewat terminal komputer server, bukan formulir daftar publik.
if __name__ == "__main__" and "--buat-pemilik" in sys.argv:
    if query("SELECT id FROM akun WHERE peran = 'pemilik'", baca=True):
        print("Akun pemilik sudah ada. Login menggunakan akun tersebut.")
        sys.exit(0)
    print("Buat akun pemilik LaundryKost. Password tidak tampil saat diketik.")
    try:
        buat_akun(input("Username: "), input("Nama pemilik: "), input("Nomor WhatsApp: "),
                  getpass.getpass("Password (minimal 8 karakter): "),
                  getpass.getpass("Ulangi password: "), peran="pemilik")
    except ValueError as masalah:
        print(masalah)
        sys.exit(1)
    print("Akun pemilik dibuat. Jalankan: python -m streamlit run app.py")
    sys.exit(0)

st.set_page_config(page_title="LaundryKost", page_icon="🧺", layout="wide")
siapkan_pemilik_cloud(query, buat_akun)
# 4. Komponen ringkasan dipakai di konfirmasi, pelacakan, dan dashboard.
def tampilkan_pesanan(pesanan):
    st.write("Kode pesanan:", pesanan["id"])
    st.write("Status:", pesanan["status"])
    st.write("Pelanggan:", pesanan["nama"])
    st.write("Layanan:", pesanan["layanan"])
    st.write("Berat:", f'{pesanan["berat"]:g} kg')
    st.write("Tanggal jemput:", date.fromisoformat(pesanan["tanggal"]).strftime("%d-%m-%Y"))
    st.write("Total estimasi:", rupiah(pesanan["total"]))


# 5. Halaman publik: login dan pendaftaran pelanggan.
st.markdown("""
<style>
/* Palet sage–ivory diatur lewat .streamlit/config.toml. */
button[kind="primary"] {background: #47624B; color: #FFFFF0; border: 0; border-radius: 999px; font-weight: 600;}
button[kind="primary"]:hover {background: #344D39; color: #FFFFF0;}
[data-testid="stMetric"], [data-testid="stForm"] {padding: 20px; border-radius: 16px; border: 1px solid #CAD4C0;}
</style>
""", unsafe_allow_html=True)
st.sidebar.title("🧺 LaundryKost")
st.sidebar.caption("CUCI · SETRIKA · ANTAR JEMPUT")
st.title("🧺 LaundryKost")
akun = akun_aktif()
if akun is None:
    st.caption("Laundry harian, lebih tenang. Masuk untuk memesan atau mengelola laundry.")
    if not query("SELECT id FROM akun WHERE peran = 'pemilik'", baca=True):
        st.info("Akun pemilik belum tersedia. Siapkan lewat terminal lokal atau Secrets Streamlit Cloud.")
        st.code("python app.py --buat-pemilik", language="bash")
        st.caption("Untuk hosting, isi bagian [pemilik] pada Settings → Secrets. Lihat panduan proyek.")
        st.stop()
    tab_login, tab_daftar = st.tabs(["Login", "Daftar pelanggan"])
    with tab_login:
        with st.form("form_login", clear_on_submit=True):
            username = st.text_input("Username", max_chars=30, key="login_username")
            password = st.text_input("Password", type="password", max_chars=128, key="login_password")
            masuk = st.form_submit_button("Masuk", type="primary")
        if masuk:
            try:
                identitas = login(username, password)
            except ValueError as masalah:
                st.error(str(masalah))
            else:
                st.session_state.clear()
                st.session_state["akun_id"] = identitas
                st.session_state["aktivitas"] = time.time()
                st.rerun()
    with tab_daftar:
        st.caption("Pendaftaran di sini selalu membuat akun pelanggan.")
        with st.form("form_daftar", clear_on_submit=True):
            nama_daftar = st.text_input("Nama lengkap", max_chars=80, key="daftar_nama")
            nomor_daftar = st.text_input("Nomor WhatsApp", max_chars=25, key="daftar_nomor")
            username_daftar = st.text_input("Username baru", max_chars=30, key="daftar_username")
            password_daftar = st.text_input("Password baru", type="password", max_chars=128, key="daftar_password")
            konfirmasi = st.text_input("Ulangi password", type="password", max_chars=128, key="daftar_konfirmasi")
            daftar = st.form_submit_button("Buat akun pelanggan", type="primary")
        if daftar:
            try:
                buat_akun(username_daftar, nama_daftar, nomor_daftar, password_daftar, konfirmasi)
            except ValueError as masalah:
                st.error(str(masalah))
            else:
                st.success("Akun berhasil dibuat. Buka tab Login untuk masuk.")
    st.stop()

# Identitas dan peran dibaca dari database; pengguna tidak memilih peran.
st.sidebar.write("Login sebagai:", akun["nama"])
st.sidebar.caption("Pemilik laundry" if akun["peran"] == "pemilik" else "Pelanggan")
if st.sidebar.button("Logout", key="logout"):
    st.session_state.clear()
    st.rerun()

# 6. Tampilan pemesan: formulir pesanan dan perhitungan otomatis.
if akun["peran"] == "pelanggan":
    akun = wajib_peran("pelanggan")
    st.caption("Baju bersih, tanpa ribet. Pesan laundry dari kos kamu.")
    tab_pesan, tab_lacak = st.tabs(["Buat pesanan", "Pesanan saya"])
    with tab_pesan:
        kiri, kanan = st.columns([2, 1], gap="large")
        with kiri:
            with st.container(border=True):
                st.subheader("01 · Pilih layanan")
                layanan = st.radio("Layanan laundry", list(HARGA), index=1,
                                   horizontal=True, key="layanan")
                st.caption(f"{rupiah(HARGA[layanan])}/kg")
            with st.container(border=True):
                st.subheader("02 · Detail pesanan")
                nama = st.text_input("Nama pelanggan", value=akun["nama"], max_chars=80, key="nama")
                nomor = st.text_input("Nomor WhatsApp", value=akun["nomor"], max_chars=25, key="nomor")
                alamat = st.text_area("Alamat penjemputan", key="alamat",
                                      placeholder="Nama kos, jalan, dan nomor kamar", max_chars=500)
                berat = st.number_input("Berat pakaian (kg)", min_value=0.5,
                                        max_value=100.0, value=3.0, step=0.5, key="berat")
                tanggal = st.date_input("Tanggal penjemputan", min_value=date.today(), key="tanggal")
        total = round(HARGA[layanan] * berat)
        with kanan:
            with st.container(border=True):
                st.subheader("Ringkasan pesanan")
                st.write("Layanan:", layanan)
                st.write("Berat:", f"{berat:g} kg")
                st.write("Penjemputan: Gratis")
                st.metric("Total estimasi", rupiah(total))
                st.caption("Berat akhir dikonfirmasi setelah penimbangan.")
                pesan = st.button("Buat pesanan", type="primary", width="stretch", key="pesan")

        # 7. Validasi lalu INSERT menyimpan pesanan baru ke database.
        if pesan:
            akun = wajib_peran("pelanggan")
            nomor_bersih = bersihkan_nomor(nomor)
            if not nama.strip() or not nomor.strip() or not alamat.strip():
                st.error("Isi nama, nomor WhatsApp, dan alamat terlebih dahulu.")
            elif not nomor_bersih.isascii() or not nomor_bersih.isdigit() or not 10 <= len(nomor_bersih) <= 15:
                st.error("Nomor WhatsApp harus berisi 10–15 digit, misalnya 081234567890.")
            else:
                kode = "LK-" + uuid4().hex[:10].upper()
                query("""INSERT INTO pesanan
                      (id, nama, nomor, alamat, layanan, berat, tanggal, total, status, pelanggan_id)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (kode, nama.strip(), nomor_bersih, alamat.strip(), layanan,
                       berat, tanggal.isoformat(), total, "Baru", akun["id"]))
                st.session_state["kode_terakhir"] = kode

        if st.session_state.get("kode_terakhir"):
            data = query("SELECT * FROM pesanan WHERE id = ? AND pelanggan_id = ?",
                         (st.session_state["kode_terakhir"], akun["id"]), baca=True)
            if data:
                st.success("Pesanan berhasil disimpan. Lihat progresnya di tab Pesanan saya.")
                with st.container(border=True):
                    st.subheader("Konfirmasi pesanan terakhir")
                    tampilkan_pesanan(data[0])

    # 8. Semua query pelanggan dibatasi oleh ID akun yang sedang login.
    with tab_lacak:
        st.subheader("Pesanan milik akun kamu")
        if st.button("Muat ulang status", key="muat_status"):
            st.rerun()
        milik_saya = query("SELECT * FROM pesanan WHERE pelanggan_id = ? ORDER BY rowid DESC",
                           (akun["id"],), baca=True)
        if not milik_saya:
            st.info("Belum ada pesanan. Buat pesanan pertamamu di tab sebelah.")
        for pesanan in milik_saya:
            with st.expander(f'{pesanan["id"]} · {pesanan["status"]}', expanded=True):
                tampilkan_pesanan(pesanan)
                st.text("Alamat: " + pesanan["alamat"])

# 9. Tampilan pemilik: ringkasan operasional dan daftar pesanan.
else:
    akun = wajib_peran("pemilik")
    st.caption("Kelola pesanan masuk dan perbarui progres laundry.")
    if st.button("Muat ulang pesanan", key="muat_ulang"):
        st.rerun()
    semua = query("SELECT * FROM pesanan ORDER BY rowid DESC", baca=True)
    lama = sum(p["pelanggan_id"] is None for p in semua)
    if lama:
        st.info(f"{lama} pesanan versi lama tetap tersimpan dan hanya terlihat oleh pemilik.")
    a, b, c = st.columns(3)
    a.metric("Total pesanan", len(semua))
    b.metric("Belum selesai", sum(p["status"] != "Selesai" for p in semua))
    c.metric("Nilai estimasi pesanan", rupiah(sum(p["total"] for p in semua)))
    st.caption("Nilai estimasi pesanan bukan pendapatan yang sudah dibayar.")
    filter_status = st.selectbox("Filter status", ["Semua"] + STATUS, key="filter_status")
    daftar = [p for p in semua if filter_status == "Semua" or p["status"] == filter_status]
    if not daftar:
        st.info("Belum ada pesanan pada status ini.")
    else:
        tabel = [{"Kode": p["id"], "Nama": p["nama"], "Layanan": p["layanan"],
                  "Berat (kg)": p["berat"], "Tanggal jemput": p["tanggal"],
                  "Total estimasi": rupiah(p["total"]), "Status": p["status"]} for p in daftar]
        st.dataframe(tabel, hide_index=True, width="stretch")

        # 10. Pemilik memilih pesanan dan UPDATE memperbarui statusnya.
        pilihan = {p["id"]: p for p in daftar}
        kode_pilih = st.selectbox("Pilih pesanan untuk dikelola", list(pilihan),
                                 format_func=lambda kode: f'{kode} · {pilihan[kode]["nama"]}',
                                 key="kode_pilih")
        terpilih = pilihan[kode_pilih]
        with st.container(border=True):
            st.subheader("Detail dan status pesanan")
            tampilkan_pesanan(terpilih)
            st.text("WhatsApp: " + terpilih["nomor"])
            st.text("Alamat: " + terpilih["alamat"])
            status_baru = st.selectbox("Ubah status", STATUS,
                                      index=STATUS.index(terpilih["status"]), key="status_" + kode_pilih)
            if st.button("Simpan status", type="primary", key="simpan_status"):
                wajib_peran("pemilik")
                query("UPDATE pesanan SET status = ? WHERE id = ?", (status_baru, kode_pilih))
                st.session_state["info_status"] = f"Status {kode_pilih} diperbarui menjadi {status_baru}."
                st.rerun()
    if st.session_state.get("info_status"):
        st.success(st.session_state.pop("info_status"))

st.divider()
st.caption("LaundryKost • Data tersimpan di komputer server • Belum terhubung ke pembayaran atau WhatsApp")
