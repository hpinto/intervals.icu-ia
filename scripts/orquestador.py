import os
import sys
import datetime
import subprocess
import logging
from scripts.intervals_utils import IntervalsClient, SCRIPTS_DIR

# Configuración de logs
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def ejecutar_orquestador():
    hoy = datetime.date.today().isoformat()
    lock_file = f"/tmp/intervals_pipeline_{hoy}.lock"

    # 1. Cortafuegos de Idempotencia Diaria
    if os.path.exists(lock_file):
        logging.info("[Orquestador] El pipeline ya se ejecutó exitosamente hoy. Abortando nueva ejecución.")
        sys.exit(0)

    # 2. Verificar sincronización de Garmin (Polling Inteligente)
    logging.info(f"[Orquestador] Consultando disponibilidad biométrica en la nube para {hoy}...")
    try:
        client = IntervalsClient()
        wellness = client.get_wellness(oldest=hoy, newest=hoy)
    except Exception as e:
        logging.error(f"[Orquestador] Fallo crítico de red al consultar a Intervals.icu: {e}")
        sys.exit(1)
        
    if not wellness:
        logging.info(f"[Orquestador] No hay registros en la nube para {hoy}. Garmin aún no sincroniza. Saliendo.")
        sys.exit(0)
        
    datos_hoy = wellness[0]
    hrv = datos_hoy.get("hrv")
    sleep = datos_hoy.get("sleepScore")

    # 3. Validación estricta de la carrera de condiciones
    if hrv is None or sleep is None:
        logging.info("[Orquestador] Registro creado, pero HRV o SleepScore están vacíos. Esperando sincronización completa de Garmin.")
        sys.exit(0)

    # 4. Disparar reacción en cadena si la biometría es válida
    logging.info(f"[Orquestador] Biometría detectada (HRV: {hrv}, Sleep: {sleep}). Iniciando ignición del motor algorítmico...")
    
    # Orden estricto de ejecución
    scripts = [
        "generar_contexto_ia.py",
        "generar_workouts.py", 
        "sentinel.py",
        "push_workouts.py",
        "workout_json2zwo.py"
    ]

    for script in scripts:
        ruta_script = os.path.join(SCRIPTS_DIR, script)
        if os.path.exists(ruta_script):
            logging.info(f"[Orquestador] ---> Ejecutando {script}...")
            resultado = subprocess.run([sys.executable, ruta_script], capture_output=True, text=True)
            if resultado.returncode != 0:
                logging.error(f"[Orquestador] El script {script} falló. Salida: {resultado.stderr}")
                sys.exit(1)
            else:
                logging.info(f"[Orquestador] {script} finalizado con éxito.")
        else:
            logging.warning(f"[Orquestador] Archivo no encontrado: {ruta_script}.")

    # 5. Sellar el sistema por el resto del día
    with open(lock_file, "w") as f:
        f.write(f"Pipeline completado a las {datetime.datetime.now().isoformat()}")
    logging.info("[Orquestador] Operación de día cero finalizada. Candado activado.")

if __name__ == "__main__":
    ejecutar_orquestador()
