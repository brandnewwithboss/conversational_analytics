# Import library utama Streamlit
import streamlit as st
import os, re, glob, zipfile, hashlib
import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import create_engine, text
from groq import Groq
import matplotlib
import matplotlib.pyplot as plt
import logging, time
from datetime import datetime, timezone
from pathlib import Path
import json

# Judul & caption halaman
st.set_page_config(page_title='Conversational Analytics — HC', page_icon='📊', layout='centered')
st.title("Chatbot Human Capital PLN")
st.caption("Conversational Analytics - Streamlit Community Cloud")

# Sidebar
with st.sidebar:
  st.subheader("⚙️ Pengaturan")                          # judul kecil
  paksa = st.selectbox('Paksa format', ['auto', 'tabel', 'narasi', 'json', 'chart'])
  st.markdown('**Contoh:**')
  for ex in ["Berapa jumlah pegawai per divisi?",
             "Siapa yang belum mengikuti diklat Data Engineering?",
             "Berapa rata-rata nilai diklat per unit (divisi)?",]:
             st.caption('• ' + ex)

  if st.button('🗑️ Bersihkan chat'):
    st.session_state.messages = []
    st.session_state.cache = {}
    st.rerun()

if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'cache' not in st.session_state:
    st.session_state.cache = {}

# Riwayat percakapan (disimpan agar bertahan antar-rerun)
if "messages" not in st.session_state:
    st.session_state.messages = []

DATA = Path("data")
MODEL_NAME = "llama-3.3-70b-versatile"
# MODEL_NAME = "llama-3.1-8b-instant"

# Ambil API key dari Secrets Streamlit Community Cloud (Manage app -> Settings -> Secrets)
api_key = st.secrets.get("GROQ_API_KEY", None)              # baca dari panel Secrets

if not api_key:
    st.error("GROQ_API_KEY belum diset di panel Secrets.")
    st.stop()

groq_client = Groq(
    api_key = api_key,
)

@st.cache_resource
def init_database():
    # database SQLite disimpan sementara di folder project
    engine = create_engine("sqlite:///hc_database.db")

    # Import semua CSV menjadi tabel SQLite
    for csv_file in DATA.glob("*.csv"):
        df = pd.read_csv(csv_file)

        # nama tabel = nama file
        # employees.csv -> employees
        df.to_sql(
            csv_file.stem,
            engine,
            if_exists="replace",
            index=False
        )

    return engine

engine = init_database()

def tanya_llm(prompt, temperature=0, **kwargs):
  resp = groq_client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        model=MODEL_NAME,
        temperature=temperature,
    ).choices[0].message.content

  return resp

def get_few_shots():
  return"""
    Pertanyaan: Siapa yang mengikuti diklat Data Engineering?
    SQL:
    SELECT e.nama
    FROM employees e
    JOIN enrollments en ON e.nip=en.nip
    JOIN trainings t ON en.training_id=t.training_id
    WHERE t.nama_diklat ILIKE '%Data Engineering%';

    Pertanyaan: Siapa yang belum mengikuti diklat Data Engineering?
    SQL:
    SELECT e.nama
    FROM employees e
    WHERE NOT EXISTS (
        SELECT 1
        FROM enrollments en
        JOIN trainings t ON en.training_id=t.training_id
        WHERE en.nip=e.nip
          AND t.nama_diklat ILIKE '%Data Engineering%'
    );
    """
DIALEK = 'PostgreSQL'

SCHEMA_STR = """employees(nip, nama, divisi, jabatan, join_date)
trainings(training_id, nama_diklat, tanggal)
enrollments(nip, training_id, status, nilai)

Relasi:
- enrollments.nip      -> employees.nip
- enrollments.training_id -> trainings.training_id
Catatan: enrollments.nilai bisa kosong (NULL) jika status = 'berjalan'."""

