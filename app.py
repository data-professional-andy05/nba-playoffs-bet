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

def calcular_probabilidades_serie(p_a, s_a, s_b):
    memo = {}
    def encontrar_camino(curr_a, curr_b):
        if curr_a == 4 or curr_b == 4: return {(curr_a, curr_b): 1.0}
        estado = (curr_a, curr_b)
        if estado in memo: return memo[estado]
        res = {}
        for (f_a, f_b), prob in encontrar_camino(curr_a + 1, curr_b).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * p_a
        for (f_a, f_b), prob in encontrar_camino(curr_a, curr_b + 1).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * (1 - p_a)
        memo[estado] = res
        return res
    return encontrar_camino(s_a, s_b)

def procesar_datos(resp_df, stat_df, playin_df):
    # Normalizar nombres de columnas
    resp_df.columns = [c.strip() for c in resp_df.columns]
    stat_df.columns = [c.strip() for c in stat_df.columns]
    
    series_cols = [c for c in resp_df.columns if " vs " in c]
    # Crear diccionario de estado usando IDs normalizados
    status_dict = {clean(k): v for k, v in stat_df.set_index('Series_ID').to_dict('index').items()}
    
    nombre_col = next((c for c in resp_df.columns if 'nombre' in c.lower()), resp_df.columns[2])
    email_col = next((c for c in resp_df.columns if 'correo' in c.lower() or 'email' in c.lower()), resp_df.columns[1])

    # 1. Probabilidades de la Multitud (Crowd)
    crowd_probs = {}
    for col in series_cols:
        t_a_name = col.split(" vs ")[0].strip()
        wins_a, total_g = 0, 0
        for val in resp_df[col]:
            p = parse_prediccion(val)
            if p:
                total_g += p['total_juegos']
                wins_a += 4 if clean(p['ganador']) == clean(t_a_name) else (p['total_juegos'] - 4)
        crowd_probs[col] = wins_a / total_g if total_g > 0 else 0.5

    resultados = []
    for _, user in resp_df.iterrows():
        puntos_reales, ev, max_posible = 0, 0, 0
        
        for col in series_cols:
            stat = status_dict.get(clean(col))
            pred = parse_prediccion(user[col])
            if not pred or not stat: continue
            
            t_a_name, t_b_name = [t.strip() for t in col.split(" vs ")]
            s_a = int(stat.get('Games_Team_A', 0))
            s_b = int(stat.get('Games_Team_B', 0))
            n = s_a + s_b
            
            # --- EV LOGIC (Weighted formula) ---
            w = min(n / 7, 0.85) 
            p_l = (s_a / n) if n > 0 else 0.5
            p_c = crowd_probs.get(col, 0.5)
            p_final_a = (w * p_l) + ((1 - w) * p_c)
            
            outcomes = calcular_probabilidades_serie(p_final_a, s_a, s_b)
            
            m_ev = 0
            pts_posibles_match = []
            
            for (f_a, f_b), prob in outcomes.items():
                pts = 0
                ganador_final = t_a_name if f_a == 4 else t_b_name
                if clean(pred['ganador']) == clean(ganador_final):
                    pts += 1
                    if int(pred['total_juegos']) == (f_a + f_b):
                        pts += 2
                m_ev += pts * prob
                pts_posibles_match.append(pts)

            if s_a == 4 or s_b == 4:
                final = 0
                winner_real = t_a_name if s_a == 4 else t_b_name
                if clean(pred['ganador']) == clean(winner_real):
                    final += 1
                    if int(pred['total_juegos']) == (s_a + s_b):
                        final += 2
                puntos_reales += final; ev += final; max_posible += final
            else:
                ev += m_ev
                max_posible += max(pts_posibles_match) if pts_posibles_match else 0

        resultados.append({
            "Email": user[email_col], 
            "Participante": user[nombre_col], 
            "Puntos": int(puntos_reales), 
            "Esperado": round(float(ev), 2), 
            "Máximo": int(max_posible)
        })

    lb = pd.DataFrame(resultados)
    if not lb.empty:
        pi_email = next((c for c in playin_df.columns if 'correo' in c.lower() or 'email' in c.lower()), playin_df.columns[0])
        pi_score = next((c for c in playin_df.columns if 'score' in c.lower() or 'puntos' in c.lower()), playin_df.columns[1])
        pi_clean = playin_df[[pi_email, pi_score]].rename(columns={pi_email: 'Email', pi_score: 'PlayIn'})
        lb = lb.merge(pi_clean, on='Email', how='left').fillna(0)
        lb['PlayIn'] = lb['PlayIn'].astype(int)
        lb = lb.sort_values(by=["Puntos", "Esperado", "PlayIn"], ascending=False).reset_index(drop=True)
        lb.insert(0, 'Posición', range(1, len(lb) + 1))
    return lb

# --- 3. CARGA Y UI ---

@st.cache_data(ttl=60)
def cargar_todo():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    sh = client.open("NBA_Playoffs_2026")
    r = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
    s = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
    p = pd.DataFrame(sh.worksheet("PlayIn_Score").get_all_records())
    return procesar_datos(r, s, p), r

try:
    df_l, df_r = cargar_todo()
    st.title("🏀 Apuestas NBA Playoffs 2026")
    tab1, tab2, tab3 = st.tabs(["🏆 Tabla de Posiciones", "📊 Resumen", "🔍 Registro"])

    with tab1:
        vista_df = df_l[['Posición', 'Participante', 'Puntos', 'Esperado', 'Máximo', 'PlayIn']].copy()
        def format_name(row):
            name = str(row['Participante'])
            short = name[:18] + ".." if len(name) > 18 else name
            return f"{row['Posición']} - {short}"
        vista_df['Participante'] = vista_df.apply(format_name, axis=1)
        st.table(vista_df.drop(columns=['Posición']).style.apply(lambda x: ["background-color: #90ee90" if x.name < 15 else "background-color: #ffcccb"] * len(x), axis=1).format({"Esperado": "{:.2f}"}))

    with tab2:
        series_cols = [c for c in df_r.columns if " vs " in c]
        if series_cols:
            melted = df_r.melt(id_vars=[df_r.columns[2]], value_vars=series_cols, var_name='Serie', value_name='Pred')
            melted['Ganador'] = melted['Pred'].apply(lambda x: parse_prediccion(x)['ganador'] if parse_prediccion(x) else "N/A")
            resumen = melted[melted['Ganador'] != "N/A"].groupby(['Serie', 'Ganador']).size().reset_index(name='Votos')
            st.plotly_chart(px.bar(resumen, x='Serie', y='Votos', color='Ganador', barmode='stack', text='Votos'), use_container_width=True)

    with tab3:
        st.dataframe(df_r.drop(columns=[c for c in ['Marca temporal', 'Dirección de correo electrónico'] if c in df_r.columns]), use_container_width=True)

except Exception as e:
    st.error(f"Error: {e}")
