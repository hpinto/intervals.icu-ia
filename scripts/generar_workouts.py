import os
import json
import datetime
import logging

# 0. QUITARLE LA VENDA A LA CONSOLA
logging.basicConfig(level=logging.INFO, format='%(message)s')

# 1. FORZAR INYECCIÓN DE ENTORNO LOCAL ANTES DE IMPORTAR UTILIDADES
if os.path.exists("local.settings.json"):
    with open("local.settings.json", "r") as f:
        settings = json.load(f)
        for k, v in settings.get("Values", {}).items():
            os.environ[k] = str(v)

# 2. AHORA SÍ, IMPORTAR LOS COMPONENTES DE NEGOCIO
from google import genai
from google.genai import types
from scripts.intervals_utils import AzureBlobManager

class IntervalsWorkoutGenerator:
    def __init__(self):
        self.blob_manager = AzureBlobManager()
        self.macro_file = "config_ia/macrociclo.json"
        self.system_prompt_file = "config_ia/system_prompt.txt"
        self.manifest_file = "config_ia/manifiesto.md"
        self.csv_file = "contexto_ia.csv"
        self.lock_file = "workouts_ia/pipeline_estado.lock"
        
        api_key = os.environ.get("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def _determinar_fase(self, macro_data):
        hoy = datetime.date.today()
        fase = "CARGA"
        tipo_evento = ""
        
        carreras = macro_data.get("calendario_carreras", [])
        carrera_proxima = None
        dias_minimos = 9999
        
        for carrera in carreras:
            try:
                fecha_c = datetime.datetime.strptime(carrera["fecha"], "%Y-%m-%d").date()
                dias = (fecha_c - hoy).days
                if 0 <= dias < dias_minimos:
                    dias_minimos = dias
                    carrera_proxima = carrera
            except ValueError:
                logging.error("[Error] Formato de fecha inválido en calendario_carreras. Use YYYY-MM-DD.")
        
        if carrera_proxima:
            prioridad = carrera_proxima.get("prioridad", "C")
            tipo_evento = carrera_proxima.get("tipo", "Evento General")
            
            if prioridad == "A" and dias_minimos <= 14:
                return "TAPER_A", tipo_evento, macro_data
            elif prioridad == "B" and dias_minimos <= 5:
                return "TAPER_B", tipo_evento, macro_data

        # --- EVALUACIÓN BIO-ADAPTATIVA DE FATIGA (NUEVO BLOQUE) ---
        # Verificamos si el TSB acumulado o el estrés exigen una descarga defensiva imprevista
        forzar_descarga_por_fatiga = False
        try:
            contexto_csv = self.blob_manager.leer_texto(self.csv_file)
            if contexto_csv:
                lineas = contexto_csv.strip().split('\n')
                # Buscamos la última línea con datos biométricos válidos
                ultima_linea = [l for l in lineas if l.startswith("2026-")]
                if ultima_linea:
                    partes = ultima_linea[-1].split()
                    # El TSB suele estar en la tercera columna numérica del CSV de rendimiento
                    tsb_actual = float(partes[2])
                    if tsb_actual < -30.0:
                        logging.warning(f"[Alerta Fisiológica] TSB crítico detectado ({tsb_actual}). Forzando fase de DESCARGA por sobrecarga.")
                        forzar_descarga_por_fatiga = True
        except Exception as e:
            logging.error(f"[Error leyendo CSV para fatiga] No se pudo evaluar el TSB: {e}")

        modelo = macro_data.get("modelo", "2x1")
        semana_actual = macro_data.get("semana_actual", 1)
        semanas_carga = int(modelo.split('x')[0])  # 2
        # La semana de descarga es estrictamente la que sigue a las de carga (ej. semana 3)
        semana_descarga = semanas_carga + 1 
        
        if forzar_descarga_por_fatiga or semana_actual >= semana_descarga:
            fase = "DESCARGA"
            macro_data["semana_actual"] = 1  # Resetea a 1 para el siguiente bloque
        else:
            fase = "CARGA"
            macro_data["semana_actual"] = semana_actual + 1  # Avanza de 1 a 2, o de 2 a 3

    def generar_entrenamientos(self):
        logging.info("\n>>> INICIANDO MOTOR DE GENERACIÓN DE WORKOUTS <<<")
        
        # VALIDACIÓN DE IDEMPOTENCIA (LOCK)
        hoy_date = datetime.date.today()
        hoy_str = hoy_date.isoformat()
        
        lock_existente = self.blob_manager.leer_texto(self.lock_file)
        if lock_existente and hoy_str in lock_existente:
            logging.warning(f"[Lock] Ya existe un registro de ejecución para hoy ({hoy_str}). Abortando para evitar duplicidad.")
            return

        macro_str = self.blob_manager.leer_texto(self.macro_file)
        if not macro_str:
            logging.error(f"[Error Crítico] Archivo {self.macro_file} no encontrado en Azure.")
            return
            
        macro_data = json.loads(macro_str)
        fase, tipo_evento, nuevo_macro_data = self._determinar_fase(macro_data)
        logging.info(f"[Fase Estratégica Calculada] {fase}")
        
        self.blob_manager.guardar_texto(self.macro_file, json.dumps(nuevo_macro_data, indent=4))
        
        system_prompt = self.blob_manager.leer_texto(self.system_prompt_file)
        manifiesto = self.blob_manager.leer_texto(self.manifest_file)
        contexto_csv = self.blob_manager.leer_texto(self.csv_file)
        
        if not contexto_csv:
            logging.error(f"[Error Crítico] No se encontró {self.csv_file}. Abortando.")
            return
        
        directriz_fase = ""
        if fase == "CARGA":
            directriz_fase = "\n[FASE ESTRATÉGICA: CARGA]\nAplica sobrecarga progresiva respetando las métricas de fatiga. Aumenta volumen o intensidad respecto al bloque anterior.\n"
        elif fase == "DESCARGA":
            directriz_fase = "\n[FASE ESTRATÉGICA: DESCARGA]\nREGLA OBLIGATORIA: Reduce el volumen total de la semana en un 30-40%. Prohibido programar sesiones de VO2Max o umbral sostenido. Prioriza Z1 y Z2.\n"
        elif fase == "TAPER_A":
            directriz_fase = f"\n[FASE ESTRATÉGICA: TAPER PROFUNDO PARA {tipo_evento}]\nREGLA OBLIGATORIA: Reduce el volumen de resistencia drásticamente (50%), pero MANTÉN LA INTENSIDAD. Debes incluir intervalos cortos a ritmo de carrera con foco absoluto en la disciplina {tipo_evento}. Mantén la tensión neuromuscular sin generar fatiga residual.\n"
        elif fase == "TAPER_B":
            directriz_fase = f"\n[FASE ESTRATÉGICA: MICRO-TAPER PARA {tipo_evento}]\nREGLA OBLIGATORIA: Mantén el volumen y estructura normal de lunes a miércoles. Solo a partir del jueves reduce drásticamente el volumen y carga de las sesiones previas al evento. Mantén activaciones de intensidad cortas orientadas biomecánicamente a {tipo_evento}.\n"
            
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        dia_str = dias_es[hoy_date.weekday()]
        
        dias_para_domingo = 6 - hoy_date.weekday()
        domingo_date = hoy_date + datetime.timedelta(days=dias_para_domingo)
        domingo_str = domingo_date.isoformat()

        anclaje_temporal = (
            f"\n[RELOJ DEL SISTEMA]\n"
            f"CRÍTICO: Hoy es {dia_str}, {hoy_str}. "
            f"Genera los entrenamientos estrictamente para los días restantes de esta semana (desde hoy {hoy_str} hasta el domingo {domingo_str}). "
            f"Asegura que los entrenamientos de mayor volumen y tiradas largas se programen orgánicamente para el fin de semana (sábado y domingo).\n"
        )
        
        prompt_final = f"{system_prompt}{anclaje_temporal}{directriz_fase}\n{manifiesto}\n\n[DATOS BIOMÉTRICOS Y DE RENDIMIENTO ACTUALES]\n{contexto_csv}"
        
        logging.info(f"[Conexión] Solicitando inferencia a Gemini Pro Latest (Prompt de {len(prompt_final)} caracteres)...")
        
        try:
            response = self.client.models.generate_content(
                model='gemini-3.1-pro-preview',
                contents=prompt_final,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            if not response.text:
                logging.error("[Error] Gemini devolvió una respuesta completamente vacía.")
                return
                
            logging.info("[Depuración] Parseando JSON...")
            workouts = json.loads(response.text)
            
            logging.info(f"[Resultado] Gemini generó {len(workouts)} sesiones de entrenamiento.")
            
            if len(workouts) == 0:
                logging.warning("\n[ALERTA] La IA devolvió un array vacío []. El modelo colapsó con las reglas.")
                logging.warning(f"Respuesta cruda del modelo:\n{response.text}")
                return
            
            guardados = 0
            for workout in workouts:
                fecha = workout.get("start_date_local", "").split("T")[0]
                deporte = workout.get("type", "Unknown")
                timestamp = int(datetime.datetime.now().timestamp())
                nombre_archivo = f"workouts_ia/{fecha}_{deporte}_{timestamp}.json"
                
                exito = self.blob_manager.guardar_texto(nombre_archivo, json.dumps(workout, indent=4))
                if exito:
                    logging.info(f"[Upload OK] Subido a Azure -> {nombre_archivo}")
                    guardados += 1
                else:
                    logging.error(f"[Upload FAIL] Falló la subida de {nombre_archivo} a Azure.")
            
            # ESCRITURA DEL CANDADO DE IDEMPOTENCIA TRAS ÉXITO
            self.blob_manager.guardar_texto(self.lock_file, f"Pipeline ejecutado exitosamente el {hoy_str}")
            logging.info(f"[Lock] Archivo de estado {self.lock_file} registrado en Azure.")
                    
            logging.info(f"\n>>> PROCESO FINALIZADO: {guardados}/{len(workouts)} archivos inyectados en la nube. <<<")
                
        except json.JSONDecodeError:
            logging.error("[Error Crítico] Gemini no devolvió un JSON válido. Respuesta cruda:")
            logging.error(response.text)
        except Exception as e:
            logging.error(f"[Error Fatal] Falla en la ejecución de la IA: {e}")

if __name__ == "__main__":
    generador = IntervalsWorkoutGenerator()
    generador.generar_entrenamientos()