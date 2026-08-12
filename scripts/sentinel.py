import os
import csv
import json
import subprocess
import sys
import logging
import datetime
from google import genai
from google.genai import types

from intervals_utils import WORKOUTS_DIR, CSV_PATH, UPLOADER_SCRIPT

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class IntervalsSentinel:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Falta la credencial GEMINI_API_KEY en el entorno.")
        self.client = genai.Client(api_key=self.api_key)

    def evaluar_fatiga(self):
        if not os.path.exists(CSV_PATH):
            logging.warning(f"[Sentinel] Archivo de contexto no encontrado en {CSV_PATH}.")
            return 0, "No hay contexto."

        filas = []
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                filas.append(row)

        if not filas:
            return 0, "CSV vacío."

        ultima_fila = filas[-1]
        try:
            # Captura la columna plana 'HRV' generada por el contexto
            hrv_anoche = float(ultima_fila.get("HRV", 0))
        except ValueError:
            hrv_anoche = 0

        # Calcular el promedio de los 7 días inmediatamente anteriores a "anoche"
        hrv_historico = []
        for row in filas[-8:-1]:
            val = row.get("HRV", "")
            if val:
                try:
                    hrv_historico.append(float(val))
                except ValueError:
                    pass
        
        hrv_7d = sum(hrv_historico) / len(hrv_historico) if hrv_historico else 0

        if hrv_7d <= 0 or hrv_anoche <= 0:
            return 0, "Métricas de HRV inválidas o en cero."

        caida_porcentaje = ((hrv_7d - hrv_anoche) / hrv_7d) * 100

        if caida_porcentaje >= 20:
            return 3, f"Fatiga Severa: Caída HRV del {caida_porcentaje:.1f}% (>20%)."
        elif 15 <= caida_porcentaje < 20:
            return 2, f"Fatiga Moderada: Caída HRV del {caida_porcentaje:.1f}% (15-20%)."
        elif 10 <= caida_porcentaje < 15:
            return 1, f"Fatiga Leve: Caída HRV del {caida_porcentaje:.1f}% (10-15%)."
        
        return 0, f"Recuperación óptima. Variación HRV: {caida_porcentaje:.1f}%."

    def obtener_instruccion_nivel(self, nivel, motivo):
        base = f"El atleta presenta {motivo}. REGLAS ESTRICTAS DE MUTACIÓN PARA EL JSON:\n"
        if nivel == 1:
            return base + "- NIVEL 1: PROTECCIÓN DE INTENSIDAD. PROHIBIDO modificar los valores de Pace o Power. RECORTA el tiempo/distancia de los intervalos de trabajo principales en un 25%. Mantén el calentamiento y enfriamiento intactos."
        elif nivel == 2:
            return base + "- NIVEL 2: RECORTE DUAL. Reduce el número de repeticiones del set principal a la mitad. Además, REDUCE los objetivos de intensidad (Pace/Power) al límite inferior de la zona inmediatamente anterior."
        elif nivel == 3:
            return base + "- NIVEL 3: APLANAMIENTO TOTAL. Destruye la estructura actual de intervalos del 'workout_doc'. Reemplázala OBLIGATORIAMENTE por una sesión continua de recuperación de máximo 45 minutos en Z1 o Z2 baja."
        return ""

    def mutar_entrenamiento(self, archivo_json, nivel, motivo):
        logging.info(f"[Sentinel] Inyectando mutación Nivel {nivel} sobre {os.path.basename(archivo_json)}...")
        with open(archivo_json, "r", encoding="utf-8") as f:
            workout_data = json.load(f)

        instruccion_matematica = self.obtener_instruccion_nivel(nivel, motivo)
        prompt = f"""
Eres un motor de periodización deportiva estricto. Se requiere ajustar este entrenamiento de Intervals.icu.
{instruccion_matematica}
- Agrega obligatoriamente la etiqueta [AJUSTADO TIER {nivel}] al inicio del campo "name".
- Devuelve ÚNICAMENTE el JSON validado como un diccionario plano ({{}}), sin arrays ni markdown envolvente.
- Mantén la llave "category" ESTRICTAMENTE como "WORKOUT".

JSON ORIGINAL:
{json.dumps(workout_data, indent=2, ensure_ascii=False)}
"""
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1, 
                    response_mime_type="application/json"
                )
            )
            texto_limpio = response.text.strip()
            return json.loads(texto_limpio)
        except json.JSONDecodeError as e:
            logging.error(f"[Error Crítico] Gemini no devolvió un JSON válido: {e}")
            return None
        except Exception as e:
            logging.error(f"[Error Crítico] Fallo en API Gemini: {e}")
            return None

    def ejecutar(self):
        hoy = datetime.date.today().isoformat()
        nivel, motivo = self.evaluar_fatiga()
        logging.info(f"[Sentinel] Diagnóstico diario: {motivo}")

        if nivel == 0:
            logging.info("[Sentinel] No se requiere mitigación algorítmica hoy. Saliendo.")
            sys.exit(0)

        archivos_hoy = [os.path.join(WORKOUTS_DIR, f) for f in os.listdir(WORKOUTS_DIR) if f.startswith(hoy) and f.endswith(".json")]
        if not archivos_hoy:
            logging.info(f"[Sentinel] No se encontraron archivos JSON para hoy ({hoy}). Nada que ajustar.")
            sys.exit(0)

        mutaciones_exitosas = 0
        for archivo_hoy in archivos_hoy:
            try:
                with open(archivo_hoy, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "[AJUSTADO TIER" in data.get("name", "").upper():
                        logging.info(f"[Sentinel] {os.path.basename(archivo_hoy)} ya fue ajustado algorítmicamente. Omitiendo.")
                        continue
            except json.JSONDecodeError:
                continue

            json_mutado = self.mutar_entrenamiento(archivo_hoy, nivel, motivo)
            if json_mutado:
                with open(archivo_hoy, "w", encoding="utf-8") as f:
                    json.dump(json_mutado, f, indent=4, ensure_ascii=False)
                logging.info(f"[Éxito] JSON reescrito matemáticamente con mitigación Nivel {nivel}.")
                mutaciones_exitosas += 1

        if mutaciones_exitosas > 0 and os.path.exists(UPLOADER_SCRIPT):
            logging.info("[Sentinel] Disparando el Uploader para inyectar los cambios en la nube...")
            subprocess.run([sys.executable, UPLOADER_SCRIPT])

if __name__ == "__main__":
    sentinel = IntervalsSentinel()
    sentinel.ejecutar()
