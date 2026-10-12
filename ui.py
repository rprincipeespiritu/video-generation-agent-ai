"""Panel de escritorio web de VideoAgenteIA, disponible solo en 127.0.0.1."""
import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import tomllib
from urllib.parse import unquote, urlsplit
import webbrowser

from dotenv import set_key
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
    proposals = state.get('kind') == 'topic_proposals'
    info = {'id': folder.name, 'kind': state.get('kind', 'video'),
            'title': ('Propuestas de actualidad e historia · ' + folder.name.removeprefix('propuestas-')
                      if proposals else script.get('title') or state.get('requested_topic') or 'Investigación en curso'),
            'status': state.get('status', 'UNKNOWN'), 'demo': bool(state.get('demo')),
            'created_at': state.get('created_at'), 'updated_at': state.get('updated_at'),
            'duration': state.get('duration_seconds'), 'target': state.get('target_seconds'),
            'error': state.get('last_error'), 'ready': ready, 'locked': (folder / '.lock').exists(),
            'poster': f'/media/{folder.name}/poster' if job_file(folder, 'scene-00.png').is_file() else None}
    if detail:
        topics = read_json(folder, 'topics.json', []) if proposals else []
        info.update(topics=topics, selections=state.get('selections', {}),
                    topics_hash=agent.topics_hash(folder) if proposals and topics else None)
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
    values = agent.config_values()
    schedule = {'status': 'UNKNOWN', 'name': 'Propuestas diarias', 'time': '06:00', 'timezone': 'America/Lima'}
    paths = []
    if not agent.cloud_mode():
        codex = Path(os.getenv('CODEX_HOME') or Path.home() / '.codex')
        paths = (codex / 'automations').glob('*/automation.toml')
    for path in paths:
        try:
            data = tomllib.loads(path.read_text(encoding='utf-8'))
            if str(agent.ROOT) in data.get('prompt', '') and 'agent.py diario' in data.get('prompt', ''):
                schedule.update(status=data.get('status', 'UNKNOWN'), name=data.get('name', 'Propuestas diarias'))
                break
        except (OSError, ValueError):
            continue
    if agent.cloud_mode():
        schedule.update(status='ACTIVE' if os.getenv('DAILY_RESEARCH_ENABLED') == 'true' else 'PAUSED')
    return {'cloud': agent.cloud_mode(), 'openai_configured': bool(values.get('OPENAI_API_KEY')),
            'oauth_configured': bool(os.getenv('YOUTUBE_TOKEN_JSON')) if agent.cloud_mode() else agent.private_file('client_secret.json').is_file(),
            'youtube_connected': agent.private_file('youtube_token.json').is_file(),
            'schedule': schedule, 'focus': agent.DEFAULT_FOCUS,
            'production': agent.production.settings(values)}


