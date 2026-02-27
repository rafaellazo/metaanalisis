# Sistema de Gestión de Proyectos de Metaanálisis

[![Django](https://img.shields.io/badge/Django-4.2+-092E20?style=flat&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
Sistema web integral para la gestión colaborativa de proyectos de metaanálisis científicos. Permite a equipos de investigación organizar, procesar, revisar y aprobar artículos científicos de manera estructurada.

## Características Principales

- Sistema de autenticación con roles diferenciados (Administrador, Investigador, Colaborador, Invitado)
- Importación masiva de artículos desde archivos BibTeX
- Plantillas personalizables con campos de extracción de datos
- Colaboración en equipo con sistema de invitaciones y permisos granulares
- Flujo de revisión y aprobación de artículos campo por campo
- Sistema de notificaciones in-app y por correo electrónico
- Estadísticas y dashboards con gráficos interactivos
- Variables globales y comunitarias reutilizables entre proyectos

## Tecnologías

- **Backend**: Django 4.2+
- **Base de datos**: SQLite (desarrollo) / PostgreSQL 14+ (producción)
- **Frontend**: Tailwind CSS + ApexCharts
- **Procesamiento**: bibtexparser para archivos BibTeX
- **Autenticación**: Django contrib.auth

## Inicio Rápido

### Prerrequisitos

- Python 3.10 o superior
- pip y virtualenv

### Instalación

Clonar el repositorio y crear entorno virtual:

```bash
git clone https://github.com/RonnyAreUneMi/Pymns.git
cd pymetanalisis
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Aplicar migraciones:

```bash
python manage.py makemigrations
python manage.py migrate
```

Cargar variables globales del sistema:

```bash
python manage.py shell
exec(open('fixtures_campos_metanalisis_completo.py').read())
crear_campos_predefinidos()
exit()
```

Crear usuario administrador:

```bash
python manage.py createsuperuser
```

Iniciar servidor de desarrollo:

```bash
python manage.py runserver
```

### Configuración

Crear archivo `.env` en la raíz del proyecto (opcional para desarrollo):

```
SECRET_KEY=tu-clave-secreta
DEBUG=True
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=tu-email@gmail.com
EMAIL_HOST_PASSWORD=tu-password
```

### Base de Datos

**Desarrollo**: El sistema usa SQLite por defecto (archivo `db.sqlite3`), ideal para desarrollo local.

**Producción**: Se recomienda PostgreSQL 14+ para entornos de producción por su mejor rendimiento y características avanzadas.

## Arquitectura

El sistema está construido con Django siguiendo un patrón MVT con tres aplicaciones principales:

### 1. Usuarios
Gestión de usuarios, perfiles y roles del sistema.

### 2. Pymetanalis
Gestión de proyectos, colaboradores, invitaciones y notificaciones.

### 3. Artículos
Gestión de artículos, campos de metaanálisis, asignaciones y revisiones.

## Flujo de Trabajo

1. **Creación de Proyecto**: El investigador crea un proyecto y define la plantilla con variables personalizadas
2. **Importación**: Subir archivos BibTeX que se procesan automáticamente
3. **Asignación**: Distribuir artículos entre colaboradores del equipo
4. **Extracción**: Completar campos de datos con sistema de autoguardado
5. **Revisión**: Supervisor revisa y aprueba o solicita correcciones
6. **Análisis**: Visualización de estadísticas y progreso del proyecto

## Roles y Permisos

### Administrador
Gestión completa del sistema, usuarios y proyectos globales.

### Investigador
Crear proyectos, definir plantillas, invitar colaboradores y supervisar revisiones.

### Colaborador
Trabajar en artículos asignados, completar campos y enviar a revisión.

### Invitado
Visualización de proyectos públicos sin permisos de edición.

## Estructura del Proyecto

```
sistema-metanalisis/
├── usuarios/          # App de gestión de usuarios
├── pymetanalis/       # App de gestión de proyectos
├── articulos/         # App de gestión de artículos
├── static/            # Archivos estáticos
├── templates/         # Templates base
├── config/            # Configuración Django
└── requirements.txt
```

## Características Avanzadas

### Plantillas Dinámicas
Sistema flexible de variables globales y personalizadas por proyecto con múltiples tipos de datos.

### Importación Inteligente
Procesamiento automático de archivos BibTeX con mapeo de más de 50 variantes de campos bibliográficos.

### Workspace Interactivo
Interfaz AJAX con autoguardado, indicadores de progreso y separación visual por estado de completitud.

### Sistema de Notificaciones
Notificaciones en tiempo real para invitaciones, revisiones, aprobaciones y cambios de estado.

### Dashboards Analíticos
Visualizaciones interactivas de progreso personal, estadísticas de proyecto y comparativas entre usuarios.

## Seguridad

- Protección CSRF en todos los formularios
- Autenticación requerida en vistas sensibles
- Validación de permisos a nivel de modelo
- Sanitización de inputs en procesamiento BibTeX
- Protección contra eliminación de datos aprobados

## Despliegue en Producción

### Configuración de Base de Datos PostgreSQL

Instalar PostgreSQL y crear base de datos:

```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# Crear base de datos
sudo -u postgres createdb metanalisis_db
sudo -u postgres createuser metanalisis_user
```

Configurar variables de entorno para producción:

```
DEBUG=False
ALLOWED_HOSTS=tu-dominio.com
DATABASE_URL=postgres://metanalisis_user:password@localhost:5432/metanalisis_db
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

Migrar a PostgreSQL y recolectar archivos estáticos:

```bash
python manage.py migrate
python manage.py collectstatic --noinput

# Cargar variables globales en producción
python manage.py shell
exec(open('fixtures_campos_metanalisis_completo.py').read())
crear_campos_predefinidos()
```

Ejecutar con servidor WSGI:

```bash
gunicorn pymetanalis.wsgi:application --bind 0.0.0.0:8000
```


## Licencia

Este proyecto es un producto UNEMI

