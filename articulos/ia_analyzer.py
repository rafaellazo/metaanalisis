# ==================== ANALIZADOR DE ARTÍCULOS CON IA ====================
# 🤖 Servicio de análisis usando OpenAI API
# Adaptado del script original para funcionar dentro de Django

import json
import time
from django.conf import settings
from django.core.files.storage import default_storage
from openai import OpenAI
from pypdf import PdfReader
from io import BytesIO

# Inicializar cliente OpenAI
client = OpenAI(api_key=settings.OPENAI_API_KEY)


# ==========================================================
# 1️⃣ EXTRAER TEXTO DEL PDF
# ==========================================================

def extraer_texto_pdf(archivo_pdf):
    """
    Extrae texto de un archivo PDF (puede ser FileField o path).
    
    Args:
        archivo_pdf: FileField de Django o path
        
    Returns:
        str: Texto extraído completo
    """
    try:
        # Si es FileField de Django
        if hasattr(archivo_pdf, 'read'):
            contenido = archivo_pdf.read()
            reader = PdfReader(BytesIO(contenido))
        else:
            # Si es path local
            with open(str(archivo_pdf), 'rb') as f:
                reader = PdfReader(f)
        
        texto = ""
        for page in reader.pages:
            contenido_pagina = page.extract_text()
            if contenido_pagina:
                texto += contenido_pagina + "\n"
        
        return texto
    
    except Exception as e:
        raise ValueError(f"Error extrayendo PDF: {str(e)}")


# ==========================================================
# 2️⃣ CONSTRUIR PROMPT DINÁMICO
# ==========================================================

