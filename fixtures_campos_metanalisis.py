# -*- coding: utf-8 -*-
"""
Script para poblar la base de datos con campos predefinidos de metaanálisis
Ejecutar: python manage.py shell
         exec(open('fixtures_campos_metanalisis.py').read())
         crear_campos_predefinidos()
"""

from articulos.models import CampoMetanalisis

# Lista completa de campos basados en estándares de metaanálisis
CAMPOS_PREDEFINIDOS = [
    # ==================== IDENTIFICACION DEL ESTUDIO ====================
    {
        'nombre': 'Autor(es) principal(es)',
        'codigo': 'autor_principal',
        'categoria': 'IDENTIFICACION',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Apellido y nombre del primer autor o autores principales del estudio',
    },
    {
        'nombre': 'Año de publicación',
        'codigo': 'anio_publicacion',
        'categoria': 'IDENTIFICACION',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Año en que se publicó el estudio',
    },
    {
        'nombre': 'País del estudio',
        'codigo': 'pais_estudio',
        'categoria': 'IDENTIFICACION',
        'tipo_dato': 'TEXTO',
        'descripcion': 'País donde se realizó la investigación',
    },
    {
        'nombre': 'Revista/Journal',
        'codigo': 'revista',
        'categoria': 'IDENTIFICACION',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Nombre de la revista científica donde se publicó',
    },
    {
        'nombre': 'Factor de Impacto',
        'codigo': 'factor_impacto',
        'categoria': 'IDENTIFICACION',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Factor de impacto de la revista al momento de publicación',
    },
    
    # ==================== METODOLOGIA ====================
    {
        'nombre': 'Diseño del estudio',
        'codigo': 'diseno_estudio',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Tipo de diseño metodológico empleado',
        'opciones_validas': [
            'Experimental',
            'Cuasi-experimental',
            'Observacional',
            'Longitudinal',
            'Transversal',
            'Caso-control',
            'Cohorte',
            'Ensayo clínico aleatorizado (RCT)',
            'Revisión sistemática',
            'Otro'
        ]
    },
    {
        'nombre': 'Tipo de intervención/tratamiento',
        'codigo': 'tipo_intervencion',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Descripción de la intervención o tratamiento aplicado',
    },
    {
        'nombre': 'Grupo control',
        'codigo': 'grupo_control',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'SI_NO',
        'descripcion': '¿El estudio incluye grupo control?',
    },
    {
        'nombre': 'Tipo de control',
        'codigo': 'tipo_control',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Tipo de grupo control utilizado',
        'opciones_validas': [
            'Placebo',
            'Sin tratamiento',
            'Lista de espera',
            'Tratamiento estándar',
            'Atención habitual',
            'Otro',
            'N/A'
        ]
    },
    {
        'nombre': 'Aleatorización',
        'codigo': 'aleatorizacion',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'SI_NO',
        'descripcion': '¿Se realizó asignación aleatoria de participantes?',
    },
    {
        'nombre': 'Cegamiento',
        'codigo': 'cegamiento',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Tipo de cegamiento empleado',
        'opciones_validas': [
            'Ninguno',
            'Simple ciego',
            'Doble ciego',
            'Triple ciego',
            'N/A'
        ]
    },
    {
        'nombre': 'Duración del estudio',
        'codigo': 'duracion_estudio',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Duración total del estudio (incluir unidad: días, semanas, meses, años)',
    },
    {
        'nombre': 'Seguimiento (follow-up)',
        'codigo': 'seguimiento',
        'categoria': 'METODOLOGIA',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Período de seguimiento post-intervención',
    },
    
    # ==================== MUESTRA Y PARTICIPANTES ====================
    {
        'nombre': 'Tamaño de muestra (n total)',
        'codigo': 'n_total',
        'categoria': 'MUESTRA',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Número total de participantes en el estudio',
    },
    {
        'nombre': 'Tamaño grupo experimental (n)',
        'codigo': 'n_experimental',
        'categoria': 'MUESTRA',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Número de participantes en grupo experimental/intervención',
    },
    {
        'nombre': 'Tamaño grupo control (n)',
        'codigo': 'n_control',
        'categoria': 'MUESTRA',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Número de participantes en grupo control',
    },
    {
        'nombre': 'Edad media',
        'codigo': 'edad_media',
        'categoria': 'MUESTRA',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Edad promedio de los participantes',
    },
    {
        'nombre': 'Desviación estándar edad',
        'codigo': 'edad_sd',
        'categoria': 'MUESTRA',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Desviación estándar de la edad',
    },
    {
        'nombre': 'Rango de edad',
        'codigo': 'rango_edad',
        'categoria': 'MUESTRA',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Rango de edad de los participantes (ej: 18-65 años)',
    },
    {
        'nombre': 'Porcentaje mujeres',
        'codigo': 'porcentaje_mujeres',
        'categoria': 'MUESTRA',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Porcentaje de participantes mujeres (0-100)',
    },
    {
        'nombre': 'Características población',
        'codigo': 'caracteristicas_poblacion',
        'categoria': 'MUESTRA',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Características específicas de la población estudiada',
    },
    {
        'nombre': 'Criterios de inclusión',
        'codigo': 'criterios_inclusion',
        'categoria': 'MUESTRA',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Criterios utilizados para incluir participantes',
    },
    {
        'nombre': 'Criterios de exclusión',
        'codigo': 'criterios_exclusion',
        'categoria': 'MUESTRA',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Criterios utilizados para excluir participantes',
    },
    {
        'nombre': 'Tasa de abandono (%)',
        'codigo': 'tasa_abandono',
        'categoria': 'MUESTRA',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Porcentaje de participantes que abandonaron el estudio',
    },
    
    # ==================== RESULTADOS ESTADISTICOS ====================
    {
        'nombre': 'Variable de resultado principal',
        'codigo': 'variable_resultado',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Variable dependiente o resultado principal medido',
    },
    {
        'nombre': 'Instrumento de medición',
        'codigo': 'instrumento_medicion',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Herramienta o escala utilizada para medir el resultado',
    },
    {
        'nombre': 'Media grupo experimental (pre)',
        'codigo': 'media_exp_pre',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Media del grupo experimental en pre-test',
    },
    {
        'nombre': 'DE grupo experimental (pre)',
        'codigo': 'de_exp_pre',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Desviación estándar grupo experimental pre-test',
    },
    {
        'nombre': 'Media grupo experimental (post)',
        'codigo': 'media_exp_post',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Media del grupo experimental en post-test',
    },
    {
        'nombre': 'DE grupo experimental (post)',
        'codigo': 'de_exp_post',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Desviación estándar grupo experimental post-test',
    },
    {
        'nombre': 'Media grupo control (pre)',
        'codigo': 'media_control_pre',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Media del grupo control en pre-test',
    },
    {
        'nombre': 'DE grupo control (pre)',
        'codigo': 'de_control_pre',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Desviación estándar grupo control pre-test',
    },
    {
        'nombre': 'Media grupo control (post)',
        'codigo': 'media_control_post',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Media del grupo control en post-test',
    },
    {
        'nombre': 'DE grupo control (post)',
        'codigo': 'de_control_post',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Desviación estándar grupo control post-test',
    },
    {
        'nombre': 'Valor p',
        'codigo': 'p_value',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Valor de probabilidad (p-value) del resultado principal',
    },
    {
        'nombre': 'Nivel de significación (α)',
        'codigo': 'alpha',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Nivel de significación estadística establecido (ej: 0.05)',
    },
    {
        'nombre': 'Intervalo de confianza',
        'codigo': 'intervalo_confianza',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Intervalo de confianza (ej: 95% IC [0.25, 0.85])',
    },
    {
        'nombre': 'Estadístico de prueba',
        'codigo': 'estadistico_prueba',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Tipo de test estadístico utilizado (t, F, χ², etc.)',
    },
    {
        'nombre': 'Valor del estadístico',
        'codigo': 'valor_estadistico',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Valor numérico del estadístico de prueba',
    },
    {
        'nombre': 'Grados de libertad',
        'codigo': 'grados_libertad',
        'categoria': 'RESULTADOS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Grados de libertad del estadístico',
    },
    
    # ==================== TAMAÑOS DE EFECTO ====================
    {
        'nombre': 'Cohen\'s d',
        'codigo': 'cohens_d',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Tamaño de efecto estandarizado Cohen\'s d',
    },
    {
        'nombre': 'Hedges\' g',
        'codigo': 'hedges_g',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Tamaño de efecto estandarizado Hedges\' g (corrección para muestras pequeñas)',
    },
    {
        'nombre': 'Glass\'s Delta',
        'codigo': 'glass_delta',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Tamaño de efecto Glass\'s Delta',
    },
    {
        'nombre': 'Odds Ratio (OR)',
        'codigo': 'odds_ratio',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Razón de momios para resultados dicotómicos',
    },
    {
        'nombre': 'Risk Ratio (RR)',
        'codigo': 'risk_ratio',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Razón de riesgo relativo',
    },
    {
        'nombre': 'Correlación (r)',
        'codigo': 'correlacion_r',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Coeficiente de correlación',
    },
    {
        'nombre': 'R² (R cuadrado)',
        'codigo': 'r_cuadrado',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Coeficiente de determinación',
    },
    {
        'nombre': 'Eta cuadrado (η²)',
        'codigo': 'eta_cuadrado',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Proporción de varianza explicada',
    },
    {
        'nombre': 'Omega cuadrado (ω²)',
        'codigo': 'omega_cuadrado',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Estimador insesgado de varianza explicada',
    },
    {
        'nombre': 'Partial Eta Squared',
        'codigo': 'partial_eta_squared',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Eta cuadrado parcial',
    },
    {
        'nombre': 'Number Needed to Treat (NNT)',
        'codigo': 'nnt',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Número necesario a tratar para observar un efecto',
    },
    {
        'nombre': 'Error estándar del efecto',
        'codigo': 'se_efecto',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Error estándar del tamaño del efecto',
    },
    {
        'nombre': 'Varianza del efecto',
        'codigo': 'varianza_efecto',
        'categoria': 'EFECTOS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Varianza del tamaño del efecto',
    },
    
    # ==================== CALIDAD DEL ESTUDIO ====================
    {
        'nombre': 'Puntuación escala Jadad',
        'codigo': 'jadad_score',
        'categoria': 'CALIDAD',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Puntuación de calidad metodológica (0-5)',
    },
    {
        'nombre': 'Puntuación escala PEDro',
        'codigo': 'pedro_score',
        'categoria': 'CALIDAD',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Escala PEDro de calidad metodológica (0-10)',
    },
    {
        'nombre': 'Riesgo de sesgo (overall)',
        'codigo': 'riesgo_sesgo',
        'categoria': 'CALIDAD',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Evaluación general del riesgo de sesgo',
        'opciones_validas': [
            'Bajo',
            'Moderado',
            'Alto',
            'Poco claro'
        ]
    },
    {
        'nombre': 'Sesgo de selección',
        'codigo': 'sesgo_seleccion',
        'categoria': 'CALIDAD',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Riesgo de sesgo en la selección de participantes',
        'opciones_validas': ['Bajo', 'Moderado', 'Alto', 'Poco claro']
    },
    {
        'nombre': 'Sesgo de realización',
        'codigo': 'sesgo_realizacion',
        'categoria': 'CALIDAD',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Riesgo de sesgo en la ejecución del estudio',
        'opciones_validas': ['Bajo', 'Moderado', 'Alto', 'Poco claro']
    },
    {
        'nombre': 'Sesgo de detección',
        'codigo': 'sesgo_deteccion',
        'categoria': 'CALIDAD',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Riesgo de sesgo en la medición de resultados',
        'opciones_validas': ['Bajo', 'Moderado', 'Alto', 'Poco claro']
    },
    {
        'nombre': 'Sesgo de desgaste',
        'codigo': 'sesgo_desgaste',
        'categoria': 'CALIDAD',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Riesgo de sesgo por pérdidas de seguimiento',
        'opciones_validas': ['Bajo', 'Moderado', 'Alto', 'Poco claro']
    },
    {
        'nombre': 'Sesgo de reporte',
        'codigo': 'sesgo_reporte',
        'categoria': 'CALIDAD',
        'tipo_dato': 'OPCIONES',
        'descripcion': 'Riesgo de sesgo en el reporte selectivo de resultados',
        'opciones_validas': ['Bajo', 'Moderado', 'Alto', 'Poco claro']
    },
    {
        'nombre': 'Conflictos de interés',
        'codigo': 'conflictos_interes',
        'categoria': 'CALIDAD',
        'tipo_dato': 'SI_NO',
        'descripcion': '¿Se reportan conflictos de interés?',
    },
    {
        'nombre': 'Fuente de financiamiento',
        'codigo': 'financiamiento',
        'categoria': 'CALIDAD',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Fuente de financiamiento del estudio',
    },
    
    # ==================== OTROS ====================
    {
        'nombre': 'Contexto/Setting',
        'codigo': 'contexto',
        'categoria': 'OTROS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Contexto donde se realizó el estudio (hospital, universidad, comunidad, etc.)',
    },
    {
        'nombre': 'Subgrupo analizado',
        'codigo': 'subgrupo',
        'categoria': 'OTROS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Si se analizó un subgrupo específico de la población',
    },
    {
        'nombre': 'Momento de medición',
        'codigo': 'momento_medicion',
        'categoria': 'OTROS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Momento temporal de la medición (baseline, post, follow-up)',
    },
    {
        'nombre': 'Efectos adversos reportados',
        'codigo': 'efectos_adversos',
        'categoria': 'OTROS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Efectos adversos o secundarios reportados',
    },
    {
        'nombre': 'Heterogeneidad (I²)',
        'codigo': 'i_cuadrado',
        'categoria': 'OTROS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Índice de heterogeneidad entre estudios (0-100%)',
    },
    {
        'nombre': 'Q de Cochran',
        'codigo': 'q_cochran',
        'categoria': 'OTROS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Estadístico Q de Cochran para heterogeneidad',
    },
    {
        'nombre': 'Tau² (Tau cuadrado)',
        'codigo': 'tau_cuadrado',
        'categoria': 'OTROS',
        'tipo_dato': 'NUMERO',
        'descripcion': 'Varianza entre estudios',
    },
    {
        'nombre': 'Notas adicionales',
        'codigo': 'notas',
        'categoria': 'OTROS',
        'tipo_dato': 'TEXTO',
        'descripcion': 'Cualquier observación o nota adicional relevante',
    },
]


