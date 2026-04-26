import pandas as pd
import numpy as np

def parse_pred(pred_str):
    if not pred_str or pd.isna(pred_str) or 'vs' in pred_str: return None
    try:
        parts = pred_str.split(" ")
        winner = parts[0]
        score = parts[1].split("-")
        g1, g2 = int(score[0]), int(score[1])
        return {"winner": winner, "total": g1 + g2, "high": g1, "low": g2}
    except:
        return None

def get_series_probability(team_a_prob, curr_a, curr_b):
    memo = {}
    def p_reach(target_a, target_b, cur_a, cur_b, p):
        if cur_a == 4 or cur_b == 4:
            return 1.0 if (cur_a == target_a and cur_b == target_b) else 0.0
        state = (cur_a, cur_b)
        if state in memo: return memo[state]
        prob = p * p_reach(target_a, target_b, cur_a + 1, cur_b, p) + \
               (1-p) * p_reach(target_a, target_b, cur_a, cur_b + 1, p)
        memo[state] = prob
        return prob

    results = {}
    for b_f in range(4): results[(4, b_f)] = p_reach(4, b_f, curr_a, curr_b, team_a_prob)
    for a_f in range(4): results[(a_f, 4)] = p_reach(a_f, 4, curr_a, curr_b, team_a_prob)
    return results

def run_analytics(responses_df, status_df, playin_df):
    series_cols = [c for c in responses_df.columns if "vs" in c]
    status_dict = status_df.set_index('Series_ID').to_dict('index')
    
    # 1. Calculate Crowd Source Probabilities
    crowd_probs = {}
    for col in series_cols:
        team_a_name = col.split(" vs ")[0]
        wins_a, total_g = 0, 0
        for val in responses_df[col]:
            p = parse_pred(val)
            if p:
                total_g += p['total']
                wins_a += p['high'] if p['winner'] == team_a_name else p['low']
        crowd_probs[col] = wins_a / total_g if total_g > 0 else 0.5

    # 2. Process Standings
    user_results = []
    for _, user in responses_df.iterrows():
        real_pts, ev_pts, max_pts = 0, 0, 0
        email = user['Dirección de correo electrónico']
        
        for col in series_cols:
            stat = status_dict.get(col)
            pred = parse_pred(user[col])
            if not pred or not stat: continue
            
            # Logic: Split Series_ID to get team names
            teams = col.split(" vs ")
            team_a, team_b = teams[0], teams[1]
            s_a, s_b = stat['Games_Team_A'], stat['Games_Team_B']
            
            n = s_a + s_b
            is_finished = (s_a == 4 or s_b == 4)
            
            # Probability Blending
            p_crowd = crowd_probs[col]
            p_live = (s_a / n) if n > 0 else 0.5
            w = min(n / 6, 1.0)
            p_final_a = (w * p_live) + ((1 - w) * p_crowd)
            
            outcomes = get_series_probability(p_final_a, s_a, s_b)
            
            # Map Points
            user_points_map = {}
            for a in range(5):
                for b in range(5):
                    if a < 4 and b < 4: continue
                    if a == b: continue
                    pts = 0
                    winner = team_a if a == 4 else team_b
                    if pred['winner'] == winner:
                        pts += 1
                        if pred['total'] == (a + b): pts += 2
                    user_points_map[(a, b)] = pts

            if is_finished:
                p = user_points_map.get((s_a, s_b), 0)
                real_pts += p; ev_pts += p; max_pts += p
            else:
                ev_pts += sum(prob * user_points_map.get(out, 0) for out, prob in outcomes.items())
                possible = [user_points_map.get(out) for out, prob in outcomes.items() if prob > 0]
                max_pts += max(possible) if possible else 0

        user_results.append({"Email": email, "Name": user['Nombre'], "Real": real_pts, "EV": round(ev_pts, 2), "Max": max_pts})

    final_df = pd.DataFrame(user_results)
    
    # 3. Merge Tiebreak (PlayIn Score)
    final_df = final_df.merge(playin_df[['Email', 'Score']], on='Email', how='left').fillna(0)
    final_df = final_df.rename(columns={'Score': 'Tiebreak_PlayIn'})
    
    # 4. Sort: Real Points first, then EV, then Tiebreak
    return final_df.sort_values(by=["Real", "EV", "Tiebreak_PlayIn"], ascending=False).reset_index(drop=True)
