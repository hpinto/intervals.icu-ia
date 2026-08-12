import os
import sys
import glob
import json
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from intervals_utils import WORKOUTS_DIR

class ZWOConverter:
    def __init__(self):
        # Mapeo estricto del centro de las zonas de potencia a ratios decimales
        self.zonas_potencia = {
            'Z1': 0.55, 'Z2': 0.75, 'Z3': 0.90, 'Z4': 1.05,
            'Z5': 1.15, 'Z6': 1.30, 'Z7': 1.50
        }
        self.autor = "Héctor Alejandro Pinto Fernández"

    def _prettify(self, elem):
        rough_string = ET.tostring(elem, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")

    def _parsear_duracion(self, duration_str):
        duration_str = duration_str.lower()
        total_segundos = 0
        match_h = re.search(r'(\d+)h', duration_str)
        if match_h: total_segundos += int(match_h.group(1)) * 3600
        match_m = re.search(r'(\d+)(?:m|min)', duration_str)
        if match_m: total_segundos += int(match_m.group(1)) * 60
        match_s = re.search(r'(\d+)s', duration_str)
        if match_s: total_segundos += int(match_s.group(1))
        return total_segundos

    def _parsear_potencia(self, intensity_str):
        match_pct = re.search(r'(\d+)%', intensity_str)
        if match_pct: return float(match_pct.group(1)) / 100.0
        for zona, ratio in self.zonas_potencia.items():
            if zona in intensity_str: return ratio
        return 0.50

    def procesar_json_a_zwo(self, json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except json.JSONDecodeError:
            print(f"[Error Crítico] El archivo {json_path} no es un JSON válido.")
            return False

        if payload.get("type") != "Ride":
            print(f"[Suposición] El archivo {os.path.basename(json_path)} no es de ciclismo. Conversión ZWO omitida.")
            return False

        workout_file = ET.Element("workout_file")
        ET.SubElement(workout_file, "author").text = self.autor
        ET.SubElement(workout_file, "name").text = payload.get("name", "Entrenamiento Indoor")
        ET.SubElement(workout_file, "description").text = payload.get("description", "Generado por IA")
        ET.SubElement(workout_file, "sportType").text = "bike"
        ET.SubElement(workout_file, "tags")
        
        workout_element = ET.SubElement(workout_file, "workout")
        doc = payload.get("workout_doc", "")
        lineas = doc.split('\n')
        
        bloque_actual = ""
        repeticiones = 1
        pasos_bucle = []

        def procesar_paso(linea):
            texto_limpio = linea.strip('- ').strip()
            match = re.match(r'^((?:\d+[hms]\s*)+)(.*)', texto_limpio, re.IGNORECASE)
            if not match: return None
            tiempo_str = match.group(1).strip()
            intensidad_str = match.group(2).strip()
            return {
                "duration": self._parsear_duracion(tiempo_str),
                "power": self._parsear_potencia(intensidad_str)
            }

        def inyectar_nodos_xml():
            nonlocal pasos_bucle, repeticiones, bloque_actual
            if not pasos_bucle: return
            
            if "warmup" in bloque_actual.lower() and len(pasos_bucle) == 1:
                step = ET.SubElement(workout_element, "Warmup")
                step.set("Duration", str(pasos_bucle[0]["duration"]))
                step.set("PowerLow", "0.40")
                step.set("PowerHigh", str(pasos_bucle[0]["power"]))
            elif "cooldown" in bloque_actual.lower() and len(pasos_bucle) == 1:
                step = ET.SubElement(workout_element, "Cooldown")
                step.set("Duration", str(pasos_bucle[0]["duration"]))
                step.set("PowerLow", str(pasos_bucle[0]["power"]))
                step.set("PowerHigh", "0.25")
            elif repeticiones > 1 and len(pasos_bucle) == 2:
                step = ET.SubElement(workout_element, "IntervalsT")
                step.set("Repeat", str(repeticiones))
                step.set("OnDuration", str(pasos_bucle[0]["duration"]))
                step.set("OffDuration", str(pasos_bucle[1]["duration"]))
                step.set("OnPower", str(pasos_bucle[0]["power"]))
                step.set("OffPower", str(pasos_bucle[1]["power"]))
            else:
                for _ in range(repeticiones):
                    for p in pasos_bucle:
                        step = ET.SubElement(workout_element, "SteadyState")
                        step.set("Duration", str(p["duration"]))
                        step.set("Power", str(p["power"]))
            
            pasos_bucle.clear()
            repeticiones = 1

        for linea in lineas:
            linea = linea.strip()
            if not linea: continue
            if not linea.startswith('-'):
                inyectar_nodos_xml()
                bloque_actual = linea
                match_rep = re.search(r'(\d+)x', linea, re.IGNORECASE)
                if match_rep:
                    repeticiones = int(match_rep.group(1))
            else:
                datos = procesar_paso(linea)
                if datos: pasos_bucle.append(datos)
        
        inyectar_nodos_xml()

        zwo_path = json_path.replace('.json', '.zwo')
        with open(zwo_path, 'w', encoding='utf-8') as f:
            f.write(self._prettify(workout_file))
        print(f"[Éxito] Archivo ZWO compilado matemáticamente: {zwo_path}")
        return True

    def convertir_directorio(self):
        archivos_json = glob.glob(os.path.join(WORKOUTS_DIR, "*.json"))
        if not archivos_json:
            print("[Info] No hay archivos JSON para convertir a ZWO.")
            return

        conversiones = 0
        for json_path in archivos_json:
            zwo_path = json_path.replace('.json', '.zwo')
            # Omitir si el ZWO ya existe y es más reciente que el JSON
            if os.path.exists(zwo_path) and os.path.getmtime(zwo_path) >= os.path.getmtime(json_path):
                continue
            
            if self.procesar_json_a_zwo(json_path):
                conversiones += 1

        if conversiones == 0:
            print("[Info] No se detectaron nuevos entrenamientos de ciclismo pendientes de conversión.")

if __name__ == "__main__":
    conversor = ZWOConverter()
    if len(sys.argv) > 1:
        # Modo manual: python3 workout_json2zwo.py /ruta/al/entreno.json
        conversor.procesar_json_a_zwo(sys.argv[1])
    else:
        # Modo masivo (Orquestador): escanea todo WORKOUTS_DIR
        conversor.convertir_directorio()
