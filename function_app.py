import azure.functions as func
import logging

app = func.FunctionApp()

@app.timer_trigger(schedule="0 */5 * * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def timer_centinela(mytimer: func.TimerRequest) -> None:
    logging.info("[Azure Function] El contenedor de Python está vivo y el empaquetado offline funciona.")
