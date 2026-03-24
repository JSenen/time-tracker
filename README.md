# Time Tracker

Aplicación web sencilla para registrar horas trabajadas por proyecto y categoría.

## Qué hace ahora mismo

- Alta y listado de proyectos
- Color por proyecto para distinguirlos visualmente
- Alta y listado de categorías
- Alta, edición y borrado de entradas de tiempo
- Histórico de horas agrupado por proyecto, con paneles plegables y resumen facturable
- Filtro del histórico por rango de fechas
- Dashboard con métricas generales y desglose por proyecto/categoría
- Arranque con `docker compose`
- Administración de PostgreSQL con `pgAdmin`

## Stack

- Python 3.11
- Flask
- Flask-SQLAlchemy
- PostgreSQL 16
- Bootstrap 5

## Estructura

```text
.
├── app/
│   ├── __init__.py        # Factory de Flask y arranque de SQLAlchemy
│   ├── config.py          # Configuración por variables de entorno
│   ├── models.py          # Modelos Project, Category y TimeEntry
│   ├── routes.py          # Rutas, validaciones, agrupaciones y acciones CRUD
│   ├── static/
│   │   └── style.css      # Estilos del dashboard y de la vista agrupada de horas
│   └── templates/         # Plantillas Jinja2 de dashboard y CRUD
├── docker-compose.yml     # Servicios web + PostgreSQL
├── Dockerfile             # Imagen de la aplicación
├── requirements.txt       # Dependencias Python
└── run.py                 # Punto de entrada principal
```

## Variables de entorno

Se leen desde `.env`.

```env
FLASK_ENV=development
SECRET_KEY=cambia-esta-clave
DATABASE_URL=postgresql://timetracker:timetracker_pass@db:5432/timetracker
PGADMIN_DEFAULT_EMAIL=admin@timetracker.com
PGADMIN_DEFAULT_PASSWORD=cambia-esta-password
```

## Arranque con Docker

```bash
docker compose up --build
```

La aplicación queda disponible en:

```text
http://localhost:8000
```

`pgAdmin` queda disponible en:

```text
http://localhost:5050
```

Acceso inicial de `pgAdmin`:

- Email: valor de `PGADMIN_DEFAULT_EMAIL`
- Password: valor de `PGADMIN_DEFAULT_PASSWORD`

Para registrar el servidor PostgreSQL dentro de `pgAdmin`:

- Host: `db`
- Port: `5432`
- Database: `timetracker`
- Username: `timetracker`
- Password: `timetracker_pass`

## Arranque local sin Docker

1. Crear entorno virtual.
2. Instalar dependencias.
3. Configurar `DATABASE_URL`.
4. Ejecutar la app.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

## Pantallas disponibles

- `/` dashboard
- `/projects` proyectos
- `/categories` categorías
- `/entries` registro e histórico de horas agrupado por proyecto

## Modelo de datos

### `Project`

- nombre único
- cliente opcional
- color opcional
- descripción opcional
- flag `active`

### `Category`

- nombre único
- color opcional
- flag `active`

### `TimeEntry`

- proyecto
- categoría
- fecha de trabajo
- hora de inicio
- hora de fin
- duración en minutos
- descripción opcional
- facturable o no

## Estado actual y siguientes mejoras razonables

Pendiente de mejorar:

- validación de duplicados en proyectos y categorías con mensaje amigable
- manejo más fino de errores de base de datos
- acciones globales para expandir o contraer todos los proyectos en `/entries`
- tests automatizados persistentes

## Notas

- La base de datos se crea automáticamente al arrancar la aplicación.
- La vista `/entries` muestra métricas del filtro activo y agrupa las entradas por proyecto.
- `app/init.py` y `app/run.py` se mantienen como archivos de compatibilidad con una estructura anterior.
