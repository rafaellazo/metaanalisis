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
cd Pymns   # o el nombre de la carpeta donde quedó el proyecto
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

Aplicar migraciones (ya vienen incluidas en el repositorio, **no** ejecutes `makemigrations`):

```bash
python manage.py migrate
```

Esto crea las tablas y los roles base: `administrador`, `investigador` e `invitado`.

Cargar variables globales del sistema:

```bash
python manage.py shell
exec(open('fixtures_campos_metanalisis.py', encoding='utf-8').read())
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
ALLOWED_HOSTS=localhost,127.0.0.1
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=tu-email@gmail.com
EMAIL_HOST_PASSWORD=tu-password
OPENAI_API_KEY=sk-...   # solo para el análisis con IA
```

Si no defines `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD`, los correos se imprimen en la consola del servidor en lugar de enviarse.

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

### Aprobación de nuevas cuentas

Todo usuario que se registra recibe el rol **invitado** y ve la pantalla *"Cuenta Pendiente de Aprobación"*. El rol no cambia solo: un administrador debe entrar a `/usuarios/list/` (o a `/admin/` → Profiles) y cambiarlo a **investigador** (puede crear proyectos) o **administrador**.

Nota: *Colaborador* y *Supervisor* son roles **dentro de un proyecto**, no roles globales.

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

El proyecto usa SQLite si `POSTGRES_DB` no está definido. Para usar PostgreSQL, configura estas variables en el archivo `.env` de la raíz:

```dotenv
POSTGRES_DB=metanalisis_db
POSTGRES_USER=metanalisis_user
POSTGRES_PASSWORD=una-clave-segura
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
```

Instala el adaptador de PostgreSQL junto con las dependencias:

```bash
pip install -r requirements.txt
```

En Ubuntu/Debian, instala el servidor y crea un usuario y una base de datos:

```bash
sudo apt-get install postgresql postgresql-contrib
sudo -u postgres createuser --login metanalisis_user
sudo -u postgres createdb --owner=metanalisis_user metanalisis_db
```

En Windows, instala PostgreSQL y crea el usuario y la base de datos con pgAdmin o `psql`.

`python manage.py migrate` crea el esquema, pero no copia datos de SQLite. Antes de cambiar una base existente, conserva una copia de `db.sqlite3` y de los archivos en `media/`. La importación debe tener en cuenta que este proyecto crea roles, perfiles y plantillas mediante señales; una importación genérica con `dumpdata`/`loaddata` puede duplicar esos registros o cambiar cuál plantilla queda como predeterminada. Compara los conteos y las relaciones de ambas bases antes de retirar el respaldo SQLite.

Para un despliegue en producción, configura además `DEBUG=False` y `ALLOWED_HOSTS` en `.env`. Después aplica las migraciones y recolecta archivos estáticos:

```bash
python manage.py migrate
python manage.py collectstatic --noinput

# Cargar variables globales en producción
python manage.py shell
exec(open('fixtures_campos_metanalisis.py', encoding='utf-8').read())
crear_campos_predefinidos()
```

Ejecutar con servidor WSGI:

```bash
gunicorn pymetanalis.wsgi:application --bind 0.0.0.0:8000
```


## Licencia

Este proyecto es un producto UNEMI
