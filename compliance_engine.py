from datetime import datetime, timedelta

class ComplianceEngine:
    """
    Senior Regulatory Compliance Engine for EU Regulation 561/2006.
    Implements complex logic for split breaks, 24-hour shift cycles, and infraction severity.
    """

    # Severity Constants
    MSI = "MSI"  # Most Serious Infringement
    SI  = "SI"   # Serious Infringement
    MI  = "MI"   # Minor Infringement

    def __init__(self):
        self.infractions = []

    def analyze(self, activities):
        """
        Analyzes activities across multiple days.
        Activities format: list of {"data": "DD/MM/YYYY", "eventi": [{"tipo": "...", "ora": "HH:MM", "durata": min}]}
        Note: The input format is slightly adjusted to ensure durations are handled correctly.
        """
        if not activities:
            return []

        self.infractions = []
        
        # 1. Build a continuous timeline of events
        timeline = self._build_timeline(activities)
        if not timeline:
            return []

        # 2. Analyze Continuous Driving and Split Breaks
        self._check_driving_and_breaks(timeline)

        # 3. Analyze Daily Rest (24h Shift Logic)
        self._check_daily_rest_cycles(timeline)

        # 4. Analyze Weekly Rest, Compensation and Bi-weekly driving limits
        self._check_weekly_compliance(timeline)

        return self.infractions

    def _build_timeline(self, activities):
        """Converts day-based activity objects into a flat list of chronological events."""
        full_timeline = []
        sorted_days = sorted(activities, key=lambda x: datetime.strptime(x["data"], "%d/%m/%Y"))

        for day in sorted_days:
            date_base = datetime.strptime(day["data"], "%d/%m/%Y")
            events = day.get("eventi", [])
            # Sort events by time to ensure we can calculate durations
            sorted_events = sorted(events, key=lambda x: x["ora"])
            
            for i in range(len(sorted_events)):
                ev = sorted_events[i]
                h, m = map(int, ev["ora"].split(":"))
                start_dt = date_base + timedelta(hours=h, minutes=m)
                
                # Calculate duration from next event or end of day
                if i < len(sorted_events) - 1:
                    next_ev = sorted_events[i+1]
                    nh, nm = map(int, next_ev["ora"].split(":"))
                    end_dt = date_base + timedelta(hours=nh, minutes=nm)
                else:
                    # Last event of the day goes until the first event of the NEXT day
                    # or 23:59:59 if it's the last day
                    end_dt = date_base + timedelta(hours=23, minutes=59, seconds=59)
                    
                    # Look ahead to see if there's a next day to get a more precise end time
                    for next_day in sorted_days:
                        ndate = datetime.strptime(next_day["data"], "%d/%m/%Y")
                        if ndate == date_base + timedelta(days=1):
                            nevents = sorted(next_day.get("eventi", []), key=lambda x: x["ora"])
                            if nevents:
                                fnh, fnm = map(int, nevents[0]["ora"].split(":"))
                                end_dt = ndate + timedelta(hours=fnh, minutes=fnm)
                            break
                
                durata = int((end_dt - start_dt).total_seconds() / 60)
                if durata < 0: continue # Should not happen with sorted events
                
                full_timeline.append({
                    "start": start_dt,
                    "end": end_dt,
                    "tipo": ev["tipo"],
                    "durata": durata
                })
        
        # Secondary safety sort and merge consecutive identical activities
        full_timeline.sort(key=lambda x: x["start"])
        return self._merge_timeline(full_timeline)

    def _merge_timeline(self, timeline):
        """Merges consecutive events of the same type across midnight or within the same day."""
        if not timeline: return []
        merged = []
        current = timeline[0].copy()
        
        for i in range(1, len(timeline)):
            next_ev = timeline[i]
            # If same type and contiguous (or very close), merge
            if next_ev["tipo"] == current["tipo"] and (next_ev["start"] - current["end"]).total_seconds() <= 60:
                current["end"] = next_ev["end"]
                current["durata"] = int((current["end"] - current["start"]).total_seconds() / 60)
            else:
                merged.append(current)
                current = next_ev.copy()
        merged.append(current)
        return merged

    def _check_driving_and_breaks(self, timeline):
        """
        Objective 2: Implementa la logica della 'Pausa Frazionata'.
        Rule: 4.5h driving -> 45m break. 
        Split: 15m (min) followed by 30m (min).
        """
        driving_accumulator = 0
        has_15m_part = False

        for ev in timeline:
            tipo = ev["tipo"]
            durata = ev["durata"]

            if tipo == "GUIDA":
                driving_accumulator += durata
                if driving_accumulator > 270:
                    # We have an infraction
                    excess = driving_accumulator - 270
                    severity = self._get_driving_severity(excess)
                    self.infractions.append({
                        "data": ev["start"].strftime("%d/%m/%Y"),
                        "tipo": "ECCESSO_GUIDA_CONTINUA",
                        "severita": severity,
                        "descrizione": f"Guida continua di {driving_accumulator} min supera il limite di 4.5h."
                    })
                    # Reset accumulator after infraction to catch the next stretch
                    driving_accumulator = 0
                    has_15m_part = False

            elif tipo in ["RIPOSO", "DISPONIBILITÀ"]:
                # Logic for Split Break
                if durata >= 45:
                    driving_accumulator = 0
                    has_15m_part = False
                elif not has_15m_part and durata >= 15:
                    has_15m_part = True
                    # Driving accumulator is NOT reset yet
                elif has_15m_part and durata >= 30:
                    driving_accumulator = 0
                    has_15m_part = False
                # If it's a small break < 15, it does nothing to the accumulator

            else: # LAVORO
                # Work doesn't reset driving, but it counts towards the shift (handled in daily rest)
                pass

    def _check_daily_rest_cycles(self, timeline):
        """
        Objective 3: Implementa il calcolo del 'Turno di 24 ore'.
        Rule: Within 24h from the start of activities, a rest of 11h (or 9h reduced) must be completed.
        """
        if not timeline: return

        # Identify the start of the first shift
        # A shift starts after a significant rest (> 9h)
        idx = 0
        n = len(timeline)
        
        while idx < n:
            # Start of a shift is the first non-rest activity
            shift_start_ev = None
            for i in range(idx, n):
                if timeline[i]["tipo"] != "RIPOSO":
                    shift_start_ev = timeline[i]
                    idx = i
                    break
            
            if not shift_start_ev: break
            
            shift_limit = shift_start_ev["start"] + timedelta(hours=24)
            
            # Look for the longest rest period that FINISHES within this 24h window
            # and starts after the activities began.
            max_rest_in_window = 0
            found_rest_end = shift_start_ev["start"]
            
            # Track if we found a valid daily rest
            current_idx = idx
            while current_idx < n and timeline[current_idx]["start"] < shift_limit:
                ev = timeline[current_idx]
                if ev["tipo"] == "RIPOSO":
                    # Rest must be finished within the 24h window to count
                    # If it overflows, only the part within 24h counts? 
                    # Actually, the requirement is "completed within 24h".
                    if ev["end"] <= shift_limit:
                        max_rest_in_window = max(max_rest_in_window, ev["durata"])
                    else:
                        # Part of rest within window
                        minutes_within = (shift_limit - ev["start"]).total_seconds() / 60
                        if minutes_within > 0:
                            max_rest_in_window = max(max_rest_in_window, minutes_within)
                
                found_rest_end = ev["end"]
                current_idx += 1

            # Determine infraction
            if max_rest_in_window < 540: # Less than 9h (minimum reduced rest)
                shortfall = 540 - max_rest_in_window
                severity = self._get_rest_severity(shortfall)
                self.infractions.append({
                    "data": shift_start_ev["start"].strftime("%d/%m/%Y"),
                    "tipo": "RIPOSO_GIORNALIERO_INSUFFICIENTE",
                    "severita": severity,
                    "descrizione": f"Entro il turno di 24h (inizio {shift_start_ev['start'].strftime('%H:%M')}), il riposo massimo completato è di {int(max_rest_in_window)} min (minimo 9h)."
                })
            
            # Advance to the next shift: find the next activity after a rest > 9h
            # This is a simplification: usually the next shift starts after the daily rest.
            found_next_shift = False
            for i in range(current_idx - 1, n):
                if timeline[i]["tipo"] == "RIPOSO" and timeline[i]["durata"] >= 540:
                    idx = i + 1
                    found_next_shift = True
                    break
            
            if not found_next_shift:
                break # No more shifts found

    def _get_driving_severity(self, excess_min):
        """Objective 4: Aggiungi la severità dell'infrazione."""
        if excess_min <= 30: return self.MI
        if excess_min <= 90: return self.SI
        return self.MSI

    def _get_rest_severity(self, shortfall_min):
        """Objective 4: Aggiungi la severità dell'infrazione."""
        if shortfall_min <= 60: return self.MI
        if shortfall_min <= 120: return self.SI
        return self.MSI

    def _check_weekly_compliance(self, timeline):
        """
        Implementation of Weekly Rest (UE 561/2006).
        1. Max 6 periods of 24h between weekly rests.
        2. Weekly rest: 45h (regular) or 24h (reduced).
        3. Compensation for reduced rest: must be taken before the end of the 3rd week.
        4. Bi-weekly driving limit: 90h.
        """
        if not timeline: return

        # Constants in minutes
        WEEKLY_REGULAR = 45 * 60
        WEEKLY_REDUCED = 24 * 60
        BIWEEKLY_DRIVING_LIMIT = 90 * 60

        weekly_rests = [] # List of {"start": dt, "end": dt, "duration": min, "is_reduced": bool, "deadline": dt, "to_compensate": min}
        
        # Identify all rests longer than 24h
        for ev in timeline:
            if ev["tipo"] == "RIPOSO" and ev["durata"] >= WEEKLY_REDUCED:
                # To distinguish between a Daily Rest and Weekly Rest:
                # This is simplified. In reality, a rest is weekly if it occurs after max 6 days.
                is_reduced = ev["durata"] < WEEKLY_REGULAR
                to_compensate = WEEKLY_REGULAR - ev["durata"] if is_reduced else 0
                
                # Deadline for compensation: end of the third week following the week in question.
                # Find the Monday of the week containing the rest.
                monday_of_week = ev["start"] - timedelta(days=ev["start"].weekday())
                monday_of_week = monday_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
                deadline = monday_of_week + timedelta(weeks=4) # Start of 4th week = end of 3rd week

                weekly_rests.append({
                    "start": ev["start"],
                    "end": ev["end"],
                    "duration": ev["durata"],
                    "is_reduced": is_reduced,
                    "to_compensate": to_compensate,
                    "deadline": deadline,
                    "compensated_in": None
                })

        # Check: Max 6 days (144h) between weekly rests
        # The period begins at the end of the previous weekly rest and ends at the start of the next.
        for i in range(len(weekly_rests)):
            current_rest = weekly_rests[i]
            
            # Start of working period: end of previous rest or start of timeline
            period_start = timeline[0]["start"] if i == 0 else weekly_rests[i-1]["end"]
            period_end = current_rest["start"]
            
            duration_hours = (period_end - period_start).total_seconds() / 3600
            if duration_hours > 144: # 6 * 24h
                self.infractions.append({
                    "data": period_end.strftime("%d/%m/%Y"),
                    "tipo": "SUPERAMENTO_6_PERIODI_24H",
                    "severita": self.SI,
                    "descrizione": f"Intervallo tra riposi settimanali di {int(duration_hours)} ore supera il limite di 144 ore (6 giorni)."
                })

        # Check: Compensation for reduced rest
        for rest in weekly_rests:
            if rest["is_reduced"]:
                compensation_needed = rest["to_compensate"]
                found_compensation = False
                
                # Look for a rest period that can cover the compensation before the deadline
                for ev in timeline:
                    # Compensation must be taken "en bloc" attached to another rest of at least 9h
                    if ev["tipo"] == "RIPOSO" and ev["start"] > rest["end"] and ev["start"] < rest["deadline"]:
                        # Check if this rest is a "candidate" (not the same rest)
                        if ev["start"] == rest["start"]: continue
                        
                        # Calculate if this rest has "extra" time beyond its minimum requirement
                        # If it's a daily rest, minimum is 9h. If it's weekly, 24h/45h.
                        # For simplicity: if rest duration > (9h + compensation_needed), we consider it compensated.
                        if ev["durata"] >= (9 * 60 + compensation_needed):
                             found_compensation = True
                             rest["compensated_in"] = ev["start"]
                             break
                
                if not found_compensation:
                    # Only add if current time is past deadline or we are analyzing a full set of data
                    # (Here we assume the timeline covers the necessary period)
                    self.infractions.append({
                        "data": rest["start"].strftime("%d/%m/%Y"),
                        "tipo": "MANCATA_COMPENSAZIONE_SETTIMANALE",
                        "severita": self.SI,
                        "descrizione": f"Riposo ridotto di {int(rest['duration']/60)}h del {rest['start'].strftime('%d/%m')} non compensato entro il {rest['deadline'].strftime('%d/%m/%Y')}."
                    })

        # Check: Bi-weekly driving limit (90h)
        # Calculate driving for each fixed week (Mon-Sun 00:00 to 24:00)
        driving_by_week = {} 
        for ev in timeline:
            if ev["tipo"] == "GUIDA":
                # A week starts Monday 00:00
                monday = ev["start"] - timedelta(days=ev["start"].weekday())
                monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
                driving_by_week[monday] = driving_by_week.get(monday, 0) + ev["durata"]
        
        weeks = sorted(driving_by_week.keys())
        for i in range(len(weeks)):
            w1 = weeks[i]
            # Single week limit (not requested but good practice) - 56h
            if driving_by_week[w1] > 56 * 60:
                 self.infractions.append({
                    "data": w1.strftime("%d/%m/%Y"),
                    "tipo": "ECCESSO_GUIDA_SETTIMANALE",
                    "severita": self.SI,
                    "descrizione": f"Guida settimanale di {driving_by_week[w1]/60:.1f}h supera il limite di 56h."
                })
            
            # Bi-weekly check
            if i < len(weeks) - 1:
                w2 = weeks[i+1]
                if (w2 - w1).days == 7:
                    total_biweekly = driving_by_week[w1] + driving_by_week[w2]
                    if total_biweekly > BIWEEKLY_DRIVING_LIMIT:
                        self.infractions.append({
                            "data": w2.strftime("%d/%m/%Y"),
                            "tipo": "ECCESSO_GUIDA_BISETTIMANALE",
                            "severita": self.SI,
                            "descrizione": f"Guida bisettimanale di {total_biweekly/60:.1f}h supera il limite di 90h."
                        })

    def get_report(self):
        return self.infractions

    def get_daily_summary(self, activities):
        """
        Generates daily summaries for the GUI.
        Returns a list of dictionaries with totals for driving, work, rest and infraction count.
        """
        if not activities:
            return []

        # We need the analyzed timeline to attribute infractions to specific days
        # and to calculate totals based on the processed (merged) events.
        timeline = self._build_timeline(activities)
        infractions = self.analyze(activities)

        daily_data = {}

        # Initialize daily_data with all dates present in activities to ensure we don't skip empty days
        for day in activities:
            date_str = day["data"]
            if date_str not in daily_data:
                daily_data[date_str] = {
                    "guida": 0,
                    "lavoro": 0,
                    "riposo": 0,
                    "infrazioni": 0
                }

        # Aggregate durations from the timeline
        # Timeline events can span across multiple days
        for ev in timeline:
            start_dt = ev["start"]
            end_dt = ev["end"]
            tipo = ev["tipo"]
            
            curr_dt = start_dt
            while curr_dt < end_dt:
                date_str = curr_dt.strftime("%d/%m/%Y")
                
                # Calculate end of current day or end of activity
                next_day_start = (curr_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                limit = min(end_dt, next_day_start)
                
                duration_in_day = int((limit - curr_dt).total_seconds() / 60)
                
                if date_str not in daily_data:
                    daily_data[date_str] = {"guida": 0, "lavoro": 0, "riposo": 0, "infrazioni": 0}
                
                if tipo == "GUIDA":
                    daily_data[date_str]["guida"] += duration_in_day
                elif tipo == "LAVORO":
                    daily_data[date_str]["lavoro"] += duration_in_day
                elif tipo == "RIPOSO" or tipo == "DISPONIBILITÀ":
                    # Disponibilità is often treated as rest for summary purposes, or can be separate.
                    # Following typical GUI requirements, we group it with rest or keep separate.
                    # Here we treat it as Rest/Other than Work.
                    daily_data[date_str]["riposo"] += duration_in_day
                
                curr_dt = limit

        # Count infractions per day
        for inf in infractions:
            date_str = inf["data"]
            if date_str in daily_data:
                daily_data[date_str]["infrazioni"] += 1

        # Format results
        summary = []
        def format_min(m):
            hours = m // 60
            minutes = m % 60
            return f"{hours:02d}:{minutes:02d}"

        sorted_dates = sorted(daily_data.keys(), key=lambda x: datetime.strptime(x, "%d/%m/%Y"))
        for d_str in sorted_dates:
            data = daily_data[d_str]
            summary.append({
                "Data": d_str,
                "Guida Totale": format_min(data["guida"]),
                "Lavoro Totale": format_min(data["lavoro"]),
                "Riposo Totale": format_min(data["riposo"]),
                "Infrazioni": data["infrazioni"]
            })

        return summary
