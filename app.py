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

# --- 2. LÓGICA DE PROCESAMIENTO ---

def clean(text):
    if not text: return ""
    return "".join(filter(str.isalnum, str(text))).lower()

def parse_prediccion(pred_str):
    if not pred_str or pd.isna(pred_str): return None
    s = str(pred_str).strip()
    try:
        partes = s.split(" ")
        idx_marcador = next(i for i, p in enumerate(partes) if "-" in p and p.replace("-", "").isdigit())
        marcador = partes[idx_marcador].split("-")
        g1, g2 = int(marcador[0]), int(marcador[1])
        eq_a = " ".join(partes[:idx_marcador])
        eq_b = " ".join(partes[idx_marcador+1:])
        ganador = eq_a if g1 > g2 else eq_b
        return {"ganador": ganador, "total_juegos": g1 + g2}
    except: return None

def procesar_datos(resp_df, stat_df, playin_df, prev_scores=None):
    if resp_df.empty: return pd.DataFrame()
    
    resp_df.columns = [c.strip() for c in resp_df.columns]
    stat_df.columns = [c.strip() for c in stat_df.columns]
    series_cols = [c for c in resp_df.columns if " vs " in c]
    status_dict = {clean(k): v for k, v in stat_df.set_index('Series_ID').to_dict('index').items()}
    
    nombre_col = next((c for c in resp_df.columns if 'nombre' in c.lower()), resp_df.columns[2])
    email_col = next((c for c in resp_df.columns if 'correo' in c.lower() or 'email' in c.lower()), resp_df.columns[1])

    resultados = []
    for _, user in resp_df.iterrows():
        puntos_ronda = 0
        for col in series_cols:
            stat = status_dict.get(clean(col))
            pred = parse_prediccion(user[col])
            if not pred or not stat: continue
            
            t_a_name, t_b_name = [t.strip() for t in col.split(" vs ")]
            s_a, s_b = int(stat.get('Games_Team_A', 0)), int(stat.get('Games_Team_B', 0))
            
            if s_a == 4 or s_b == 4:
                final = 0
                winner_real = t_a_name if s_a == 4 else t_b_name
                if clean(pred['ganador']) == clean(winner_real):
                    final += 1
                    if int(pred['total_juegos']) == (s_a + s_b): final += 2
                puntos_ronda += final

        resultados.append({"Email": user[email_col], "Participante": user[nombre_col], "Puntos": int(puntos_ronda)})

    lb = pd.DataFrame(resultados)
    if not lb.empty:
        lb['Email_Key'] = lb['Email'].astype(str).str.lower().str.strip()
        
        # Merge PlayIn
        pi_email = next((c for c in playin_df.columns if 'correo' in c.lower() or 'email' in c.lower()), playin_df.columns[0])
        pi_score = next((c for c in playin_df.columns if 'score' in c.lower() or 'puntos' in c.lower()), playin_df.columns[1])
        pi_clean = playin_df[[pi_email, pi_score]].rename(columns={pi_email: 'Email', pi_score: 'PlayIn'})
        pi_clean['Email_Key'] = pi_clean['Email'].astype(str).str.lower().str.strip()
        lb = lb.merge(pi_clean[['Email_Key', 'PlayIn']], on='Email_Key', how='left').fillna(0)

        # Merge de históricos para desempate
        sort_cols = ["Puntos"]
        if prev_scores is not None:
            prev_scores['Email_Key'] = prev_scores['Email'].astype(str).str.lower().str.strip()
            # Identificar qué columnas de puntos previos tenemos (Pts_R2, Pts_R1, etc)
            extra_cols = [c for c in prev_scores.columns if c.startswith('Pts_')]
            lb = lb.merge(prev_scores[['Email_Key'] + extra_cols], on='Email_Key', how='left').fillna(0)
            sort_cols.extend(extra_cols)
        
        sort_cols.append("PlayIn")
        lb = lb.sort_values(by=sort_cols, ascending=False).reset_index(drop=True)
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
    
    # Lectura de hojas
    def get_df(name):
        try: return pd.DataFrame(sh.worksheet(name).get_all_records())
        except: return pd.DataFrame()

    r1, r2, rcf = get_df("Responses_R1"), get_df("Responses_R2"), get_df("Responses_CF")
    s1, s2, scf = get_df("Series_Status"), get_df("Series_Status_2"), get_df("Series_Status_CF")
    p = get_df("PlayIn_Score")
    
    # Procesar R1
    lb_r1 = procesar_datos(r1, s1, p)
    
    # Procesar R2 (Tiebreak: R1)
    r1_hist = lb_r1[['Email', 'Puntos']].rename(columns={'Puntos': 'Pts_R1'}) if not lb_r1.empty else None
    lb_r2 = procesar_datos(r2, s2, p, prev_scores=r1_hist)
    
    # Procesar CF (Tiebreak: R2, luego R1)
    cf_hist = None
    if not lb_r2.empty:
        # Combinar puntos de R2 y R1 para el desempate de CF
        cf_hist = lb_r2[['Email', 'Puntos', 'Pts_R1']].rename(columns={'Puntos': 'Pts_R2'})
    lb_cf = procesar_datos(rcf, scf, p, prev_scores=cf_hist)
    
    return lb_r1, lb_r2, lb_cf, r1, r2, rcf

