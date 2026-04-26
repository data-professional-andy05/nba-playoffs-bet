import pandas as pd
import numpy as np

def parse_pred(pred_str):
    """Parses 'Pistons 4-1 Magic' into dict"""
    if not pred_str or pd.isna(pred_str) or 'vs' in pred_str:
        return None
    try:
        parts = pred_str.split(" ")
        winner = parts[0]
        score = parts[1].split("-")
        g1, g2 = int(score[0]), int(score[1])
        return {"winner": winner, "total": g1 + g2}
    except:
        return None

def get_series_outcomes(p_a, s_a, s_b):
    """Calculates probability of all paths to 4 wins given single-game prob p_a"""
    memo = {}
    def find_path(curr_a, curr_b):
        if curr_a == 4 or curr_b == 4:
            return {(curr_a, curr_b): 1.0}
        state = (curr_a, curr_b)
        if state in memo: return memo[state]
        res = {}
        # Path 1: Team A wins next game
        for (f_a, f_b), prob in find_path(curr_a + 1, curr_b).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * p_a
        # Path 2: Team B wins next game
        for (f_a, f_b), prob in find_path(curr_a, curr_b + 1).items():
            res[(f_a, f_b)] = res.get((f_a, f_b), 0) + prob * (1 - p_a)
        memo[state] = res
        return res
    return find_path(s_a, s_b)

def run_analytics(responses_df, status_df, playin_df):
    series_cols = [c for c in responses_df.columns if " vs " in c]
    status_dict = status_df.set_index('Series_ID').to_dict('index')
    
    # 1. Consensus Probabilities (The Crowd)
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

    # 2. Individual Calculations
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