def build_prompt(question: str) -> str:
    """
    Susun prompt yang berisi:
    - skema database (SCHEMA_STR) agar LLM tahu nama tabel & kolom
    - instruksi tegas: HANYA balas SATU query PostgreSQL SELECT, tanpa penjelasan
    - pertanyaan pengguna
    Boleh tambahkan 1-2 contoh (few-shot) bila perlu.
    """
    # TODO 2: lengkapi prompt di bawah
    prompt = f"""
    Anda adalah ahli SQL untuk {DIALEK}.
    Tugas Anda adalah mengubah pertanyaan pengguna menjadi SATU query SQL SELECT yang valid.

    Aturan:
    1. Gunakan HANYA tabel dan kolom yang terdapat pada skema database.
    2. Jangan menggunakan tabel atau kolom yang tidak terdapat pada skema.
    3. Buat tepat SATU query SELECT.
    4. Gunakan JOIN apabila diperlukan.
    5. Balas HANYA query SQL tanpa penjelasan, markdown, maupun pembungkus kode.
    6. Jika pertanyaan pengguna tidak dapat dijawab menggunakan skema yang tersedia, balas PERSIS dengan:
    Mohon maaf, pertanyaan Anda di luar fungsi aplikasi ini.

    Pedoman:
    - Jika pengguna menyebut nama suatu entitas (misalnya nama diklat, divisi, jabatan, pegawai, produk, kategori, dan sebagainya) secara tidak lengkap, gunakan pencarian parsial menggunakan LIKE atau ILIKE sesuai dialek SQL, kecuali pengguna secara eksplisit meminta nama yang sama persis.
    - Jika pengguna menanyakan data yang BELUM memiliki relasi (misalnya belum mengikuti pelatihan, belum membeli produk, belum memiliki sertifikat, dan sebagainya), gunakan NOT EXISTS atau LEFT JOIN ... IS NULL dengan benar.
    - Jangan menghasilkan pola query yang bertentangan, misalnya:
        LEFT JOIN ...
        WHERE tabel_join.kolom = ...
          AND tabel_join.id IS NULL
    - Gunakan agregasi hanya bila diperlukan.
    - Gunakan ORDER BY dan LIMIT hanya bila diminta atau memang diperlukan.

    Contoh:
    {get_few_shots()}

    Skema Database:
    {SCHEMA_STR}

    Pertanyaan: {question}

    SQL:"""

    return prompt

def run_sql(sql: str) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)

