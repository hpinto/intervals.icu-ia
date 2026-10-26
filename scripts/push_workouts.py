import os
import json
import logging
import datetime

# FORZAR INYECCIÓN DE ENTORNO LOCAL ANTES DE IMPORTAR UTILIDADES
if os.path.exists("local.settings.json"):
    with open("local.settings.json", "r") as f:
        settings = json.load(f)
        for k, v in settings.get("Values", {}).items():
            os.environ[k] = str(v)

from scripts.intervals_utils import IntervalsClient, AzureBlobManager, BLOB_WORKOUTS_PREFIX

class IntervalsUploader:
    def __init__(self):
        self.client = IntervalsClient()
        self.blob_manager = AzureBlobManager()

    def normalizar_tipo_deporte(self, tipo_raw):
        """Normaliza los identificadores de deporte para compatibilidad con Intervals y Garmin."""
        t = str(tipo_raw).strip()
        mapeo = {
            "Fuerza": "WeightTraining",
            "fuerza": "WeightTraining",
            "Strength": "WeightTraining",
            "strength": "WeightTraining",
            "WeightTraining": "WeightTraining",
            "Gym": "WeightTraining",
            "Run": "Run",
            "carrera": "Run",
            "Ride": "Ride",
            "bici": "Ride",
            "ciclismo": "Ride",
            "Swim": "Swim",
            "natacion": "Swim"
        }
        return mapeo.get(t, t)

    def obtener_eventos_nube(self, oldest, newest):
        try:
            eventos = self.client.get_events(oldest=oldest, newest=newest)
            registro_nube = {}
            for evt in eventos:
                fecha = evt.get("start_date_local", "").split("T")[0]
                tipo = self.normalizar_tipo_deporte(evt.get("type", "Unknown"))
                if fecha and tipo != "Unknown":
                    # CORTAFUEGOS ESTRICTO: Una tupla (fecha, tipo) única en el calendario.
                    # Si ya existe un Swim o WeightTraining ese día, bloquea duplicados indeseados.
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
            if "history/" in blob_name:
                continue

            contenido = self.blob_manager.leer_texto(blob_name)
            if not contenido:
                continue
                
            try:
                payload = json.loads(contenido)
                fecha = payload.get("start_date_local", "").split("T")[0]
                deporte_original = payload.get("type", "Unknown")
                deporte = self.normalizar_tipo_deporte(deporte_original)
                payload["type"] = deporte
                nombre_entreno = payload.get("name", "").strip()
                
                archivo_nombre = blob_name.split('/')[-1]
                destino_historico = f"workouts_ia/history/{fecha}/{archivo_nombre}"
                
                if fecha < hoy_str:
                    logging.info(f"[Uploader] Archivando evento expirado: {blob_name}")
                    self.blob_manager.mover_archivo(blob_name, destino_historico)
                    archivados += 1
                    continue
                
                # REGLA DE UNICIDAD DIARIA POR DEPORTE:
                # Excepción controlada: Permitimos múltiples Run o Ride si son dobles turnos explícitos,
                # pero bloqueamos estrictamente duplicados en Swim y WeightTraining.
                evento_existente = eventos_nube.get((fecha, deporte))
                
                if evento_existente and deporte in ["Swim", "WeightTraining"]:
                    logging.info(f"[Cortafuegos Nube] Omitiendo {blob_name}: Ya existe un '{deporte}' el {fecha} ('{evento_existente['name']}'). Archivando JSON duplicado.")
                    self.blob_manager.mover_archivo(blob_name, destino_historico)
                    archivados += 1
                    continue
                
                payload["category"] = "WORKOUT"
                
                if "T" not in payload.get("start_date_local", ""):
                    payload["start_date_local"] = f"{fecha}T07:00:00"

                if "workout_doc" in payload and payload["workout_doc"]:
                    doc = payload["workout_doc"]
                    if not payload.get("description"):
                        payload["description"] = doc
                elif payload.get("description") and "workout_doc" not in payload:
                    payload["workout_doc"] = payload["description"]
                
                self.client.upload_event(payload)
                logging.info(f"[Éxito] JSON inyectado en Intervals.icu: {deporte} ({nombre_entreno}) para el {fecha}.")
                
                self.blob_manager.mover_archivo(blob_name, destino_historico)
                
                eventos_nube[(fecha, deporte)] = {"id": None, "name": nombre_entreno}
                subidos += 1
                archivados += 1
                
            except json.JSONDecodeError:
                logging.error(f"[Error] El archivo {blob_name} está corrupto y no es un JSON válido.")
            except Exception as e:
                logging.error(f"[Error de Red] Fallo al subir {blob_name}: {e}")

        logging.info(f"[Uploader] Proceso finalizado. Eventos subidos: {subidos}. Eventos archivados: {archivados}.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    uploader = IntervalsUploader()
    uploader.sincronizar()