def construir_prompt(campos_a_buscar):
    """
    Construye un prompt dinámico AGNÓSTICO que funciona con cualquier variable.
    Válido para campos globales, personalizados, estadísticos, sesgos, etc.
    
    Args:
        campos_a_buscar: List de objetos CampoMetanalisis
        
    Returns:
        str: Instrucciones para la IA
    """
    campos_lista = "\n".join([
        f"• {campo.codigo}: {campo.nombre}\n  Descripción: {campo.descripcion}"
        for campo in campos_a_buscar
    ])
    
    # JSON ejemplo (separado para evitar anidación excesiva en f-string)
    json_ejemplo = """{
  "analisis": {
    "codigo_campo": {
      "encontrado": true/false,
      "contexto": "valor específico encontrado en el artículo",
      "cita_textual": "frase exacta del artículo que lo prueba (máx 150 caracteres)",
      "confianza": "alta/media/baja"
    }
  }
}"""
    
    instruccion = f"""Eres un experto en análisis de artículos académicos. Tu tarea ÚNICA es extraer información específica de este artículo.

████████████████████████████████████████████████████████████
VARIABLES A BUSCAR (BÚSQUEDA INDEPENDIENTE PARA CADA UNA)
████████████████████████████████████████████████████████████

{campos_lista}


════════════════════════════════════════════════════════════
⚠️ INSTRUCCIONES CRÍTICAS
════════════════════════════════════════════════════════════

1️⃣ BÚSQUEDA INDEPENDIENTE POR VARIABLE
   → Cada variable se busca POR SEPARADO en el artículo
   → NO reutilices la misma cita/evidencia para múltiples variables
   → Cada variable debe tener su propia evidencia DIFERENTE
   → Si no encuentras una cita clara y específica → encontrado=false

2️⃣ VALIDACIÓN DE EVIDENCIA
   → La cita_textual DEBE basarse en el artículo (exacta o paráfrasis clara)
   → NO inventar citas completamente fabricadas
   → La cita debe probar el "contexto" (puede ser inferencial)
   → Si no encuentras NINGUNA evidencia → encontrado=false

3️⃣ CONFIANZA DE BÚSQUEDA (2 niveles)
   → alta: Evidencia explícita, clara y directa en el artículo
   → media: Evidencia implícita, inferencial o parcialmente clara
   → Si no hay NADA → encontrado=false

4️⃣ N/A SOLO EN CASOS JUSTIFICADOS
   → Si el variable NO APLICA AL TIPO DE ARTÍCULO → contexto="N/A"
   → Ejemplos:
      • Artículo teórico: sesgos estadísticos → "N/A"
      • Sin datos empíricos: tamaño de muestra → "N/A"
      • Revisión de literatura: método propio → "N/A"
   → Pero EXPLICA POR QUÉ en la cita_textual

5️⃣ DETECCIÓN DE INCOMPATIBILIDADES
   → Si el artículo es NO EMPÍRICO (teórico, conceptual, filosófico)
      Y se busca una variable empírica → encontrado=false, contexto="N/A"
   → Ejemplo: Buscas "tamaño de muestra" en artículo teórico → N/A
   → NO asumas que siempre existe, valida el tipo de artículo primero


════════════════════════════════════════════════════════════
FLUJO DE ANÁLISIS PARA CADA VARIABLE
════════════════════════════════════════════════════════════

PASO 1: Lee la variable a buscar (nombre + descripción)
PASO 2: Determina si APLICA a este artículo
   ✗ Si NO aplica → encontrado=false, contexto="N/A"
   ✓ Si APLICA → continúa al PASO 3

PASO 3: Busca evidencia ESPECÍFICA (BÚSQUEDA MULTINIVEL)
   NIVEL 1 - BÚSQUEDA DIRECTA:
   - Busca el valor exacto (ej: nombre del país, institución, etc.)
   - Busca en: Abstract, Método, Afiliaciones, Resultados
   
   NIVEL 2 - REFERENCIAS INDIRECTAS (si Nivel 1 falla):
   - Para PAÍS: universidades, ciudades, códigos de país (BR=Brasil, ES=España)
   - Para PAÍS: regiones geográficas u organizaciones conocidas
   - INFIERE desde contexto cuando hay suficiente evidencia indirecta
   - NO inventes, INFIERE LÓGICAMENTE desde lo que existe
   
PASO 4: Extrae cita EXACTA del artículo
   - Si fue REFERENCIA INDIRECTA: cita la frase donde está esa evidencia
   - Copia literalmente (máx 150 caracteres)
   - El "contexto" en JSON debe ser PRECISO (ej: "Brasil", no "país sudamericano")

PASO 5: Asigna confianza
   - alta: Está explícitamente descrito (Nivel 1)
   - media: Fue necesaria inferencia desde referencias indirectas (Nivel 2)


════════════════════════════════════════════════════════════
CASOS ESPECIALES Y LIMITACIONES
════════════════════════════════════════════════════════════

📍 CASO 1: Variable estadística en artículo teórico
   → encontrado=false, contexto="N/A", cita="Artículo teórico sin datos empíricos"

📍 CASO 2: Variable mencionada pero no clara
   → encontrado=false, confianza=baja, cita="Mención ambigua sin claridad"

📍 CASO 3: Misma información para múltiples variables (PROHIBIDO)
   → ❌ NO hagas esto
   → Busca DIFERENTE evidencia para cada variable
   → Si realmente no hay más evidencia → encontrado=false para algunas

📍 CASO 4: Variable sobre limitaciones del estudio
   → Busca en sección "Limitations"
   → Si NO existe sección de limitaciones → encontrado=false
   → Si sí existe pero no menciona la variable → encontrado=false

📍 CASO 5: Variables que requieren inferencia (País, Institución, Afiliación)
   → Permitida BÚSQUEDA MULTINIVEL:
      • Nivel 1: Nombre directo (ej: "Brazil", "USA")
      • Nivel 2: Referencias indirectas (universidades, ciudades, códigos ISO)
      • Validación lógica de inferencia
   → EJEMPLOS:
      • "Universidad de São Paulo" → contexto="Brasil" (confianza=media)
      • "Johns Hopkins" → contexto="Estados Unidos" (confianza=media)
      • "Fundação para a Ciência e Tecnologia" → contexto="Portugal" (confianza=media)
   → El "contexto" en JSON es el VALOR INFERIDO (país), NO la referencia indirecta
   → Cita_textual es la FUENTE donde se encontró la referencia indirecta


════════════════════════════════════════════════════════════
FORMATO OBLIGATORIO DE RESPUESTA
════════════════════════════════════════════════════════════

Responde SOLO en JSON válido, SIN MARKDOWN, SIN TEXTO ADICIONAL:

{json_ejemplo}

REGLAS:
- Una entrada JSON por cada variable en "campos_lista" arriba
- Cada entrada DEBE tener: encontrado, contexto, cita_textual, confianza
- Cada cita_textual DEBE ser una frase exacta del artículo
- NO uses comillas dentro de cita_textual, escapa si es necesario
- Respuesta SOLO JSON, nada más


════════════════════════════════════════════════════════════
VALIDACIÓN FINAL
════════════════════════════════════════════════════════════

Antes de responder:
✓ ¿Cada variable tiene evidencia DIFERENTE?
✓ ¿Cada cita es exacta del artículo (no paráfrasis)?
✓ ¿Las variables incompatibles están marcadas como "N/A"?
✓ ¿No hay dos variables con la MISMA cita?
✓ ¿El "contexto" en JSON es PRECISO Y DIRECTO (no vago)?
✓ ¿Si hay inferencia indirecta, está VALIDADA en el artículo?
✓ ¿Respuesta es SOLO JSON?

Si CUALQUIERA falla → vuelve a analizar
"""
    return instruccion


