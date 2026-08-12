import json
import csv
import os
import io
import logging
import datetime
from google import genai
from google.genai import types

from scripts.intervals_utils import AzureBlobManager, BLOB_CSV_PATH, BLOB_WORKOUTS_PREFIX
from push_workouts import IntervalsUploader

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class IntervalsSentinel:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Falta la credencial GEMINI_API_KEY en el entorno.")
        self.client = genai.Client(api_key=self.api_key)
        self.blob_manager = AzureBlobManager()

    def evaluar_fatiga(self):
        contenido_csv = self.blob_manager.leer_texto(BLOB_CSV_PATH)
        if not contenido_csv:
            logging.warning(f"[Sentinel] CSV de contexto no encontrado en Azure ({BLOB_CSV_PATH}).")
            return 0, "No hay contexto."

        f = io.StringIO(contenido_csv)
        reader = csv.DictReader(f)
        filas = list(reader)

        if not filas:
            return 0, "CSV vacío."

        ultima_fila = filas[-1]
        try:
            hrv_anoche = float(ultima_fila.get("HRV", 0))
        except ValueError:
            hrv_anoche = 0

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

    def mutar_entrenamiento(self, json_original_str, nivel, motivo):
        logging.info(f"[Sentinel] Inyectando mutación Nivel {nivel}...")
        try:
            workout_data = json.loads(json_original_str)
        except json.JSONDecodeError:
            return None

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
            return

        blobs = self.blob_manager.listar_archivos(BLOB_WORKOUTS_PREFIX)
        blobs_hoy = [b for b in blobs if hoy in b]

        if not blobs_hoy:
            logging.info(f"[Sentinel] No se encontraron archivos JSON para hoy ({hoy}) en Azure. Nada que ajustar.")
            return

        mutaciones_exitosas = 0
        for blob_name in blobs_hoy:
            contenido = self.blob_manager.leer_texto(blob_name)
            if not contenido:
                continue

            try:
                data = json.loads(contenido)
                if "[AJUSTADO TIER" in data.get("name", "").upper():
                    logging.info(f"[Sentinel] {blob_name} ya fue ajustado algorítmicamente. Omitiendo.")
                    continue
            except json.JSONDecodeError:
                continue

            json_mutado = self.mutar_entrenamiento(contenido, nivel, motivo)
            if json_mutado:
                nuevo_contenido = json.dumps(json_mutado, indent=4, ensure_ascii=False)
                if self.blob_manager.guardar_texto(blob_name, nuevo_contenido):
                    logging.info(f"[Éxito] JSON reescrito matemáticamente en Azure con mitigación Nivel {nivel}.")
                    mutaciones_exitosas += 1

        if mutaciones_exitosas > 0:
            logging.info("[Sentinel] Disparando el Uploader para inyectar los cambios desde Azure a Intervals.icu...")
            try:
                uploader = IntervalsUploader()
                uploader.sincronizar()
            except Exception as e:
                logging.error(f"[Error] Fallo al ejecutar el Uploader interno: {e}")

if __name__ == "__main__":
    sentinel = IntervalsSentinel()
    sentinel.ejecutar()
