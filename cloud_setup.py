"""Membuat akun pemilik awal dari Secrets Streamlit Community Cloud.

Password hanya dibaca di server; buat_akun menyimpan hash PBKDF2 ke SQLite.
Konfigurasi Secrets tidak menjadi bagian repository GitHub.
"""
import streamlit as st


def siapkan_pemilik_cloud(query, buat_akun):
    # Akun yang sudah ada tidak diganti setiap kali aplikasi menjalankan ulang.
    if query("SELECT id FROM akun WHERE peran = 'pemilik'", baca=True):
        return
    try:
        konfigurasi = st.secrets.get("pemilik")
    except FileNotFoundError:
        return  # Penggunaan lokal masih memakai python app.py --buat-pemilik.
    if konfigurasi is None:
        return
    try:
        password = konfigurasi["password"]
        buat_akun(konfigurasi["username"], konfigurasi["nama"],
                  konfigurasi["nomor"], password, password, peran="pemilik")
    except (KeyError, ValueError, TypeError):
        # Dua sesi dapat tiba bersamaan: UNIQUE pada peran tetap menjaga satu pemilik.
        if query("SELECT id FROM akun WHERE peran = 'pemilik'", baca=True):
            return
        st.error("Secrets pemilik belum valid. Isi username, nama, nomor WhatsApp, "
                 "dan password 8–128 karakter pada bagian [pemilik].")
        st.stop()
