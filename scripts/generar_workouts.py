import os
import json
import datetime
import logging

# 0. CONFIGURACIÓN DE CONSOLA
logging.basicConfig(level=logging.INFO, format='%(message)s')

# 1. FORZAR INYECCIÓN DE ENTORNO LOCAL ANTES DE IMPORTAR UTILIDADES
if os.path.exists("local.settings.json"):
    with open("local.settings.json", "r") as f:
        settings = json.load(f)
        for k, v in settings.get("Values", {}).items():
            os.environ[k] = str(v)

# 2. IMPORTACIÓN DE NEGOCIO
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

    def _inferir_mesociclo_dinamico(self, hoy, carreras, mesociclo_previo, forzar_descarga):
        """Infiere el mesociclo por Periodización Inversa y detecta transiciones para programar tests."""
        carreras_validas = []
        for c in carreras:
            try:
                f_c = datetime.datetime.strptime(c["fecha"], "%Y-%m-%d").date()
                carreras_validas.append((f_c, c))
            except (ValueError, KeyError):
                logging.error("[Error] Fecha inválida en calendario_carreras. Use YYYY-MM-DD.")

        carreras_validas.sort(key=lambda x: x[0])

        # 1. DETECTAR FASE DE TRANSICIÓN POST-CARRERA PRIORIDAD A (Últimos 14 días)
        for f_c, c in carreras_validas:
            dias_pasados = (hoy - f_c).days
            if 0 < dias_pasados <= 14 and c.get("prioridad") == "A":
                nom = c.get("nombre", c.get("tipo", "Competencia A"))
                Directriz = (
                    f"\n[MESOCICLO INFERIDO DINÁMICAMENTE: TRANSICION POST-COMPETENCIA ({nom})]\n"
                    f"REGLA OBLIGATORIA: El atleta compitió hace {dias_pasados} días en un evento Prioridad A. "
                    f"Aplica regeneración tisular y parasimpática estricta: volumen reducido al 50%, exclusivamente Z1 y Z2 baja, cero impacto articular intenso y cero series de umbral.\n"
                )
                return "TRANSICION", c, Directriz

        # 2. DETECTAR PRÓXIMA CARRERA INMEDIATA (PARA TAPER A O B) Y PRÓXIMA CARRERA PRIORIDAD A (RECTORA DEL MESOCICLO)
        futuras = [(f_c, c) for f_c, c in carreras_validas if f_c >= hoy]
        if not futuras:
            return "BASE", None, "\n[MESOCICLO INFERIDO: BASE GENERAL]\nSin carreras futuras. Mantén desarrollo aeróbico polarizado.\n"

        f_inmediata, c_inmediata = futuras[0]
        dias_inmediata = (f_inmediata - hoy).days
        taper_inmediata = c_inmediata.get("dias_taper", 7)

        if dias_inmediata <= taper_inmediata:
            estado_taper = "TAPER_A" if c_inmediata.get("prioridad") == "A" else "TAPER_B"
            return estado_taper, c_inmediata, ""

        # Buscar la próxima carrera Prioridad A para anclar la Periodización Inversa
        futuras_a = [(f_c, c) for f_c, c in futuras if c.get("prioridad") == "A"]
        f_rectora, c_rectora = futuras_a[0] if futuras_a else futuras[0]

        dias_restantes_a = (f_rectora - hoy).days
        dias_taper_a = c_rectora.get("dias_taper", 14)
        dias_pre_taper = max(0, dias_restantes_a - dias_taper_a)
        semanas_pre_taper = (dias_pre_taper + 6) // 7

        nom_rectora = c_rectora.get("nombre", "Objetivo Principal")
        tipo_rectora = c_rectora.get("tipo", "General")
        meta_rectora = c_rectora.get("meta", "No especificada")

        if dias_pre_taper <= 28:
            nuevo_meso = "PEAK"
            foco = (
                f"Faltan {semanas_pre_taper} semanas para iniciar el Taper de {nom_rectora} ({tipo_rectora}). "
                f"Foco en especificidad competitiva absoluta hacia la meta ({meta_rectora}), tolerancia al ritmo de carrera y eficiencia metabólica."
            )
        elif dias_pre_taper <= 84:
            nuevo_meso = "BUILD"
            foco = (
                f"Faltan {semanas_pre_taper} semanas para el Taper de {nom_rectora} ({tipo_rectora}). "
                f"Foco en construcción de umbral de lactato (Z3/Z4), resistencia a la fatiga y progresión específica de volumen."
            )
        else:
            nuevo_meso = "BASE"
            foco = (
                f"Faltan {semanas_pre_taper} semanas para el Taper de {nom_rectora} ({tipo_rectora}). "
                f"Foco en base aeróbica extensiva (Z2), capilarización, economía mecánica y acondicionamiento de fuerza estructural."
            )

        bloque_texto = f"\n[MESOCICLO INFERIDO DINÁMICAMENTE: {nuevo_meso} -> {nom_rectora}]\nDIRECTRIZ DEL MESOCICLO: {foco}\n"

        # 3. DETECCIÓN DE TRANSICIÓN DE MESOCICLO PARA DISPARAR SEMANA DE TEST
        if mesociclo_previo and mesociclo_previo != nuevo_meso and nuevo_meso in ["BASE", "BUILD", "PEAK"] and not forzar_descarga:
            es_maraton = "marat" in tipo_rectora.lower() or "42k" in tipo_rectora.lower()
            if es_maraton and nuevo_meso == "PEAK":
                protocolo_test = (
                    "Sustituye la sesión de calidad de carrera a pie (Martes o Miércoles) por un Test de Validación de Umbral: "
                    "Calentamiento 15m Z1/Z2 + 30m contrarreloj sostenido a máximo esfuerzo aeróbico (para actualizar LTHR y Pace umbral) + 10m Z1."
                )
            else:
                protocolo_test = (
                    "Esta semana se estrena el mesociclo. Programa tests de actualización de umbrales en días separados: "
                    "1) En Ciclismo (Martes): Test de FTP (20m máximo esfuerzo sostenido tras calentamiento). "
                    "2) En Natación (Miércoles): Test CSS (0.400KM + 0.200KM máxima velocidad sostenida con descanso completo). "
                    "3) En Carrera (Viernes): Test de 30m contrarreloj para determinar LTHR y Threshold Pace. "
                    "Mantén el resto de la semana estrictamente en Z1/Z2 para asegurar frescura en las mediciones."
                )
            bloque_texto += (
                f"\n[TRANSICIÓN DE MESOCICLO DETECTADA ({mesociclo_previo} -> {nuevo_meso}): SEMANA DE EVALUACIÓN ACTIVADA]\n"
                f"ORDEN OBLIGATORIA DE TEST: {protocolo_test}\n"
            )

        return nuevo_meso, c_rectora, bloque_texto

    def _determinar_fase(self, macro_data):
        hoy = datetime.date.today()
        carreras = macro_data.get("calendario_carreras", [])
        mesociclo_previo = macro_data.get("mesociclo_actual")

        # 1. EVALUACIÓN BIO-ADAPTATIVA DE FATIGA (DEFENSIVA)
        forzar_descarga_por_fatiga = False
        try:
            contexto_csv = self.blob_manager.leer_texto(self.csv_file)
            if contexto_csv:
                lineas = contexto_csv.strip().split('\n')
                ultima_linea = [l for l in lineas if l.startswith("2026-") or l.startswith("2027-")]
                if ultima_linea:
                    partes = ultima_linea[-1].split(',') if ',' in ultima_linea[-1] else ultima_linea[-1].split()
                    tsb_actual = float(partes[3] if ',' in ultima_linea[-1] else partes[2])
                    if tsb_actual < -30.0:
                        logging.warning(f"[Alerta Fisiológica] TSB crítico detectado ({tsb_actual}). Forzando fase de DESCARGA por sobrecarga.")
                        forzar_descarga_por_fatiga = True
        except Exception as e:
            logging.error(f"[Error leyendo CSV para fatiga] No se pudo evaluar el TSB: {e}")

        # 2. INFERENCIA DINÁMICA DE MESOCICLO Y TAPER
        nuevo_meso, carrera_ref, bloque_mesociclo = self._inferir_mesociclo_dinamico(
            hoy, carreras, mesociclo_previo, forzar_descarga_por_fatiga
        )

        nombre_evento = carrera_ref.get("nombre", "Competencia") if carrera_ref else "Temporada"
        tipo_evento = carrera_ref.get("tipo", "General") if carrera_ref else "General"
        meta_evento = carrera_ref.get("meta", "No especificada") if carrera_ref else "No especificada"

        # 3. MÁQUINA DE ESTADOS DEL MICROCICLO (2x1)
        modelo = macro_data.get("modelo", "2x1")
        partes_modelo = modelo.split('x')
        semanas_carga = int(partes_modelo[0])
        semanas_descarga = int(partes_modelo[1]) if len(partes_modelo) > 1 else 1
        total_semanas_ciclo = semanas_carga + semanas_descarga
        
        semana_a_ejecutar = macro_data.get("semana_proxima", macro_data.get("semana_actual", 1))
        
        if forzar_descarga_por_fatiga or nuevo_meso == "TRANSICION":
            fase_micro = "DESCARGA"
            semana_a_ejecutar = semanas_carga + 1 
        elif mesociclo_previo != nuevo_meso and nuevo_meso in ["BASE", "BUILD", "PEAK"]:
            # Si estrenamos mesociclo, reiniciamos el contador del microciclo a Semana 1 (Carga / Test)
            fase_micro = "CARGA"
            semana_a_ejecutar = 1
        elif semana_a_ejecutar > semanas_carga:
            fase_micro = "DESCARGA"
            if semana_a_ejecutar > total_semanas_ciclo: 
                semana_a_ejecutar = semanas_carga + 1
        else:
            fase_micro = "CARGA"
            
        semana_proxima_num = semana_a_ejecutar + 1
        
        if semana_proxima_num > total_semanas_ciclo:
            semana_proxima_num = 1
            fase_proxima = "CARGA"
        elif semana_proxima_num > semanas_carga:
            fase_proxima = "DESCARGA"
        else:
            fase_proxima = "CARGA"

        if nuevo_meso in ["TAPER_A", "TAPER_B", "TRANSICION"]:
            fase_final_ejecucion = nuevo_meso
        else:
            fase_final_ejecucion = fase_micro
        
        macro_data["mesociclo_actual"] = nuevo_meso
        macro_data["semana_actual"] = semana_a_ejecutar
        macro_data["semana_actual_desc"] = fase_final_ejecucion
        macro_data["semana_proxima"] = semana_proxima_num
        macro_data["semana_proxima_desc"] = fase_proxima
            
        return fase_final_ejecucion, nuevo_meso, nombre_evento, tipo_evento, meta_evento, bloque_mesociclo, macro_data

    def generar_entrenamientos(self):
        logging.info("\n>>> INICIANDO MOTOR DE GENERACIÓN DE WORKOUTS <<<")
        
        hoy_date = datetime.date.today()
        hoy_str = hoy_date.isoformat()
        
        lock_existente = self.blob_manager.leer_texto(self.lock_file)
        if lock_existente:
            if hoy_str in lock_existente:
                logging.warning(f"[Lock] Ya existe un registro de ejecución para hoy ({hoy_str}). Abortando para evitar duplicidad.")
                return
            else:
                logging.info("[Lock] Purgando candado fosilizado de días anteriores...")
                self.blob_manager.eliminar_archivo(self.lock_file)

        macro_str = self.blob_manager.leer_texto(self.macro_file)
        if not macro_str:
            logging.error(f"[Error Crítico] Archivo {self.macro_file} no encontrado en Azure.")
            return
            
        macro_data = json.loads(macro_str)
        fase, meso_actual, nombre_evento, tipo_evento, meta_evento, bloque_mesociclo, nuevo_macro_data = self._determinar_fase(macro_data)
        logging.info(f"[Mesociclo Inferido] {meso_actual} | [Fase Microciclo] {fase}")
        
        self.blob_manager.guardar_texto(self.macro_file, json.dumps(nuevo_macro_data, indent=4))
        
        system_prompt = self.blob_manager.leer_texto(self.system_prompt_file)
        manifiesto = self.blob_manager.leer_texto(self.manifest_file)
        contexto_csv = self.blob_manager.leer_texto(self.csv_file)
        
        if not contexto_csv:
            logging.error(f"[Error Crítico] No se encontró {self.csv_file}. Abortando.")
            return
        
        # Inyección dinámica del calendario de carreras
        carreras = nuevo_macro_data.get("calendario_carreras", [])
        bloque_calendario = "\n[CALENDARIO DE COMPETENCIAS, METAS Y TOPOGRAFÍA]\n"
        if carreras:
            bloque_calendario += "El atleta tiene los siguientes eventos programados en su temporada:\n"
            for c in carreras:
                nom = c.get('nombre', 'Evento')
                desc = c.get('descripcion', 'Sin descripción específica.')
                meta = c.get('meta', 'No especificada.')
                taper = c.get('dias_taper', 7)
                bloque_calendario += f"- {c.get('fecha')}: {nom} [{c.get('tipo')}] (Prioridad {c.get('prioridad')}). Taper: {taper} días. Meta: {meta}. Características: {desc}\n"
            bloque_calendario += "ADAPTACIÓN BIOMECÁNICA Y PACING: Ajusta los ritmos de tempo, umbral y tiradas específicas en base a la Meta Objetivo y topografía del evento más cercano.\n"
        else:
            bloque_calendario += "No hay competencias próximas registradas. Aplica entrenamiento de base y desarrollo general.\n"

        directriz_fase = ""
        if fase == "CARGA":
            directriz_fase = "\n[FASE DEL MICROCICLO: CARGA]\nAplica sobrecarga progresiva respetando las métricas de fatiga y el foco del mesociclo inferido. Aumenta volumen o intensidad respecto al bloque anterior.\n"
        elif fase == "DESCARGA":
            directriz_fase = "\n[FASE DEL MICROCICLO: DESCARGA]\nREGLA OBLIGATORIA: Reduce el volumen total de la semana en un 30-40%. Prohibido programar sesiones de VO2Max o umbral sostenido. Prioriza Z1 y Z2.\n"
        elif fase == "TRANSICION":
            directriz_fase = "\n[FASE DEL MICROCICLO: TRANSICIÓN POST-CARRERA]\nREGLA OBLIGATORIA: Semana de recuperación profunda post-competencia. Prohibido cualquier bloque en Z3, Z4 o Z5.\n"
        elif fase == "TAPER_A":
            directriz_fase = f"\n[FASE ESTRATÉGICA: TAPER PROFUNDO PARA {nombre_evento} ({tipo_evento})]\nREGLA OBLIGATORIA: Reduce el volumen de resistencia drásticamente (50%), pero MANTÉN LA INTENSIDAD. Debes incluir intervalos cortos al ritmo de la meta ({meta_evento}) enfocado en {tipo_evento}. Mantén la tensión neuromuscular sin fatiga residual.\n"
        elif fase == "TAPER_B":
            directriz_fase = f"\n[FASE ESTRATÉGICA: MICRO-TAPER PARA {nombre_evento} ({tipo_evento})]\nREGLA OBLIGATORIA: Mantén el volumen y estructura normal de lunes a miércoles. Solo a partir del jueves reduce drásticamente el volumen y carga de las sesiones previas al evento. Mantén activaciones de intensidad cortas orientadas al ritmo de {meta_evento}.\n"
            
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        dia_str = dias_es[hoy_date.weekday()]
        
        if hoy_date.weekday() == 6:
            dias_para_domingo = 7
        else:
            dias_para_domingo = 6 - hoy_date.weekday()
            
        domingo_date = hoy_date + datetime.timedelta(days=dias_para_domingo)
        domingo_str = domingo_date.isoformat()

        anclaje_temporal = (
            f"\n[RELOJ DEL SISTEMA]\n"
            f"CRÍTICO: Hoy es {dia_str}, {hoy_str}. "
            f"Genera los entrenamientos estrictamente para los días restantes de esta semana (desde hoy {hoy_str} hasta el domingo {domingo_str}). "
            f"Asegura que los entrenamientos de mayor volumen y tiradas largas se programen orgánicamente para el fin de semana (sábado y domingo).\n"
        )
        
        prompt_final = f"{system_prompt}{anclaje_temporal}{bloque_calendario}{bloque_mesociclo}{directriz_fase}\n{manifiesto}\n\n[DATOS BIOMÉTRICOS Y DE RENDIMIENTO ACTUALES]\n{contexto_csv}"
        
        logging.info(f"[Conexión] Solicitando inferencia a Gemini 4 Argon (Prompt de {len(prompt_final)} caracteres)...")
        
        try:
            response = self.client.models.generate_content(
                model='gemini-4-argon',
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