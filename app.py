# Import library utama Streamlit
import streamlit as st
# Import pandas untuk data tabel
import pandas as pd
# Import client Gemini
from google import genai
# Import 'types' untuk konfigurasi (system prompt, temperature)
from google.genai import types

# Judul & caption halaman
st.title("Chatbot Analitik PLN")
st.caption("Conversational Analytics - Streamlit Community Cloud")

# Data contoh (anggap hasil query database)
DATA = pd.DataFrame({
    "wilayah":      ["Jakarta", "Bandung", "Surabaya", "Medan", "Makassar"],  # wilayah
    "pelanggan":    [1200, 870, 1010, 640, 520],                              # jumlah pelanggan
    "konsumsi_mwh": [340, 250, 300, 180, 150],                               # konsumsi (MWh)
    "gangguan":     [12, 9, 14, 7, 5],                                       # jumlah gangguan
})

# System prompt: persona + ATURAN + data (ramah saat disapa, akurat saat ditanya data)
SYSTEM_PROMPT = f"""Anda adalah "Asisten Analitik PLN" yang ramah dan membantu.

ATURAN MENJAWAB:
1. Jika pengguna menyapa atau basa-basi (mis. "halo", "hai", "terima kasih", "siapa kamu"),
   balas ramah dan singkat. Boleh tawarkan 1-2 contoh pertanyaan tentang data.
2. Jika pengguna bertanya tentang data, jawab ringkas berdasarkan TABEL DATA di bawah,
   sebutkan satuan (MWh untuk konsumsi), lalu tutup dengan satu insight singkat.
3. Jika pertanyaan di luar cakupan data, katakan dengan sopan bahwa datanya tidak tersedia.
4. Jangan memaksakan analisis data pada sapaan/percakapan biasa.
5. Selalu jawab dalam Bahasa Indonesia.

TABEL DATA (konsumsi dalam MWh):
{DATA.to_string(index=False)}
"""

# Ambil API key dari Secrets Streamlit Community Cloud (Manage app -> Settings -> Secrets)
try:
    api_key = st.secrets["GOOGLE_API_KEY"]              # baca dari panel Secrets
except Exception:
    api_key = ""                                        # kosong bila belum diset

# --- Sidebar: panel pengaturan (tanpa input API key) ---
with st.sidebar:
    st.subheader("Pengaturan")                          # judul kecil
    model = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-flash-lite"])  # pilih model
    temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.1)  # kreativitas jawaban
    st.caption("Tekan Reset untuk menghapus riwayat percakapan.")  # catatan kecil
    if st.button("Reset"):                              # tombol reset percakapan
        st.session_state.messages = []                  # kosongkan riwayat
        st.rerun()

# Hentikan bila API key belum diset di Secrets
if not api_key:
    st.error("GOOGLE_API_KEY belum diset di panel Secrets (Manage app -> Settings -> Secrets).")
    st.stop()

# Buat client Gemini SEKALI dan simpan di cache (mencegah error "client has been closed"
# yang muncul bila client dibuat ulang setiap kali Streamlit menjalankan ulang skrip).
@st.cache_resource
def get_client(key):
    return genai.Client(api_key=key)                    # objek koneksi ke Gemini

client = get_client(api_key)                            # ambil client dari cache

# Riwayat percakapan (disimpan agar bertahan antar-rerun)
if "messages" not in st.session_state:
    st.session_state.messages = []

# Fungsi bantu: tampilkan tabel/grafik sesuai jenis
def tampilkan_visual(jenis):
    if jenis == "table":
        st.dataframe(DATA, use_container_width=True)
    elif jenis == "chart":
        st.bar_chart(DATA.set_index("wilayah")["konsumsi_mwh"])
    elif jenis == "gangguan":
        st.bar_chart(DATA.set_index("wilayah")["gangguan"])

# Gambar ulang riwayat percakapan
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["content"])
        tampilkan_visual(m.get("show"))

# Kotak input chat
prompt = st.chat_input("Tanya tentang data...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})  # simpan pesan user
    with st.chat_message("user"):
        st.write(prompt)

    # Susun SELURUH riwayat menjadi 'contents' agar model punya MEMORI percakapan
    contents = []
    for h in st.session_state.messages:                 # untuk tiap pesan tersimpan
        peran = "user" if h["role"] == "user" else "model"   # peta peran ke format Gemini
        contents.append(types.Content(role=peran, parts=[types.Part(text=h["content"])]))

    # Panggil Gemini (client tetap hidup karena disimpan di cache)
    with st.spinner("Menganalisis..."):
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=temperature,
            ),
        )
        jawaban = resp.text

    p = prompt.lower()                                  # cek kata kunci untuk visual
    if "gangguan" in p:
        show = "gangguan"
    elif any(k in p for k in ["grafik", "chart"]):
        show = "chart"
    elif any(k in p for k in ["tabel", "data"]):
        show = "table"
    else:
        show = None

    with st.chat_message("assistant"):
        st.write(jawaban)
        tampilkan_visual(show)

    st.session_state.messages.append({"role": "assistant", "content": jawaban, "show": show})