def crear_campos_predefinidos():
    """Crea todos los campos predefinidos en la base de datos"""
    print("🚀 Iniciando creación de campos predefinidos de metaanálisis...")
    
    campos_creados = 0
    campos_existentes = 0
    
    for campo_data in CAMPOS_PREDEFINIDOS:
        campo, created = CampoMetanalisis.objects.get_or_create(
            codigo=campo_data['codigo'],
            defaults={
                'nombre': campo_data['nombre'],
                'categoria': campo_data['categoria'],
                'tipo_dato': campo_data['tipo_dato'],
                'descripcion': campo_data['descripcion'],
                'opciones_validas': campo_data.get('opciones_validas'),
                'es_predefinido': True,
                'activo': True,
            }
        )
        
        if created:
            campos_creados += 1
            print(f"✅ Creado: {campo.nombre}")
        else:
            campos_existentes += 1
            print(f"⏭️  Ya existe: {campo.nombre}")
    
    print("\n" + "="*60)
    print(f"📊 RESUMEN:")
    print(f"   Campos creados: {campos_creados}")
    print(f"   Campos ya existentes: {campos_existentes}")
    print(f"   Total en catálogo: {CampoMetanalisis.objects.filter(es_predefinido=True).count()}")
    print("="*60)
    print("\n✨ ¡Campos predefinidos listos para usar!\n")


# Para ejecutar directamente
if __name__ == '__main__':
    import django
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pymetanalisis.settings')
    django.setup()
    crear_campos_predefinidos()