class Activity:
    """Un proceso del agente a la vez; nunca interpretar texto del usuario como comandos."""
    def __init__(self, state_path=None):
        self.lock = threading.Lock()
        self.value = None
        self.thread = None
        self.state_path = state_path
        self.process = None
        self.stopping = threading.Event()
        if state_path and state_path.exists():
            try:
                self.value = agent.load(state_path)
                if self.value and self.value.get('status') == 'RUNNING':
                    self.value.update(status='ERROR', ended_at=agent.now())
                    self.value['lines'] = ['El servidor se reinició durante una operación. Revisa el estado del trabajo antes de reintentar.']
                    self.persist()
            except (OSError, ValueError, AttributeError):
                self.value = {'status': 'ERROR', 'lines': ['No se pudo leer la actividad anterior. Revisa los trabajos.']}

    def persist(self):
        if self.state_path:
            agent.save(self.state_path, self.value)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.value))

    def start(self, label, commands):
        with self.lock:
            if self.stopping.is_set():
                raise ValueError('El servidor se está cerrando. Actualiza la página después del reinicio.')
            if self.value and self.value['status'] == 'RUNNING':
                raise ValueError('Ya hay una operación en curso. Espera a que termine.')
            self.value = {'id': secrets.token_hex(6), 'label': label, 'status': 'RUNNING',
                          'started_at': agent.now(), 'lines': []}
            self.persist()
            self.thread = threading.Thread(target=self._run, args=(commands,), daemon=False)
            self.thread.start()
        return self.snapshot()

    def stop(self):
        with self.lock:
            self.stopping.set()
            process = self.process
        if process and process.poll() is None:
            if os.name == 'nt':
                process.terminate()
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def _run(self, commands):
        try:
            values = agent.config_values()
            private = [value for key, value in values.items() if value and any(word in key for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]
            if os.getenv('OPENAI_API_KEY'):
                private.append(os.environ['OPENAI_API_KEY'])
            code = 0
            for args in commands:
                command = [sys.executable, '-X', 'utf8', '-u', str(agent.ROOT / 'agent.py'), *args]
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                with self.lock:
                    if self.stopping.is_set():
                        code = -15
                        break
                    process = subprocess.Popen(command, cwd=agent.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                                               creationflags=flags, start_new_session=os.name != 'nt')
                    self.process = process
                with process:
                    for line in process.stdout:
                        for value in private:
                            line = line.replace(value, '[oculto]')
                        with self.lock:
                            self.value['lines'] = (self.value['lines'] + [line.strip()])[-50:]
                    code = process.wait()
                with self.lock:
                    self.process = None
                if code:
                    break
            with self.lock:
                self.value.update(status='DONE' if code == 0 else 'ERROR', exit_code=code, ended_at=agent.now())
                if self.stopping.is_set():
                    self.value.update(status='ERROR')
                    self.value['lines'].append('El servidor se detuvo. Revisa el estado del trabajo antes de reintentar.')
                self.persist()
        except Exception as error:
            with self.lock:
                self.value.update(status='ERROR', ended_at=agent.now(),
                                  lines=[f'No se pudo ejecutar el agente ({type(error).__name__}).'])
                self.persist()
        finally:
            self.process = None


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8765):
        self.token = secrets.token_urlsafe(32)
        self.activity = Activity()
        self.mutation_lock = threading.Lock()
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class Actions:
    """Acciones compartidas por el panel local y el servidor de producción."""
    def __init__(self, runtime):
        self.server = runtime

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
                    raise ValueError('Configura tu clave de OpenAI antes de investigar los temas de hoy.')
                command = ['diario']
            elif mode == 'demo':
                command = ['demo']
            else:
                raise ValueError('Modo de generación inválido.')
            label = {'daily': 'Investigando propuestas de temas', 'topic': 'Generando tu tema', 'demo': 'Generando demo'}[mode]
            return self.server.activity.start(label, [command])
        if path == '/api/config':
            if agent.cloud_mode():
                raise ValueError('Configura OPENAI_API_KEY en Railway Variables y despliega los cambios.')
            key = data.get('openai_key')
            if not isinstance(key, str) or not key.strip() or len(key) > 500 or any(c.isspace() for c in key):
                raise ValueError('Introduce una clave válida, sin espacios.')
            set_key(str(agent.private_file('.env')), 'OPENAI_API_KEY', key)
            # El entorno heredado tiene precedencia para CLI; mantenerlo consistente en este proceso.
            if 'OPENAI_API_KEY' in os.environ:
                os.environ['OPENAI_API_KEY'] = key
            return {'saved': True}
        if path == '/api/production':
            voice, mode = data.get('voice'), data.get('visual_mode')
            if voice not in agent.production.VOICES or mode not in agent.production.VISUAL_MODES:
                raise ValueError('Elige una voz y un estilo visual disponibles.')
            for key, value in (('TTS_VOICE', voice), ('VISUAL_MODE', mode)):
                set_key(str(agent.private_file('.env')), key, value)
                if key in os.environ:
                    os.environ[key] = value
            return {'saved': True}
        if path == '/api/channel':
            if not configuration()['oauth_configured'] and not configuration()['youtube_connected']:
                if agent.cloud_mode():
                    raise ValueError('Conecta el canal desde tu PC y configura YOUTUBE_TOKEN_JSON en Railway Variables.')
                raise ValueError('Guarda client_secret.json en la carpeta del proyecto antes de conectar YouTube.')
            return self.server.activity.start('Conectando YouTube', [['canal']])
        match = re.fullmatch(r'/api/jobs/([^/]+)/(approve|publish|reject|save-script|regenerate|retry|preview|select-topic)', path)
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
            child = None
            if action == 'select-topic':
                if not isinstance(data.get('topics_hash'), str) or not data['topics_hash']:
                    raise ValueError('Abre primero las propuestas para revisarlas.')
                child = agent.reserve_topic(folder, data.get('number'), confirmation=data.get('confirmed'),
                                            expected_hash=data['topics_hash'])
                commands = [['continuar-tema', child.name]]
            elif state.get('kind') == 'topic_proposals':
                if action != 'retry' or state['status'] not in ('ERROR', 'TOPIC_RESEARCHING') or state.get('demo'):
                    raise ValueError('Revisa las propuestas y aprueba un tema para iniciar un video.')
                commands = [['proponer', '--reanudar', folder.name]]
            elif action == 'approve':
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
                if state['status'] == 'TOPIC_APPROVED':
                    commands = [['continuar-tema', folder.name]]
                elif action == 'retry' and (state.get('last_error', {}).get('phase') == 'RESEARCHING'
                                          or state['status'] == 'RESEARCHING'):
                    commands = [['investigar', '--reanudar', folder.name], ['generar', folder.name]]
                else:
                    commands = [['generar', folder.name]]
                    if (folder / 'script.json').exists():
                        commands[0].append('--usar-guion')
                        if action == 'retry' and not state.get('demo'):
                            commands[0].append('--corregir-guion')
        # El proceso CLI tomará el mismo bloqueo después de liberar el de esta solicitud.
        if action in ('publish', 'regenerate', 'retry', 'preview', 'select-topic'):
            label = 'Subiendo a YouTube' if action == 'publish' else 'Preparando muestra' if action == 'preview' else 'Generando video'
            if state.get('kind') == 'topic_proposals' and action == 'retry':
                label = 'Investigando propuestas de temas'
            result = self.server.activity.start(label, commands)
            if child:
                result = {**result, 'job_id': child.name}
            return result
        return {'saved': True}


class Handler(BaseHTTPRequestHandler, Actions):
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
