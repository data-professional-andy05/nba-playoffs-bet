# Cargar DataFrames
r1 = pd.DataFrame(sh.worksheet("Responses_R1").get_all_records())
r2 = pd.DataFrame(sh.worksheet("Responses_R2").get_all_records())

s1 = pd.DataFrame(sh.worksheet("Series_Status").get_all_records())
s2 = pd.DataFrame(sh.worksheet("Series_Status_2").get_all_records())

p = pd.DataFrame(sh.worksheet("PlayIn_Score").get_all_records())

# Procesar R1
lb_r1 = procesar_datos(r1, s1, p)

# Extraer puntajes de R1 para usarlos como criterio de desempate en R2
r1_scores = None
if not lb_r1.empty:
    r1_scores = lb_r1[['Email', 'Puntos']].rename(columns={'Puntos': 'Pts_R1'})
    
# Procesar R2 usando los puntajes de R1
lb_r2 = procesar_datos(r2, s2, p, r1_scores=r1_scores)

return lb_r1, lb_r2, r1, r2
