import streamlit as st
import pandas as pd
import numpy as np
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIG & STYLING ---
st.set_page_config(page_title="NBA Playoffs 2026", layout="wide")

# --- LOGIC FUNCTIONS ---

def parse_prediction_string(pred_str):
    """Safely converts 'Pistons 4-1 Magic' to usable dict."""
    if not pred_str or pd.isna(pred_str):
        return None
    s = str(pred_str).strip()
    if "vs" in s.lower(): # Skip header-like strings
        return None
    try:
        parts = s.split(" ")
        # Expecting: ['Pistons', '4-1', 'Magic']
        winner_name = parts[0]
        score_part = parts[1].split("-")
        g1, g2 = int(score_part[0]), int(score_part[1])
        return {"winner": winner_name, "total_games": g1 + g2}
    except:
        return None

def get_series_prob_outcomes(p_a, s_a, s_b):
    """Markov-style probability of all possible final results."""
    memo = {}
    def find_path(curr_a, curr_b):
        if curr_a == 4 or curr_b == 4:
            return {(curr_a, curr_b): 1.0}
        state = (curr_a, curr_b)
        if state in memo: return memo[state]
        res = {}
        # Path: Team A wins next game
        for (f_a, f_b), prob in find_path(curr_a + 1, curr_b).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * p_a
        # Path: Team B wins next game
        for (f_a, f_b), prob in find_path(curr_a, curr_b + 1).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * (1 - p_a)
        memo[state] = res
        return res
    return find_path(s_a, s_b)

def process_leaderboard(resp_df, stat_df, playin_df):
    """The main DA engine."""
    # 1. Standardize column names (remove spaces, etc.)
    resp_df.columns = [c.strip() for c in resp_df.columns]
    stat_df.columns = [c.strip() for c in stat_df.columns]
    playin_df.columns = [c.strip() for c in playin_df.columns]

    series_cols = [c for c in resp_df.columns if " vs " in c]
    status_dict = stat_df.set_index('Series_ID').to_dict('index')

    # Find the Name and Email columns regardless of the exact Spanish/English string
    name_col = next((c for c in resp_df.columns if 'nombre' in c.lower() or 'name' in c.lower()), resp_df.columns[2])
    email_col = next((c for c in resp_df.columns if 'correo' in c.lower() or 'email' in c.lower()), resp_df.columns[1])

    # 2. Crowd Probs
    crowd_probs = {}
    for col in series_cols:
        t_a = col.split(" vs ")[0]
        wins_a, total_g = 0, 0
        for val in resp_df[col]:
            p = parse_prediction_string(val)
            if p:
                total_g += p['total_games']
                wins_a += 4 if p['winner'] == t_a else (p['total_games'] - 4)
        crowd_probs[col] = wins_a / total_g if total_g > 0 else 0.5

    # 3. Calculate Scores
    results = []
    for _, user in resp_df.iterrows():
        real_p, ev_p, max_p = 0, 0, 0
        
        for col in series_cols:
            stat = status_dict.get(col)
            pred = parse_prediction_string(user[col])
            if not pred or not stat: continue
            
            t_a, t_b = col.split(" vs ")
            s_a, s_b = int(stat.get('Games_Team_A', 0)), int(stat.get('Games_Team_B', 0))
            
            # Probability Model
            n = s_a + s_b
            p_crowd = crowd_probs[col]
            p_live = (s_a / n) if n > 0 else 0.5
            weight = min(n / 6, 1.0)
            p_final_a = (weight * p_live) + ((1 - weight) * p_crowd)
            
            outcomes = get_series_prob_outcomes(p_final_a, s_a, s_b)
            
            # Points Map
            m_ev = 0
            possible_pts = []
            for (f_a, f_b), prob in outcomes.items():
                pts = 0
                winner = t_a if f_a == 4 else t_b
                if pred['winner'] == winner:
                    pts += 1
                    if pred['total_games'] == (f_a + f_b): pts += 2
                m_ev += pts * prob
                if prob > 0: possible_pts.append(pts)
            
            if s_a == 4 or s_b == 4:
                final = 0
                actual_win = t_a if s_a == 4 else t_b
                if pred['winner'] == actual_win:
                    final += 1
                    if pred['total_games'] == (s_a + s_b): final += 2
                real_p += final; ev_p += final; max_p += final
            else:
                ev_p += m_ev
                max_p += max(possible_pts) if possible_pts else 0

        results.append({
            "Email": user[email_col], 
            "Name": user[name_col], 
            "Real": int(real_p), 
            "EV": round(float(ev_p), 2), 
            "Max": int(max_p)
        })

    lb = pd.DataFrame(results)
    
    # 4. Tiebreak Merge
    if not lb.empty:
        pi_email = next((c for c in playin_df.columns if 'correo' in c.lower() or 'email' in c.lower()), playin_df.columns[0])
        pi_score = next((c for c in playin_df.columns if 'score' in c.lower() or 'puntos' in c.lower()), playin_df.columns[1])
        
        playin_subset = playin_df[[pi_email, pi_score]].rename(columns={pi_email: 'Email', pi_score: 'PlayIn'})
        lb = lb.merge(playin_subset, on='Email', how='left').fillna(0)
        lb['PlayIn'] = lb['PlayIn'].astype(int)
        lb = lb.sort_values(by=["Real", "EV", "PlayIn"], ascending=False).reset_index(drop=True)
    
    return lb

