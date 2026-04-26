import pandas as pd
import numpy as np

def parse_pred(pred_str):
    if not pred_str or pd.isna(pred_str) or 'vs' in pred_str: return None
    try:
        parts = pred_str.split(" ")
        winner = parts[0]
        score = parts[1].split("-")
        g1, g2 = int(score[0]), int(score[1])
        return {"winner": winner, "total": g1 + g2}
    except:
        return None

def get_series_outcomes(p_a, s_a, s_b):
    """
    Calculates the probability of every possible final result (4-0...0-4)
    given current score (s_a, s_b) and probability p_a of Team A winning a single game.
    """
    # outcomes[(final_a, final_b)] = prob
    outcomes = {}
    
    # Simple recursive path finding with memoization
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
    series_cols = [c for c in responses_df.columns if "vs" in c]
    status_dict = status_df.set_index('Series_ID').to_dict('index')
    
    # 1. Calculate Crowd Probs (Used to anchor the model)
    crowd_probs = {}
    for col in series_cols:
        t_a = col.split(" vs ")[0]
        wins_a, total_g = 0, 0
        for val in responses_df[col]:
            p = parse_pred(val)
            if p:
                total_g += p['total']
                # If winner is team A, they were predicted to win 4 games
                wins_a += 4 if p['winner'] == t_a else (p['total'] - 4)
        crowd_probs[col] = wins_a / total_g if total_g > 0 else 0.5

    user_results = []
    for _, user in responses_df.iterrows():
        real_pts, ev_pts, max_pts = 0, 0, 0
        
        for col in series_cols:
            stat = status_dict.get(col)
            pred = parse_pred(user[col])
            if not pred or not stat: continue
            
            t_a, t_b = col.split(" vs ")
            s_a, s_b = int(stat['Games_Team_A']), int(stat['Games_Team_B'])
            
            # Probability Blending
            n = s_a + s_b
            p_c = crowd_probs[col]
            p_l = (s_a / n) if n > 0 else 0.5
            w = min(n / 6, 1.0)
            p_final_a = (w * p_l) + ((1 - w) * p_c)
            
            # All possible final outcomes from current score
            outcomes = get_series_outcomes(p_final_a, s_a, s_b)
            
            # Map points for every final outcome
            possible_points_for_this_match = []
            match_ev = 0
            
            for (f_a, f_b), prob in outcomes.items():
                pts = 0
                final_winner = t_a if f_a == 4 else t_b
                if pred['winner'] == final_winner:
                    pts += 1 # Winner point
                    if pred['total'] == (f_a + f_b):
                        pts += 2 # Exact bonus
                
                match_ev += pts * prob
                if prob > 0:
                    possible_points_for_this_match.append(pts)
            
            # Logic: If series is over (someone has 4 wins)
            if s_a == 4 or s_b == 4:
                final_pts = 0
                win = t_a if s_a == 4 else t_b
                if pred['winner'] == win:
                    final_pts += 1
                    if pred['total'] == (s_a + s_b): final_pts += 2
                real_pts += final_pts
                ev_pts += final_pts
                max_pts += final_pts
            else:
                ev_pts += match_ev
                max_pts += max(possible_points_for_this_match) if possible_points_for_this_match else 0

        user_results.append({
            "Email": user['Dirección de correo electrónico'],
            "Name": user['Nombre'],
            "Real": int(real_pts),
            "EV": round(ev_pts, 2),
            "Max": int(max_pts)
        })

    final_df = pd.DataFrame(user_results)
    final_df = final_df.merge(playin_df[['Email', 'Score']], on='Email', how='left').fillna(0)
    final_df = final_df.rename(columns={'Score': 'PlayIn_Tiebreak'})
    
    # Senior DA Sorting: Real -> EV -> PlayIn Tiebreak
    return final_df.sort_values(by=["Real", "EV", "PlayIn_Tiebreak"], ascending=False).reset_index(drop=True)
