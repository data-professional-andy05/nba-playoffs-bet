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
        pts_actual = 0
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
                pts_actual += final

        resultados.append({"Email": user[email_col], "Participante": user[nombre_col], "Puntos": int(pts_actual)})

    lb = pd.DataFrame(resultados)
    if not lb.empty:
        lb['Email_Key'] = lb['Email'].astype(str).str.lower().str.strip()
        pi_email = next((c for c in playin_df.columns if 'correo' in c.lower() or 'email' in c.lower()), playin_df.columns[0])
        pi_score = next((c for c in playin_df.columns if 'score' in c.lower() or 'puntos' in c.lower()), playin_df.columns[1])
        pi_clean = playin_df[[pi_email, pi_score]].rename(columns={pi_email: 'Email', pi_score: 'PlayIn'})
        pi_clean['Email_Key'] = pi_clean['Email'].astype(str).str.lower().str.strip()
        lb = lb.merge(pi_clean[['Email_Key', 'PlayIn']], on='Email_Key', how='left').fillna(0)

        sort_cols = ["Puntos"]
        if prev_scores is not None:
            prev_scores['Email_Key'] = prev_scores['Email'].astype(str).str.lower().str.strip()
            extra_cols = [c for c in prev_scores.columns if c.startswith('Pts_')]
            lb = lb.merge(prev_scores[['Email_Key'] + extra_cols], on='Email_Key', how='left').fillna(0)
            sort_cols.extend(extra_cols)
        
        sort_cols.append("PlayIn")
        lb = lb.sort_values(by=sort_cols, ascending=False).reset_index(drop=True)
        lb = lb.drop(columns=['Email_Key'])
        lb.insert(0, 'Posición', range(1, len(lb) + 1))
        
    return lb

# --- 3. CARGA DE DATOS ---

@st.cache_data(ttl=60)
def cargar_todo():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    sh = client.open("NBA_Playoffs_2026")
    
    r1 = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
    s1 = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
    p = pd.DataFrame(sh.worksheet("PlayIn_Score").get_all_records())
    lb_r1 = procesar_datos(r1, s1, p)
    
    r2 = pd.DataFrame(sh.worksheet("Responses_R2").get_all_records())
    s2 = pd.DataFrame(sh.worksheet("Series_Status_2").get_all_records())
    r1_scores = lb_r1[['Email', 'Puntos']].rename(columns={'Puntos': 'Pts_R1'}) if not lb_r1.empty else None
    lb_r2 = procesar_datos(r2, s2, p, r1_scores)
    
    rcf = pd.DataFrame(sh.worksheet("Responses_CF").get_all_records())
    scf = pd.DataFrame(sh.worksheet("Series_Status_CF").get_all_records())
    if not lb_r2.empty:
        cf_scores = lb_r2[['Email', 'Puntos', 'Pts_R1']].rename(columns={'Puntos': 'Pts_R2'})
    else:
        cf_scores = None
    lb_cf = procesar_datos(rcf, scf, p, cf_scores)
    
    return lb_r1, lb_r2, lb_cf, r1, r2, rcf

def get_vista_df(df, current_pts_col='Puntos', cols_extra=[]):
    if df.empty: return df
    cols = ['Posición', 'Participante', current_pts_col] + cols_extra + ['PlayIn']
    vista_df = df[cols].copy()
    # Asegurar que PlayIn sea entero sin decimales
    vista_df['PlayIn'] = vista_df['PlayIn'].astype(int)
    vista_df['Participante'] = vista_df.apply(lambda row: f"{row['Posición']} - {str(row['Participante'])[:18]}", axis=1)
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

# --- 4. UI Y LÓGICA DE BRACKETS ---