# ==========================================================
# 3️⃣ TRUNCADO INTELIGENTE (para PDFs muy largos)
# ==========================================================

def truncado_inteligente(texto, limite=100_000):
    """
    Para PDFs muy largos, toma secciones relevantes.
    
    Args:
        texto: Texto completo del PDF
        limite: Máximo de caracteres
        
    Returns:
        str: Texto truncado inteligentemente
    """
    if len(texto) <= limite:
        return texto
    
    mitad = limite // 2
    
    # Buscar secciones clave
    secciones_clave = ["method", "result", "participant", "muestra", "análisis", "procedure", "design"]
    inicio_clave = len(texto)
    
    texto_lower = texto.lower()
    for seccion in secciones_clave:
        pos = texto_lower.find(seccion)
        if pos != -1 and pos < inicio_clave:
            inicio_clave = pos
    
    # Tomar inicio + sección clave
    inicio = texto[:mitad]
    zona_clave_inicio = max(0, inicio_clave - 500)
    zona_clave_fin = min(len(texto), zona_clave_inicio + mitad)
    zona_clave = texto[zona_clave_inicio:zona_clave_fin]
    
    return inicio + "\n\n[...SECCIÓN TRUNCADA...]\n\n" + zona_clave


# ==========================================================
# 4️⃣ ANALIZAR CON OPENAI (versión mejorada)
# ==========================================================

def analizar_articulo_con_ia(texto_articulo, campos_a_buscar):
    """
    Envía el artículo a OpenAI para análisis completo.
    
    Args:
        texto_articulo: Texto extraído del PDF
        campos_a_buscar: Queryset de CampoMetanalisis
        
    Returns:
        dict: {
            "exito": bool,
            "resultados": dict (JSON del análisis),
            "tokens": int,
            "tiempo": float,
            "error": str (si aplica)
        }
    """
    
    inicio_tiempo = time.time()
    
    try:
        # Validar que hay campos
        if not campos_a_buscar.exists():
            return {
                "exito": False,
                "error": "No hay campos para analizar",
                "resultados": None,
                "tokens": 0,
                "tiempo": 0
            }
        
        # Preparar texto (truncar si es necesario)
        if len(texto_articulo) > 100_000:
            texto_articulo = truncado_inteligente(texto_articulo)
        
        if len(texto_articulo) < 200:
            return {
                "exito": False,
                "error": "No se pudo extraer texto suficiente del PDF",
                "resultados": None,
                "tokens": 0,
                "tiempo": time.time() - inicio_tiempo
            }
        
        # Construir prompt
        prompt = construir_prompt(campos_a_buscar)
        
        # Llamar a OpenAI
        response = client.chat.completions.create(
            model="gpt-5-mini",  # 🆕 Usando gpt-5-mini (mejor precisión)
            messages=[
                {
                    "role": "system",
                    "content": "Eres un experto en análisis de artículos académicos. Respondes SOLO en JSON válido, sin explicaciones adicionales."
                },
                {
                    "role": "user",
                    "content": f"Artículo a analizar:\n\n{texto_articulo}\n\n{prompt}"
                }
            ],
            max_completion_tokens=8000,
        )
        
        # Extraer respuesta
        texto_respuesta = response.choices[0].message.content.strip() if response.choices[0].message.content else ""
        
        # Validar que la respuesta no esté vacía
        if not texto_respuesta:
            return {
                "exito": False,
                "error": "OpenAI devolvió una respuesta vacía. Intenta de nuevo o reduce el número de variables.",
                "resultados": None,
                "tokens": 0,
                "tiempo": time.time() - inicio_tiempo
            }
        
        # Limpiar markdown si está presente
        texto_respuesta = texto_respuesta.replace("```json", "").replace("```", "").strip()
        
        # Parsear JSON
        resultado_json = json.loads(texto_respuesta)
        
        # Calcular tokens
        tokens_input = response.usage.prompt_tokens
        tokens_output = response.usage.completion_tokens
        tokens_total = tokens_input + tokens_output
        
        tiempo_total = time.time() - inicio_tiempo
        
        return {
            "exito": True,
            "resultados": resultado_json.get("analisis", {}),
            "tokens": tokens_total,
            "tiempo": tiempo_total,
            "error": None
        }
    
    except json.JSONDecodeError as e:
        tiempo_total = time.time() - inicio_tiempo
        return {
            "exito": False,
            "error": f"Error parseando respuesta JSON: {str(e)}. Respuesta: {texto_respuesta[:200]}",
            "resultados": None,
            "tokens": 0,
            "tiempo": tiempo_total
        }
    
    except Exception as e:
        tiempo_total = time.time() - inicio_tiempo
        return {
            "exito": False,
            "error": f"Error en llamada a OpenAI: {str(e)}",
            "resultados": None,
            "tokens": 0,
            "tiempo": tiempo_total
        }


