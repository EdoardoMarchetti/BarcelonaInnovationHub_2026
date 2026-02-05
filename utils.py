def build_pro_tactical_phases(events_df):
    """
    Identifica secuencias de posesión (fases tácticas) a partir de eventos.
    
    Args:
        events_df: DataFrame con eventos del partido
        
    Returns:
        DataFrame con fases tácticas identificadas
    """
    # Trabajar sobre una copia para no alterar el original
    df = events_df.copy()
    
    # ---------------------------------------------------------
    # 1. LÓGICA DE POSESIÓN (Algoritmo de Dueño)
    # ---------------------------------------------------------
    possession_owners = []
    # Inicializar con el primer equipo que hace algo
    current_owner = df.iloc[0]['Team']
    
    # Eventos que NO cambian la posesión (Interrupciones)
    interruptions = ['FAULT RECEIVED', 'CARD', 'BALL OUT', 'CHALLENGE', 'RECOVERY']
    
    for idx, row in df.iterrows():
        evt_type = row['Type']
        evt_sub = str(row['Subtype'])
        evt_team = row['Team']
        
        # Un regate ganado CONFIRMA la posesión
        if evt_type == 'DRIBBLE' and 'WON' in evt_sub:
            current_owner = evt_team
        # Balón parado INICIA posesión
        elif evt_type == 'SET PIECE':
            current_owner = evt_team
        # Acciones activas CONFIRMAN posesión
        elif evt_type in ['PASS', 'SHOT', 'TOQUE']:
            current_owner = evt_team
        # Si es interrupción, mantenemos el dueño anterior
        elif evt_type in interruptions:
            pass 
        
        possession_owners.append(current_owner)
    
    df['Smart_Owner'] = possession_owners
    
    # Detectar CAMBIO DE FASE:
    # 1. Cambia el equipo dueño.
    # 2. Ocurre un Balón Parado (Set Piece) -> Reinicia jugada.
    df['New_Phase'] = (df['Smart_Owner'] != df['Smart_Owner'].shift()) | (df['Type'] == 'SET PIECE')
    df['Phase_ID'] = df['New_Phase'].cumsum()
    
    # ---------------------------------------------------------
    # 2. AGREGACIÓN (Micro-Ciclos)
    # ---------------------------------------------------------
    # Agrupamos los eventos por Phase_ID para sacar métricas de la jugada completa
    phases = df.groupby('Phase_ID').agg(
        Team=('Smart_Owner', 'first'),
        Period=('Period', 'first'),
        Start_Time=('Start Time [s]', 'min'),
        Duration=('Start Time [s]', lambda x: x.max() - x.min()),
        Event_Count=('Type', 'count'),
        # IMPORTANTE: Usamos nombres con guion bajo para estandarizar
        Start_Frame=('Start Frame', 'min'), 
        End_Frame=('End Frame', 'max'),     
        Start_X=('Start X', 'first'), 
        End_X=('End X', 'last'),    
        Events_List=('Type', list),
        Subtypes_List=('Subtype', list),
        Events_Ids = ('Type', lambda x: list(x.index)),
        Start_Type=('Type', 'first'),
        Start_Subtype=('Subtype', 'first')
    ).reset_index()
    
    # ---------------------------------------------------------
    # 3. ENRIQUECIMIENTO TÁCTICO (Zonas y Resultado)
    # ---------------------------------------------------------
    
    # Función de Zona (Normalizada 0-1)
    def get_zone(x_coord, period, team):
        # Lógica Metrica: Home ataca a 1 en P1, a 0 en P2
        attack_dir = 1 
        if (team == 'Home' and period == 2) or (team == 'Away' and period == 1):
            attack_dir = -1 
            
        # Normalizar X relativo a "Mi Portería" (0) -> "Rival" (1)
        rel_x = x_coord if attack_dir == 1 else (1.0 - x_coord)
            
        if rel_x < 0.35: return "Iniciación"
        if rel_x < 0.65: return "Creación"
        return "Finalización"

    # Aplicar Zonas
    phases['Start_Zone'] = phases.apply(lambda r: get_zone(r['Start_X'], r['Period'], r['Team']), axis=1)
    phases['End_Zone'] = phases.apply(lambda r: get_zone(r['End_X'], r['Period'], r['Team']), axis=1)
    
    # Definir Contexto (Cómo empezó)
    def define_context(row):
        if row['Start_Type'] == 'SET PIECE': return 'ABP'
        if 'RECOVERY' in row['Events_List']: return 'Recuperación'
        return 'Juego Abierto'
    phases['Context'] = phases.apply(define_context, axis=1)
    
    # Definir Resultado (Outcome)
    def define_outcome(row):
        evs = row['Events_List']
        subs = [str(x) for x in row['Subtypes_List']]
        
        if 'SHOT' in evs:
            if any('GOAL' in s for s in subs): return 'GOL'
            return 'Tiro'
        if 'BALL LOST' in evs: return 'Pérdida'
        if 'BALL OUT' in evs: return 'Fuera'
        return 'Posesión'

    phases['Outcome'] = phases.apply(define_outcome, axis=1)
    
    # Filtrar jugadas "basura" (menos de 1 segundo)
    return phases[phases['Duration'] > 1.0].copy()


def get_events_by_possession_id(phases_df, phase_id, events_df):
    """
    Recupera los eventos de una secuencia de posesión específica.
    
    Args:
        phases_df: DataFrame con fases tácticas (pro_phases)
        phase_id: ID de la fase a recuperar
        events_df: DataFrame con eventos del partido
        
    Returns:
        DataFrame con eventos de la fase, o None si no se encuentra
    """
    # Recupera la fila de la fase correspondiente
    phase_row = phases_df.loc[phases_df['Phase_ID'] == phase_id]
    if phase_row.empty:
        return None

    # Extrae los valores de Team y Events_Ids
    possession_team = phase_row.iloc[0]['Team']
    events_ids_list = phase_row.iloc[0]['Events_Ids']

    # events_ids_list dovrebbe essere una lista di indici o ID
    if not isinstance(events_ids_list, list):
        raise ValueError("Il campo 'Events_Ids' non contiene una lista.")

    # Devuelve las filas del DataFrame correspondientes a los eventos de la fase
    possession_events = events_df.loc[events_ids_list].copy()
    possession_events['Possession_Team'] = possession_team
    return possession_events