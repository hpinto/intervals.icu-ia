import os
import json
import datetime
import logging
import google.generativeai as genai
from scripts.intervals_utils import AzureBlobManager

class IntervalsWorkoutGenerator:
    def __init__(self):
        self.blob_manager = AzureBlobManager()
        self.macro_file = "config_ia/macrociclo.json"
        self.system_prompt_file = "config_ia/system_prompt.txt"
        self.manifest_file = "config_ia/manifiesto.md"
        self.csv_file = "workouts_ia/contexto_ia.csv"
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
        
        # Configuracion estricta para forzar respuesta en JSON
        self.generation_config = genai.GenerationConfig(
            response_mime_type="application/json"
        )

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
                logging.error("[WorkoutGenerator] Formato de fecha inválido en calendario_carreras. Use YYYY-MM-DD.")
        
        if carrera_proxima:
            prioridad = carrera_proxima.get("prioridad", "C")
            tipo_evento = carrera_proxima.get("tipo", "Evento General")
            
            if prioridad == "A" and dias_minimos <= 14:
                logging.info(f"¡ALERTA! A {dias_minimos} días de carrera PRIORIDAD A ({tipo_evento}). Activando TAPER PROFUNDO.")
                return "TAPER_A", tipo_evento, macro_data
            
            elif prioridad == "B" and dias_minimos <= 5:
                logging.info(f"¡ALERTA! A {dias_minimos} días de carrera PRIORIDAD B ({tipo_evento}). Activando MICRO-TAPER.")
                return "TAPER_B", tipo_evento, macro_data

        modelo = macro_data.get("modelo", "2x1")
        semana_actual = macro_data.get("semana_actual", 1)
        semanas_carga = int(modelo.split('x')[0]) 
        
        if semana_actual > semanas_carga:
            fase = "DESCARGA"
            macro_data["semana_actual"] = 1 
        else:
            fase = "CARGA"
            macro_data["semana_actual"] = semana_actual + 1 
            
        return fase, tipo_evento, macro_data

    def generar_entrenamientos(self):
        logging.info("[WorkoutGenerator] Iniciando máquina de estados del macrociclo...")
        
        macro_str = self.blob_manager.leer_texto(self.macro_file)
        if not macro_str:
            logging.error(f"[WorkoutGenerator] Archivo {self.macro_file} no encontrado. Abortando.")
            return
            
        macro_data = json.loads(macro_str)
        fase, tipo_evento, nuevo_macro_data = self._determinar_fase(macro_data)
        logging.info(f"[WorkoutGenerator] Fase calculada para la semana entrante: {fase}")
        
        self.blob_manager.guardar_texto(self.macro_file, json.dumps(nuevo_macro_data, indent=4))
        
        system_prompt = self.blob_manager.leer_texto(self.system_prompt_file)
        manifiesto = self.blob_manager.leer_texto(self.manifest_file)
        contexto_csv = self.blob_manager.leer_texto(self.csv_file)
        
        if not contexto_csv:
            logging.error(f"[Error Crítico] No se encontró {self.csv_file}. El motor operaría a ciegas. Abortando.")
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
            
        # Acoplamiento del motor algorítmico, reglas estratégicas y estado biométrico actual
        prompt_final = f"{system_prompt}\n{directriz_fase}\n{manifiesto}\n\n[DATOS BIOMÉTRICOS Y DE RENDIMIENTO ACTUALES]\n{contexto_csv}"
        
        logging.info("[WorkoutGenerator] Contactando a la API de Gemini...")
        
        try:
            model = genai.GenerativeModel('gemini-1.5-pro')
            response = model.generate_content(prompt_final, generation_config=self.generation_config)
            
            if not response.text:
                logging.error("[WorkoutGenerator] La API devolvió una respuesta vacía.")
                return
                
            workouts = json.loads(response.text)
            
            for workout in workouts:
                fecha = workout.get("start_date_local", "").split("T")[0]
                deporte = workout.get("type", "Unknown")
                timestamp = int(datetime.datetime.now().timestamp())
                nombre_archivo = f"workouts_ia/{fecha}_{deporte}_{timestamp}.json"
                
                self.blob_manager.guardar_texto(nombre_archivo, json.dumps(workout, indent=4))
                logging.info(f"[WorkoutGenerator] Guardado en nube: {nombre_archivo}")
                
        except json.JSONDecodeError:
            logging.error("[Error Crítico] El motor no devolvió un JSON válido. Revisa los logs de Gemini.")
        except Exception as e:
            logging.error(f"[Error Crítico] Falla en la ejecución de la IA: {e}")