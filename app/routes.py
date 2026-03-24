"""HTTP routes and form helpers for the time tracker UI."""

from collections import defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app import db
from app.models import Project, Category, TimeEntry

main = Blueprint("main", __name__)


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


def build_entries_url(start_date="", end_date="", edit_id=None) -> str:
    """Build the entries URL keeping the active filters and edit context."""
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if edit_id is not None:
        params["edit_id"] = edit_id
    return url_for("main.entries", **params)


def get_entry_filters(source) -> tuple[str, str]:
    """Extract the date filter values from request args or form data."""
    start_date = source.get("start_date", "").strip()
    end_date = source.get("end_date", "").strip()
    return start_date, end_date


def parse_optional_date(date_str: str):
    """Parse an ISO date string when present."""
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").date()


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


def get_entries_query(start_date="", end_date=""):
    """Return the historical entries query with optional date filters applied."""
    # Eager load project and category so the grouped history view can render without extra queries.
    query = TimeEntry.query.options(
        joinedload(TimeEntry.project),
        joinedload(TimeEntry.category),
    )

    try:
        if start_date:
            query = query.filter(TimeEntry.work_date >= parse_optional_date(start_date))
        if end_date:
            query = query.filter(TimeEntry.work_date <= parse_optional_date(end_date))
    except ValueError:
        raise ValueError("Alguna de las fechas del filtro no tiene un formato válido.")

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

    return render_template(
        "index.html",
        total_projects=total_projects,
        total_categories=total_categories,
        total_entries=total_entries,
        total_hours=round(total_minutes / 60, 2),
        project_breakdown=project_breakdown,
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
        start_date, end_date = get_entry_filters(request.form)
        entry_data, error_message = parse_entry_form(request.form)
        if error_message:
            flash(error_message, "danger")
            return redirect(build_entries_url(start_date, end_date))

        entry = TimeEntry(**entry_data)
        db.session.add(entry)

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("No se pudo guardar el registro de tiempo. Inténtalo de nuevo.", "danger")
            return redirect(build_entries_url(start_date, end_date))

        flash("Registro de tiempo guardado correctamente.", "success")
        return redirect(build_entries_url(start_date, end_date))

    start_date, end_date = get_entry_filters(request.args)
    edit_id = request.args.get("edit_id", type=int)

    try:
        entries_list = get_entries_query(start_date, end_date).all()
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.entries"))

    entry_groups, history_summary = build_entry_groups(entries_list)
    projects_list = Project.query.filter_by(active=True).order_by(Project.name.asc()).all()
    categories_list = Category.query.filter_by(active=True).order_by(Category.name.asc()).all()
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
        filters={"start_date": start_date, "end_date": end_date},
        format_duration=format_duration,
    )


@main.route("/entries/<int:entry_id>/edit", methods=["POST"])
def update_entry(entry_id):
    """Update an existing time entry from the shared entry form."""
    start_date, end_date = get_entry_filters(request.form)
    entry = TimeEntry.query.get_or_404(entry_id)
    entry_data, error_message = parse_entry_form(request.form)

    if error_message:
        flash(error_message, "danger")
        return redirect(build_entries_url(start_date, end_date, edit_id=entry_id))

    for field, value in entry_data.items():
        setattr(entry, field, value)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("No se pudo actualizar el registro de tiempo. Inténtalo de nuevo.", "danger")
        return redirect(build_entries_url(start_date, end_date, edit_id=entry_id))

    flash("Registro de tiempo actualizado correctamente.", "success")
    return redirect(build_entries_url(start_date, end_date))


@main.route("/entries/<int:entry_id>/delete", methods=["POST"])
def delete_entry(entry_id):
    """Delete one time entry and return to the filtered history."""
    start_date, end_date = get_entry_filters(request.form)
    entry = TimeEntry.query.get_or_404(entry_id)
    db.session.delete(entry)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("No se pudo eliminar el registro de tiempo. Inténtalo de nuevo.", "danger")
        return redirect(build_entries_url(start_date, end_date))

    flash("Registro de tiempo eliminado correctamente.", "success")
    return redirect(build_entries_url(start_date, end_date))
