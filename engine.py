import pandas as pd
import numpy as np

def parse_pred(pred_str):
    if not pred_str or pd.isna(pred_str) or 'vs' in str(pred_str):
        return None
    try:
        parts = str(pred_str).split(" ")
        winner = parts[0]
        score = parts[1].split("-")
        g1, g2 = int(score[0]), int(score[1])
        return {"winner": winner, "total": g1 + g2}
    except:
        return None

def get_series_outcomes(p_a, s_a, s_b):
    memo = {}
    def find_path(curr_a, curr_b):
        if curr_a == 4 or curr_b == 4:
            return {(curr_a, curr_b): 1.0}
        state = (curr_a, curr_b)
        if state in memo: return memo[state]
        res = {}
        for (f_a, f_b), prob in find_path(curr_a + 1, curr_b).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * p_a
        for (f_a, f_b), prob in find_path(curr_a, curr_b + 1).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * (1 - p_a)
        memo[state] = res
        return res
    return find_path(s_a, s_b)

def run_analytics(responses_df, status_df, playin_df):
    if responses_df.empty:
        return pd.DataFrame()

    # Identify series columns
    series_cols = [c for c in responses_df.columns if " vs " in c]
    status_dict = status_df.set_index('Series_ID').to_dict('index') if not status_df.empty else {}
    
    # Identify Name and Email columns flexibly
    name_col = next((c for c in responses_df.columns if 'Nombre' in c or 'Name' in c), responses_df.columns[2])
    email_col = next((c for c in responses_df.columns if 'correo' in c or 'Email' in c), responses_df.columns[1])

    # 1. Group Consensus Probability
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

    # 2. Main Calculation Loop
    user_results = []
    for _, user in responses_df.iterrows():
        real_pts, ev_pts, max_pts = 0, 0, 0
        
        for col in series_cols:
            stat = status_dict.get(col)
            pred = parse_pred(user[col])
            if not pred or not stat: continue
            
            t_a, t_b = col.split(" vs ")
            try:
                s_a, s_b = int(stat.get('Games_Team_A', 0)), int(stat.get('Games_Team_B', 0))
            except: s_a, s_b = 0, 0
            
            # Probability Model
            n = s_a + s_b
            p_c = crowd_probs[col]
            p_l = (s_a / n) if n > 0 else 0.5
            w = min(n / 6, 1.0)
            p_final_a = (w * p_l) + ((1 - w) * p_c)
            
            outcomes = get_series_outcomes(p_final_a, s_a, s_b)
            
            possible_pts_match = []
            match_ev = 0
            for (f_a, f_b), prob in outcomes.items():
                pts = 0
                f_winner = t_a if f_a == 4 else t_b
                if pred['winner'] == f_winner:
                    pts += 1
                    if pred['total'] == (f_a + f_b): pts += 2
                match_ev += pts * prob
                if prob > 0: possible_pts_match.append(pts)
            
            if s_a == 4 or s_b == 4:
                final = 0
                win = t_a if s_a == 4 else t_b
                if pred['winner'] == win:
                    final += 1
                    if pred['total'] == (s_a + s_b): final += 2
                real_pts += final; ev_pts += final; max_pts += final
            else:
                ev_pts += match_ev
                max_pts += max(possible_pts_match) if possible_pts_match else 0

        user_results.append({
            "Email": user[email_col], 
            "Name": user[name_col], 
            "Real": int(real_pts), 
            "EV": float(ev_pts), 
            "Max": int(max_pts)
        })

    leaderboard = pd.DataFrame(user_results)
    
    # 3. Handle Tiebreaks
    if not leaderboard.empty:
        if not playin_df.empty:
            # Flexible merge on PlayIn sheet too
            pi_email_col = next((c for c in playin_df.columns if 'correo' in c or 'Email' in c), playin_df.columns[0])
            pi_score_col = next((c for c in playin_df.columns if 'Score' in c or 'Puntos' in c), playin_df.columns[1])
            
            playin_clean = playin_df[[pi_email_col, pi_score_col]].rename(columns={pi_email_col: 'Email', pi_score_col: 'PlayIn'})
            leaderboard = leaderboard.merge(playin_clean, on='Email', how='left').fillna(0)
        else:
            leaderboard['PlayIn'] = 0
            
        leaderboard['PlayIn'] = leaderboard['PlayIn'].astype(int)
        leaderboard = leaderboard.sort_values(by=["Real", "EV", "PlayIn"], ascending=False).reset_index(drop=True)
    
    return leaderboard
