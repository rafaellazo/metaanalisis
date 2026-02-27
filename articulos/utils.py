import re
import PyPDF2
import pdfplumber
from docx import Document
from django.utils import timezone
import io

class ExtractorTexto:
    """Clase para extraer texto y metadata de diferentes tipos de archivos."""
    
    @staticmethod
    def extraer_de_pdf(archivo):
        """Extrae texto de un archivo PDF."""
        texto_completo = ""
        
        try:
            # Intentar con pdfplumber (mejor para PDFs con texto)
            archivo.seek(0)
            with pdfplumber.open(archivo) as pdf:
                for pagina in pdf.pages:
                    texto = pagina.extract_text()
                    if texto:
                        texto_completo += texto + "\n"
        except Exception as e1:
            print(f"Error con pdfplumber: {e1}, intentando con PyPDF2...")
            
            try:
                # Fallback a PyPDF2
                archivo.seek(0)
                pdf_reader = PyPDF2.PdfReader(archivo)
                for pagina in pdf_reader.pages:
                    texto = pagina.extract_text()
                    if texto:
                        texto_completo += texto + "\n"
            except Exception as e2:
                print(f"Error con PyPDF2: {e2}")
                raise Exception(f"No se pudo extraer texto del PDF: {str(e2)}")
        
        return texto_completo
    
    @staticmethod
    def extraer_de_docx(archivo):
        """Extrae texto de un archivo DOCX."""
        try:
            archivo.seek(0)
            doc = Document(archivo)
            texto_completo = ""
            
            for parrafo in doc.paragraphs:
                texto_completo += parrafo.text + "\n"
            
            return texto_completo
        except Exception as e:
            raise Exception(f"No se pudo extraer texto del DOCX: {str(e)}")
    
    @staticmethod
    def extraer_de_txt(archivo):
        """Extrae texto de un archivo TXT."""
        try:
            archivo.seek(0)
            contenido = archivo.read()
            
            # Intentar diferentes encodings
            encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
            
            for encoding in encodings:
                try:
                    if isinstance(contenido, bytes):
                        texto = contenido.decode(encoding)
                    else:
                        texto = contenido
                    return texto
                except (UnicodeDecodeError, AttributeError):
                    continue
            
            raise Exception("No se pudo decodificar el archivo TXT")
        except Exception as e:
            raise Exception(f"No se pudo leer el archivo TXT: {str(e)}")
    
    @staticmethod
    def extraer_metadata(texto):
        """Extrae metadata del texto usando expresiones regulares."""
        metadata = {
            'titulo': None,
            'autores': None,
            'abstract': None,
            'doi': None,
            'anio': None,
            'journal': None,
            'palabras_clave': None,
            'url': None
        }
        
        # Normalizar texto
        texto_limpio = ' '.join(texto.split())
        
        # Extraer DOI
        doi_pattern = r'(?:DOI|doi)[\s:]+([10]\.\d{4,}[^\s]+)'
        doi_match = re.search(doi_pattern, texto, re.IGNORECASE)
        if doi_match:
            metadata['doi'] = doi_match.group(1).strip()
        
        # Extraer año (buscar años entre 1900 y 2099)
        anio_pattern = r'\b(19|20)\d{2}\b'
        anios = re.findall(anio_pattern, texto)
        if anios:
            # Tomar el primer año encontrado
            metadata['anio'] = int(anios[0])
        
        # Extraer título (generalmente las primeras líneas del documento)
        lineas = texto.split('\n')
        lineas_no_vacias = [l.strip() for l in lineas if l.strip()]
        if lineas_no_vacias:
            # El título suele ser la primera línea significativa
            posibles_titulos = []
            for linea in lineas_no_vacias[:10]:  # Revisar las primeras 10 líneas
                if len(linea) > 20 and len(linea) < 300:  # Longitud razonable para un título
                    posibles_titulos.append(linea)
            
            if posibles_titulos:
                metadata['titulo'] = posibles_titulos[0]
        
        # Extraer abstract
        abstract_patterns = [
            r'(?:ABSTRACT|Abstract|Resumen|RESUMEN)[\s:]+(.{100,2000}?)(?:\n\n|Keywords|KEYWORDS|Palabras clave|Introduction|INTRODUCTION)',
            r'(?:ABSTRACT|Abstract)[\s:]+(.{100,2000}?)(?:\n\n|\n[A-Z])',
        ]
        
        for pattern in abstract_patterns:
            abstract_match = re.search(pattern, texto, re.IGNORECASE | re.DOTALL)
            if abstract_match:
                abstract_text = abstract_match.group(1).strip()
                # Limpiar el abstract
                abstract_text = ' '.join(abstract_text.split())
                metadata['abstract'] = abstract_text
                break
        
        # Extraer palabras clave
        keywords_patterns = [
            r'(?:Keywords|KEYWORDS|Palabras clave|PALABRAS CLAVE)[\s:]+(.+?)(?:\n\n|\n[A-Z]|Introduction|INTRODUCTION)',
        ]
        
        for pattern in keywords_patterns:
            keywords_match = re.search(pattern, texto, re.IGNORECASE | re.DOTALL)
            if keywords_match:
                keywords_text = keywords_match.group(1).strip()
                # Limpiar y formatear palabras clave
                keywords_text = re.sub(r'\n', ' ', keywords_text)
                keywords_text = re.sub(r'\s+', ' ', keywords_text)
                metadata['palabras_clave'] = keywords_text
                break
        
        # Extraer journal/revista
        journal_patterns = [
            r'(?:Published in|Journal|Revista)[\s:]+([A-Z][^\n]{10,100})',
        ]
        
        for pattern in journal_patterns:
            journal_match = re.search(pattern, texto, re.IGNORECASE)
            if journal_match:
                metadata['journal'] = journal_match.group(1).strip()
                break
        
        # Extraer autores (generalmente después del título)
        # Este es más complejo y puede necesitar ajustes según el formato
        if metadata['titulo'] and lineas_no_vacias:
            try:
                titulo_idx = next(i for i, l in enumerate(lineas_no_vacias) if metadata['titulo'] in l)
                if titulo_idx + 1 < len(lineas_no_vacias):
                    posible_autores = lineas_no_vacias[titulo_idx + 1]
                    # Verificar si parece una línea de autores
                    if re.search(r'[A-Z][a-z]+.*[A-Z][a-z]+', posible_autores) and len(posible_autores) < 200:
                        metadata['autores'] = posible_autores
            except StopIteration:
                pass
        
        return metadata
    
    @staticmethod
    def generar_bibtex_key(autores, anio):
        """Genera una clave BibTeX única."""
        if autores:
            # Obtener primer apellido del primer autor
            primer_autor = autores.split(';')[0].split(',')[0].strip()
            # Limpiar caracteres especiales
            primer_autor = re.sub(r'[^a-zA-Z]', '', primer_autor).lower()
        else:
            primer_autor = "unknown"
        
        if anio:
            return f"{primer_autor}{anio}"
        else:
            return f"{primer_autor}{timezone.now().year}"
    
    @staticmethod
    def generar_bibtex(metadata, bibtex_key):
        """Genera el formato BibTeX a partir de la metadata."""
        bibtex = f"@article{{{bibtex_key},\n"
        
        if metadata.get('autores'):
            bibtex += f"  author = {{{metadata['autores']}}},\n"
        
        if metadata.get('titulo'):
            bibtex += f"  title = {{{metadata['titulo']}}},\n"
        
        if metadata.get('anio'):
            bibtex += f"  year = {{{metadata['anio']}}},\n"
        
        if metadata.get('journal'):
            bibtex += f"  journal = {{{metadata['journal']}}},\n"
        
        if metadata.get('doi'):
            bibtex += f"  doi = {{{metadata['doi']}}},\n"
        
        if metadata.get('url'):
            bibtex += f"  url = {{{metadata['url']}}},\n"
        
        bibtex += "}"
        
        return bibtex
    
    @classmethod
    def procesar_archivo(cls, archivo, nombre_archivo):
        """Método principal para procesar cualquier tipo de archivo."""
        ext = nombre_archivo.lower().split('.')[-1]
        
        # Extraer texto según el tipo de archivo
        if ext == 'pdf':
            texto = cls.extraer_de_pdf(archivo)
        elif ext in ['doc', 'docx']:
            texto = cls.extraer_de_docx(archivo)
        elif ext == 'txt':
            texto = cls.extraer_de_txt(archivo)
        else:
            raise Exception(f"Formato de archivo no soportado: {ext}")
        
        # Extraer metadata
        metadata = cls.extraer_metadata(texto)
        
        # Valores por defecto si no se encontró información
        if not metadata['titulo']:
            metadata['titulo'] = f"Artículo extraído de {nombre_archivo}"
        
        if not metadata['autores']:
            metadata['autores'] = "Autor desconocido"
        
        if not metadata['abstract']:
            # Tomar los primeros 500 caracteres como abstract
            texto_limpio = ' '.join(texto.split())
            metadata['abstract'] = texto_limpio[:500] + "..." if len(texto_limpio) > 500 else texto_limpio
        
        if not metadata['anio']:
            metadata['anio'] = timezone.now().year
        
        if not metadata['palabras_clave']:
            metadata['palabras_clave'] = "pendiente de clasificación"
        
        return metadata, texto


