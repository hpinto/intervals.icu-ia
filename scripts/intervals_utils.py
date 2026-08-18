import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient

# Cargar automáticamente el archivo .env (vital para pruebas locales; en Azure se usan los Application Settings)
load_dotenv()

class Config:
    INTERVALS_ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
    INTERVALS_API_KEY = os.environ.get("INTERVALS_API_KEY")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    AZURE_CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    AZURE_CONTAINER = os.environ.get("AZURE_CONTAINER_NAME", "intervals-icu-data")

    @classmethod
    def validate(cls):
        if not cls.INTERVALS_ATHLETE_ID or not cls.INTERVALS_API_KEY:
            raise ValueError("Faltan las credenciales INTERVALS_ATHLETE_ID o INTERVALS_API_KEY.")
        if not cls.AZURE_CONN_STR:
            raise ValueError("Falta la credencial AZURE_STORAGE_CONNECTION_STRING en el entorno.")

# --- RUTAS LÓGICAS EN EL BLOB STORAGE (Nombres de los Blobs) ---
BLOB_CSV_PATH = "contexto_ia.csv"
BLOB_MANIFEST_PATH = "manifiesto.md"
BLOB_PROMPT_PATH = "system_prompt.txt"
BLOB_WORKOUTS_PREFIX = "workouts_ia/"

class AzureBlobManager:
    """Gestor unificado para interactuar con Azure Storage Account en memoria RAM."""
    def __init__(self):
        Config.validate()
        self.blob_service_client = BlobServiceClient.from_connection_string(Config.AZURE_CONN_STR)
        self.container_client = self.blob_service_client.get_container_client(Config.AZURE_CONTAINER)

    def leer_texto(self, blob_name):
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            if blob_client.exists():
                return blob_client.download_blob().readall().decode("utf-8")
            else:
                print(f"[Azure] Advertencia: El blob {blob_name} no existe.")
                return ""
        except Exception as e:
            print(f"[Azure] Error crítico al leer {blob_name}: {e}")
            return ""

    def guardar_texto(self, blob_name, contenido):
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_client.upload_blob(contenido, overwrite=True)
            return True
        except Exception as e:
            print(f"[Azure] Error al guardar {blob_name}: {e}")
            return False

    def listar_archivos(self, prefijo):
        try:
            return [blob.name for blob in self.container_client.list_blobs(name_starts_with=prefijo)]
        except Exception as e:
            print(f"[Azure] Error al listar blobs con prefijo {prefijo}: {e}")
            return []

    def eliminar_archivo(self, blob_name):
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            if blob_client.exists():
                blob_client.delete_blob()
                return True
            return False
        except Exception as e:
            print(f"[Azure] Error al eliminar {blob_name}: {e}")
            return False

    def mover_archivo(self, origen, destino):
        """Emula un comando 'move' leyendo, guardando en nueva ruta y eliminando el original."""
        try:
            contenido = self.leer_texto(origen)
            if contenido:
                if self.guardar_texto(destino, contenido):
                    self.eliminar_archivo(origen)
                    return True
            return False
        except Exception as e:
            print(f"[Azure] Error al mover {origen} a {destino}: {e}")
            return False


class IntervalsClient:
    def __init__(self):
        Config.validate()
        self.athlete_id = Config.INTERVALS_ATHLETE_ID
        self.api_key = Config.INTERVALS_API_KEY
        self.base_url = "https://intervals.icu/api/v1"

    def _get_auth(self):
        return HTTPBasicAuth("API_KEY", self.api_key)

    def get_wellness(self, oldest=None, newest=None):
        url = f"{self.base_url}/athlete/{self.athlete_id}/wellness"
        params = {}
        if oldest: params["oldest"] = oldest
        if newest: params["newest"] = newest
        response = requests.get(url, auth=self._get_auth(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_activities(self, oldest=None, newest=None):
        url = f"{self.base_url}/athlete/{self.athlete_id}/activities"
        params = {}
        if oldest: params["oldest"] = oldest
        if newest: params["newest"] = newest
        response = requests.get(url, auth=self._get_auth(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_events(self, oldest=None, newest=None):
        url = f"{self.base_url}/athlete/{self.athlete_id}/events"
        params = {}
        if oldest: params["oldest"] = oldest
        if newest: params["newest"] = newest
        response = requests.get(url, auth=self._get_auth(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def upload_event(self, payload):
        url = f"{self.base_url}/athlete/{self.athlete_id}/events"
        response = requests.post(url, auth=self._get_auth(), json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def update_event(self, event_id, payload):
        """Actualiza quirúrgicamente un evento existente en Intervals.icu (Método PUT)."""
        url = f"{self.base_url}/athlete/{self.athlete_id}/events/{event_id}"
        response = requests.put(url, auth=self._get_auth(), json=payload, timeout=30)
        response.raise_for_status()
        return response.json()