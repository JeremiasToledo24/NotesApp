import os
import time
from typing import Optional

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import pymysql

# Configuración leída dinámicamente desde variables de entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "prod_app")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "notesdb_prod")


def get_db_connection():
    """Conexión directa a MySQL según las variables de entorno del ambiente."""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        autocommit=True,
    )


app = FastAPI(
    title=f"NotesApp ({ENVIRONMENT.upper()})",
    description=f"Aplicación NotesApp corriendo en ambiente de {ENVIRONMENT.upper()}",
    version="1.0.0",
)


class NoteCreate(BaseModel):
    title: str
    content: str


@app.get("/api/health")
def health_check():
    """Endpoint de diagnóstico que reporta el ambiente y la conexión a la base de datos."""
    start_time = time.time()
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version;")
            row = cursor.fetchone()
        conn.close()
        latency_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "status": "healthy",
            "environment": ENVIRONMENT,
            "db_connected": True,
            "database_name": DB_NAME,
            "database_user": DB_USER,
            "engine_version": row["version"] if row else "unknown",
            "latency_ms": latency_ms,
            "db_host": DB_HOST,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "environment": ENVIRONMENT,
            "db_connected": False,
            "database_name": DB_NAME,
            "error": str(e),
            "db_host": DB_HOST,
        }


@app.get("/api/notes")
def list_notes():
    """Devuelve la lista de notas de este ambiente en formato JSON."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, title, content, created_at FROM notes ORDER BY id DESC;")
            notes = cursor.fetchall()
        conn.close()
        return {"environment": ENVIRONMENT, "database": DB_NAME, "notes": notes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/notes")
def create_note(note: NoteCreate):
    """Crea una nota en la base de datos de este ambiente vía JSON."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO notes (title, content) VALUES (%s, %s);",
                (note.title, note.content),
            )
            note_id = cursor.lastrowid
        conn.close()
        return {
            "id": note_id,
            "environment": ENVIRONMENT,
            "title": note.title,
            "content": note.content,
            "message": f"Nota guardada en {DB_NAME}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/notes")
