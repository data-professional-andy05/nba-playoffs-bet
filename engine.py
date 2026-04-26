# ... (parse_pred and get_series_outcomes stay the same) ...

def run_analytics(responses_df, status_df, playin_df):
    series_cols = [c for c in responses_df.columns if "vs" in c]
    status_dict = status_df.set_index('Series_ID').to_dict('index')
    
    # Calculate Crowd Probs
    crowd_probs = {}
    for col in series_cols:
        t_a = col.split(" vs ")[0]
        wins_a, total_g = 0, 0
        for val in responses_df[col]:
            p = parse_pred(val)
            if p:
                total_g += p['total']
                wins_a += 4 if p['winner'] == t_a else (p['total'] - 4)
        crowd_probs[col] = wins_a / total_g if total_g > 0 else 0.5

    user_results = []
    for _, user in responses_df.iterrows():
        real_pts, ev_pts, max_pts = 0, 0, 0
        email = user['Dirección de correo electrónico']
        
        for col in series_cols:
            stat = status_dict.get(col)
            pred = parse_pred(user[col])
            if not pred or not stat: continue
            
            t_a, t_b = col.split(" vs ")
            s_a, s_b = int(stat['Games_Team_A']), int(stat['Games_Team_B'])
            
            n = s_a + s_b
            p_final_a = ((min(n/6, 1.0)) * (s_a/n if n>0 else 0.5)) + ((1 - min(n/6, 1.0)) * crowd_probs[col])
            outcomes = get_series_outcomes(p_final_a, s_a, s_b)
            
            possible_pts = []
            match_ev = 0
            for (f_a, f_b), prob in outcomes.items():
                pts = 0
                winner = t_a if f_a == 4 else t_b
                if pred['winner'] == winner:
                    pts += 1
                    if pred['total'] == (f_a + f_b): pts += 2
                match_ev += pts * prob
                if prob > 0: possible_pts.append(pts)
            
            if s_a == 4 or s_b == 4:
                final = 0
                w = t_a if s_a == 4 else t_b
                if pred['winner'] == w:
                    final += 1
                    if pred['total'] == (s_a + s_b): final += 2
                real_pts += final; ev_pts += final; max_pts += final
            else:
                ev_pts += match_ev
                max_pts += max(possible_pts) if possible_pts else 0

        user_results.append({
            "Email": email, "Name": user['Nombre'], 
            "Real": int(real_pts), "EV": round(ev_pts, 2), "Max": int(max_pts)
        })

    leaderboard = pd.DataFrame(user_results)
    leaderboard = leaderboard.merge(playin_df[['Email', 'Score']], on='Email', how='left').fillna(0)
    leaderboard['Score'] = leaderboard['Score'].astype(int)
    leaderboard = leaderboard.rename(columns={'Score': 'PlayIn'})
    
    leaderboard = leaderboard.sort_values(by=["Real", "EV", "PlayIn"], ascending=False).reset_index(drop=True)
    
    # Return both the leaderboard and the raw predictions for the "Transparency" tab
    return leaderboard, responses_df
