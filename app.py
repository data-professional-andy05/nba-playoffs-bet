import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from engine import run_analytics

st.set_page_config(page_title="NBA Playoff Analytics", layout="wide")

@st.cache_data(ttl=600) # Refresh every 10 mins
def fetch_and_process():
    # Auth (Use Streamlit Secrets in production)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    
    sh = client.open("NBA_Playoffs_2026")
    responses = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
    status = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
    
    return run_analytics(responses, status)

st.title("🏀 NBA Playoff Betting: Live Insights")

try:
    df = fetch_and_process()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Leader", df.iloc[0]['Name'], f"{df.iloc[0]['EV']} EV")
    col2.metric("Participants", len(df))
    col3.metric("Round", "1st Round")

    st.subheader("Leaderboard (Ranked by Expected Value)")
    
    # Stylized dataframe
    st.dataframe(
        df.style.background_gradient(subset=['EV'], cmap='Greens')
                .background_gradient(subset=['Max'], cmap='Oranges'),
        use_container_width=True
    )
    
    st.info("💡 **EV (Expected Value):** Your projected score based on current series status and group consensus.")

except Exception as e:
    st.error(f"Error connecting to Google Sheets: {e}")