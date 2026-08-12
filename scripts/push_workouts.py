import os
import glob
import json
import requests
import datetime

# Inyección de dependencias desde el módulo unificado
from intervals_utils import IntervalsClient, WORKOUTS_DIR

class IntervalsUploader:
    def __init__(self):
        # Reutilizamos el cliente agnóstico que ya carga las llaves del .env
        self.client = IntervalsClient()
        self.base_url = f"{self.client.base_url}/athlete/{self.client.athlete_id}"
        self.auth = self.client._get_auth()

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

    def sincronizar(self, input_dir=WORKOUTS_DIR):
        archivos_json = glob.glob(os.path.join(input_dir, "*.json"))
        if not archivos_json:
            print("[Info] No hay archivos JSON locales en el directorio.")
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

        print(f"[Uploader] Eventos existentes detectados en la nube: {len(eventos_nube)}")
        
        subidos = 0
        purgados = 0
        
        for archivo in archivos_json:
            try:
                with open(archivo, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                    
                fecha = payload.get("start_date_local", "").split("T")[0]
                deporte = payload.get("type", "Unknown")
                
                if fecha < hoy_str:
                    os.remove(archivo)
                    purgados += 1
                    continue
                
                if (fecha, deporte) in eventos_nube:
                    print(f"[Cortafuegos Nube] Omitiendo {archivo}: Ya existe un '{deporte}' el {fecha} en el servidor.")
                    continue
                    
                url_post = f"{self.base_url}/events"
                respuesta = requests.post(url_post, auth=self.auth, json=[payload], timeout=30)
                respuesta.raise_for_status()
                
                print(f"[Éxito] JSON inyectado en Intervals.icu: {deporte} para el {fecha}.")
                eventos_nube.add((fecha, deporte))
                subidos += 1
                
            except json.JSONDecodeError:
                print(f"[Error] El archivo {archivo} está corrupto y no es un JSON válido.")
            except requests.exceptions.RequestException as e:
                print(f"[Error de Red] Fallo al subir {archivo}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                     print(f"Detalle API: {e.response.text}")

        print(f"[Uploader] Proceso finalizado. Eventos nuevos subidos: {subidos}. Archivos históricos purgados: {purgados}.")

if __name__ == "__main__":
    uploader = IntervalsUploader()
    uploader.sincronizar()
