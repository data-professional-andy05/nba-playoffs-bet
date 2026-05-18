import streamlit as st
import pandas as pd
import numpy as np
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="NBA Playoffs 2026 - La Porra", layout="wide")

st.markdown("""
    <style>
    [data-testid="stTable"] { display: block; overflow-x: auto; white-space: nowrap; }
    [data-testid="stTable"] th { text-align: center !important; font-size: 17px !important; background-color: #1e1e1e !important; color: white !important; padding: 12px !important; border-right: 2px solid #555 !important; border-bottom: 3px solid #000 !important; }
    [data-testid="stTable"] td { text-align: center !important; font-size: 20px !important; vertical-align: middle !important; color: black !important; border-bottom: 2px solid #666 !important; border-right: 1.5px solid #888 !important; padding: 10px !important; }
    [data-testid="stTable"] td:nth-child(1), [data-testid="stTable"] th:nth-child(1) { position: sticky; left: 0; z-index: 2; min-width: 180px !important; background-color: inherit; border-right: 3px solid #333 !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. LÓGICA DE NORMALIZACIÓN Y PROCESAMIENTO ---

def clean(text):
    """Elimina espacios y convierte a minúsculas para comparaciones infalibles"""
    if not text: return ""
    return "".join(filter(str.isalnum, str(text))).lower()

def parse_prediccion(pred_str):
    if not pred_str or pd.isna(pred_str): return None
    s = str(pred_str).strip()
    try:
        partes = s.split(" ")
        idx_marcador = -1
        for i, parte in enumerate(partes):
            if "-" in parte and parte.replace("-", "").isdigit():
                idx_marcador = i
                break
        if idx_marcador == -1: return None
        marcador = partes[idx_marcador].split("-")
        g1, g2 = int(marcador[0]), int(marcador[1])
        eq_a = " ".join(partes[:idx_marcador])
        eq_b = " ".join(partes[idx_marcador+1:])
        ganador = eq_a if g1 > g2 else eq_b
        return {"ganador": ganador, "total_juegos": g1 + g2}
    except:
        return None

def procesar_datos(resp_df, stat_df, playin_df, r1_scores=None):
    if resp_df.empty: return pd.DataFrame()
    
    # Normalizar nombres de columnas
    resp_df.columns = [c.strip() for c in resp_df.columns]
    stat_df.columns = [c.strip() for c in stat_df.columns]
    
    series_cols = [c for c in resp_df.columns if " vs " in c]
    # Crear diccionario de estado usando IDs normalizados
    status_dict = {clean(k): v for k, v in stat_df.set_index('Series_ID').to_dict('index').items()}
    
    nombre_col = next((c for c in resp_df.columns if 'nombre' in c.lower()), resp_df.columns[2])
    email_col = next((c for c in resp_df.columns if 'correo' in c.lower() or 'email' in c.lower()), resp_df.columns[1])

    resultados = []
    for _, user in resp_df.iterrows():
        puntos_reales = 0
        
        for col in series_cols:
            stat = status_dict.get(clean(col))
            pred = parse_prediccion(user[col])
            if not pred or not stat: continue
            
            t_a_name, t_b_name = [t.strip() for t in col.split(" vs ")]
            s_a = int(stat.get('Games_Team_A', 0))
            s_b = int(stat.get('Games_Team_B', 0))
            
            # Solo puntuamos si la serie ha terminado (alguien llegó a 4)
            if s_a == 4 or s_b == 4:
                final = 0
                winner_real = t_a_name if s_a == 4 else t_b_name
                if clean(pred['ganador']) == clean(winner_real):
                    final += 1
                    if int(pred['total_juegos']) == (s_a + s_b):
                        final += 2
                puntos_reales += final

        resultados.append({
            "Email": user[email_col], 
            "Participante": user[nombre_col], 
            "Puntos": int(puntos_reales)
        })

    lb = pd.DataFrame(resultados)
    if not lb.empty:
        # Preparamos keys minúsculas para un cruce a prueba de errores
        lb['Email_Key'] = lb['Email'].astype(str).str.lower().str.strip()
        
        # Merge de PlayIn
        pi_email = next((c for c in playin_df.columns if 'correo' in c.lower() or 'email' in c.lower()), playin_df.columns[0])
        pi_score = next((c for c in playin_df.columns if 'score' in c.lower() or 'puntos' in c.lower()), playin_df.columns[1])
        pi_clean = playin_df[[pi_email, pi_score]].rename(columns={pi_email: 'Email', pi_score: 'PlayIn'})
        pi_clean['Email_Key'] = pi_clean['Email'].astype(str).str.lower().str.strip()
        
        lb = lb.merge(pi_clean[['Email_Key', 'PlayIn']], on='Email_Key', how='left').fillna(0)
        lb['PlayIn'] = lb['PlayIn'].astype(int)

        # Merge R1 Scores para R2 y ordenamiento
        if r1_scores is not None and not r1_scores.empty:
            r1_scores['Email_Key'] = r1_scores['Email'].astype(str).str.lower().str.strip()
            lb = lb.merge(r1_scores[['Email_Key', 'Pts_R1']], on='Email_Key', how='left').fillna(0)
            lb['Pts_R1'] = lb['Pts_R1'].astype(int)
            # Desempate en R2: 1) Puntos R2, 2) Puntos R1, 3) Puntos PlayIn
            lb = lb.sort_values(by=["Puntos", "Pts_R1", "PlayIn"], ascending=False).reset_index(drop=True)
        else:
            # Desempate estándar R1: 1) Puntos R1, 2) Puntos PlayIn
            lb = lb.sort_values(by=["Puntos", "PlayIn"], ascending=False).reset_index(drop=True)
            
        lb = lb.drop(columns=['Email_Key'])
        lb.insert(0, 'Posición', range(1, len(lb) + 1))
        
    return lb

# --- 3. CARGA Y UI ---

@st.cache_data(ttl=60)
def cargar_todo():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    sh = client.open("NBA_Playoffs_2026")
    
    # Cargar DataFrames
    r1 = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
    r2 = pd.DataFrame(sh.worksheet("Responses_R2").get_all_records())
    
    s1 = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
    s2 = pd.DataFrame(sh.worksheet("Series_Status_2").get_all_records())
    
    p = pd.DataFrame(sh.worksheet("PlayIn_Score").get_all_records())
    
    # Procesar R1
    lb_r1 = procesar_datos(r1, s1, p)
    
    # Extraer puntajes de R1 para usarlos como criterio de desempate en R2
    r1_scores = None
    if not lb_r1.empty:
        r1_scores = lb_r1[['Email', 'Puntos']].rename(columns={'Puntos': 'Pts_R1'})
        
    # Procesar R2 usando los puntajes de R1
    lb_r2 = procesar_datos(r2, s2, p, r1_scores=r1_scores)
    
    return lb_r1, lb_r2, r1, r2

# Funciones de ayuda para UI
def get_vista_df(df, is_r2=False):
    if df.empty: return df
    
    # Si es R2 incluimos la columna de puntos de R1
    if is_r2 and 'Pts_R1' in df.columns:
        cols = ['Posición', 'Participante', 'Puntos', 'Pts_R1', 'PlayIn']
    else:
        cols = ['Posición', 'Participante', 'Puntos', 'PlayIn']
        
    vista_df = df[cols].copy()
    def format_name(row):
        name = str(row['Participante'])
        short = name[:18] + ".." if len(name) > 18 else name
        return f"{row['Posición']} - {short}"
    vista_df['Participante'] = vista_df.apply(format_name, axis=1)
    return vista_df.drop(columns=['Posición'])

def plot_resumen(df_resp):
    if df_resp.empty: return
    series_cols = [c for c in df_resp.columns if " vs " in c]
    if series_cols:
        nombre_col = next((c for c in df_resp.columns if 'nombre' in c.lower()), df_resp.columns[2])
        melted = df_resp.melt(id_vars=[nombre_col], value_vars=series_cols, var_name='Serie', value_name='Pred')
        melted['Ganador'] = melted['Pred'].apply(lambda x: parse_prediccion(x)['ganador'] if parse_prediccion(x) else "N/A")
        resumen = melted[melted['Ganador'] != "N/A"].groupby(['Serie', 'Ganador']).size().reset_index(name='Votos')
        if not resumen.empty:
            st.plotly_chart(px.bar(resumen, x='Serie', y='Votos', color='Ganador', barmode='stack', text='Votos'), use_container_width=True)

try:
    lb_r1, lb_r2, df_r1, df_r2 = cargar_todo()
    st.title("🏀 Apuestas NBA Playoffs 2026")
    
    # --- LOGICA DE SEPARACIÓN DE BRACKETS (R2) ---
    if not lb_r1.empty:
        # Extraer los emails de los 15 primeros en R1
        winners_emails = lb_r1.iloc[:15]['Email'].str.lower().str.strip().tolist()
    else:
        winners_emails = []

    if not lb_r2.empty:
        lb_r2['Email_Clean'] = lb_r2['Email'].astype(str).str.lower().str.strip()
        
        # Filtrar Winners Bracket
        lb_r2_winners = lb_r2[lb_r2['Email_Clean'].isin(winners_emails)].copy().reset_index(drop=True)
        lb_r2_winners['Posición'] = range(1, len(lb_r2_winners) + 1)
        
        # Filtrar Losers Bracket
        lb_r2_losers = lb_r2[~lb_r2['Email_Clean'].isin(winners_emails)].copy().reset_index(drop=True)
        lb_r2_losers['Posición'] = range(1, len(lb_r2_losers) + 1)
        
        lb_r2_winners = lb_r2_winners.drop(columns=['Email_Clean'])
        lb_r2_losers = lb_r2_losers.drop(columns=['Email_Clean'])
    else:
        lb_r2_winners = pd.DataFrame()
        lb_r2_losers = pd.DataFrame()

    # Creación de pestañas (Ronda 2 primero)
    tabs = st.tabs([
        "🏆 R2 - Winners", 
        "🔥 R2 - Losers", 
        "📊 Resumen R2", 
        "🏆 R1 - Posiciones Finales", 
        "📊 Resumen R1", 
        "🔍 Registro R2", 
        "🔍 Registro R1"
    ])

    with tabs[0]:
        st.subheader("Ronda 2 - Winners Bracket (Top 7 avanzan)")
        if not lb_r2_winners.empty:
            # Pasamos is_r2=True y removemos el formateo anterior
            st.table(get_vista_df(lb_r2_winners, is_r2=True).style.apply(
                lambda x: ["background-color: #90ee90" if x.name < 7 else "background-color: #ffcccb"] * len(x), axis=1
            ))
        else:
            st.info("Esperando predicciones de la Ronda 2...")

    with tabs[1]:
        st.subheader("Ronda 2 - Losers Bracket (Top 3 se mantienen vivos)")
        if not lb_r2_losers.empty:
            st.table(get_vista_df(lb_r2_losers, is_r2=True).style.apply(
                lambda x: ["background-color: #90ee90" if x.name < 3 else "background-color: #ffcccb"] * len(x), axis=1
            ))
        else:
            st.info("Esperando predicciones de la Ronda 2...")

    with tabs[2]:
        st.subheader("Gráficas Predicciones Ronda 2")
        plot_resumen(df_r2)

    with tabs[3]:
        st.subheader("Ronda 1 - Tabla General Final (Top 15 pasaron a Winners)")
        if not lb_r1.empty:
            st.table(get_vista_df(lb_r1, is_r2=False).style.apply(
                lambda x: ["background-color: #90ee90" if x.name < 15 else "background-color: #ffcccb"] * len(x), axis=1
            ))

    with tabs[4]:
        st.subheader("Gráficas Predicciones Ronda 1")
        plot_resumen(df_r1)

    with tabs[5]:
        st.subheader("Respuestas Originales Ronda 2")
        st.dataframe(df_r2.drop(columns=[c for c in ['Marca temporal', 'Dirección de correo electrónico'] if c in df_r2.columns], errors='ignore'), use_container_width=True)

    with tabs[6]:
        st.subheader("Respuestas Originales Ronda 1")
        st.dataframe(df_r1.drop(columns=[c for c in ['Marca temporal', 'Dirección de correo electrónico'] if c in df_r1.columns], errors='ignore'), use_container_width=True)

except Exception as e:
    st.error(f"Error: {e}")
