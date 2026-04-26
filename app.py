import streamlit as st
import pandas as pd
import numpy as np
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="NBA Playoffs 2026 - La Porra", layout="wide")

# --- LÓGICA DE PROCESAMIENTO ---

def parse_prediccion(pred_str):
    """Parsea 'Pistons 4-1 Magic' a diccionario identificando al verdadero ganador."""
    if not pred_str or pd.isna(pred_str):
        return None
    s = str(pred_str).strip()
    if "vs" in s.lower(): 
        return None
    try:
        partes = s.split(" ")
        
        # Buscar el índice donde está el marcador numérico (ej. "4-1", "2-4")
        idx_marcador = -1
        for i, parte in enumerate(partes):
            if "-" in parte and parte.replace("-", "").isdigit():
                idx_marcador = i
                break
                
        if idx_marcador == -1:
            return None
            
        equipo_a = " ".join(partes[:idx_marcador])
        equipo_b = " ".join(partes[idx_marcador+1:])
        
        marcador = partes[idx_marcador].split("-")
        g1, g2 = int(marcador[0]), int(marcador[1])
        
        # El ganador es el equipo con más victorias
        ganador = equipo_a if g1 > g2 else equipo_b
        
        return {"ganador": ganador, "total_juegos": g1 + g2}
    except:
        return None

def calcular_probabilidades_serie(p_a, s_a, s_b):
    """Cálculo de caminos de Markov para resultados finales."""
    memo = {}
    def encontrar_camino(curr_a, curr_b):
        if curr_a == 4 or curr_b == 4:
            return {(curr_a, curr_b): 1.0}
        estado = (curr_a, curr_b)
        if estado in memo: return memo[estado]
        res = {}
        # Camino: Gana Equipo A el siguiente
        for (f_a, f_b), prob in encontrar_camino(curr_a + 1, curr_b).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * p_a
        # Camino: Gana Equipo B el siguiente
        for (f_a, f_b), prob in encontrar_camino(curr_a, curr_b + 1).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * (1 - p_a)
        memo[estado] = res
        return res
    return encontrar_camino(s_a, s_b)

def procesar_datos(resp_df, stat_df, playin_df):
    """Motor de cálculo principal."""
    # Estandarización de nombres de columnas
    resp_df.columns = [c.strip() for c in resp_df.columns]
    stat_df.columns = [c.strip() for c in stat_df.columns]
    playin_df.columns = [c.strip() for c in playin_df.columns]

    series_cols = [c for c in resp_df.columns if " vs " in c]
    status_dict = stat_df.set_index('Series_ID').to_dict('index')

    nombre_col = next((c for c in resp_df.columns if 'nombre' in c.lower()), resp_df.columns[2])
    email_col = next((c for c in resp_df.columns if 'correo' in c.lower() or 'email' in c.lower()), resp_df.columns[1])

    # 1. Probabilidades del Consenso (Crowd Source)
    crowd_probs = {}
    for col in series_cols:
        t_a = col.split(" vs ")[0]
        wins_a, total_g = 0, 0
        for val in resp_df[col]:
            p = parse_prediccion(val)
            if p:
                total_g += p['total_juegos']
                wins_a += 4 if p['ganador'] == t_a else (p['total_juegos'] - 4)
        crowd_probs[col] = wins_a / total_g if total_g > 0 else 0.5

    # 2. Bucle de cálculo por usuario
    resultados = []
    for _, user in resp_df.iterrows():
        puntos_reales, ev, max_posible = 0, 0, 0
        
        for col in series_cols:
            stat = status_dict.get(col)
            pred = parse_prediccion(user[col])
            if not pred or not stat: continue
            
            t_a, t_b = col.split(" vs ")
            s_a, s_b = int(stat.get('Games_Team_A', 0)), int(stat.get('Games_Team_B', 0))
            
            # Modelo de Probabilidad Combinado
            n = s_a + s_b
            p_c = crowd_probs[col]
            p_l = (s_a / n) if n > 0 else 0.5
            w = min(n / 6, 1.0)
            p_final_a = (w * p_l) + ((1 - w) * p_c)
            
            outcomes = calcular_probabilidades_serie(p_final_a, s_a, s_b)
            
            m_ev = 0
            pts_posibles_match = []
            for (f_a, f_b), prob in outcomes.items():
                pts = 0
                ganador_final = t_a if f_a == 4 else t_b
                if pred['ganador'] == ganador_final:
                    pts += 1
                    if pred['total_juegos'] == (f_a + f_b): pts += 2
                m_ev += pts * prob
                if prob > 0: pts_posibles_match.append(pts)
            
            if s_a == 4 or s_b == 4:
                final = 0
                w_real = t_a if s_a == 4 else t_b
                if pred['ganador'] == w_real:
                    final += 1
                    if pred['total_juegos'] == (s_a + s_b): final += 2
                puntos_reales += final; ev += final; max_posible += final
            else:
                ev += m_ev
                max_posible += max(pts_posibles_match) if pts_posibles_match else 0

        resultados.append({
            "Email": user[email_col], 
            "Participante": user[nombre_col], 
            "Puntos": int(puntos_reales), 
            "EV": round(float(ev), 2), 
            "Máximo": int(max_posible)
        })

    lb = pd.DataFrame(resultados)
    