try:
    lb_r1, lb_r2, lb_cf, df_r1, df_r2, df_cf = cargar_todo()
    st.title("🏀 Apuestas NBA Playoffs 2026")

    winners_r1_emails = lb_r1.iloc[:15]['Email'].str.lower().str.strip().tolist() if not lb_r1.empty else []
    
    if not lb_r2.empty:
        lb_r2['Email_Clean'] = lb_r2['Email'].str.lower().str.strip()
        lb_r2_winners_full = lb_r2[lb_r2['Email_Clean'].isin(winners_r1_emails)].reset_index(drop=True)
        lb_r2_losers_full = lb_r2[~lb_r2['Email_Clean'].isin(winners_r1_emails)].reset_index(drop=True)
        cf_winners_pool = lb_r2_winners_full.iloc[:7]['Email_Clean'].tolist()
        cf_losers_pool = lb_r2_winners_full.iloc[7:15]['Email_Clean'].tolist() + lb_r2_losers_full.iloc[:3]['Email_Clean'].tolist()
    else:
        lb_r2_winners_full, lb_r2_losers_full = pd.DataFrame(), pd.DataFrame()
        cf_winners_pool, cf_losers_pool = [], []

    if not lb_cf.empty:
        lb_cf['Email_Clean'] = lb_cf['Email'].str.lower().str.strip()
        lb_cf_winners = lb_cf[lb_cf['Email_Clean'].isin(cf_winners_pool)].copy().reset_index(drop=True)
        lb_cf_winners['Posición'] = range(1, len(lb_cf_winners) + 1)
        
        lb_cf_losers = lb_cf[lb_cf['Email_Clean'].isin(cf_losers_pool)].copy().reset_index(drop=True)
        lb_cf_losers['Posición'] = range(1, len(lb_cf_losers) + 1)

        # Clasificación a finales
        finalistas = lb_cf_winners.iloc[:3].copy()
        if len(lb_cf_winners) >= 4 and not lb_cf_losers.empty:
            w4 = lb_cf_winners.iloc[3:4]
            l1 = lb_cf_losers.iloc[0:1]
            candidatos_4to = pd.concat([w4, l1]).sort_values(by=['Puntos', 'Pts_R2', 'Pts_R1', 'PlayIn'], ascending=False)
            finalistas = pd.concat([finalistas, candidatos_4to.iloc[:1]])
        elif len(lb_cf_winners) >= 4:
            finalistas = pd.concat([finalistas, lb_cf_winners.iloc[3:4]])
        elif not lb_cf_losers.empty:
            finalistas = pd.concat([finalistas, lb_cf_losers.iloc[0:1]])
            
        lb_finals = finalistas.sort_values(by=['Puntos', 'Pts_R2', 'Pts_R1', 'PlayIn'], ascending=False).reset_index(drop=True)
        lb_finals = lb_finals.rename(columns={'Puntos': 'Pts_CF'})
        lb_finals['Posición'] = range(1, len(lb_finals) + 1)
    else:
        lb_cf_winners, lb_cf_losers, lb_finals = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # --- TABS ---
    tabs = st.tabs([
        "⭐ FINALES", "🏆 CF - Winners", "🔥 CF - Losers", "📊 Resumen CF",
        "🏆 R2 - Winners", "🔥 R2 - Losers", "📊 Resumen R2",
        "🏆 R1 - Posiciones", "📊 Resumen R1",
        "🔍 Registro CF", "🔍 Registro R2", "🔍 Registro R1"
    ])

    # --- TAB 0: FINALES ---
    with tabs[0]:
        st.subheader("Clasificados a la Gran Final")
        if not lb_finals.empty:
            # Se usa 'Pts_CF' como columna de puntos actual para este tab
            st.table(get_vista_df(lb_finals, 'Pts_CF', ['Pts_R2', 'Pts_R1']).style.apply(
                lambda x: ["background-color: #90ee90"] * len(x), axis=1
            ))
            st.info("Clasifican: Top 3 Winners + Mejor entre 4to Winners y 1ero Losers.")
        else: st.info("Esperando resultados para definir finalistas...")

    # --- TAB 1: CF Winners ---
    with tabs[1]:
        st.subheader("Conference Finals - Winners Bracket")
        if not lb_cf_winners.empty:
            st.table(get_vista_df(lb_cf_winners, 'Puntos', ['Pts_R2', 'Pts_R1']).style.apply(
                lambda x: ["background-color: #90ee90" if x.name < 3 else "background-color: #ffff99" if x.name == 3 else "background-color: #ffcccb"] * len(x), axis=1
            ))
        else: st.info("Esperando resultados CF...")

    # --- TAB 2: CF Losers ---
    with tabs[2]:
        st.subheader("Conference Finals - Losers Bracket")
        if not lb_cf_losers.empty:
            st.table(get_vista_df(lb_cf_losers, 'Puntos', ['Pts_R2', 'Pts_R1']).style.apply(
                lambda x: ["background-color: #ffff99" if x.name == 0 else "background-color: #ffcccb"] * len(x), axis=1
            ))
        else: st.info("Esperando resultados CF...")

    with tabs[3]: plot_resumen(df_cf)

    # --- TAB 4: R2 Winners ---
    with tabs[4]:
        st.subheader("Ronda 2 - Winners Bracket")
        if not lb_r2_winners_full.empty:
            df_v = get_vista_df(lb_r2_winners_full.assign(Posición=range(1, len(lb_r2_winners_full)+1)), 'Puntos', ['Pts_R1'])
            st.table(df_v.style.apply(lambda x: ["background-color: #90ee90" if x.name < 7 else "background-color: #ffcccb"] * len(x), axis=1))

    # --- TAB 5: R2 Losers ---
    with tabs[5]:
        st.subheader("Ronda 2 - Losers Bracket")
        if not lb_r2_losers_full.empty:
            df_v = get_vista_df(lb_r2_losers_full.assign(Posición=range(1, len(lb_r2_losers_full)+1)), 'Puntos', ['Pts_R1'])
            st.table(df_v.style.apply(lambda x: ["background-color: #90ee90" if x.name < 3 else "background-color: #ffcccb"] * len(x), axis=1))

    with tabs[6]: plot_resumen(df_r2)

    # --- TAB 7: R1 ---
    with tabs[7]:
        st.subheader("Ronda 1 - Posiciones Finales")
        if not lb_r1.empty:
            st.table(get_vista_df(lb_r1, 'Puntos').style.apply(lambda x: ["background-color: #90ee90" if x.name < 15 else "background-color: #ffcccb"] * len(x), axis=1))

    with tabs[8]: plot_resumen(df_r1)

    # --- REGISTROS ---
    with tabs[9]: st.dataframe(df_cf, use_container_width=True)
    with tabs[10]: st.dataframe(df_r2, use_container_width=True)
    with tabs[11]: st.dataframe(df_r1, use_container_width=True)

except Exception as e:
    st.error(f"Error: {e}")
