import os
import csv
import requests
from intervals_utils import IntervalsClient, CSV_PATH

class IntervalsContextGenerator:
    def __init__(self):
        self.client = IntervalsClient()

    def _convertir_ms_a_ritmo(self, velocidad_ms, distancia_referencia):
        # Convierte metros por segundo a formato MM:SS según la distancia base
        if not velocidad_ms or velocidad_ms <= 0:
            return "0:00"
        segundos_totales = distancia_referencia / velocidad_ms
        minutos = int(segundos_totales // 60)
        segundos = int(segundos_totales % 60)
        return f"{minutos}:{segundos:02d}"

    def obtener_umbrales(self):
        url = f"{self.client.base_url}/athlete/{self.client.athlete_id}"
        response = requests.get(url, auth=self.client._get_auth(), timeout=30)
        response.raise_for_status()
        athlete_data = response.json()
        
        # Valores de contingencia extrema
        umbrales = {"FTP_Ride": 211, "CSS_Swim": "1:40", "Pace_Run": "5:19"}
        
        for sport in athlete_data.get("sportSettings", []):
            sport_id = str(sport.get("id", "")).lower()
            
            if sport_id == "ride":
                umbrales["FTP_Ride"] = sport.get("ftp") or 211
            elif sport_id == "swim":
                velocidad_ms = sport.get("thresholdSpeed")
                if velocidad_ms:
                    # Natación: Ritmo por cada 100 metros
                    umbrales["CSS_Swim"] = self._convertir_ms_a_ritmo(velocidad_ms, 100)
            elif sport_id == "run":
                velocidad_ms = sport.get("thresholdSpeed")
                if velocidad_ms:
                    # Trote: Ritmo por cada 1000 metros (1 km)
                    umbrales["Pace_Run"] = self._convertir_ms_a_ritmo(velocidad_ms, 1000)

        return umbrales

    def generar_csv(self, output_path=CSV_PATH):
        wellness_data = self.client.get_wellness()
        umbrales = self.obtener_umbrales()
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        campos = [
            "Fecha", "CTL", "ATL", "TSB", "HRV", "HR_Rest", 
            "Sleep_Secs", "Sleep_Score", "FTP_Ride", "CSS_Swim", "Pace_Run"
        ]
        
        with open(output_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            
            for item in wellness_data[-14:]:
                ctl = item.get("ctl") or 0
                atl = item.get("atl") or 0
                writer.writerow({
                    "Fecha": item.get("id"),
                    "CTL": round(ctl, 2),
                    "ATL": round(atl, 2),
                    "TSB": round(ctl - atl, 2),
                    "HRV": item.get("hrv", ""),
                    "HR_Rest": item.get("restingHR", ""),
                    "Sleep_Secs": item.get("sleepSecs", ""),
                    "Sleep_Score": item.get("sleepScore", ""),
                    "FTP_Ride": umbrales["FTP_Ride"],
                    "CSS_Swim": umbrales["CSS_Swim"],
                    "Pace_Run": umbrales["Pace_Run"]
                })
        print(f"[Contexto] CSV generado exitosamente en {output_path}")

if __name__ == "__main__":
    try:
        generador = IntervalsContextGenerator()
        generador.generar_csv()
    except Exception as e:
        print(f"Error al generar contexto: {e}")
