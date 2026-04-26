import streamlit as st
import pandas as pd
import gspread
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
    
    return run_analytics(responses, status, playin)

st.title("🏀 NBA Playoffs 2026")

try:
    df = fetch_data()

    # UI Styling: Bold colors, Black text for contrast
    def style_rows(row):
        if row.name < 15: # Safe Zone
            return ['background-color: #90ee90; color: black; font-weight: bold'] * len(row)
        return ['background-color: #ffcccb; color: black'] * len(row) # Danger Zone

    st.subheader("Leaderboard & Projections")
    
    # Display table
    st.dataframe(
        df.style.apply(style_rows, axis=1)
                .format({"EV": "{:.2f}"}), 
        use_container_width=True,
        height=750
    )

    st.markdown("""
    **Legend:**
    *   **Real:** Points from finished series.
    *   **EV (Expected Value):** Your projected total points based on live series scores and group consensus.
    *   **Max:** The maximum points you can still mathematically achieve.
    """)

except Exception as e:
    st.error(f"Error: {e}")
