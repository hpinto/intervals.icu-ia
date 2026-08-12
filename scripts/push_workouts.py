import json
import requests
import datetime
from intervals_utils import IntervalsClient, AzureBlobManager, BLOB_WORKOUTS_PREFIX

class IntervalsUploader:
    def __init__(self):
        self.client = IntervalsClient()
        self.base_url = f"{self.client.base_url}/athlete/{self.client.athlete_id}"
        self.auth = self.client._get_auth()
        self.blob_manager = AzureBlobManager()

    def obtener_eventos_nube(self, oldest, newest):
        url = f"{self.base_url}/events"
        params = {"oldest": oldest, "newest": newest}
        try:
            response = requests.get(url, auth=self.auth, params=params, timeout=30)
            response.raise_for_status()
            eventos = response.json()
            
            registro_nube = set()
            for evt in eventos:
                fecha = evt.get("start_date_local", "").split("T")[0]
                tipo = evt.get("type", "Unknown")
                if fecha and tipo != "Unknown":
                    registro_nube.add((fecha, tipo))
            return registro_nube
        except requests.exceptions.RequestException as e:
            print(f"[Error Crítico] Falló la lectura del calendario en la nube: {e}")
            return None

    def sincronizar(self):
        blobs_json = self.blob_manager.listar_archivos(BLOB_WORKOUTS_PREFIX)
        if not blobs_json:
            print("[Info] No hay archivos JSON en el contenedor de Azure.")
            return

        hoy = datetime.date.today()
        hoy_str = hoy.isoformat()
        dias_para_domingo = 6 - hoy.weekday()
        domingo_str = (hoy + datetime.timedelta(days=dias_para_domingo)).isoformat()

        print(f"[Uploader] Consultando calendario de Intervals.icu desde {hoy_str} hasta {domingo_str}...")
        eventos_nube = self.obtener_eventos_nube(hoy_str, domingo_str)

        if eventos_nube is None:
            print("[Uploader] Sincronización abortada por falta de visibilidad en la nube.")
            return
        
        subidos = 0
        purgados = 0
        
        for blob_name in blobs_json:
            contenido = self.blob_manager.leer_texto(blob_name)
            if not contenido:
                continue
            try:
                payload = json.loads(contenido)
                fecha = payload.get("start_date_local", "").split("T")[0]
                deporte = payload.get("type", "Unknown")
                
                if fecha < hoy_str:
                    self.blob_manager.eliminar_archivo(blob_name)
                    purgados += 1
                    continue
                
                if (fecha, deporte) in eventos_nube:
                    print(f"[Cortafuegos Nube] Omitiendo {blob_name}: Ya existe un '{deporte}' el {fecha} en el servidor.")
                    continue
                    
                url_post = f"{self.base_url}/events"
                respuesta = requests.post(url_post, auth=self.auth, json=[payload], timeout=30)
                respuesta.raise_for_status()
                
                print(f"[Éxito] JSON inyectado en Intervals.icu: {deporte} para el {fecha}.")
                eventos_nube.add((fecha, deporte))
                subidos += 1
                
            except json.JSONDecodeError:
                print(f"[Error] El archivo {blob_name} está corrupto y no es un JSON válido.")
            except requests.exceptions.RequestException as e:
                print(f"[Error de Red] Fallo al subir {blob_name}: {e}")

        print(f"[Uploader] Proceso finalizado. Eventos nuevos subidos: {subidos}. Archivos históricos purgados: {purgados}.")

if __name__ == "__main__":
    uploader = IntervalsUploader()
    uploader.sincronizar()
