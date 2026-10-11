"""Panel de escritorio web de VideoAgenteIA, disponible solo en 127.0.0.1."""
import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import tomllib
from urllib.parse import unquote, urlsplit
import webbrowser

from dotenv import dotenv_values, set_key
import agent

WEB = Path(__file__).resolve().parent / 'web'
MEDIA = {'video': ('video.mp4', 'video/mp4'), 'poster': ('scene-00.png', 'image/png'),
         'preview': ('preview.mp4', 'video/mp4')}
FINAL_STATES = {'REVIEW', 'APPROVED', 'REJECTED', 'UPLOADED'}


def folder_for(job_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', job_id):
        raise ValueError('ID de video inválido.')
    folder = agent.job(job_id)
    if not folder.resolve().is_relative_to(agent.DATA.resolve()):
        raise ValueError('Ruta fuera de la carpeta de trabajos.')
    return folder


def job_file(folder, name):
    path = folder / name
    if not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError('Archivo fuera del trabajo.')
    return path


def read_json(folder, name, default=None):
    path = job_file(folder, name)
    return agent.load(path) if path.is_file() else default


def job_info(folder, detail=False):
    state = read_json(folder, 'state.json', {})
    script = read_json(folder, 'script.json', {})
    if not isinstance(state, dict) or not isinstance(script, dict):
        raise ValueError('El estado o el guion del trabajo tiene un formato inválido.')
    ready = state.get('status') in FINAL_STATES and job_file(folder, 'video.mp4').is_file()
    info = {'id': folder.name, 'title': script.get('title') or state.get('requested_topic') or 'Investigación en curso',
            'status': state.get('status', 'UNKNOWN'), 'demo': bool(state.get('demo')),
            'created_at': state.get('created_at'), 'updated_at': state.get('updated_at'),
            'duration': state.get('duration_seconds'), 'target': state.get('target_seconds'),
            'error': state.get('last_error'), 'ready': ready, 'locked': (folder / '.lock').exists(),
            'poster': f'/media/{folder.name}/poster' if job_file(folder, 'scene-00.png').is_file() else None}
    if detail:
        review_hash = agent.render_digest(folder) if ready else None
        research = job_file(folder, 'research.md')
        info.update(script=script, sources=read_json(folder, 'sources.json', []),
                    research=research.read_text(encoding='utf-8') if research.exists() else '',
                    publication=read_json(folder, 'publication.json'), report=read_json(folder, 'render_report.json'),
                    video=f'/media/{folder.name}/video' if ready else None,
                    review_hash=review_hash, render_current=ready and review_hash == state.get('render_hash'),
                    script_hash=script_hash(folder),
                    preview=f'/media/{folder.name}/preview' if job_file(folder, 'preview.mp4').is_file() else None,
                    preview_report=read_json(folder, 'preview_report.json'),
                    approved_hash=state.get('approved_hash'), youtube_id=state.get('youtube_id'))
    return info


def all_jobs():
    result = []
    for folder in agent.DATA.glob('*'):
        if not folder.is_dir() or folder.name.startswith('.'):
            continue
        try:
            result.append(job_info(folder_for(folder.name)))
        except (ValueError, OSError, TypeError, KeyError, AttributeError):
            result.append({'id': folder.name, 'title': 'Trabajo con archivos incompletos', 'status': 'UNKNOWN',
                           'demo': False, 'ready': False})
    return sorted(result, key=lambda item: item.get('created_at') or item['id'], reverse=True)


def configuration():
    values = dotenv_values(agent.ROOT / '.env')
    schedule = {'status': 'UNKNOWN', 'name': 'Video diario', 'time': '06:00', 'timezone': 'America/Lima'}
    codex = Path(os.getenv('CODEX_HOME') or Path.home() / '.codex')
    for path in (codex / 'automations').glob('*/automation.toml'):
        try:
            data = tomllib.loads(path.read_text(encoding='utf-8'))
            if str(agent.ROOT) in data.get('prompt', '') and 'agent.py diario' in data.get('prompt', ''):
                schedule.update(status=data.get('status', 'UNKNOWN'), name=data.get('name', 'Video diario'))
                break
        except (OSError, ValueError):
            continue
    return {'openai_configured': bool(os.getenv('OPENAI_API_KEY') or values.get('OPENAI_API_KEY')),
            'oauth_configured': (agent.ROOT / 'client_secret.json').is_file(),
            'youtube_connected': (agent.ROOT / 'youtube_token.json').is_file(),
            'schedule': schedule, 'focus': agent.DEFAULT_FOCUS,
            'production': agent.production.settings({**values, **os.environ})}


class Activity:
    """Un proceso del agente a la vez; nunca interpretar texto del usuario como comandos."""
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None
        self.thread = None

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.value))

    def start(self, label, commands):
        with self.lock:
            if self.value and self.value['status'] == 'RUNNING':
                raise ValueError('Ya hay una operación en curso. Espera a que termine.')
            self.value = {'id': secrets.token_hex(6), 'label': label, 'status': 'RUNNING',
                          'started_at': agent.now(), 'lines': []}
            self.thread = threading.Thread(target=self._run, args=(commands,), daemon=False)
            self.thread.start()
        return self.snapshot()

    def _run(self, commands):
        try:
            values = dotenv_values(agent.ROOT / '.env')
            private = [value for key, value in values.items() if value and ('KEY' in key or 'TOKEN' in key)]
            if os.getenv('OPENAI_API_KEY'):
                private.append(os.environ['OPENAI_API_KEY'])
            code = 0
            for args in commands:
                command = [sys.executable, '-X', 'utf8', '-u', str(agent.ROOT / 'agent.py'), *args]
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                with subprocess.Popen(command, cwd=agent.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                                      creationflags=flags) as process:
                    for line in process.stdout:
                        for value in private:
                            line = line.replace(value, '[oculto]')
                        with self.lock:
                            self.value['lines'] = (self.value['lines'] + [line.strip()])[-50:]
                    code = process.wait()
                if code:
                    break
            with self.lock:
                self.value.update(status='DONE' if code == 0 else 'ERROR', exit_code=code, ended_at=agent.now())
        except Exception as error:
            with self.lock:
                self.value.update(status='ERROR', ended_at=agent.now(),
                                  lines=[f'No se pudo ejecutar el agente ({type(error).__name__}).'])


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8765):
        self.token = secrets.token_urlsafe(32)
        self.activity = Activity()
        self.mutation_lock = threading.Lock()
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # No registrar cuerpos de formularios, secretos ni URLs de autorización.

    def send(self, status, data, content_type='application/json; charset=utf-8'):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def trusted(self, mutation=False):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self.send(403, {'error': 'Abre el panel usando su dirección 127.0.0.1.'})
            return False
        origin = self.headers.get('Origin')
        if (origin and origin != self.server.origin) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.send(403, {'error': 'Origen no permitido.'})
            return False
        if mutation and not secrets.compare_digest(self.headers.get('X-Local-Token', ''), self.server.token):
            self.send(403, {'error': 'La sesión cambió. Actualiza la página.'})
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return
        path = unquote(urlsplit(self.path).path)
        try:
            static = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8'),
                      '/icon.svg': ('icon.svg', 'image/svg+xml')}
            if path in static:
                name, mime = static[path]
                return self.send(200, (WEB / name).read_bytes(), mime)
            if path == '/api/session':
                return self.send(200, {'token': self.server.token})
            if path == '/api/status':
                return self.send(200, {'configuration': configuration(), 'activity': self.server.activity.snapshot()})
            if path == '/api/jobs':
                return self.send(200, {'jobs': all_jobs()})
            match = re.fullmatch(r'/api/jobs/([^/]+)', path)
            if match:
                return self.send(200, job_info(folder_for(match[1]), detail=True))
            match = re.fullmatch(r'/media/([^/]+)/([^/]+)', path)
            if match and match[2] in MEDIA:
                folder = folder_for(match[1])
                name, mime = MEDIA[match[2]]
                return self.serve_media(job_file(folder, name), mime)
            return self.send(404, {'error': 'Recurso no encontrado.'})
        except (ConnectionResetError, BrokenPipeError):
            pass
        except (ValueError, OSError, TypeError, KeyError) as error:
            self.send(400, {'error': str(error) if isinstance(error, ValueError) else 'No se puede leer este trabajo.'})

    def serve_media(self, path, mime):
        with path.open('rb') as stream:
            size = path.stat().st_size
            if not size:
                return self.send(404, {'error': 'El archivo está vacío.'})
            start, end, status = 0, size - 1, 200
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    return self.send(416, {'error': 'Rango no válido.'})
                if match[1]:
                    start = int(match[1])
                    end = min(int(match[2]), end) if match[2] else end
                else:
                    start = max(0, size - int(match[2]))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                status = 206
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(end - start + 1))
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            stream.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = stream.read(min(128 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (ConnectionResetError, BrokenPipeError):
                pass

    def do_POST(self):
        if not self.trusted(mutation=True):
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 512_000 or self.headers.get_content_type() != 'application/json':
                raise ValueError('Se requiere un formulario JSON válido.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Formulario inválido.')
            with self.server.mutation_lock:
                result = self.action(urlsplit(self.path).path, data)
            self.send(200, result)
        except (ValueError, OSError, TypeError, KeyError) as error:
            self.send(400, {'error': str(error) if isinstance(error, ValueError) else 'No se pudo completar la acción.'})

    def action(self, path, data):
        activity = self.server.activity.snapshot()
        if activity and activity['status'] == 'RUNNING':
            raise ValueError('Hay una operación en curso. Espera a que termine antes de realizar cambios.')
        if path == '/api/create':
            mode = data.get('mode')
            if mode == 'topic':
                agent.validate_text(data.get('topic'), 'Tema', 500)
                if not configuration()['openai_configured']:
                    raise ValueError('Configura tu clave de OpenAI en Configuración para generar videos reales.')
                command = ['crear', '--tema', data['topic'].strip()]
            elif mode == 'daily':
                if not configuration()['openai_configured']:
                    raise ValueError('Configura tu clave de OpenAI antes de generar la actualidad de hoy.')
                command = ['diario']
            elif mode == 'demo':
                command = ['demo']
            else:
                raise ValueError('Modo de generación inválido.')
            return self.server.activity.start('Generando video' if mode != 'demo' else 'Generando demo', [command])
        if path == '/api/config':
            key = data.get('openai_key')
            if not isinstance(key, str) or not key.strip() or len(key) > 500 or any(c.isspace() for c in key):
                raise ValueError('Introduce una clave válida, sin espacios.')
            set_key(str(agent.ROOT / '.env'), 'OPENAI_API_KEY', key)
            # El entorno heredado tiene precedencia para CLI; mantenerlo consistente en este proceso.
            if 'OPENAI_API_KEY' in os.environ:
                os.environ['OPENAI_API_KEY'] = key
            return {'saved': True}
        if path == '/api/production':
            voice, mode = data.get('voice'), data.get('visual_mode')
            if voice not in agent.production.VOICES or mode not in agent.production.VISUAL_MODES:
                raise ValueError('Elige una voz y un estilo visual disponibles.')
            for key, value in (('TTS_VOICE', voice), ('VISUAL_MODE', mode)):
                set_key(str(agent.ROOT / '.env'), key, value)
                if key in os.environ:
                    os.environ[key] = value
            return {'saved': True}
        if path == '/api/channel':
            if not configuration()['oauth_configured']:
                raise ValueError('Guarda client_secret.json en la carpeta del proyecto antes de conectar YouTube.')
            return self.server.activity.start('Conectando YouTube', [['canal']])
        match = re.fullmatch(r'/api/jobs/([^/]+)/(approve|publish|reject|save-script|regenerate|retry|preview)', path)
        if not match:
            raise ValueError('Acción desconocida.')
        folder = folder_for(match[1])
        action = match[2]
        with agent.lock(folder):
            state = agent.load(job_file(folder, 'state.json'))
            if state['status'] in ('UPLOADING', 'UPLOADED'):
                raise ValueError('El video ya se subió o su envío es incierto. Revisa YouTube Studio.')
            if state['status'] in ('RESEARCHING', 'GENERATING') and action not in ('retry', 'regenerate'):
                raise ValueError('Termina o recupera la generación antes de cambiar este trabajo.')
            if action == 'approve':
                if data.get('reviewed') is not True or data.get('confirmation') != 'APROBAR':
                    raise ValueError('Confirma la revisión completa y escribe APROBAR.')
                if not isinstance(data.get('review_hash'), str) or not data['review_hash']:
                    raise ValueError('Abre primero el video para revisarlo.')
                pub = data.get('publication', {})
                if not isinstance(pub, dict) or not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', str(pub.get('channel_id', ''))):
                    raise ValueError('Introduce el ID real del canal (UC seguido de 22 caracteres).')
                if pub.get('privacy') not in ('private', 'unlisted', 'public') or any(
                    not isinstance(pub.get(field), bool) for field in ('made_for_kids', 'synthetic_media')):
                    raise ValueError('Completa las opciones de publicación.')
                agent.approve(folder, pub, confirmation='APROBAR', expected_hash=data['review_hash'])
            elif action == 'reject':
                agent.invalidate_approval(state)
                state.update(status='REJECTED', updated_at=agent.now())
                agent.save(folder / 'state.json', state)
            elif action == 'save-script':
                if data.get('script_hash') != script_hash(folder):
                    raise ValueError('El guion cambió. Vuelve a abrir el video antes de editar.')
                script = data.get('script')
                agent.validate_script(script, agent.load(job_file(folder, 'sources.json')))
                agent.invalidate_approval(state)
                state.pop('render_hash', None)
                state.update(status='RESEARCHED', updated_at=agent.now())
                agent.save(folder / 'state.json', state)
                agent.save(folder / 'script.json', script)
            elif action == 'publish':
                approved = agent.require_approved(folder)
                if data.get('confirmation') != 'SUBIR' or data.get('approved_hash') != approved.get('approved_hash'):
                    raise ValueError('Revisa la aprobación vigente y escribe SUBIR para confirmar el envío.')
                commands = [['publicar', folder.name]]
            elif action == 'preview':
                if state.get('demo') or not (folder / 'script.json').is_file():
                    raise ValueError('La muestra requiere un guion real.')
                commands = [['muestra', folder.name]]
            else:
                if action == 'retry' and (state.get('last_error', {}).get('phase') == 'RESEARCHING'
                                          or state['status'] == 'RESEARCHING'):
                    commands = [['investigar', '--reanudar', folder.name], ['generar', folder.name]]
                else:
                    commands = [['generar', folder.name]]
                    if (folder / 'script.json').exists():
                        commands[0].append('--usar-guion')
                        if action == 'retry' and not state.get('demo'):
                            commands[0].append('--corregir-guion')
        # El proceso CLI tomará el mismo bloqueo después de liberar el de esta solicitud.
        if action in ('publish', 'regenerate', 'retry', 'preview'):
            label = 'Subiendo a YouTube' if action == 'publish' else 'Preparando muestra' if action == 'preview' else 'Generando video'
            return self.server.activity.start(label, commands)
        return {'saved': True}


def script_hash(folder):
    return agent.digest(folder, ('script.json',)) if (folder / 'script.json').exists() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true', help='Abrir en el navegador predeterminado')
    args = parser.parse_args()
    server = LocalServer(args.port)
    print(f'VideoAgenteIA · Panel local: {server.origin}', flush=True)
    print('Mantén esta ventana abierta. Ctrl+C cierra el panel; las operaciones iniciadas deben terminar.', flush=True)
    if args.open:
        webbrowser.open(server.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nCerrando el panel. Si hay un proceso activo, espera a que termine.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
