import pandas as pd
import numpy as np
from math import comb

def parse_pred(pred_str):
    """Returns (WinnerName, TotalGames, GamesA, GamesB)"""
    if pd.isna(pred_str) or 'vs' in pred_str: return None
    parts = pred_str.split(" ")
    winner = parts[0]
    score = parts[1].split("-")
    g1, g2 = int(score[0]), int(score[1])
    # We assume the first number in '4-3' belongs to the winner
    return {"winner": winner, "total": g1 + g2, "high": g1, "low": g2}

def get_series_probability(team_a_prob, curr_a, curr_b):
    """
    Calculates probability of all possible final outcomes (4-0...0-4)
    given current score and probability of Team A winning a single game.
    """
    outcomes = {} # Format: {(winsA, winsB): prob}
    
    def simulate(a, b, p):
        # Recursive or iterative approach to find probability of reaching (4, b) or (a, 4)
        memo = {}
        def p_reach(target_a, target_b, cur_a, cur_b):
            if cur_a == 4 or cur_b == 4:
                return 1.0 if (cur_a == target_a and cur_b == target_b) else 0.0
            state = (cur_a, cur_b)
            if state in memo: return memo[state]
            
            # Probability of reaching target from here
            prob = p * p_reach(target_a, target_b, cur_a + 1, cur_b) + \
                   (1-p) * p_reach(target_a, target_b, cur_a, cur_b + 1)
            memo[state] = prob
            return prob

        results = {}
        for b_final in range(4): results[(4, b_final)] = p_reach(4, b_final, a, b)
        for a_final in range(4): results[(a_final, 4)] = p_reach(a_final, 4, a, b)
        return results

    return simulate(curr_a, curr_b, team_a_prob)

def run_analytics(responses_df, status_df):
    series_cols = [c for c in responses_df.columns if "vs" in c]
    
    # 1. Calculate Crowd Source Probabilities
    # Prob A = Total Predicted Wins for A / Total Predicted Games
    crowd_probs = {}
    for col in series_cols:
        team_a_name = col.split(" vs ")[0]
        total_a_wins = 0
        total_games = 0
        for val in responses_df[col]:
            p = parse_pred(val)
            if p:
                total_games += p['high'] + p['low']
                total_a_wins += p['high'] if p['winner'] == team_a_name else p['low']
        crowd_probs[col] = total_a_wins / total_games if total_games > 0 else 0.5

    # 2. Process Standings
    user_results = []
    status_dict = status_df.set_index('Series_ID').to_dict('index')

    for _, user in responses_df.iterrows():
        real_pts = 0
        ev_pts = 0
        max_pts = 0
        
        for col in series_cols:
            stat = status_dict.get(col)
            pred = parse_pred(user[col])
            if not pred or not stat: continue
            
            # Current Series Math
            n = stat['Score_A'] + stat['Score_B']
            is_finished = stat['Score_A'] == 4 or stat['Score_B'] == 4
            
            # Blend Probabilities
            p_crowd = crowd_probs[col]
            p_live = (stat['Score_A'] / n) if n > 0 else 0.5
            weight_live = min(n / 6, 1.0)
            p_final_a = (weight_live * p_live) + ((1 - weight_live) * p_crowd)
            
            # Get Probabilities for all possible outcomes
            outcomes = get_series_probability(p_final_a, stat['Score_A'], stat['Score_B'])
            
            # Points for this specific user prediction
            team_a_name = col.split(" vs ")[0]
            
            # Logic: If I picked Team A 4-2, what outcomes give me points?
            user_points_map = {} # (winsA, winsB) -> points
            for a in range(5):
                for b in range(5):
                    if a < 4 and b < 4: continue
                    if a == b: continue
                    
                    pts = 0
                    winner = team_a_name if a == 4 else col.split(" vs ")[1]
                    if pred['winner'] == winner:
                        pts += 1
                        if pred['total'] == (a + b):
                            pts += 2
                    user_points_map[(a, b)] = pts

            # Calculate Real, EV, and Max
            if is_finished:
                actual_outcome = (stat['Score_A'], stat['Score_B'])
                pts = user_points_map.get(actual_outcome, 0)
                real_pts += pts
                ev_pts += pts
                max_pts += pts
            else:
                # EV = Sum(Prob_Outcome * Points_If_Outcome)
                series_ev = sum(prob * user_points_map.get(out, 0) for out, prob in outcomes.items())
                ev_pts += series_ev
                
                # Max = If any outcome still possible gives points, take the highest
                possible_pts = [user_points_map.get(out) for out, prob in outcomes.items() if prob > 0]
                max_pts += max(possible_pts) if possible_pts else 0

        user_results.append({
            "Name": user['Nombre'],
            "Real": real_pts,
            "EV": round(ev_pts, 2),
            "Max": max_pts
        })

    return pd.DataFrame(user_results).sort_values(by="EV", ascending=False)