# ==========================================================
# 5️⃣ GUARDAR ANÁLISIS EN BD
# ==========================================================

def guardar_analisis_en_bd(articulo, proyecto, campos_analizados, resultados_ia, usuario, tokens=0):
    """
    Guarda los resultados del análisis en la BD.
    
    Args:
        articulo: Instancia de Articulo
        proyecto: Instancia de Proyecto
        campos_analizados: QuerySet de CampoMetanalisis
        resultados_ia: Dict con datos de OpenAI
        usuario: User que inició el análisis
        tokens: Cantidad de tokens utilizados
        
    Returns:
        AnalisisArticulo: Instancia guardada
    """
    from .models import AnalisisArticulo
    
    # Calcular costo (estimado)
    # GPT-4o mini: ~$0.00015 por 1K input tokens, ~$0.0006 por 1K output tokens
    costo_input = (resultados_ia.get("input_tokens", 0) / 1000) * 0.00015
    costo_output = (resultados_ia.get("output_tokens", 0) / 1000) * 0.0006
    costo_total = costo_input + costo_output
    
    analisis = AnalisisArticulo.objects.create(
        articulo=articulo,
        proyecto=proyecto,
        resultados=resultados_ia.get("resultados", {}),
        estado='COMPLETADO' if resultados_ia.get("exito") else 'ERROR',
        tokens_utilizados=tokens,
        costo_estimado=costo_total if costo_total > 0 else None,
        tiempo_procesamiento=int(resultados_ia.get("tiempo", 0)),
        analizado_por=usuario,
        mensaje_error=resultados_ia.get("error", "")
    )
    
    # Agregar campos analizados
    analisis.campos_analizados.set(campos_analizados)
    
    return analisis


# ==========================================================
# 6️⃣ PROCESAR ANÁLISIS COMPLETO (flujo integrado)
# ==========================================================

def procesar_articulo_completo(articulo, campos_a_buscar, usuario):
    """
    Flujo completo: extrae PDF → analiza con IA → guarda resultados.
    
    Args:
        articulo: Instancia de Articulo
        campos_a_buscar: QuerySet de CampoMetanalisis
        usuario: User que inicia el análisis
        
    Returns:
        dict: {
            "exito": bool,
            "analisis": AnalisisArticulo instance o None,
            "mensaje": str,
            "detalles": dict
        }
    """
    
    try:
        # Paso 1: Validar que exista PDF
        if not articulo.archivo_pdf:
            return {
                "exito": False,
                "analisis": None,
                "mensaje": "El artículo no tiene PDF asociado",
                "detalles": {}
            }
        
        # Paso 2: Extraer texto
        try:
            texto_extraido = extraer_texto_pdf(articulo.archivo_pdf)
        except Exception as e:
            return {
                "exito": False,
                "analisis": None,
                "mensaje": f"Error extrayendo PDF: {str(e)}",
                "detalles": {}
            }
        
        # Paso 3: Analizar con IA
        resultado_ia = analizar_articulo_con_ia(texto_extraido, campos_a_buscar)
        
        if not resultado_ia["exito"]:
            return {
                "exito": False,
                "analisis": None,
                "mensaje": resultado_ia["error"],
                "detalles": {
                    "tokens": resultado_ia["tokens"],
                    "tiempo": resultado_ia["tiempo"]
                }
            }
        
        # Paso 4: Guardar en BD
        analisis = guardar_analisis_en_bd(
            articulo=articulo,
            proyecto=articulo.proyecto,
            campos_analizados=campos_a_buscar,
            resultados_ia=resultado_ia,
            usuario=usuario,
            tokens=resultado_ia["tokens"]
        )
        
        return {
            "exito": True,
            "analisis": analisis,
            "mensaje": f"Análisis completado en {resultado_ia['tiempo']:.2f} segundos",
            "detalles": {
                "tokens": resultado_ia["tokens"],
                "tiempo": resultado_ia["tiempo"],
                "campos_analizados": len(campos_a_buscar)
            }
        }
    
    except Exception as e:
        return {
            "exito": False,
            "analisis": None,
            "mensaje": f"Error inesperado: {str(e)}",
            "detalles": {}
        }