def generate_sql(question: str) -> str:
    prompt = build_prompt(question)
    # TODO 3:
    #  1) panggil model -> resp = model.generate_content(prompt)
    #  2) ambil teksnya -> resp.text
    text = tanya_llm(prompt)

    #  3) bersihkan: buang ```sql ... ``` bila ada, .strip()
    text_clean = re.sub(r"^\s*```(?:sql)?\s*|\s*```\s*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text_clean = re.sub(r"^\s*SQL\s*:\s*", "", text_clean, flags=re.IGNORECASE).strip()
    text_clean = text_clean.strip().rstrip(";").strip()

    #  4) return string SQL
    sql = text_clean   # TODO 3: ganti dengan hasil parsing
    return sql

FORBIDDEN = ["drop", "delete", "update", "insert", "alter", "truncate", "create", "grant"]
TABEL_OK = {'employees','enrollments','trainings'}
FORBIDDEN = ('drop','delete','update','insert','alter','truncate','create','replace',
             'grant','revoke','merge','into','attach','detach','pragma','vacuum','copy','dblink')
POLA_BAHAYA = (r'\binformation_schema\b', r'\bpg_catalog\b', r'\bpg_\w+\b',
               r'\bsqlite_master\b', r'\bload_extension\b', r'\blo_import\b', r'\blo_export\b')

_FUNGSI_FROM = r'\b(?:extract|substring|trim|position|overlay)\s*\([^)]*\)'

def validate_sql(sql: str, batas=200, batas_maks=1000) -> bool:
    """
    Kembalikan True hanya jika query AMAN untuk dijalankan:
    - tidak kosong
    - diawali SELECT (boleh setelah di-strip & lowercase)
    - tidak mengandung kata di FORBIDDEN
    - bukan multi-statement (tidak ada ';' di tengah)
    """
    t = sql.strip(); low = t.lower()
    if low == "": raise ValueError('Query tidak boleh kosong.')
    if not (low.startswith('select')): raise ValueError('Hanya SELECT yang diizinkan')
    if ';' in low: raise ValueError('Multi-statement')
    for k in FORBIDDEN:
        if re.search(rf'\b{k}\b', low): raise ValueError(f'Terlarang: {k}')
    for pola in POLA_BAHAYA:
        m = re.search(pola, low)
        if m: raise ValueError(f'Objek terlarang: {m.group()}')
    low_tab = re.sub(_FUNGSI_FROM, ' ', low)            # buang body EXTRACT(... FROM kolom) dll.
    asing = set(re.findall(r'(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)', low_tab)) - TABEL_OK
    if asing: raise ValueError(f'Tabel tak dikenal: {asing}')
    m = re.search(r'\blimit\s+(\d+)', low)              # paksa / clamp LIMIT
    if m:
        if int(m.group(1)) > batas_maks: t = re.sub(r'\blimit\s+\d+', f'LIMIT {batas_maks}', t, flags=re.I)
    else:
        t += f' LIMIT {batas}'

    # TODO 4: implementasikan pemeriksaan di atas
    return t

# Routing output

def output_routing(question, df=None):
    p = question.lower()
    if any(k in p for k in [
        "grafik", "chart", "visual", "plot", "diagram", "pie", "pie chart", "proporsi",
        "bar", "bar chart", "komposisi", "line", "line chart", "periode", "tren", "trend"
        ]):
      return "chart"

    if any(k in p for k in [
        "kenapa", "mengapa", "insight", "analisis", "jelaskan", "ceritakan",
        "interpretasi", "kesimpulan", "ringkas", "ringkasan"
        ]):
        return "narasi"

    if any(k in p for k in [
        "json", "api", "dashboard"
        ]):
      return "json"

    if any(k in p for k in [
            "tabel", "table", "daftar", "list", "urutkan", "ranking", "top", "bottom",
            "detail", "rinci", "seluruh", "semua data", "data lengkap", "tampilkan data"
        ]):
      return "tabel"

    return "auto"

# Function untuk Format Chart

def pilih_jenis_chart(pertanyaan, df):
    p, x = pertanyaan.lower(), str(df.columns[0]).lower()
    if 'pie' in p or 'komposisi' in p or 'proporsi' in p: return 'pie'
    if 'periode' in x or 'bulan' in p or 'tren' in p: return 'line'
    return 'bar'

TEAL = '#0E8388'
def buat_chart(df, pertanyaan='', jenis=None, tampil=True):
    x, y = df.columns[0], df.columns[-1]
    jenis = jenis or pilih_jenis_chart(pertanyaan, df)
    fig, ax = plt.subplots(figsize=(7, 4))
    if jenis == 'line':
        ax.plot(df[x].astype(str), df[y], marker='o', color=TEAL)
        ax.set_ylabel(str(y)); plt.xticks(rotation=30, ha='right')
    elif jenis == 'pie':
        ax.pie(df[y], labels=df[x].astype(str), autopct='%1.0f%%',
               colors=plt.cm.Greens([0.4,0.55,0.7,0.85,0.6,0.45]))
    else:
        ax.bar(df[x].astype(str), df[y], color=TEAL)
        ax.set_ylabel(str(y)); plt.xticks(rotation=30, ha='right')
    ax.set_title(pertanyaan or f'{y} per {x}')
    plt.tight_layout()
    if tampil: plt.show()
    return fig

# Function untuk Format Narasi

def _ringkas_df(df):
    if df is None or len(df) == 0: return 'tidak ada data'
    cols = list(df.columns)
    if len(cols) >= 2 and pd.api.types.is_numeric_dtype(df[cols[-1]]):
        top = df.iloc[0]
        return f"'{top[cols[0]]}' tertinggi pada {cols[-1]} = {top[cols[-1]]:,.0f}; {len(df)} baris"
    return f'{len(df)} baris; kolom: ' + ', '.join(cols)

def buat_narasi(df, pertanyaan):
    fakta = _ringkas_df(df)
    prompt = (f'Anda analis data. Pertanyaan: {pertanyaan}\n'
              f'Data:\n{df.head(10).to_string(index=False)}\n'
              f'RINGKAS_DATA: {fakta}\n'
              'Tulis narasi 2-3 kalimat berbasis data di atas saja.')
    return tanya_llm(prompt)

# Function untuk Format JSON

def format_json(df, pertanyaan):
    return {
        'format': 'json',
        'pertanyaan': pertanyaan,
        'kolom': list(df.columns),
        'jumlah_baris': int(len(df)),
        'data': df.head(50).to_dict(orient='records'),
        'ringkasan': _ringkas_df(df),
    }

LOG_RECORDS = []; LOG_FILE = 'ask_db_log.jsonl'
logger = logging.getLogger('text2sql'); logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler(); _h.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')); logger.addHandler(_h)

def _catat_log(rec):
    LOG_RECORDS.append(rec)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception: pass

def ask(question: str, maks_retry=2, verbose=True):
    t0 = time.perf_counter()
    # TODO 6: implementasikan alur di atas dengan fallback/retry sederhana
    st.write("="*60)
    st.write(f"Pertanyaan: {question}")

    res = None
    for attempt in range(1, maks_retry + 2):
        sql = generate_sql(question)
        st.write("SQL dari LLM: ")
        st.code(sql)
        try:
            sql_aman = validate_sql(sql)
            st.write("\nSQL setelah validasi:")
            st.code(sql_aman)
        except ValueError as e:
            last = f'validasi: {e}'
            # if verbose: print(f'[attempt {attempt}] {sql}  ->  ✗ {last}')
            st.write(f"\nVALIDATE ERROR: {last}")
            prompt = build_prompt(question) + f'\nSQL gagal: {sql}\nERROR: {last}\nPerbaiki.'; continue
        try:
            df = run_sql(sql_aman)
            st.write(f"\nRUN_SQL BERHASIL ({len(df)} baris)")
            st.code(df.head())
            # if verbose: print(f'[attempt {attempt}] {sql_aman}  ->  ✓ OK ({len(df)} baris)')
            res = {'ok': True, 'sql': sql_aman, 'data': df, 'attempts': attempt}; break
        except Exception as e:
            last = str(e)
            # if verbose: print(f'[attempt {attempt}] {sql_aman}  ->  ✗ {last}')
            st.write("\nRUN_SQL ERROR:")
            st.error(type(e).__name__)
            st.exception(e)
            prompt = build_prompt(question) + f'\nSQL gagal: {sql_aman}\nERROR: {last}\nPerbaiki.'
    
    if res is None:
        st.write("\nASK GAGAL")
        st.write("LAST ERROR:", last)
        res = {'ok': False, 'error': last, 'fallback': 'Maaf, query valid tidak dapat disusun.'}
        # if verbose: print(f'[fallback] gagal setelah {maks_retry + 1} percobaan :: {last}')
    
    data = res.get('data')
    rec = {'waktu': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'pertanyaan': question, 'ok': res.get('ok', False), 'sql': res.get('sql'),
           'attempts': res.get('attempts'), 'error': res.get('error'),
           'n_baris': (len(data) if data is not None else 0),
           'latency_ms': round((time.perf_counter()-t0)*1000, 1)}
    _catat_log(rec)
    # logger.info(f"ok={rec['ok']} attempts={rec['attempts']} {rec['latency_ms']}ms :: {question}")
    st.write("\nHASIL:")
    st.code(res)

    return res

def jawab(pertanyaan, force=None):
    res = ask(pertanyaan)
    if not res['ok']:
        return {'format': 'error', 'isi': res.get('fallback')}
    df = res['data']
    fmt = force or output_routing(pertanyaan, df)

    out = {
    "format": fmt,
    "sql": res["sql"],
    "df": df,
    "pertanyaan": pertanyaan
    }

    if fmt == "chart":
        buat_chart(df, pertanyaan)
        out['isi'] = None
    elif fmt == "narasi":
        out["isi"] = buat_narasi(df, pertanyaan)
    elif fmt == "json":
        out["isi"] = format_json(df, pertanyaan)
    else:
        out["isi"] = df
    return out



for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        if m["role"] == "user":
            st.markdown(m["content"])
        else:
            payload = m["payload"]
            fmt = payload.get("format")         

            if fmt == "tabel":
                st.dataframe(payload.get("df"), use_container_width=True)

            elif fmt in ("narasi"):
                st.write(payload.get("isi"))

            elif fmt == "json":
                st.json(payload.get("isi"))

            elif fmt == "chart":
                st.pyplot(
                    buat_chart(
                        payload.get("df"),
                        payload.get("pertanyaan", "")
                    )
                )

            elif fmt == "error":
                st.error(payload.get("isi"))

            else:
                st.write(payload.get("isi"))

q = st.chat_input("Pertanyaan...")

if q:
    st.session_state.messages.append({
        "role": "user",
        "content": q
    })

    key = hashlib.sha256((q.lower().strip() + "|" + paksa).encode()).hexdigest()

    with st.spinner("Memproses..."):
        if key in st.session_state.cache:
            out = st.session_state.cache[key]
        else:
            out = jawab(q, force=None if paksa == "auto" else paksa)
            st.session_state.cache[key] = out

    if not isinstance(out, dict):
        out = {
            "format": "narasi",
            "isi": str(out)
        }

    st.session_state.messages.append({
        "role": "assistant",
        "payload": out
    })

    st.rerun()