def get_vista_df(df, rondas_previas=[]):
    if df.empty: return df
    cols = ['Posición', 'Participante', 'Puntos'] + rondas_previas + ['PlayIn']
    vista_df = df[cols].copy()
    vista_df['Participante'] = vista_df.apply(lambda r: f"{int(r['Posición'])} - {str(r['Participante'])[:18]}", axis=1)
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
    lb_r1, lb_r2, lb_cf, df_r1, df_r2, df_cf = cargar_todo()
    st.title("🏀 NBA Playoffs 2026 - Conference Finals")

    # --- LÓGICA DE CLASIFICACIÓN CF ---
    # Necesitamos saber quién venía de dónde en R2 para armar los Brackets de CF
    emails_winners_r2 = []
    emails_losers_r2 = []
    
    if not lb_r1.empty:
        top_15_r1 = lb_r1.iloc[:15]['Email'].str.lower().str.strip().tolist()
        if not lb_r2.empty:
            lb_r2['Email_Clean'] = lb_r2['Email'].str.lower().str.strip()
            # Identificar quiénes estaban en cada bracket en R2
            w_r2_all = lb_r2[lb_r2['Email_Clean'].isin(top_15_r1)].reset_index(drop=True)
            l_r2_all = lb_r2[~lb_r2['Email_Clean'].isin(top_15_r1)].reset_index(drop=True)
            
            # Reglas para CF:
            # CF Winners = Top 7 del Winners R2
            cf_winners_pool = w_r2_all.iloc[:7]['Email_Clean'].tolist()
            # CF Losers = Puestos 8-15 Winners R2 + Top 3 Losers R2
            cf_losers_pool = w_r2_all.iloc[7:15]['Email_Clean'].tolist() + l_r2_all.iloc[:3]['Email_Clean'].tolist()
        else:
            cf_winners_pool, cf_losers_pool = [], []
    
    # Brackets CF
    if not lb_cf.empty:
        lb_cf['Email_Clean'] = lb_cf['Email'].str.lower().str.strip()
        lb_cf_winners = lb_cf[lb_cf['Email_Clean'].isin(cf_winners_pool)].copy().reset_index(drop=True)
        lb_cf_winners['Posición'] = range(1, len(lb_cf_winners) + 1)
        
        lb_cf_losers = lb_cf[lb_cf['Email_Clean'].isin(cf_losers_pool)].copy().reset_index(drop=True)
        lb_cf_losers['Posición'] = range(1, len(lb_cf_losers) + 1)
    else:
        lb_cf_winners, lb_cf_losers = pd.DataFrame(), pd.DataFrame()

    tabs = st.tabs(["🏆 CF Winners", "🔥 CF Losers", "📊 Resumen CF", "📜 Histórico R2", "📜 Histórico R1", "🔍 Data CF"])

    with tabs[0]:
        st.subheader("Conference Finals - Winners Bracket")
        st.caption("Top 3: Finales (Verde) | 4to: Repechaje (Amarillo) | Resto: Eliminados (Rojo)")
        if not lb_cf_winners.empty:
            st.table(get_vista_df(lb_cf_winners, ['Pts_R2', 'Pts_R1']).style.apply(
                lambda x: ["background-color: #90ee90" if x.name < 3 else "background-color: #ffff99" if x.name == 3 else "background-color: #ffcccb"] * len(x), axis=1
            ))
        else: st.info("Sin datos para CF Winners")

    with tabs[1]:
        st.subheader("Conference Finals - Losers Bracket")
        st.caption("1er lugar: Repechaje vs 4to Winners (Amarillo) | Resto: Eliminados (Rojo)")
        if not lb_cf_losers.empty:
            st.table(get_vista_df(lb_cf_losers, ['Pts_R2', 'Pts_R1']).style.apply(
                lambda x: ["background-color: #ffff99" if x.name == 0 else "background-color: #ffcccb"] * len(x), axis=1
            ))
        else: st.info("Sin datos para CF Losers")

    with tabs[2]:
        plot_resumen(df_cf)

    with tabs[3]:
        st.subheader("Posiciones Finales Ronda 2")
        if not lb_r2.empty:
            st.dataframe(get_vista_df(lb_r2, ['Pts_R1']), use_container_width=True)

    with tabs[4]:
        st.subheader("Posiciones Finales Ronda 1")
        if not lb_r1.empty:
            st.dataframe(get_vista_df(lb_r1), use_container_width=True)

    with tabs[5]:
        st.subheader("Respuestas Originales CF")
        st.dataframe(df_cf, use_container_width=True)

except Exception as e:
    st.error(f"Error en la aplicación: {e}")
