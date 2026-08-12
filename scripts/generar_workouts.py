import os
import glob
import json
import datetime
import time
from google import genai
from google.genai import types

# Importar rutas centralizadas. Esto dispara automáticamente la carga del .env en intervals_utils
from intervals_utils import WORKOUTS_DIR, CSV_PATH, MANIFEST_PATH, PROMPT_PATH

class IntervalsWorkoutGenerator:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Falta la credencial GEMINI_API_KEY en el entorno o en el archivo .env.")
        self.client = genai.Client(api_key=self.api_key)

    def cargar_archivo(self, ruta):
        if not os.path.exists(ruta):
            print(f"[Advertencia] El archivo {ruta} no existe. Se omitirá su contenido.")
            return ""
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()

    def obtener_estado_calendario(self, output_dir):
        archivos_json = glob.glob(os.path.join(output_dir, "*.json"))
        registro_bloqueos = set()
        texto_calendario = []
        
        for archivo in archivos_json:
            with open(archivo, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    fecha = data.get("start_date_local", "").split("T")[0]
                    deporte = data.get("type", "Desconocido")
                    registro_bloqueos.add((fecha, deporte))
                    texto_calendario.append(f"- {fecha}: {deporte}")
                except json.JSONDecodeError:
                    continue
        
        if not texto_calendario:
            return "Ninguno. El calendario de esta semana está vacío.", registro_bloqueos
        return "\n".join(sorted(texto_calendario)), registro_bloqueos

    def generar_entrenamientos(self):
        print("[Generator] Cargando directrices, manifiesto y telemetría...")
        system_prompt = self.cargar_archivo(PROMPT_PATH)
        contexto_datos = self.cargar_archivo(CSV_PATH)
        manifiesto_datos = self.cargar_archivo(MANIFEST_PATH)

        if not system_prompt:
            print("[Error Crítico] Sin system prompt no se puede inicializar el modelo.")
            return

        hoy = datetime.date.today()
        dias_para_domingo = 6 - hoy.weekday()
        domingo = hoy + datetime.timedelta(days=dias_para_domingo)
        
        texto_actual, registro_bloqueos = self.obtener_estado_calendario(WORKOUTS_DIR)
        
        prompt_usuario = f"""
Fecha de inicio del cálculo: {hoy.isoformat()}.
Fecha de término estricta: Domingo {domingo.isoformat()}.

--- CALENDARIO YA PROGRAMADO ESTA SEMANA ---
{texto_actual}

--- MANIFIESTO DE ENTRENAMIENTO DE LA SEMANA ---
{manifiesto_datos}

--- CONTEXTO FISIOLÓGICO Y UMBRALES (Últimos 14 días) ---
{contexto_datos}

INSTRUCCIÓN OPERATIVA:
1. Cruza las directrices del MANIFIESTO con la carga aguda del CONTEXTO FISIOLÓGICO.
2. Genera EXCLUSIVAMENTE los entrenamientos faltantes para rellenar el microciclo hasta el {domingo.isoformat()}.
3. Si el calendario actual ya cubre las necesidades del manifiesto y la telemetría, devuelve un JSON vacío: []
"""
        print(f"[Generator] Solicitando inferencia a Gemini con límite {domingo.isoformat()}...")
        print(f"[Generator] Entrenamientos actuales protegidos por cortafuegos:\n{texto_actual}")
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_usuario,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2, 
                    response_mime_type="application/json"
                )
            )
            
            texto_limpio = response.text.strip()
            entrenamientos = json.loads(texto_limpio)
            
            os.makedirs(WORKOUTS_DIR, exist_ok=True)
            timestamp = int(time.time())
            
            if not entrenamientos:
                print("[Info] La IA determinó que no faltan entrenamientos por programar esta semana.")
                return

            eventos_guardados = 0
            for idx, ent in enumerate(entrenamientos):
                fecha = ent.get("start_date_local", "").split("T")[0]
                deporte = ent.get("type", "Unknown")
                
                if (fecha, deporte) in registro_bloqueos:
                    print(f"[Cortafuegos] Interceptado: Se bloqueó la creación de un nuevo '{deporte}' para el día {fecha} porque ya existe uno.")
                    continue
                
                filepath = os.path.join(WORKOUTS_DIR, f"{fecha}_{deporte}_{timestamp}_{idx}.json")
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(ent, f, indent=4, ensure_ascii=False)
                
                print(f"[Éxito] Nuevo JSON nativo generado: {filepath}")
                eventos_guardados += 1
            
            if eventos_guardados == 0:
                print("[Info] Todos los eventos propuestos por la IA fueron aniquilados por el cortafuegos.")
                
        except json.JSONDecodeError as e:
            print(f"[Error Crítico] Gemini no devolvió un JSON válido: {e}")
            if 'response' in locals():
                print(f"Salida cruda devuelta por la IA:\n{response.text}")
        except Exception as e:
            print(f"[Error] Fallo inesperado en el procesamiento: {e}")

if __name__ == "__main__":
    generador = IntervalsWorkoutGenerator()
    generador.generar_entrenamientos()
