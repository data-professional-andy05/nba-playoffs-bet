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
    return leaderboard, responses

st.title("🏀 NBA Playoffs 2026 Leaderboard")

try:
    df_leaderboard, df_raw = fetch_data()
    
    tab1, tab2, tab3 = st.tabs(["🏆 Standings", "📊 Group Consensus", "🔍 All Predictions"])

    with tab1:
        st.subheader("Leaderboard")
        st.write("Top 15 are Safe (Green). Bottom 6 to Losers Bracket (Red).")

        # UI Styling: Bold colors, Black text for contrast
        def style_rows(row):
            if row.name < 15:
                return ['background-color: #90ee90; color: black; font-weight: bold'] * len(row)
            return ['background-color: #ffcccb; color: black'] * len(row)

        display_df = df_leaderboard.drop(columns=['Email'])

        st.dataframe(
            display_df.style.apply(style_rows, axis=1),
            use_container_width=True,
            height=750,
            column_config={
                "Name": st.column_config.TextColumn("Bettor", width="medium"),
                "Real": st.column_config.NumberColumn("Points", width="small", format="%d"),
                "EV": st.column_config.NumberColumn("EV", width="small", format="%.2f"),
                "Max": st.column_config.NumberColumn("Max", width="small", format="%d"),
                "PlayIn": st.column_config.NumberColumn("PlayIn", width="small", format="%d"),
            }
        )

    with tab2:
        st.subheader("Consensus Summary")
        series_cols = [c for c in df_raw.columns if " vs " in c]
        melted = df_raw.melt(id_vars=['Nombre'], value_vars=series_cols, var_name='Series', value_name='Pred')
        melted['Winner'] = melted['Pred'].str.split(" ").str[0]
        
        summary = melted.groupby(['Series', 'Winner']).size().reset_index(name='Votes')
        fig = px.bar(summary, x='Series', y='Votes', color='Winner', 
                     title="Total Votes per Series", barmode='stack', text='Votes')
        fig.update_layout(xaxis_title="", yaxis_title="Number of Bettors")
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("Transparency Grid")
        st.write("Full record of every prediction made for Round 1.")
        clean_raw = df_raw.drop(columns=['Marca temporal', 'Dirección de correo electrónico'])
        st.dataframe(clean_raw, use_container_width=True)

except Exception as e:
    st.error(f"Error fetching data: {e}")
