"""Servidor privado de producción: python server.py (Railway / Docker)."""
from datetime import datetime
import os
from pathlib import Path
import re
import secrets
import signal
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

import agent
import ui


def production_config():
    if not agent.cloud_mode():
        raise ValueError('Configura APP_ENV=production. Para el panel local ejecuta ui.py.')
    username = os.getenv('ADMIN_USERNAME', 'admin')
    password = os.getenv('ADMIN_PASSWORD', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', username) or len(password) < 20:
        raise ValueError('Configura ADMIN_USERNAME y una ADMIN_PASSWORD única de al menos 20 caracteres.')
    origin = (os.getenv('PUBLIC_URL') or 'https://' + os.getenv('RAILWAY_PUBLIC_DOMAIN', '')).rstrip('/')
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Configura PUBLIC_URL con el origen HTTPS del panel, sin ruta ni parámetros.')
    if not os.getenv('VIDEO_DATA_DIR') or not os.getenv('VIDEO_CONFIG_DIR'):
        raise ValueError('Configura VIDEO_DATA_DIR y VIDEO_CONFIG_DIR dentro del volumen persistente.')
    paths = [Path(os.environ['VIDEO_DATA_DIR']), Path(os.environ['VIDEO_CONFIG_DIR'])]
    if any(not path.is_absolute() for path in paths):
        raise ValueError('Las rutas persistentes deben ser absolutas.')
    mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
    if os.getenv('RAILWAY_ENVIRONMENT_ID') and not mount:
        raise ValueError('Adjunta un volumen persistente al servicio de Railway.')
    if mount and (not Path(mount).is_dir() or any(not p.resolve().is_relative_to(Path(mount).resolve()) for p in paths)):
        raise ValueError('Los datos y la configuración deben quedar dentro del volumen de Railway.')
    if paths[0].resolve() == paths[1].resolve() or paths[1].resolve().is_relative_to(paths[0].resolve()):
        raise ValueError('Guarda la configuración privada fuera de la carpeta de trabajos.')
    if os.getenv('DAILY_RESEARCH_ENABLED', 'false') not in ('true', 'false'):
        raise ValueError('DAILY_RESEARCH_ENABLED debe ser true o false.')
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
        with (path / '.write-check').open('wb'):
            pass
        (path / '.write-check').unlink()
    agent.DATA = paths[0].resolve()
    agent.load_settings()
    return origin, username, password


def create_app():
    origin, username, password = production_config()
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=512_000)
    runtime = SimpleNamespace(token=secrets.token_urlsafe(32), mutation_lock=threading.Lock(),
                              activity=ui.Activity(agent.private_file('activity.json')), closing=False)
    app.extensions['video_runtime'] = runtime
    actions = ui.Actions(runtime)

    @app.before_request
    def protect():
        if request.path == '/healthz' and request.method in ('GET', 'HEAD'):
            return None
        if request.host.lower() != urlsplit(origin).netloc.lower():
            return jsonify(error='Dominio no permitido.'), 403
        # Railway termina TLS. No se confía en X-Forwarded-Host ni se construyen URLs con él.
        if request.headers.get('X-Forwarded-Proto', request.scheme) != 'https':
            return jsonify(error='Abre el panel por HTTPS.'), 403
        auth = request.authorization
        if not (auth and auth.type == 'basic'
                and secrets.compare_digest((auth.username or '').encode(), username.encode())
                and secrets.compare_digest((auth.password or '').encode(), password.encode())):
            return jsonify(error='Introduce el usuario y la contraseña del estudio.'), 401, {
                'WWW-Authenticate': 'Basic realm="VideoAgente", charset="UTF-8"'}
        if (request.headers.get('Origin') not in (None, origin)
                or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            return jsonify(error='Origen no permitido.'), 403
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not secrets.compare_digest(request.headers.get('X-Local-Token', '').encode(), runtime.token.encode()):
                return jsonify(error='La sesión cambió. Actualiza la página.'), 403
            if runtime.closing:
                return jsonify(error='El servidor se está reiniciando. Espera y actualiza.'), 503

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    @app.errorhandler(Exception)
    def failure(error):
        if isinstance(error, HTTPException):
            return jsonify(error='Solicitud o recurso no válido.'), error.code
        if isinstance(error, (ValueError, OSError, TypeError, KeyError)):
            return jsonify(error=str(error) if isinstance(error, ValueError) else 'No se pudo completar la acción.'), 400
        # Nunca incluir respuestas de proveedores, cabeceras o variables en los logs.
        app.logger.error('Error interno: %s', type(error).__name__)
        return jsonify(error='Error interno. Revisa el estado del trabajo.'), 500

    @app.get('/healthz')
    def health():
        return jsonify(status='stopping' if runtime.closing else 'ok'), 503 if runtime.closing else 200

    @app.get('/')
    def index():
        return send_file(ui.WEB / 'index.html')

    @app.get('/<name>')
    def static(name):
        if name not in ('app.js', 'style.css', 'icon.svg'):
            return jsonify(error='Recurso no encontrado.'), 404
        return send_file(ui.WEB / name)

    @app.get('/api/session')
    def session():
        return jsonify(token=runtime.token)

    @app.get('/api/status')
    def status():
        return jsonify(configuration=ui.configuration(), activity=runtime.activity.snapshot())

    @app.get('/api/jobs')
    def jobs():
        return jsonify(jobs=ui.all_jobs())

    @app.get('/api/jobs/<job_id>')
    def job(job_id):
        return jsonify(ui.job_info(ui.folder_for(job_id), detail=True))

    @app.get('/media/<job_id>/<kind>')
    def media(job_id, kind):
        if kind not in ui.MEDIA:
            return jsonify(error='Recurso no encontrado.'), 404
        name, mime = ui.MEDIA[kind]
        return send_file(ui.job_file(ui.folder_for(job_id), name), mimetype=mime, conditional=True)

    @app.post('/api/<path:action>')
    def mutate(action):
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Formulario inválido.')
        with runtime.mutation_lock:
            return jsonify(actions.action('/api/' + action, data))

    return app


class DailyResearch:
    """Una reserva persistente por día; solo investiga, nunca genera ni publica."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.stop = threading.Event()

    def tick(self, current=None):
        if os.getenv('DAILY_RESEARCH_ENABLED') != 'true' or self.runtime.closing:
            return
        current = current or datetime.now(ZoneInfo('America/Lima'))
        current = current.astimezone(ZoneInfo('America/Lima'))
        if current.hour < 6:
            return
        day = current.date().isoformat()
        reservations = agent.private_file('schedule')
        reservations.mkdir(exist_ok=True)
        marker = reservations / (day + '.json')
        with self.runtime.mutation_lock:
            active = self.runtime.activity.snapshot()
            if marker.exists() or (agent.DATA / ('propuestas-' + day)).exists() or (active and active['status'] == 'RUNNING'):
                return
            # Crear antes de iniciar: incluso una caída en este punto exige reintento humano.
            with marker.open('x', encoding='utf-8') as stream:
                stream.write('{"command":"diario","reserved":true}')
            self.runtime.activity.start('Investigando propuestas de temas', [['diario']])

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                # Sin reintentos pagados ni secretos en el diagnóstico.
                print('No se pudo iniciar la investigación diaria. Revisa el volumen y la actividad del panel.', flush=True)
            self.stop.wait(30)


def main():
    from waitress import create_server
    try:
        app = create_app()
        port = int(os.getenv('PORT', '8080'))
    except (ValueError, OSError) as error:
        print(str(error) if isinstance(error, ValueError) else 'No se puede escribir en el volumen persistente.', flush=True)
        raise SystemExit(1) from None
    runtime = app.extensions['video_runtime']
    scheduler = DailyResearch(runtime)
    http = create_server(app, host='0.0.0.0', port=port, threads=4, max_request_body_size=512_000,
                         channel_timeout=60, clear_untrusted_proxy_headers=False)

    def shutdown(*_):
        runtime.closing = True
        scheduler.stop.set()
        runtime.activity.stop()
        http.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=scheduler.run, daemon=True).start()
    print('VideoAgente: servidor de producción iniciado.', flush=True)
    http.run()


if __name__ == '__main__':
    main()
