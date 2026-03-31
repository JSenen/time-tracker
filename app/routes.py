"""HTTP routes and form helpers for the time tracker UI."""

import csv
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from io import StringIO

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app import db
from app.models import Project, Category, TimeEntry

main = Blueprint("main", __name__)

CHART_PALETTE = [
    "#198754",
    "#0d6efd",
    "#fd7e14",
    "#dc3545",
    "#20c997",
    "#6f42c1",
    "#ffc107",
    "#0dcaf0",
]


def calculate_duration_minutes(start_str: str, end_str: str) -> int:
    """Return the worked minutes between two HH:MM strings."""
    start_dt = datetime.strptime(start_str, "%H:%M")
    end_dt = datetime.strptime(end_str, "%H:%M")
    delta = end_dt - start_dt
    return int(delta.total_seconds() // 60)


def format_duration(minutes: int) -> str:
    """Render minutes as a human-friendly hours and minutes string."""
    hours, remainder = divmod(minutes or 0, 60)
    return f"{hours}h {remainder:02d}m"


def build_entries_url(filters=None, edit_id=None) -> str:
    """Build the entries URL keeping the active filters and edit context."""
    filters = filters or {}
    params = {}
    for field in ("start_date", "end_date", "project_id"):
        value = filters.get(field, "").strip()
        if value:
            params[field] = value
    if edit_id is not None:
        params["edit_id"] = edit_id
    return url_for("main.entries", **params)


def get_entry_filters(source) -> dict[str, str]:
    """Extract the active filters from request args or form data."""
    return {
        "start_date": source.get("start_date", "").strip(),
        "end_date": source.get("end_date", "").strip(),
        "project_id": source.get("filter_project_id", source.get("project_id", "")).strip(),
    }


def parse_optional_date(date_str: str):
    """Parse an ISO date string when present."""
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def parse_optional_project_id(project_id: str):
    """Return an integer project id when the filter is present."""
    if not project_id:
        return None
    return int(project_id)


def parse_entry_form(form):
    """Validate and normalize a time-entry form payload."""
    project_id = form.get("project_id", "").strip()
    category_id = form.get("category_id", "").strip()
    work_date = form.get("work_date", "").strip()
    start_time = form.get("start_time", "").strip()
    end_time = form.get("end_time", "").strip()
    description = form.get("description", "").strip()
    billable = form.get("billable") == "on"

    if not all([project_id, category_id, work_date, start_time, end_time]):
        return None, "Todos los campos obligatorios deben estar informados."

    try:
        parsed_data = {
            "project_id": int(project_id),
            "category_id": int(category_id),
            "work_date": datetime.strptime(work_date, "%Y-%m-%d").date(),
            "start_time": datetime.strptime(start_time, "%H:%M").time(),
            "end_time": datetime.strptime(end_time, "%H:%M").time(),
            "description": description or None,
            "billable": billable,
        }
    except ValueError:
        return None, "La fecha o la hora no tienen un formato válido."

    duration_minutes = calculate_duration_minutes(start_time, end_time)
    if duration_minutes <= 0:
        return None, "La hora de fin debe ser posterior a la hora de inicio."

    parsed_data["duration_minutes"] = duration_minutes
    return parsed_data, None


def get_entries_query(filters=None):
    """Return the historical entries query with optional date filters applied."""
    filters = filters or {}
    # Eager load project and category so the grouped history view can render without extra queries.
    query = TimeEntry.query.options(
        joinedload(TimeEntry.project),
        joinedload(TimeEntry.category),
    )

    try:
        if filters.get("start_date"):
            query = query.filter(TimeEntry.work_date >= parse_optional_date(filters["start_date"]))
        if filters.get("end_date"):
            query = query.filter(TimeEntry.work_date <= parse_optional_date(filters["end_date"]))
        if filters.get("project_id"):
            query = query.filter(TimeEntry.project_id == parse_optional_project_id(filters["project_id"]))
    except ValueError:
        raise ValueError("Alguno de los filtros no tiene un formato válido.")

    return query.order_by(TimeEntry.work_date.desc(), TimeEntry.start_time.desc())


def build_entry_form_data(entry=None):
    """Prepare values for the create/edit form."""
    if entry is None:
        return {
            "project_id": "",
            "category_id": "",
            "work_date": "",
            "start_time": "",
            "end_time": "",
            "description": "",
            "billable": True,
        }

    return {
        "project_id": entry.project_id,
        "category_id": entry.category_id,
        "work_date": entry.work_date.isoformat(),
        "start_time": entry.start_time.strftime("%H:%M"),
        "end_time": entry.end_time.strftime("%H:%M"),
        "description": entry.description or "",
        "billable": entry.billable,
    }


def build_entry_groups(entries_list):
    """Build per-project groups and totals for the collapsible history view."""
    grouped_entries = {}
    total_minutes = 0
    billable_minutes = 0

    for entry in entries_list:
        duration_minutes = entry.duration_minutes or 0
        total_minutes += duration_minutes
        if entry.billable:
            billable_minutes += duration_minutes

        project_id = entry.project_id
        if project_id not in grouped_entries:
            grouped_entries[project_id] = {
                "project": entry.project,
                "entries": [],
                "entry_count": 0,
                "total_minutes": 0,
                "billable_minutes": 0,
            }

        group = grouped_entries[project_id]
        group["entries"].append(entry)
        group["entry_count"] += 1
        group["total_minutes"] += duration_minutes
        if entry.billable:
            group["billable_minutes"] += duration_minutes

    return list(grouped_entries.values()), {
        "entry_count": len(entries_list),
        "project_count": len(grouped_entries),
        "total_minutes": total_minutes,
        "billable_minutes": billable_minutes,
    }


def get_chart_color(color_value: str | None, index: int) -> str:
    """Return the configured color or a fallback from the dashboard palette."""
    return color_value or CHART_PALETTE[index % len(CHART_PALETTE)]


def minutes_to_hours(minutes: int) -> float:
    """Convert minutes to decimal hours rounded for charts and exports."""
    return round((minutes or 0) / 60, 2)


def format_decimal_hours(minutes: int) -> str:
    """Render minutes as decimal hours with two digits for CSV output."""
    return f"{minutes_to_hours(minutes):.2f}"


def limit_chart_segments(items, limit=6, other_label="Otros"):
    """Collapse the tail of large doughnut charts into a single segment."""
    if len(items) <= limit:
        return items

    kept_items = items[: limit - 1]
    remaining_items = items[limit - 1 :]
    kept_items.append(
        {
            "label": other_label,
            "minutes": sum(item["minutes"] for item in remaining_items),
            "color": "#adb5bd",
        }
    )
    return kept_items


def build_dashboard_charts(project_breakdown, category_rows):
    """Prepare compact chart datasets for the dashboard."""
    project_items = [
        {
            "label": project["name"],
            "minutes": project["total_minutes"],
            "color": get_chart_color(project["color"], index),
        }
        for index, project in enumerate(project_breakdown)
        if project["total_minutes"] > 0
    ]

    category_totals = defaultdict(lambda: {"label": "", "minutes": 0, "color": None})
    for row in category_rows:
        category_totals[row.id]["label"] = row.name
        category_totals[row.id]["minutes"] += row.total_minutes or 0
        category_totals[row.id]["color"] = row.color

    category_items = sorted(
        category_totals.values(),
        key=lambda item: (-item["minutes"], item["label"].lower()),
    )
    category_items = limit_chart_segments(category_items, limit=6, other_label="Otras categorías")

    for index, item in enumerate(category_items):
        item["color"] = get_chart_color(item["color"], index + 2)

    return {
        "projects": {
            "labels": [item["label"] for item in project_items[:8]],
            "hours": [minutes_to_hours(item["minutes"]) for item in project_items[:8]],
            "colors": [item["color"] for item in project_items[:8]],
        },
        "categories": {
            "labels": [item["label"] for item in category_items],
            "hours": [minutes_to_hours(item["minutes"]) for item in category_items],
            "colors": [item["color"] for item in category_items],
        },
    }


def build_export_detail_rows(entries_list):
    """Return one CSV row per tracked time entry."""
    rows = []
    for entry in entries_list:
        rows.append(
            [
                entry.work_date.isoformat(),
                entry.project.name,
                entry.project.client_name or "",
                entry.category.name,
                entry.start_time.strftime("%H:%M"),
                entry.end_time.strftime("%H:%M"),
                format_decimal_hours(entry.duration_minutes),
                "Sí" if entry.billable else "No",
                entry.description or "",
            ]
        )
    return rows


def build_export_summary_rows(entries_list):
    """Aggregate the filtered entries by project and category for reporting."""
    grouped_rows = {}

    for entry in entries_list:
        key = (entry.project_id, entry.category_id)
        if key not in grouped_rows:
            grouped_rows[key] = {
                "project_name": entry.project.name,
                "client_name": entry.project.client_name or "",
                "category_name": entry.category.name,
                "entry_count": 0,
                "total_minutes": 0,
                "billable_minutes": 0,
            }

        row = grouped_rows[key]
        duration_minutes = entry.duration_minutes or 0
        row["entry_count"] += 1
        row["total_minutes"] += duration_minutes
        if entry.billable:
            row["billable_minutes"] += duration_minutes

    ordered_rows = sorted(
        grouped_rows.values(),
        key=lambda item: (-item["total_minutes"], item["project_name"].lower(), item["category_name"].lower()),
    )

    return [
        [
            row["project_name"],
            row["client_name"],
            row["category_name"],
            row["entry_count"],
            format_decimal_hours(row["total_minutes"]),
            format_decimal_hours(row["billable_minutes"]),
            format_decimal_hours(row["total_minutes"] - row["billable_minutes"]),
        ]
        for row in ordered_rows
    ]


def slugify_filename(value: str) -> str:
    """Build an ASCII-safe filename fragment."""
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-") or "todos"


def build_export_filename(mode: str, filters, selected_project=None) -> str:
    """Create a download filename that reflects the active filter context."""
    filename_parts = ["horas", mode]
    if selected_project is not None:
        filename_parts.append(slugify_filename(selected_project.name))
    if filters.get("start_date"):
        filename_parts.append(filters["start_date"])
    if filters.get("end_date"):
        filename_parts.append(filters["end_date"])
    return "-".join(filename_parts) + ".csv"


def build_csv_response(headers, rows, filename: str) -> Response:
    """Return a CSV attachment compatible with spreadsheet apps."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)

    response = Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@main.route("/")
def index():
    """Render the dashboard with the current high-level counters."""
    total_projects = Project.query.count()
    total_categories = Category.query.count()
    total_entries = TimeEntry.query.count()
    total_minutes = db.session.query(func.coalesce(func.sum(TimeEntry.duration_minutes), 0)).scalar() or 0

    project_totals = (
        db.session.query(
            Project.id,
            Project.name,
            Project.client_name,
            Project.color,
            func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("total_minutes"),
            func.count(TimeEntry.id).label("entry_count"),
        )
        .outerjoin(TimeEntry, TimeEntry.project_id == Project.id)
        .group_by(Project.id, Project.name, Project.client_name, Project.color)
        .order_by(func.coalesce(func.sum(TimeEntry.duration_minutes), 0).desc(), Project.name.asc())
        .all()
    )

    category_rows = (
        db.session.query(
            TimeEntry.project_id,
            Category.id,
            Category.name,
            Category.color,
            func.sum(TimeEntry.duration_minutes).label("total_minutes"),
        )
        .join(Category, Category.id == TimeEntry.category_id)
        .group_by(TimeEntry.project_id, Category.id, Category.name, Category.color)
        .all()
    )

    category_breakdown_map = defaultdict(list)
    for row in category_rows:
        category_breakdown_map[row.project_id].append(
            {
                "id": row.id,
                "name": row.name,
                "color": row.color,
                "minutes": row.total_minutes or 0,
            }
        )

    project_breakdown = []
    for row in project_totals:
        category_breakdown = sorted(
            category_breakdown_map.get(row.id, []),
            key=lambda item: (-item["minutes"], item["name"].lower()),
        )
        project_breakdown.append(
            {
                "id": row.id,
                "name": row.name,
                "client_name": row.client_name,
                "color": row.color,
                "total_minutes": row.total_minutes or 0,
                "entry_count": row.entry_count or 0,
                "category_breakdown": category_breakdown,
            }
        )

    dashboard_charts = build_dashboard_charts(project_breakdown, category_rows)

    return render_template(
        "index.html",
        total_projects=total_projects,
        total_categories=total_categories,
        total_entries=total_entries,
        total_hours=round(total_minutes / 60, 2),
        project_breakdown=project_breakdown,
        dashboard_charts=dashboard_charts,
        format_duration=format_duration,
    )


@main.route("/projects", methods=["GET", "POST"])
def projects():
    """Create projects and render the project list."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        client_name = request.form.get("client_name", "").strip()
        color = request.form.get("color", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("El nombre del proyecto es obligatorio.", "danger")
            return redirect(url_for("main.projects"))

        project = Project(
            name=name,
            client_name=client_name or None,
            color=color or None,
            description=description or None,
        )
        db.session.add(project)
        db.session.commit()
        flash("Proyecto creado correctamente.", "success")
        return redirect(url_for("main.projects"))

    projects_list = Project.query.order_by(Project.created_at.desc()).all()
    return render_template("projects.html", projects=projects_list)


@main.route("/categories", methods=["GET", "POST"])
def categories():
    """Create categories and render the category list."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        color = request.form.get("color", "").strip()

        if not name:
            flash("El nombre de la categoría es obligatorio.", "danger")
            return redirect(url_for("main.categories"))

        category = Category(name=name, color=color or None)
        db.session.add(category)
        db.session.commit()
        flash("Categoría creada correctamente.", "success")
        return redirect(url_for("main.categories"))

    categories_list = Category.query.order_by(Category.created_at.desc()).all()
    return render_template("categories.html", categories=categories_list)


@main.route("/entries", methods=["GET", "POST"])
def entries():
    """Create entries and render the filtered history grouped by project."""
    if request.method == "POST":
        filters = get_entry_filters(request.form)
        entry_data, error_message = parse_entry_form(request.form)
        if error_message:
            flash(error_message, "danger")
            return redirect(build_entries_url(filters))

        entry = TimeEntry(**entry_data)
        db.session.add(entry)

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("No se pudo guardar el registro de tiempo. Inténtalo de nuevo.", "danger")
            return redirect(build_entries_url(filters))

        flash("Registro de tiempo guardado correctamente.", "success")
        return redirect(build_entries_url(filters))

    filters = get_entry_filters(request.args)
    edit_id = request.args.get("edit_id", type=int)

    try:
        entries_list = get_entries_query(filters).all()
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.entries"))

    entry_groups, history_summary = build_entry_groups(entries_list)
    projects_list = Project.query.filter_by(active=True).order_by(Project.name.asc()).all()
    categories_list = Category.query.filter_by(active=True).order_by(Category.name.asc()).all()
    selected_project = next(
        (project for project in projects_list if str(project.id) == filters["project_id"]),
        None,
    )
    edit_entry = None

    if edit_id is not None:
        edit_entry = TimeEntry.query.get_or_404(edit_id)

    return render_template(
        "entries.html",
        entry_groups=entry_groups,
        history_summary=history_summary,
        projects=projects_list,
        categories=categories_list,
        edit_entry=edit_entry,
        form_data=build_entry_form_data(edit_entry),
        filters=filters,
        selected_project=selected_project,
        format_duration=format_duration,
    )


@main.route("/entries/export")
def export_entries():
    """Export the current filtered entry set as a CSV file."""
    filters = get_entry_filters(request.args)
    export_mode = request.args.get("mode", "summary").strip().lower()

    try:
        entries_list = get_entries_query(filters).all()
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.entries"))

    selected_project = None
    if filters.get("project_id"):
        selected_project = Project.query.get(parse_optional_project_id(filters["project_id"]))

    if export_mode == "detail":
        headers = [
            "Fecha",
            "Proyecto",
            "Cliente",
            "Categoría",
            "Inicio",
            "Fin",
            "Horas",
            "Facturable",
            "Descripción",
        ]
        rows = build_export_detail_rows(entries_list)
    else:
        headers = [
            "Proyecto",
            "Cliente",
            "Categoría",
            "Registros",
            "Horas totales",
            "Horas facturables",
            "Horas no facturables",
        ]
        rows = build_export_summary_rows(entries_list)
        export_mode = "summary"

    filename = build_export_filename(export_mode, filters, selected_project)
    return build_csv_response(headers, rows, filename)


@main.route("/entries/<int:entry_id>/edit", methods=["POST"])
def update_entry(entry_id):
    """Update an existing time entry from the shared entry form."""
    filters = get_entry_filters(request.form)
    entry = TimeEntry.query.get_or_404(entry_id)
    entry_data, error_message = parse_entry_form(request.form)

    if error_message:
        flash(error_message, "danger")
        return redirect(build_entries_url(filters, edit_id=entry_id))

    for field, value in entry_data.items():
        setattr(entry, field, value)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("No se pudo actualizar el registro de tiempo. Inténtalo de nuevo.", "danger")
        return redirect(build_entries_url(filters, edit_id=entry_id))

    flash("Registro de tiempo actualizado correctamente.", "success")
    return redirect(build_entries_url(filters))


@main.route("/entries/<int:entry_id>/delete", methods=["POST"])
def delete_entry(entry_id):
    """Delete one time entry and return to the filtered history."""
    filters = get_entry_filters(request.form)
    entry = TimeEntry.query.get_or_404(entry_id)
    db.session.delete(entry)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("No se pudo eliminar el registro de tiempo. Inténtalo de nuevo.", "danger")
        return redirect(build_entries_url(filters))

    flash("Registro de tiempo eliminado correctamente.", "success")
    return redirect(build_entries_url(filters))
