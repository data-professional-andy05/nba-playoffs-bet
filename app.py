import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from engine import run_analytics

st.set_page_config(page_title="NBA Playoff Bet", layout="wide")

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
    
    return run_analytics(responses, status, playin)

st.title("🏀 NBA Playoffs 2026 Leaderboard")

try:
    df = fetch_data()

    # Define the Cut Logic
    def style_rows(row):
        if row.name < 15:
            return ['background-color: #d4edda'] * len(row) # Green (Safe)
        return ['background-color: #f8d7da'] * len(row) # Red (Losers Bracket)

    st.subheader("Current Standings")
    st.write("Top 15 advance to Round 2. Others to Losers Bracket.")
    
    st.dataframe(df.style.apply(style_rows, axis=1), use_container_width=True)

    # Simple metric dashboard
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Current Leader", df.iloc[0]['Name'], f"{df.iloc[0]['Real']} pts")
    with c2:
        st.metric("The Bubble (#15)", df.iloc[14]['Name'], f"{df.iloc[14]['Real']} pts")

except Exception as e:
    st.error(f"Error: {e}")
