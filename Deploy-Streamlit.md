# Deploy LaundryKost ke Streamlit Community Cloud

## 1. Perbarui kode di GitHub

Di repository laundrykost, pilih Add file → Upload files. Unggah app.py baru dan cloud_setup.py dari paket ini. requirements.txt dan folder .streamlit/config.toml harus ada di repository. Letakkan app.py dan cloud_setup.py langsung di root repository, bukan di dalam folder pembungkus ZIP. Klik Commit changes. File database dan Secrets tidak diunggah.

## 2. Buka Streamlit Community Cloud

Buka https://share.streamlit.io, login menggunakan GitHub dan selesaikan proses akun yang tampil. Klik Create app → Yup, I have an app. Pilih repository laundrykost, branch main, dan Main file path app.py. Pilih Python 3.12 pada Advanced settings.

## 3. Isi akun pemilik lewat Secrets

Di Advanced settings → Secrets, masukkan konfigurasi di bawah. Username dan password harus dipilih sendiri. Isi password yang kosong dengan 8–128 karakter. Nomor adalah nomor pemilik dalam format 08…; contoh di bawah boleh diganti.

```toml
[pemilik]
username = "pemilik"
nama = "Pemilik LaundryKost"
nomor = "081234567890"
password = ""
```

Password kosong ditolak oleh aplikasi. Jika password berisi tanda kutip atau backslash, gunakan aturan string TOML yang sesuai. Simpan konfigurasi hanya di pengaturan Secrets Streamlit; jangan dimasukkan ke file publik GitHub atau chat. Konfigurasi ini membuat pemilik ketika database belum berisi pemilik. Perubahan Secrets tidak otomatis mengubah password akun pemilik yang sudah tersimpan.

## 4. Deploy dan bagikan link

Klik Save pada Advanced settings, kemudian Deploy. Tunggu proses instalasi selesai. Buka alamat streamlit.app yang dihasilkan. Login pemilik memakai username/password dari Secrets. Pelanggan memilih Daftar pelanggan, membuat akun sendiri, lalu login. Teman cukup membuka link web; tidak perlu GitHub, Python, atau Wi-Fi yang sama. Laptop pemilik boleh dimatikan karena aplikasi berjalan di hosting.

## 5. Batas penyimpanan versi ini

Versi ini dapat dibuka online dengan login, tetapi masih memakai SQLite di disk server Streamlit. Community Cloud tidak menjamin penyimpanan file lokal bertahan. Jika server membuat ulang disk atau melakukan redeploy, akun pelanggan dan pesanan dapat hilang; pemilik dibuat lagi dari Secrets. Data yang ada di database laptop tidak otomatis pindah ke hosting. Gunakan data contoh untuk pengujian UTS. Akun/pesanan yang perlu disimpan permanen membutuhkan database eksternal persisten.

## Troubleshooting

- ModuleNotFoundError: cloud_setup: unggah cloud_setup.py ke folder yang sama dengan app.py.
- Akun pemilik belum tersedia: isi Secrets [pemilik] di aplikasi Cloud, lalu muat ulang.
- Secrets pemilik belum valid: username 3–30 huruf/angka/underscore, nama maksimal 80 karakter, nomor 10–15 digit, password 8–128 karakter; perbaiki di Settings → Secrets.
- File app.py tidak ditemukan: Main file path harus mengikuti lokasi aktual pada repository.
- Tema belum sesuai: pastikan .streamlit/config.toml berada di root repository. Pilih tema kustom aplikasi jika browser menyimpan tema lain.

## Referensi resmi

- Deploy: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- Batas SQLite lokal: https://docs.streamlit.io/develop/concepts/connections/connecting-to-data
