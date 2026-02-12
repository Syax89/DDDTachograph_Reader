from datetime import datetime, timedelta

class FinesCalculator:
    """
    Calculates estimated fines for tachograph infractions based on 
    the Italian 'Codice della Strada' (Art. 174).
    """
    
    # Art. 174 penalties (estimates)
    # Note: Fines are often reduced if paid within 5 days.
    # We provide the standard range.
    
    FINES = {
        "ECCESSO_GUIDA_CONTINUA": {
            "MI": (167, 668),
            "SI": (334, 1336),
            "MSI": (445, 1780)
        },
        "RIPOSO_GIORNALIERO_INSUFFICIENTE": {
            "MI": (167, 668),
            "SI": (334, 1336),
            "MSI": (445, 1780)
        },
        "RIPOSO_SETTIMANALE_INSUFFICIENTE": {
            "MI": (167, 668),
            "SI": (334, 1336),
            "MSI": (445, 1780)
        }
    }

    @staticmethod
    def estimate_fine(infraction_type, severity):
        """Returns (min_fine, max_fine) for a given infraction."""
        fine_range = FinesCalculator.FINES.get(infraction_type, {}).get(severity)
        if not fine_range:
            # Default for unknown types or severities
            return (41, 168) 
        return fine_range

    @staticmethod
    def get_total_estimate(infractions):
        """Calculates total min and max estimated fines."""
        total_min = 0
        total_max = 0
        for inf in infractions:
            # Note: handle 'severita' or 'severity' key
            severity = inf.get("severita") or inf.get("severity") or "SI"
            inf_type = inf.get("tipo")
            f_min, f_max = FinesCalculator.estimate_fine(inf_type, severity)
            total_min += f_min
            total_max += f_max
        return total_min, total_max
