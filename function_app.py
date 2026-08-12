import azure.functions as func
import logging

# Importamos las clases de tu ecosistema refactorizado
from scripts.generar_contexto_ia import IntervalsContextGenerator
from scripts.generar_workouts import IntervalsWorkoutGenerator
from scripts.sentinel import IntervalsSentinel
from scripts.push_workouts import IntervalsUploader

app = func.FunctionApp()

# 1. Generador de Contexto (Ejecución diaria a las 08:00 AM UTC / 04:00 AM Chile)
@app.timer_trigger(schedule="0 0 8 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def timer_generar_contexto(mytimer: func.TimerRequest) -> None:
    logging.info("[Azure Function] Iniciando generación de contexto IA y telemetría...")
    try:
        generador = IntervalsContextGenerator()
        generador.generar_csv()
    except Exception as e:
        logging.error(f"[Error Crítico] Fallo en timer_generar_contexto: {e}")

# 2. Motor de Inferencia (Ejecución diaria a las 09:00 AM UTC / 05:00 AM Chile)
@app.timer_trigger(schedule="0 0 9 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def timer_generar_workouts(mytimer: func.TimerRequest) -> None:
    logging.info("[Azure Function] Iniciando motor de inferencia Gemini...")
    try:
        generador = IntervalsWorkoutGenerator()
        generador.generar_entrenamientos()
    except Exception as e:
        logging.error(f"[Error Crítico] Fallo en timer_generar_workouts: {e}")

# 3. Escudo Fisiológico y Sincronización (Ejecución diaria a las 10:00 AM UTC / 06:00 AM Chile)
@app.timer_trigger(schedule="0 0 10 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def timer_sentinel_uploader(mytimer: func.TimerRequest) -> None:
    logging.info("[Azure Function] Iniciando Sentinel y barrido hacia Intervals.icu...")
    try:
        # 1. El Sentinel evalúa fatiga y muta los JSON en el blob si es necesario
        sentinel = IntervalsSentinel()
        sentinel.ejecutar()
        
        # 2. El Uploader realiza un barrido de todo el contenedor para inyectar en la plataforma
        uploader = IntervalsUploader()
        uploader.sincronizar()
    except Exception as e:
        logging.error(f"[Error Crítico] Fallo en timer_sentinel_uploader: {e}")
