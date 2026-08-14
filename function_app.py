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
@app.timer_trigger(schedule="0 */30 10-15 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def timer_orquestador_inteligente(mytimer: func.TimerRequest) -> None:
    hoy_dt = datetime.date.today()
    hoy = hoy_dt.isoformat()
    # Candado estático único
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

    logging.info(f"[Orquestador] Biometría detectada (HRV: {hrv}, Sleep: {sleep}). Iniciando ignición...")

    # 4. Disparar Reacción en Cadena
    try:
        logging.info("---> Ejecutando 1/4: Contexto IA")
        IntervalsContextGenerator().generar_csv()
        
        # Cortafuegos Estructural: Bloqueo de Inferencia Diaria
        if hoy_dt.weekday() == 0:
            logging.info("---> Ejecutando 2/4: Inferencia Gemini (Día Lunes - Generación Semanal Autorizada)")
            IntervalsWorkoutGenerator().generar_entrenamientos()
        else:
            logging.info("---> Omitiendo 2/4: Inferencia Gemini (Bloqueada de Martes a Domingo para evitar alucinaciones algorítmicas)")
        
        logging.info("---> Ejecutando 3/4: Mutación Sentinel")
        IntervalsSentinel().ejecutar()
        
        logging.info("---> Ejecutando 4/4: Push a Intervals.icu")
        IntervalsUploader().sincronizar()
        
        # 5. Sellar el sistema sobrescribiendo el candado único
        blob_manager.guardar_texto(lock_blob, hoy)
        logging.info("[Orquestador] Operación de día cero finalizada. Candado estático actualizado en la nube.")

    except Exception as e:
        logging.error(f"[Error Crítico] Colapso en la cadena de ejecución: {e}")