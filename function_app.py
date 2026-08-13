import azure.functions as func
import logging
import datetime

from scripts.intervals_utils import IntervalsClient, AzureBlobManager
from scripts.generar_contexto_ia import IntervalsContextGenerator
from scripts.generar_workouts import IntervalsWorkoutGenerator
from scripts.sentinel import IntervalsSentinel
from scripts.push_workouts import IntervalsUploader
from scripts.workout_json2zwo import ZWOConverter

app = func.FunctionApp()

# Ejecuta cada 30 minutos entre las 10:00 y las 15:00 UTC (06:00 AM a 11:00 AM hora de Chile)
@app.timer_trigger(schedule="0 */30 10-15 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def timer_orquestador_inteligente(mytimer: func.TimerRequest) -> None:
    hoy = datetime.date.today().isoformat()
    lock_blob = f"workouts_ia/pipeline_{hoy}.lock"
    blob_manager = AzureBlobManager()

    logging.info(f"[Orquestador] Iniciando ciclo de verificación para {hoy}...")

    # 1. Cortafuegos de Idempotencia en Blob Storage
    if blob_manager.leer_texto(lock_blob):
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

    # 3. Validación estricta de condiciones fisiológicas
    if hrv is None or sleep is None:
        logging.info("[Orquestador] Registro creado, pero HRV o SleepScore están vacíos. Esperando sincronización de Garmin...")
        return

    logging.info(f"[Orquestador] Biometría detectada (HRV: {hrv}, Sleep: {sleep}). Iniciando ignición del motor algorítmico...")

    # 4. Disparar Reacción en Cadena
    try:
        logging.info("---> Ejecutando 1/5: Contexto IA")
        IntervalsContextGenerator().generar_csv()
        
        logging.info("---> Ejecutando 2/5: Inferencia Gemini")
        IntervalsWorkoutGenerator().generar_entrenamientos()
        
        logging.info("---> Ejecutando 3/5: Mutación Sentinel")
        IntervalsSentinel().ejecutar()
        
        logging.info("---> Ejecutando 4/5: Push a Intervals.icu")
        IntervalsUploader().sincronizar()
        
        logging.info("---> Ejecutando 5/5: Conversión a ZWO")
        ZWOConverter().convertir_directorio()
        
        # 5. Sellar el sistema por el resto del día depositando el candado en Azure
        blob_manager.guardar_texto(lock_blob, f"Pipeline completado exitosamente a las {datetime.datetime.now().isoformat()}")
        logging.info("[Orquestador] Operación de día cero finalizada. Candado activado en la nube.")

    except Exception as e:
        logging.error(f"[Error Crítico] Colapso en la cadena de ejecución: {e}")