# --- STREAMLIT APP ---

@st.cache_data(ttl=60)
def get_all_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    sh = client.open("NBA_Playoffs_2026")
    
    r = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
    s = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
    p = pd.DataFrame(sh.worksheet("PlayIn_Score").get_all_records())
    
    l = process_leaderboard(r, s, p)
    return l, r

st.title("🏀 NBA Playoffs 2026")

try:
    df_l, df_r = get_all_data()

    if df_l is not None and not df_l.empty:
        t1, t2, t3 = st.tabs(["🏆 Leaderboard", "📊 Consensus", "🔍 Full Records"])

        with t1:
            # STYLE: Force black text for contrast, narrow columns
            def apply_style(row):
                bg = "#90ee90" if row.name < 15 else "#ffcccb" # Green if Safe, Red if Out
                return [f'background-color: {bg}; color: black; font-weight: bold'] * len(row)

            # Drop Email for UI
            view_df = df_l.drop(columns=['Email']) if 'Email' in df_l.columns else df_l

            st.dataframe(
                view_df.style.apply(apply_style, axis=1).format({"EV": "{:.2f}"}),
                use_container_width=True,
                height=700,
                column_config={
                    "Name": st.column_config.TextColumn("Bettor", width="medium"),
                    "Real": st.column_config.NumberColumn("Pts", width="small", format="%d"),
                    "EV": st.column_config.NumberColumn("EV", width="small"),
                    "Max": st.column_config.NumberColumn("Max", width="small", format="%d"),
                    "PlayIn": st.column_config.NumberColumn("Tiebreak", width="small", format="%d"),
                }
            )

        with t2:
            st.subheader("Series Votes")
            series_cols = [c for c in df_r.columns if " vs " in c]
            if series_cols:
                m = df_r.melt(id_vars=[df_r.columns[2]], value_vars=series_cols, var_name='Series', value_name='Pred')
                m['Winner'] = m['Pred'].str.split(" ").str[0]
                summary = m.groupby(['Series', 'Winner']).size().reset_index(name='Votes')
                fig = px.bar(summary, x='Series', y='Votes', color='Winner', barmode='stack', text='Votes')
                st.plotly_chart(fig, use_container_width=True)

        with t3:
            st.subheader("Raw Prediction Grid")
            # Drop personal info
            cols_to_hide = ['Marca temporal', 'Dirección de correo electrónico']
            st.dataframe(df_r.drop(columns=[c for c in cols_to_hide if c in df_r.columns]), use_container_width=True)
    else:
        st.warning("Data found, but processing returned an empty leaderboard. Check that 'Series_ID' in your Status sheet matches your Form columns exactly.")

except Exception as e:
    st.error(f"System Error: {e}")
