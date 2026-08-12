import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# --- RUTAS Y DIRECTORIOS CENTRALIZADOS ---
BASE_DIR = os.environ.get("INTERVALS_BASE_DIR", "/opt/intervals.icu")

# Cargar automáticamente el archivo .env desde la raíz del proyecto
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.path.join(BASE_DIR, "data")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

WORKOUTS_DIR = os.path.join(DATA_DIR, "workouts_ia")
CSV_PATH = os.path.join(DATA_DIR, "contexto_ia.csv")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifiesto.md")
PROMPT_PATH = os.path.join(DATA_DIR, "system_prompt.txt")

UPLOADER_SCRIPT = os.path.join(SCRIPTS_DIR, "push_workouts.py")
GENERATOR_SCRIPT = os.path.join(SCRIPTS_DIR, "generar_workouts.py")
SENTINEL_SCRIPT = os.path.join(SCRIPTS_DIR, "sentinel.py")
ZWO_CONVERTER_SCRIPT = os.path.join(SCRIPTS_DIR, "workout_json2zwo.py")


# --- CONFIGURACIÓN Y CLIENTE API ---
class Config:
    INTERVALS_ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
    INTERVALS_API_KEY = os.environ.get("INTERVALS_API_KEY")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

    @classmethod
    def validate_intervals(cls):
        if not cls.INTERVALS_ATHLETE_ID or not cls.INTERVALS_API_KEY:
            raise ValueError("Faltan las credenciales INTERVALS_ATHLETE_ID o INTERVALS_API_KEY en el entorno o en el archivo .env.")

class IntervalsClient:
    def __init__(self):
        Config.validate_intervals()
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
