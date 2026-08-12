import os
import json
import datetime
import time
from google import genai
from google.genai import types

# Importamos las herramientas de Azure unificadas
from scripts.intervals_utils import AzureBlobManager, BLOB_CSV_PATH, BLOB_MANIFEST_PATH, BLOB_PROMPT_PATH, BLOB_WORKOUTS_PREFIX

class IntervalsWorkoutGenerator:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Falta la credencial GEMINI_API_KEY en el entorno o en el archivo .env.")
        self.client = genai.Client(api_key=self.api_key)
        self.blob_manager = AzureBlobManager()

    def obtener_estado_calendario(self):
        blobs = self.blob_manager.listar_archivos(BLOB_WORKOUTS_PREFIX)
        registro_bloqueos = set()
        texto_calendario = []
        
        for blob_name in blobs:
            contenido = self.blob_manager.leer_texto(blob_name)
            if not contenido:
                continue
            try:
                data = json.loads(contenido)
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
        print("[Generator] Cargando directrices, manifiesto y telemetría desde Azure Blob Storage...")
        system_prompt = self.blob_manager.leer_texto(BLOB_PROMPT_PATH)
        contexto_datos = self.blob_manager.leer_texto(BLOB_CSV_PATH)
        manifiesto_datos = self.blob_manager.leer_texto(BLOB_MANIFEST_PATH)

        if not system_prompt:
            print("[Error Crítico] Sin system prompt en Azure no se puede inicializar el modelo.")
            return

        hoy = datetime.date.today()
        dias_para_domingo = 6 - hoy.weekday()
        domingo = hoy + datetime.timedelta(days=dias_para_domingo)
        
        texto_actual, registro_bloqueos = self.obtener_estado_calendario()
        
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
                
                blob_name = f"{BLOB_WORKOUTS_PREFIX}{fecha}_{deporte}_{timestamp}_{idx}.json"
                contenido_json = json.dumps(ent, indent=4, ensure_ascii=False)
                
                exito = self.blob_manager.guardar_texto(blob_name, contenido_json)
                if exito:
                    print(f"[Éxito] Nuevo JSON nativo generado e inyectado en Azure: {blob_name}")
                    eventos_guardados += 1
                else:
                    print(f"[Error] Falló la escritura de {blob_name} en la nube.")
            
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
