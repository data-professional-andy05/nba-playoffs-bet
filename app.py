import streamlit as st
import pandas as pd
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials
from engine import run_analytics

st.set_page_config(page_title="NBA Bet Tracker", layout="wide")

@st.cache_data(ttl=300)
def fetch_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sh = client.open("NBA_Playoffs_2026")
    
    responses = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
    status = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
    playin = pd.DataFrame(sh.worksheet("PlayIn_Score").get_all_records())
    
    leaderboard = run_analytics(responses, status, playin)
    return leaderboard, responses, status, playin

st.title("🏀 NBA Playoffs 2026")

try:
    df_l, df_r, df_s, df_p = fetch_data()
    
    if df_l is not None and not df_l.empty:
        t1, t2, t3 = st.tabs(["🏆 Standings", "📊 Consensus", "🔍 All Predictions"])

        with t1:
            def style_rows(row):
                if row.name < 15:
                    return ['background-color: #90ee90; color: black; font-weight: bold'] * len(row)
                return ['background-color: #ffcccb; color: black'] * len(row)

            disp = df_l.drop(columns=['Email']) if 'Email' in df_l.columns else df_l

            st.dataframe(
                disp.style.apply(style_rows, axis=1).format({"EV": "{:.2f}"}),
                use_container_width=True,
                height=700,
                column_config={
                    "Name": st.column_config.TextColumn("Bettor", width="medium"),
                    "Real": st.column_config.NumberColumn("Points", width="small", format="%d"),
                    "EV": st.column_config.NumberColumn("EV", width="small"),
                    "Max": st.column_config.NumberColumn("Max", width="small", format="%d"),
                    "PlayIn": st.column_config.NumberColumn("PlayIn", width="small", format="%d"),
                }
            )

        with t2:
            st.subheader("Group Consensus")
            series_cols = [c for c in df_r.columns if " vs " in c]
            if series_cols:
                m = df_r.melt(id_vars=['Nombre'], value_vars=series_cols, var_name='Series', value_name='Pred')
                m['Winner'] = m['Pred'].str.split(" ").str[0]
                sum_df = m.groupby(['Series', 'Winner']).size().reset_index(name='Votes')
                fig = px.bar(sum_df, x='Series', y='Votes', color='Winner', barmode='stack', text='Votes')
                st.plotly_chart(fig, use_container_width=True)

        with t3:
            st.subheader("Raw Prediction Data")
            drop_cols = ['Marca temporal', 'Dirección de correo electrónico']
            st.dataframe(df_r.drop(columns=[c for c in drop_cols if c in df_r.columns]), use_container_width=True)
            
    else:
        st.error("No leaderboard data was generated.")
        with st.expander("Diagnostic Info - Check your Sheet Data"):
            st.write(f"Responses Found: {len(df_r)}")
            st.write(f"Series Status Rows: {len(df_s)}")
            st.write(f"PlayIn Rows: {len(df_p)}")
            st.write("Series Columns detected:", [c for c in df_r.columns if " vs " in c])

except Exception as e:
    st.error(f"Critical Error: {e}")