# 3. Cruce con Play-In para Desempates
    if not lb.empty:
        pi_email = next((c for c in playin_df.columns if 'correo' in c.lower() or 'email' in c.lower()), playin_df.columns[0])
        pi_score = next((c for c in playin_df.columns if 'score' in c.lower() or 'puntos' in c.lower()), playin_df.columns[1])
        
        pi_clean = playin_df[[pi_email, pi_score]].rename(columns={pi_email: 'Email', pi_score: 'PlayIn'})
        lb = lb.merge(pi_clean, on='Email', how='left').fillna(0)
        lb['PlayIn'] = lb['PlayIn'].astype(int)
        
        # Ordenar a los participantes
        lb = lb.sort_values(by=["Puntos", "EV", "PlayIn"], ascending=False).reset_index(drop=True)
        
        # --- NUEVO: Insertar la columna de Posición al principio (basada en el orden) ---
        lb.insert(0, 'Posición', range(1, len(lb) + 1))
    
    return lb

# --- INTERFAZ STREAMLIT ---

@st.cache_data(ttl=60)
def cargar_todo():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    sh = client.open("NBA_Playoffs_2026")
    
    r = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
    s = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
    p = pd.DataFrame(sh.worksheet("PlayIn_Score").get_all_records())
    
    l = procesar_datos(r, s, p)
    return l, r

st.title("🏀 Apuestas NBA Playoffs 2026")

try:
    df_l, df_r = cargar_todo()

    if df_l is not None and not df_l.empty:
        tab1, tab2, tab3 = st.tabs(["🏆 Tabla de Posiciones", "📊 Resumen por Serie", "🔍 Registro de Predicciones"])

        with tab1:
            st.markdown("### Clasificación en Vivo")
            st.write("Verde: Pasan a 2da Ronda (Top 15) | Rojo: Cuadro de Consolación")

            def aplicar_estilos(row):
                # row.name es el índice (0-14 para los primeros 15). 
                # Esto coloreará de verde de la Posición 1 a la 15, y rojo de la 16 en adelante.
                color_fondo = "#90ee90" if row.name < 15 else "#ffcccb"
                return [f'background-color: {color_fondo}; color: black; font-weight: bold'] * len(row)

            # Quitar Email de la vista
            vista_df = df_l.drop(columns=['Email']) if 'Email' in df_l.columns else df_l

            st.dataframe(
                vista_df.style.apply(aplicar_estilos, axis=1).format({"EV": "{:.2f}"}),
                use_container_width=True,
                height=700,
                column_config={
                    "Posición": st.column_config.NumberColumn("Pos.", width="small", format="%d"),
                    "Participante": st.column_config.TextColumn("Participante", width="medium", pinned=True),
                    "Puntos": st.column_config.NumberColumn("Puntos", width="small", format="%d"),
                    "EV": st.column_config.NumberColumn("EV", width="small"),
                    "Máximo": st.column_config.NumberColumn("Máximo", width="small", format="%d"),
                    "PlayIn": st.column_config.NumberColumn("Play-In", width="small", format="%d"),
                },
                hide_index=True # Sigue ocultando el índice por defecto de pandas, dejando solo nuestra columna "Posición"
            )
        with tab2:
            st.subheader("Distribución de Predicciones")
            series_cols = [c for c in df_r.columns if " vs " in c]
            if series_cols:
                melted = df_r.melt(id_vars=[df_r.columns[2]], value_vars=series_cols, var_name='Serie', value_name='Pred')
                
                # Usamos la función parse_prediccion para extraer al verdadero ganador
                def extraer_ganador(pred):
                    resultado = parse_prediccion(pred)
                    return resultado['ganador'] if resultado else "N/A"
                    
                melted['Ganador'] = melted['Pred'].apply(extraer_ganador)
                
                # Opcional: Filtrar predicciones vacías o N/A para no ensuciar el gráfico
                melted = melted[melted['Ganador'] != "N/A"]
                
                resumen_votos = melted.groupby(['Serie', 'Ganador']).size().reset_index(name='Votos')
                
                fig = px.bar(resumen_votos, x='Serie', y='Votos', color='Ganador', 
                             title="Votos por Equipo en cada Serie", 
                             barmode='stack', text='Votos',
                             color_discrete_sequence=px.colors.qualitative.Bold)
                
                fig.update_layout(xaxis_title="", yaxis_title="Número de Apostadores")
                st.plotly_chart(fig, use_container_width=True)

        with tab3:
            st.subheader("Grid de Transparencia")
            st.write("Datos originales de todas las predicciones recibidas.")
            cols_ocultar = ['Marca temporal', 'Dirección de correo electrónico']
            grid_raw = df_r.drop(columns=[c for c in cols_ocultar if c in df_r.columns])
            st.dataframe(grid_raw, use_container_width=True, hide_index=True)
    else:
        st.warning("No se generaron datos. Revisa que los nombres de las series en 'Series_Status' coincidan con los del formulario.")

except Exception as e:
    st.error(f"Error Crítico del Sistema: {e}")
