import azure.functions as func
import logging
import datetime

from scripts.intervals_utils import IntervalsClient, AzureBlobManager
from scripts.generar_contexto_ia import IntervalsContextGenerator
from scripts.generar_workouts import IntervalsWorkoutGenerator
from scripts.sentinel import IntervalsSentinel
from scripts.push_workouts import IntervalsUploader

app = func.FunctionApp()

# Ejecuta cada 30 minutos entre las 10:00 y las 15:00 UTC (06:00 AM a 11:00 AM hora de Chile)
@app.timer_trigger(schedule="%SCHEDULE_CRON%", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def timer_orquestador_inteligente(mytimer: func.TimerRequest) -> None:
    hoy_dt = datetime.date.today()
    hoy = hoy_dt.isoformat()
    # Candado estático único para evitar doble ejecución en el mismo día
    lock_blob = "workouts_ia/pipeline_estado.lock"
    blob_manager = AzureBlobManager()

    logging.info(f"[Orquestador] Iniciando ciclo de verificación para {hoy}...")

    # 1. Cortafuegos de Idempotencia (evaluación por contenido)
    contenido_lock = blob_manager.leer_texto(lock_blob)
    if contenido_lock and hoy in contenido_lock:
        logging.info("[Orquestador] El pipeline ya se ejecutó exitosamente hoy. Abortando.")
        return

    # 2. Verificar sincronización de Garmin
    try:
        client = IntervalsClient()
        wellness = client.get_wellness(oldest=hoy, newest=hoy)
    except Exception as e:
        logging.error(f"[Orquestador] Fallo crítico de red al consultar Intervals.icu: {e}")
        return

    if not wellness:
        logging.info("[Orquestador] No hay registros en la nube para hoy. Esperando a Garmin...")
        return

    datos_hoy = wellness[0]
    hrv = datos_hoy.get("hrv")
    sleep = datos_hoy.get("sleepScore")

    # 3. Validación estricta
    if hrv is None or sleep is None:
        logging.info("[Orquestador] Registro creado, pero HRV o Sleep están vacíos. Esperando...")
        return

    logging.info(f"[Orquestador] Biometría detectada (HRV: {hrv}, Sleep: {sleep}). Evaluando enrutamiento por día...")

    # 4. Enrutamiento Condicional de Lógica de Negocio
    es_domingo = (hoy_dt.weekday() == 6)

    try:
        # Siempre se actualiza la biometría diaria para el Sentinel
        logging.info("---> Ejecutando Contexto IA (Actualización diaria de biometría)")
        IntervalsContextGenerator().generar_csv()
        
        if es_domingo:
            logging.info("[PLANIFICACIÓN MACRO] Domingo detectado. Generando semana completa...")
            logging.info("---> Ejecutando Inferencia Gemini")
            IntervalsWorkoutGenerator().generar_entrenamientos()
            
            logging.info("---> Ejecutando Push a Intervals.icu")
            IntervalsUploader().sincronizar()
        else:
            logging.info("[MICRO-GESTIÓN] Día regular detectado. Omitiendo generación semanal.")

        # Siempre se ejecuta Sentinel para aplicar mutaciones por fatiga al entrenamiento de hoy
        logging.info("---> Ejecutando Mutación Sentinel (Ajuste de fatiga diario)")
        IntervalsSentinel().ejecutar()
        
        # 5. Sellar el sistema sobrescribiendo el candado único
        blob_manager.guardar_texto(lock_blob, hoy)
        logging.info("[Orquestador] Operación diaria finalizada. Candado estático actualizado en la nube.")

    except Exception as e:
        logging.error(f"[Error Crítico] Colapso en la cadena de ejecución: {e}")