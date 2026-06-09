import os
from datetime import datetime

def _get_pandas():
    import pandas as pd
    return pd


class ExportManager:
    @staticmethod
    def export_to_excel(data, filepath):
        """
        Exports data to an Excel file with multiple sheets.
        """
        pd = _get_pandas()
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # 1. Summary sheet
            metadata = data.get('metadata', {})
            driver = data.get('driver', {})
            vehicle = data.get('vehicle', {})
            
            summary_data = {
                'Field': [
                    'File', 'Analysis Date', 'Integrity', 
                    'Driver', 'Card No.', 
                    'Vehicle', 'Plate', 'VIN',
                    'Total Distance (KM)', 'Total Driving Hours'
                ],
                'Value': [
                    metadata.get('filename', 'N/A'),
                    metadata.get('parsed_at', datetime.now().strftime("%Y-%m-%d %H:%M")),
                    metadata.get('integrity_check', 'OK'),
                    f"{driver.get('surname', '')} {driver.get('firstname', '')}".strip() or 'N/A',
                    driver.get('card_number', 'N/A'),
                    'N/A',
                    vehicle.get('plate', 'N/A'),
                    vehicle.get('vin', 'N/A'),
                    ExportManager._calculate_total_km(data.get('activities', [])),
                    ExportManager._calculate_total_hours(data.get('daily_summaries', []))
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)

            # 2. Daily Activities sheet
            daily_summaries = data.get('daily_summaries', [])
            if daily_summaries:
                pd.DataFrame(daily_summaries).to_excel(writer, sheet_name='Daily Activities', index=False)

            # 3. Infringements sheet
            infractions = data.get('infractions', [])
            if infractions:
                pd.DataFrame(infractions).to_excel(writer, sheet_name='Infringements', index=False)

            # 4. GPS Positions sheet (if available)
            gps_data = data.get('locations', []) or data.get('gps_positions', [])
            if gps_data:
                pd.DataFrame(gps_data).to_excel(writer, sheet_name='GPS Positions', index=False)

    @staticmethod
    def export_to_csv(data, filepath):
        """
        Exports data to flat CSV format for accounting systems.
        """
        pd = _get_pandas()
        rows = []
        driver_name = f"{data.get('driver', {}).get('surname', '')} {data.get('driver', {}).get('firstname', '')}".strip()
        card_number = data.get('driver', {}).get('card_number', 'N/A')
        plate = data.get('vehicle', {}).get('plate', 'N/A')
        
        for day in data.get('activities', []):
            date = day.get('data', 'N/A')
            events = day.get('eventi', [])
            
            for i in range(len(events)):
                ev = events[i]
                activity_type = ev.get('tipo', 'N/A')
                start_time = ev.get('ora', 'N/A')
                
                # Calculate end time (from next event)
                end_time = "23:59"
                duration = "N/A"
                if i < len(events) - 1:
                    end_time = events[i+1].get('ora', '23:59')
                    try:
                        h1, m1 = map(int, start_time.split(':'))
                        h2, m2 = map(int, end_time.split(':'))
                        diff = (h2 * 60 + m2) - (h1 * 60 + m1)
                        duration = f"{diff} min"
                    except (ValueError, TypeError, AttributeError):
                        pass
                
                rows.append({
                    'Date': date,
                    'Start': start_time,
                    'End': end_time,
                    'Duration': duration,
                    'Activity Type': activity_type,
                    'Driver': driver_name,
                    'Card': card_number,
                    'Vehicle': plate
                })
        
        if rows:
            pd.DataFrame(rows).to_csv(filepath, index=False, sep=';', encoding='utf-8-sig')

    @staticmethod
    def _calculate_total_km(activities):
        total = 0
        for d in activities:
            try:
                total += int(d.get('km', 0))
            except (ValueError, TypeError):
                pass
        return total

    @staticmethod
    def _calculate_total_hours(daily_summaries):
        total_min = 0
        for day in daily_summaries:
            try:
                time_str = day.get('Total Drive', '00:00')
                if ':' not in time_str:
                    time_str = '00:00'
                h, m = map(int, time_str.split(':'))
                total_min += h * 60 + m
            except (ValueError, TypeError): pass
        return f"{total_min // 60}h {total_min % 60}m"