def create_note_form(title: str = Form(...), content: str = Form(...)):
    """Maneja el formulario HTML y redirige a la página principal."""
    create_note(NoteCreate(title=title, content=content))
    return RedirectResponse(url="/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index():
    """Panel visual interactivo con tema adaptable según el ambiente."""
    health = health_check()
    db_connected = health.get("db_connected", False)
    db_version = health.get("engine_version", "Desconectado")
    latency = health.get("latency_ms", "N/A")

    is_prod = ENVIRONMENT == "production"
    env_name = "PRODUCCIÓN (Estable)" if is_prod else "DESARROLLO (Sandbox / Pruebas)"
    env_badge_color = "#38bdf8" if is_prod else "#fbbf24"
    env_badge_bg = "#0369a1" if is_prod else "#b45309"
    card_border_color = "#38bdf8" if is_prod else "#fbbf24"
    btn_color = "#0284c7" if is_prod else "#d97706"
    btn_hover = "#0369a1" if is_prod else "#b45309"

    notes_list = []
    if db_connected:
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, title, content, created_at FROM notes ORDER BY id DESC;")
                notes_list = cursor.fetchall()
            conn.close()
        except Exception:
            pass

    notes_html = ""
    if notes_list:
        for n in notes_list:
            notes_html += f"""
            <div class="note-card">
                <h3>{n['title']} <span class="note-id">#{n['id']}</span></h3>
                <p>{n['content']}</p>
                <small class="note-date">{n['created_at']}</small>
            </div>
            """
    else:
        notes_html = f"<p class='empty-state'>Aún no hay notas en {DB_NAME}. ¡Crea la primera abajo!</p>"

    badge_status_class = "badge-success" if db_connected else "badge-error"
    badge_status_text = f"Conectado a {DB_NAME} ({db_version}) - {latency} ms" if db_connected else f"Sin conexión: {health.get('error', '')}"

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NotesApp — {ENVIRONMENT.upper()}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #334155);
            padding: 24px;
            border-radius: 12px;
            margin-bottom: 24px;
            border: 1px solid #475569;
        }}
        .env-tag {{
            display: inline-block;
            background-color: {env_badge_bg};
            color: {env_badge_color};
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
            text-transform: uppercase;
        }}
        h1 {{
            margin: 0 0 10px 0;
            font-size: 24px;
            color: #f8fafc;
        }}
        .subtitle {{
            color: #94a3b8;
            margin: 0 0 15px 0;
            font-size: 14px;
        }}
        .badge {{
            display: inline-block;
            padding: 6px 12px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
        }}
        .badge-success {{
            background-color: #065f46;
            color: #6ee7b7;
            border: 1px solid #059669;
        }}
        .badge-error {{
            background-color: #7f1d1d;
            color: #fca5a5;
            border: 1px solid #dc2626;
        }}
        .form-section {{
            background: #1e293b;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 24px;
            border: 1px solid #334155;
        }}
        .form-group {{
            margin-bottom: 14px;
        }}
        label {{
            display: block;
            margin-bottom: 6px;
            font-size: 13px;
            color: #cbd5e1;
        }}
        input[type="text"], textarea {{
            width: 100%;
            padding: 10px;
            border-radius: 8px;
            border: 1px solid #475569;
            background: #0f172a;
            color: #f8fafc;
            box-sizing: border-box;
            font-family: inherit;
        }}
        input[type="text"]:focus, textarea:focus {{
            outline: none;
            border-color: {card_border_color};
        }}
        button {{
            background-color: {btn_color};
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.2s;
        }}
        button:hover {{
            background-color: {btn_hover};
        }}
        .note-card {{
            background: #1e293b;
            padding: 16px;
            border-radius: 10px;
            margin-bottom: 12px;
            border-left: 4px solid {card_border_color};
            border-top: 1px solid #334155;
            border-right: 1px solid #334155;
            border-bottom: 1px solid #334155;
        }}
        .note-card h3 {{
            margin: 0 0 6px 0;
            font-size: 16px;
            color: #f1f5f9;
        }}
        .note-id {{
            color: #64748b;
            font-size: 12px;
            font-weight: normal;
        }}
        .note-card p {{
            margin: 0 0 8px 0;
            color: #cbd5e1;
            font-size: 14px;
        }}
        .note-date {{
            color: #64748b;
            font-size: 11px;
        }}
        .empty-state {{
            text-align: center;
            color: #64748b;
            padding: 40px;
        }}
        .links {{
            margin-top: 15px;
            font-size: 13px;
        }}
        .links a {{
            color: {card_border_color};
            text-decoration: none;
            margin-right: 15px;
        }}
        .links a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="env-tag">Ambiente: {env_name}</div>
            <h1>🚀 NotesApp — EC2 &amp; RDS</h1>
            <p class="subtitle">Base de datos activa: <strong>{DB_NAME}</strong> | Usuario: <strong>{DB_USER}</strong></p>
            <div class="badge {badge_status_class}">{badge_status_text}</div>
            <div class="links">
                <a href="/docs" target="_blank">📖 Swagger Docs</a>
                <a href="/api/health" target="_blank">🩺 Health Check JSON</a>
                <a href="/api/notes" target="_blank">📦 API Notes JSON</a>
            </div>
        </div>

        <div class="form-section">
            <h2 style="margin-top:0; font-size:18px;">✍️ Crear Nota en {ENVIRONMENT.upper()}</h2>
            <form action="/notes" method="POST">
                <div class="form-group">
                    <label for="title">Título:</label>
                    <input type="text" id="title" name="title" placeholder="Título de la nota" required>
                </div>
                <div class="form-group">
                    <label for="content">Contenido:</label>
                    <textarea id="content" name="content" rows="3" placeholder="Contenido de la prueba..." required></textarea>
                </div>
                <button type="submit">Guardar en {DB_NAME}</button>
            </form>
        </div>

        <div>
            <h2 style="font-size:18px;">📋 Notas en {DB_NAME}</h2>
            {notes_html}
        </div>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
