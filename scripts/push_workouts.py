import json
import logging
import datetime
from scripts.intervals_utils import IntervalsClient, AzureBlobManager, BLOB_WORKOUTS_PREFIX

class IntervalsUploader:
    def __init__(self):
        self.client = IntervalsClient()
        self.blob_manager = AzureBlobManager()

    def obtener_eventos_nube(self, oldest, newest):
        try:
            eventos = self.client.get_events(oldest=oldest, newest=newest)
            registro_nube = {}
            for evt in eventos:
                fecha = evt.get("start_date_local", "").split("T")[0]
                tipo = evt.get("type", "Unknown")
                if fecha and tipo != "Unknown":
                    registro_nube[(fecha, tipo)] = {
                        "id": evt.get("id"),
                        "name": evt.get("name", "")
                    }
            return registro_nube
        except Exception as e:
            logging.error(f"[Error Crítico] Falló la lectura del calendario en la nube: {e}")
            return None

    def sincronizar(self):
        blobs = self.blob_manager.listar_archivos(BLOB_WORKOUTS_PREFIX)
        blobs_json = [b for b in blobs if b.endswith(".json")]
        
        if not blobs_json:
            logging.info("[Info] No hay archivos JSON pendientes en la cola principal de Azure.")
            return

        hoy = datetime.date.today()
        hoy_str = hoy.isoformat()
        dias_para_domingo = 6 - hoy.weekday()
        domingo_str = (hoy + datetime.timedelta(days=dias_para_domingo)).isoformat()

        logging.info(f"[Uploader] Consultando calendario de Intervals.icu desde {hoy_str} hasta {domingo_str}...")
        eventos_nube = self.obtener_eventos_nube(hoy_str, domingo_str)

        if eventos_nube is None:
            logging.warning("[Uploader] Sincronización abortada por falta de visibilidad en la nube.")
            return
        
        subidos = 0
        archivados = 0
        
        for blob_name in blobs_json:
            # Cortafuegos para ignorar iteraciones sobre archivos que ya están en el histórico
            if "history/" in blob_name:
                continue

            contenido = self.blob_manager.leer_texto(blob_name)
            if not contenido:
                continue
                
            try:
                payload = json.loads(contenido)
                fecha = payload.get("start_date_local", "").split("T")[0]
                deporte = payload.get("type", "Unknown")
                
                archivo_nombre = blob_name.split('/')[-1]
                destino_historico = f"workouts_ia/history/{fecha}/{archivo_nombre}"
                
                if fecha < hoy_str:
                    logging.info(f"[Uploader] Archivando evento expirado: {blob_name}")
                    self.blob_manager.mover_archivo(blob_name, destino_historico)
                    archivados += 1
                    continue
                
                evento_existente = eventos_nube.get((fecha, deporte))
                
                if evento_existente:
                    logging.info(f"[Cortafuegos Nube] Omitiendo {blob_name}: Ya existe un '{deporte}' el {fecha} en el servidor. Archivando JSON.")
                    self.blob_manager.mover_archivo(blob_name, destino_historico)
                    archivados += 1
                    continue
                
                # Capa de sanitización estricta
                payload["category"] = "WORKOUT"
                
                if "T" not in payload.get("start_date_local", ""):
                    payload["start_date_local"] = f"{fecha}T00:00:00"
                
                if "workout_doc" in payload:
                    doc = payload.pop("workout_doc")
                    if "description" in payload:
                        payload["description"] = payload["description"] + "\n\n" + doc
                    else:
                        payload["description"] = doc
                
                self.client.upload_event(payload)
                logging.info(f"[Éxito] JSON inyectado en Intervals.icu: {deporte} para el {fecha}.")
                
                # Operación de archivo exitoso
                self.blob_manager.mover_archivo(blob_name, destino_historico)
                
                eventos_nube[(fecha, deporte)] = {"id": None, "name": payload.get("name", "")}
                subidos += 1
                archivados += 1
                
            except json.JSONDecodeError:
                logging.error(f"[Error] El archivo {blob_name} está corrupto y no es un JSON válido.")
            except Exception as e:
                logging.error(f"[Error de Red] Fallo al subir {blob_name}: {e}")

        logging.info(f"[Uploader] Proceso finalizado. Eventos subidos: {subidos}. Eventos archivados: {archivados}.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    uploader = IntervalsUploader()
    uploader.sincronizar()