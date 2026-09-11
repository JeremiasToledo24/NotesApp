import os
import time
import uuid
from typing import Optional

import boto3
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import pymysql

from botocore.client import Config

# Configuración leída dinámicamente desde variables de entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "prod_app")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "notesdb_prod")
S3_BUCKET = os.getenv("S3_BUCKET", "notesapp-storage-jeremias")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")

# Cliente S3 regional (aprovecha automáticamente el IAM Role asociado a la instancia EC2)
s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)


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


def get_presigned_url(file_key: Optional[str], expiration: int = 900) -> Optional[str]:
    """Genera una URL prefirmada temporal (15 minutos) para acceder a un objeto privado en S3."""
    if not file_key:
        return None
    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": file_key},
            ExpiresIn=expiration,
        )
        return url
    except Exception as e:
        print(f"Aviso: No se pudo generar la presigned URL para {file_key}: {e}")
        return None


app = FastAPI(
    title=f"NotesApp ({ENVIRONMENT.upper()})",
    description=f"Aplicación NotesApp corriendo en ambiente de {ENVIRONMENT.upper()} con soporte para Amazon S3",
    version="2.0.0",
)


class NoteCreate(BaseModel):
    title: str
    content: str
    file_key: Optional[str] = None
    file_name: Optional[str] = None


@app.get("/api/health")
def health_check():
    """Endpoint de diagnóstico que reporta ambiente, estado de base de datos y bucket S3."""
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
            "s3_bucket": S3_BUCKET,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "environment": ENVIRONMENT,
            "db_connected": False,
            "database_name": DB_NAME,
            "error": str(e),
            "db_host": DB_HOST,
            "s3_bucket": S3_BUCKET,
        }