# ==================== FUNCIONES PARA OBTENER PDFs DESDE DOI ====================

import requests
import json
from urllib.parse import quote


def obtener_pdf_desde_doi(doi):
    """
    Intenta obtener un PDF open access desde un DOI usando múltiples servicios.
    Retorna un diccionario con el resultado.
    """
    if not doi:
        return {'success': False, 'error': 'DOI no proporcionado'}

    # Limpiar DOI
    doi = doi.strip()
    if doi.startswith('doi:'):
        doi = doi[4:]
    if doi.startswith('DOI:'):
        doi = doi[4:]
    doi = doi.strip()

    resultados = {
        'doi': doi,
        'success': False,
        'pdf_url': None,
        'fuente': None,
        'licencia': None,
        'errores': []
    }

    # 1. INTENTAR CON UNPAYWALL (API gratuita y ética)
    try:
        # Unpaywall API - gratuita, sin rate limits estrictos para uso académico
        unpaywall_url = f"https://api.unpaywall.org/v2/{quote(doi)}?email=tu-email@institucion.edu"
        response = requests.get(unpaywall_url, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if data.get('is_oa', False) and data.get('best_oa_location'):
                oa_location = data['best_oa_location']

                # Verificar que sea PDF
                if oa_location.get('url_for_pdf'):
                    resultados['success'] = True
                    resultados['pdf_url'] = oa_location['url_for_pdf']
                    resultados['fuente'] = 'Unpaywall'
                    resultados['licencia'] = oa_location.get('license', 'Open Access')
                    return resultados
                elif oa_location.get('url'):
                    # Algunos repositorios dan URL directa
                    resultados['success'] = True
                    resultados['pdf_url'] = oa_location['url']
                    resultados['fuente'] = 'Unpaywall'
                    resultados['licencia'] = oa_location.get('license', 'Open Access')
                    return resultados

        resultados['errores'].append('Unpaywall: No se encontró versión open access')

    except Exception as e:
        resultados['errores'].append(f'Unpaywall error: {str(e)}')

    # 2. INTENTAR CON CROSSREF (para metadatos adicionales)
    try:
        crossref_url = f"https://api.crossref.org/works/{quote(doi)}"
        response = requests.get(crossref_url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            message = data.get('message', {})

            # Buscar links a PDFs
            links = message.get('link', [])
            for link in links:
                if link.get('content-type') == 'application/pdf' and link.get('URL'):
                    resultados['success'] = True
                    resultados['pdf_url'] = link['URL']
                    resultados['fuente'] = 'CrossRef'
                    resultados['licencia'] = link.get('content-version', 'Publisher')
                    return resultados

        resultados['errores'].append('CrossRef: No se encontraron links a PDF')

    except Exception as e:
        resultados['errores'].append(f'CrossRef error: {str(e)}')

    # 3. INTENTAR CON SEMANTIC SCHOLAR (último recurso ético)
    try:
        semantic_url = f"https://api.semanticscholar.org/v1/paper/{quote(doi)}"
        response = requests.get(semantic_url, timeout=10)

        if response.status_code == 200:
            data = response.json()

            # Buscar open access PDF
            if data.get('isOpenAccess') and data.get('openAccessPdf'):
                pdf_info = data['openAccessPdf']
                if pdf_info.get('url'):
                    resultados['success'] = True
                    resultados['pdf_url'] = pdf_info['url']
                    resultados['fuente'] = 'Semantic Scholar'
                    resultados['licencia'] = 'Open Access'
                    return resultados

        resultados['errores'].append('Semantic Scholar: No se encontró PDF open access')

    except Exception as e:
        resultados['errores'].append(f'Semantic Scholar error: {str(e)}')

    # Si no se encontró nada
    resultados['error'] = 'No se encontró versión open access del artículo'
    return resultados


def verificar_acceso_pdf(pdf_url):
    """
    Verifica si una URL de PDF es accesible haciendo una petición GET parcial.
    """
    try:
        # Hacer una petición GET con range para obtener solo los primeros 1024 bytes
        headers = {'Range': 'bytes=0-1023'}
        response = requests.get(pdf_url, timeout=10, headers=headers, allow_redirects=True)

        # Verificar que el status code sea 200 o 206 (partial content)
        if response.status_code in [200, 206]:
            # Verificar que el content-type sea PDF
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' in content_type or 'application/pdf' in content_type:
                return True

        return False
    except:
        return False


# ==================== 🆕 CONSULTAR UNPAYWALL API ====================

def consultar_open_access_unpaywall(doi):
    """
    Consulta Unpaywall API para verificar si un artículo está en Open Access.
    
    Args:
        doi: DOI del artículo (ej: "10.1371/journal.pone.0000000")
        
    Returns:
        dict: {
            'es_open_access': bool,
            'url_pdf': str (URL del PDF si está disponible),
            'error': str (si ocurre error)
        }
    """
    if not doi:
        return {
            'es_open_access': None,
            'url_pdf': None,
            'error': 'No DOI provided'
        }
    
    try:
        import requests
        
        # Limpiar DOI (remover "https://doi.org/" si está incluido)
        doi_limpio = doi.replace('https://doi.org/', '').replace('http://doi.org/', '').strip()
        
        # Llamar a Unpaywall API
        url = f'https://api.unpaywall.org/v2/{doi_limpio}?email=admin@pymetanalis.com'
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            datos = response.json()
            
            # Verificar si está en open access
            es_open_access = datos.get('is_oa', False)
            
            # Obtener URL del PDF si está disponible
            url_pdf = None
            if es_open_access:
                # Preferencia: best_oa_location > oa_locations
                best_location = datos.get('best_oa_location', {})
                if best_location and best_location.get('url'):
                    url_pdf = best_location.get('url')
                elif datos.get('oa_locations'):
                    url_pdf = datos['oa_locations'][0].get('url')
            
            return {
                'es_open_access': es_open_access,
                'url_pdf': url_pdf,
                'error': None
            }
        else:
            return {
                'es_open_access': None,
                'url_pdf': None,
                'error': f'API returned status {response.status_code}'
            }
            
    except Exception as e:
        return {
            'es_open_access': None,
            'url_pdf': None,
            'error': str(e)
        }
