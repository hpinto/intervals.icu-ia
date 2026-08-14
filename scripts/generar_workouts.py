import os
import json
import datetime
import logging
from scripts.intervals_utils import AzureBlobManager

class IntervalsWorkoutGenerator:
    def __init__(self):
        self.blob_manager = AzureBlobManager()
        # Rutas actualizadas al nuevo directorio de configuración aislado
        self.macro_file = "config_ia/macrociclo.json"
        self.system_prompt_file = "config_ia/system_prompt.txt"
        self.manifest_file = "config_ia/manifiesto.md"

    def _determinar_fase(self, macro_data):
        hoy = datetime.date.today()
        fase = "CARGA"
        tipo_evento = ""
        
        # 1. Escanear calendario para encontrar la carrera futura más próxima
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
        
        # 2. Evaluar protocolos de Taper según prioridad de la carrera más cercana
        if carrera_proxima:
            prioridad = carrera_proxima.get("prioridad", "C")
            tipo_evento = carrera_proxima.get("tipo", "Evento General")
            
            if prioridad == "A" and dias_minimos <= 14:
                logging.info(f"¡ALERTA! A {dias_minimos} días de carrera PRIORIDAD A ({tipo_evento}). Activando TAPER PROFUNDO.")
                return "TAPER_A", tipo_evento, macro_data
            
            elif prioridad == "B" and dias_minimos <= 5:
                logging.info(f"¡ALERTA! A {dias_minimos} días de carrera PRIORIDAD B ({tipo_evento}). Activando MICRO-TAPER.")
                return "TAPER_B", tipo_evento, macro_data

        # 3. Evaluar Supercompensación normal si no hay carreras inminentes
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
        
        # Sellar el nuevo estado para el próximo lunes
        self.blob_manager.guardar_texto(self.macro_file, json.dumps(nuevo_macro_data, indent=4))
        
        system_prompt = self.blob_manager.leer_texto(self.system_prompt_file)
        manifiesto = self.blob_manager.leer_texto(self.manifest_file)
        
        # Inyección dinámica de directrices estructurales acopladas a la disciplina
        directriz_fase = ""
        if fase == "CARGA":
            directriz_fase = "\n[FASE ESTRATÉGICA: CARGA]\nAplica sobrecarga progresiva respetando las métricas de fatiga. Aumenta volumen o intensidad respecto al bloque anterior.\n"
        elif fase == "DESCARGA":
            directriz_fase = "\n[FASE ESTRATÉGICA: DESCARGA]\nREGLA OBLIGATORIA: Reduce el volumen total de la semana en un 30-40%. Prohibido programar sesiones de VO2Max o umbral sostenido. Prioriza Z1 y Z2.\n"
        elif fase == "TAPER_A":
            directriz_fase = f"\n[FASE ESTRATÉGICA: TAPER PROFUNDO PARA {tipo_evento}]\nREGLA OBLIGATORIA: Reduce el volumen de resistencia drásticamente (50%), pero MANTÉN LA INTENSIDAD. Debes incluir intervalos cortos a ritmo de carrera con foco absoluto en la disciplina {tipo_evento}. Mantén la tensión neuromuscular sin generar fatiga residual.\n"
        elif fase == "TAPER_B":
            directriz_fase = f"\n[FASE ESTRATÉGICA: MICRO-TAPER PARA {tipo_evento}]\nREGLA OBLIGATORIA: Mantén el volumen y estructura normal de lunes a miércoles. Solo a partir del jueves reduce drásticamente el volumen y carga de las sesiones previas al evento. Mantén activaciones de intensidad cortas orientadas biomecánicamente a {tipo_evento}.\n"
            
        prompt_final = f"{system_prompt}\n{directriz_fase}\n{manifiesto}"
        
        # =========================================================================
        # INSERTA AQUÍ TU CÓDIGO EXISTENTE DE LLAMADA A LA API DE GEMINI
        # =========================================================================
        # Utiliza la variable 'prompt_final' como la instrucción de sistema.
        # Al recibir la respuesta JSON, guárdala iterando con self.blob_manager.guardar_texto()
        
        logging.info("[WorkoutGenerator] Ejecución completada. Esperando inyección de motor LLM.")