@app.get("/api/notes")
def list_notes():
    """Devuelve la lista de notas de este ambiente en formato JSON incluyendo URLs prefirmadas."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, content, file_key, file_name, created_at FROM notes ORDER BY id DESC;"
            )
            notes = cursor.fetchall()
        conn.close()
        for note in notes:
            note["presigned_url"] = get_presigned_url(note.get("file_key"))
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
                "INSERT INTO notes (title, content, file_key, file_name) VALUES (%s, %s, %s, %s);",
                (note.title, note.content, note.file_key, note.file_name),
            )
            note_id = cursor.lastrowid
        conn.close()
        return {
            "id": note_id,
            "environment": ENVIRONMENT,
            "title": note.title,
            "content": note.content,
            "file_key": note.file_key,
            "file_name": note.file_name,
            "presigned_url": get_presigned_url(note.file_key),
            "message": f"Nota guardada en {DB_NAME}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/notes")
async def create_note_form(
    title: str = Form(...),
    content: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    """Maneja el formulario HTML, procesa la subida a S3 si existe adjunto y redirige."""
    file_key = None
    file_name = None

    if file and file.filename:
        safe_filename = os.path.basename(file.filename)
        unique_id = uuid.uuid4().hex[:8]
        file_key = f"{ENVIRONMENT}/{unique_id}_{safe_filename}"
        file_name = safe_filename

        try:
            file_bytes = await file.read()
            content_type = file.content_type or "application/octet-stream"
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=file_key,
                Body=file_bytes,
                ContentType=content_type,
            )
        except Exception as e:
            print(f"Error cargando archivo a S3: {e}")
            raise HTTPException(status_code=500, detail=f"Error cargando archivo a S3: {e}")

    create_note(NoteCreate(title=title, content=content, file_key=file_key, file_name=file_name))
    return RedirectResponse(url="/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index():
    """Panel visual interactivo con tema adaptable según el ambiente y soporte de adjuntos."""
    health = health_check()
    db_connected = health.get("db_connected", False)
    db_version = health.get("engine_version", "Desconectado")
    latency = health.get("latency_ms", "N/A")

    is_prod = ENVIRONMENT == "production"
    env_name = "PRODUCCION (Estable)" if is_prod else "DESARROLLO (Sandbox / Pruebas)"
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
                cursor.execute(
                    "SELECT id, title, content, file_key, file_name, created_at FROM notes ORDER BY id DESC;"
                )
                notes_list = cursor.fetchall()
            conn.close()
        except Exception:
            pass

    notes_html = ""
    if notes_list:
        for n in notes_list:
            attachment_html = ""
            file_key = n.get("file_key")
            file_name = n.get("file_name")
            if file_key and file_name:
                presigned_url = get_presigned_url(file_key)
                if presigned_url:
                    is_image = any(
                        file_name.lower().endswith(ext)
                        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]
                    )
                    if is_image:
                        attachment_html = f"""
                        <div class="note-attachment">
                            <a href="{presigned_url}" target="_blank" rel="noopener noreferrer">
                                <img src="{presigned_url}" alt="{file_name}" class="attachment-preview">
                            </a>
                            <div class="attachment-info">
                                <span>Adjunto:</span>
                                <a href="{presigned_url}" target="_blank" rel="noopener noreferrer">{file_name}</a>
                                <span class="s3-tag">S3 Privado (Presigned)</span>
                            </div>
                        </div>
                        """
                    else:
                        attachment_html = f"""
                        <div class="note-attachment">
                            <div class="attachment-info">
                                <span>Adjunto:</span>
                                <a href="{presigned_url}" target="_blank" rel="noopener noreferrer">{file_name}</a>
                                <span class="s3-tag">S3 Privado (Presigned)</span>
                            </div>
                        </div>
                        """

            notes_html += f"""
            <div class="note-card">
                <h3>{n['title']} <span class="note-id">#{n['id']}</span></h3>
                <p>{n['content']}</p>
                {attachment_html}
                <small class="note-date">{n['created_at']}</small>
            </div>
            """
    else:
        notes_html = f"<p class='empty-state'>Aun no hay notas en {DB_NAME}. Crea la primera abajo.</p>"

    badge_status_class = "badge-success" if db_connected else "badge-error"
    badge_status_text = (
        f"Conectado a {DB_NAME} ({db_version}) - {latency} ms"
        if db_connected
        else f"Sin conexion: {health.get('error', '')}"
    )

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NotesApp - {ENVIRONMENT.upper()}</title>
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
        input[type="file"] {{
            width: 100%;
            padding: 8px;
            border-radius: 8px;
            border: 1px dashed #475569;
            background: #0f172a;
            color: #94a3b8;
            box-sizing: border-box;
            font-family: inherit;
            font-size: 13px;
        }}
        input[type="text"]:focus, textarea:focus, input[type="file"]:focus {{
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
        .note-attachment {{
            margin-top: 10px;
            margin-bottom: 10px;
            padding: 10px 14px;
            background: #0f172a;
            border-radius: 8px;
            border: 1px solid #334155;
        }}
        .attachment-preview {{
            max-width: 100%;
            max-height: 200px;
            border-radius: 6px;
            display: block;
            margin-bottom: 8px;
            border: 1px solid #334155;
        }}
        .attachment-info {{
            font-size: 13px;
            color: #94a3b8;
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .attachment-info a {{
            color: #38bdf8;
            text-decoration: none;
            font-weight: 500;
        }}
        .attachment-info a:hover {{
            text-decoration: underline;
        }}
        .s3-tag {{
            display: inline-block;
            font-size: 11px;
            background: #0369a1;
            color: #e0f2fe;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 500;
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
            <h1>NotesApp - EC2, RDS &amp; S3</h1>
            <p class="subtitle">Base de datos activa: <strong>{DB_NAME}</strong> | Bucket S3: <strong>{S3_BUCKET}</strong></p>
            <div class="badge {badge_status_class}">{badge_status_text}</div>
            <div class="links">
                <a href="/docs" target="_blank">Swagger Docs</a>
                <a href="/api/health" target="_blank">Health Check JSON</a>
                <a href="/api/notes" target="_blank">API Notes JSON</a>
            </div>
        </div>

        <div class="form-section">
            <h2 style="margin-top:0; font-size:18px;">Crear Nota en {ENVIRONMENT.upper()}</h2>
            <form action="/notes" method="POST" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="title">Titulo:</label>
                    <input type="text" id="title" name="title" placeholder="Titulo de la nota" required>
                </div>
                <div class="form-group">
                    <label for="content">Contenido:</label>
                    <textarea id="content" name="content" rows="3" placeholder="Contenido o descripcion..." required></textarea>
                </div>
                <div class="form-group">
                    <label for="file">Archivo o imagen adjunta (opcional):</label>
                    <input type="file" id="file" name="file">
                    <small style="color: #64748b; display:block; margin-top:4px;">
                        Se almacena cifrado en S3 y se sirve mediante URLs prefirmadas temporales.
                    </small>
                </div>
                <button type="submit">Guardar en {DB_NAME}</button>
            </form>
        </div>

        <div>
            <h2 style="font-size:18px;">Notas en {DB_NAME}</h2>
            {notes_html}
        </div>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
