import os
import io
import csv
import json
import datetime
import requests

# 1. FORZAR INYECCIÓN DE ENTORNO LOCAL ANTES DE IMPORTAR UTILIDADES
if os.path.exists("local.settings.json"):
    with open("local.settings.json", "r") as f:
        settings = json.load(f)
        for k, v in settings.get("Values", {}).items():
            os.environ[k] = str(v)

# 2. IMPORTACIÓN DE NEGOCIO (ya leerán las credenciales en memoria)
from scripts.intervals_utils import IntervalsClient, AzureBlobManager, BLOB_CSV_PATH

class IntervalsContextGenerator:
    def __init__(self):
        self.client = IntervalsClient()
        self.blob_manager = AzureBlobManager()

    def _convertir_ms_a_ritmo(self, velocidad_ms, distancia_referencia):
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
        
        umbrales = {"FTP_Ride": 211, "CSS_Swim": "1:40", "Pace_Run": "5:19"}
        
        for sport in athlete_data.get("sportSettings", []):
            sport_id = str(sport.get("id", "")).lower()
            
            if sport_id == "ride":
                umbrales["FTP_Ride"] = sport.get("ftp") or 211
            elif sport_id == "swim":
                velocidad_ms = sport.get("thresholdSpeed")
                if velocidad_ms:
                    umbrales["CSS_Swim"] = self._convertir_ms_a_ritmo(velocidad_ms, 100)
            elif sport_id == "run":
                velocidad_ms = sport.get("thresholdSpeed")
                if velocidad_ms:
                    umbrales["Pace_Run"] = self._convertir_ms_a_ritmo(velocidad_ms, 1000)

        return umbrales

    def generar_csv_biometrico(self, wellness_data, umbrales):
        campos = [
            "Fecha", "CTL", "ATL", "TSB", "HRV", "HRV_7d_Avg", "HRV_30d_Avg", 
            "HR_Rest", "Sleep_Secs", "Sleep_Score", "FTP_Ride", "CSS_Swim", "Pace_Run"
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=campos)
        writer.writeheader()
        
        # Calcular medias móviles de HRV antes de filtrar los últimos 14 días
        hrv_historico = []
        for item in wellness_data:
            hrv_val = item.get("hrv")
            if hrv_val:
                hrv_historico.append(hrv_val)
            item["HRV_7d_Avg"] = round(sum(hrv_historico[-7:]) / len(hrv_historico[-7:]), 1) if hrv_historico[-7:] else ""
            item["HRV_30d_Avg"] = round(sum(hrv_historico[-30:]) / len(hrv_historico[-30:]), 1) if hrv_historico[-30:] else ""

        for item in wellness_data[-14:]:
            ctl = item.get("ctl") or 0
            atl = item.get("atl") or 0
            writer.writerow({
                "Fecha": item.get("id"),
                "CTL": round(ctl, 2),
                "ATL": round(atl, 2),
                "TSB": round(ctl - atl, 2),
                "HRV": item.get("hrv", ""),
                "HRV_7d_Avg": item.get("HRV_7d_Avg", ""),
                "HRV_30d_Avg": item.get("HRV_30d_Avg", ""),
                "HR_Rest": item.get("restingHR", ""),
                "Sleep_Secs": item.get("sleepSecs", ""),
                "Sleep_Score": item.get("sleepScore", ""),
                "FTP_Ride": umbrales["FTP_Ride"],
                "CSS_Swim": umbrales["CSS_Swim"],
                "Pace_Run": umbrales["Pace_Run"]
            })
        return output.getvalue().strip()

    def generar_resumen_actividades_previas(self, dias=7):
        hoy = datetime.date.today()
        hace_n_dias = (hoy - datetime.timedelta(days=dias)).isoformat()
        hoy_str = hoy.isoformat()
        
        try:
            actividades = self.client.get_activities(oldest=hace_n_dias, newest=hoy_str)
        except Exception as e:
            return f"Error API Actividades: {e}", ""

        if not actividades:
            return "No se registraron actividades en los últimos 7 días.", ""

        output = io.StringIO()
        campos = ["Fecha", "Deporte", "Nombre", "Duracion_m", "TSS", "Decoupling"]
        writer = csv.DictWriter(output, fieldnames=campos)
        writer.writeheader()

        vistos = set()
        zonas_acumuladas = [0] * 7 # Contenedor para Z1 a Z7 (Intervals a veces reporta hasta 7)

        for act in actividades:
            fecha = act.get("start_date_local", "").split("T")[0]
            tipo = act.get("type", "Otro")
            nombre = act.get("name", "Entrenamiento sin nombre")
            segundos = act.get("moving_time") or act.get("elapsed_time") or 0
            minutos = round(segundos / 60)
            carga = act.get("icu_training_load") or act.get("icu_joules_load") or 0
            decoupling = act.get("icu_decoupling") or act.get("decoupling") or ""
            
            # Acumulador de Zonas
            zonas = act.get("icu_hr_zones") or act.get("icu_power_zones") or []
            for i, tiempo_en_zona in enumerate(zonas):
                if i < len(zonas_acumuladas):
                    zonas_acumuladas[i] += tiempo_en_zona

            firma = f"{fecha}_{tipo}_{minutos}_{carga}"

            if firma not in vistos:
                vistos.add(firma)
                writer.writerow({
                    "Fecha": fecha,
                    "Deporte": tipo,
                    "Nombre": nombre,
                    "Duracion_m": minutos,
                    "TSS": carga,
                    "Decoupling": round(decoupling, 2) if isinstance(decoupling, (int, float)) else decoupling
                })

        # Calcular porcentajes de polarización
        tiempo_total_zonas = sum(zonas_acumuladas)
        resumen_zonas = "[POLARIZACIÓN REAL ÚLTIMOS 7 DÍAS]\nDistribución de Intensidad: "
        if tiempo_total_zonas > 0:
            porcentajes = [round((z / tiempo_total_zonas) * 100, 1) for z in zonas_acumuladas[:5]]
            resumen_zonas += f"Z1: {porcentajes[0]}% | Z2: {porcentajes[1]}% | Z3: {porcentajes[2]}% | Z4: {porcentajes[3]}% | Z5+: {porcentajes[4]}%\n"
        else:
            resumen_zonas += "Datos de zonas cardíacas/potencia insuficientes en los últimos 7 días.\n"

        return output.getvalue().strip(), resumen_zonas

    def generar_csv(self):
        try:
            # Asumimos que get_wellness trae al menos 30 días para que la media móvil funcione
            wellness_data = self.client.get_wellness()
            umbrales = self.obtener_umbrales()
            
            csv_biometria = self.generar_csv_biometrico(wellness_data, umbrales)
            tabla_actividades, resumen_zonas = self.generar_resumen_actividades_previas(dias=7)
            
            contexto_completo = (
                "[BIOMETRÍA Y RECUPERACIÓN (ÚLTIMOS 14 DÍAS)]\n"
                f"{csv_biometria}\n\n"
                "[HISTORIAL DE ESTÍMULOS REALIZADOS (ÚLTIMOS 7 DÍAS)]\n"
                "REGLA DE VARIABILIDAD: Queda PROHIBIDO replicar la misma distribución de intensidades y deportes del microciclo previo. Aplica ondulación de cargas.\n"
                f"{tabla_actividades}\n\n"
                f"{resumen_zonas}"
            )
            
            exito = self.blob_manager.guardar_texto(BLOB_CSV_PATH, contexto_completo)
            
            if exito:
                print(f"[Contexto] Archivo enriquecido inyectado exitosamente en Azure: {BLOB_CSV_PATH}")
            else:
                print("[Error] Falló la escritura del contexto en Azure Blob Storage.")
                
        except Exception as e:
            print(f"[Error Crítico] Falla general en la construcción del contexto: {e}")

if __name__ == "__main__":
    generador = IntervalsContextGenerator()
    generador.generar_csv()