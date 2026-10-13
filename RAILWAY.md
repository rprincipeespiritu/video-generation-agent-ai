# Desplegar VideoAgente en Railway desde `prd`

El servicio incluye el panel privado, el proceso de generación y un investigador diario opcional. Usa un solo servicio y una sola réplica con volumen persistente. Conserva la aprobación del tema, la revisión del video y la confirmación separada para subir a YouTube.

## 1. Código y servicio

1. En Railway crea un proyecto y conecta el repositorio `rprincipeespiritu/video-generation-agent-ai`.
2. En **Settings → Source** selecciona la rama **`prd`**. La raíz del repositorio es `/`: contiene `Dockerfile`, `server.py` y `requirements.txt`.
3. Railway detecta el `Dockerfile`. No configures un comando de build ni sobrescribas el comando de inicio: el contenedor inicia `python -X utf8 server.py` mediante su entrypoint.
4. Mantén **una réplica** y desactiva **Serverless / App Sleeping** para ejecutar la investigación diaria aun cuando no visites el panel.
5. En **Networking** genera un dominio público HTTPS.

El build instala FFmpeg con el filtro `rubberband`, las fuentes y las dependencias de Python. El servidor usa Flask y Waitress. El proceso de trabajo funciona en segundo plano, por lo que generar un video no mantiene una solicitud HTTP abierta.

## 2. Volumen y variables

Adjunta un **Volume** al mismo servicio con **Mount Path `/storage`** antes de desplegar. El contenedor guarda:

| Carpeta | Contenido |
| --- | --- |
| `/storage/data` | Propuestas, guiones, fuentes, imágenes, audios, videos, estados y aprobaciones |
| `/storage/config` | Preferencias, actividad, reservas del horario y token autorizado de YouTube |

El contenedor prepara las carpetas y ejecuta la aplicación como usuario sin privilegios. En Railway el arranque se detiene si falta el volumen o las rutas no están dentro de él. Activa copias de seguridad del volumen; acumular videos y sus recursos consume espacio. El disco del contenedor fuera de este volumen es temporal.

En **Variables** configura:

| Variable | Valor |
| --- | --- |
| `ADMIN_USERNAME` | Tu usuario; por defecto `admin` |
| `ADMIN_PASSWORD` | Contraseña aleatoria única de **al menos 20 caracteres**; se recomiendan 32 o más |
| `PUBLIC_URL` | `https://TU-DOMINIO.up.railway.app`, sin ruta. También se admite el dominio automático de `RAILWAY_PUBLIC_DOMAIN` si omites esta variable |
| `OPENAI_API_KEY` | Tu clave de API, solo en Railway Variables |
| `DAILY_RESEARCH_ENABLED` | `false` durante las pruebas; `true` al trasladar el horario a Railway |
| `YOUTUBE_TOKEN_JSON` | Opcional inicialmente; ver sección YouTube |

El `Dockerfile` ya fija `APP_ENV=production`, `VIDEO_DATA_DIR=/storage/data`, `VIDEO_CONFIG_DIR=/storage/config`, la ruta de FFmpeg y la fuente. No copies las rutas de Windows de tu `.env` a Railway. La plataforma inyecta `PORT` y el servidor escucha en `0.0.0.0:$PORT` (8080 fuera de Railway).

Opcionales: `OPENAI_MODEL`, `TTS_MODEL`, `IMAGE_MODEL`, `TTS_VOICE` y `VISUAL_MODE`. Se conservan los valores predeterminados del proyecto. Las preferencias de voz y estilo guardadas desde el panel tienen precedencia sobre estas dos variables y persisten en el volumen. La clave de OpenAI se administra exclusivamente en Railway.

No copies `.env`, tokens, `data/` ni `.venv/` a GitHub. `.dockerignore` permite únicamente código y recursos web en el build, incluso si hay archivos multimedia en el repositorio.

## 3. Desplegar y comprobar

1. En **Deploy → Healthcheck Path** introduce `/healthz`; timeout sugerido: 120 segundos. Usa política de reinicio **On Failure**, con 3 intentos.
2. Aplica las variables y despliega la rama `prd`.
3. Abre el dominio HTTPS. El navegador solicitará usuario y contraseña. Tanto las APIs como los archivos de video requieren autenticación; `/healthz` solo informa si el servidor está disponible.
4. Pulsa **Crear una demo gratis** y reproduce el resultado. Esta prueba no usa OpenAI ni YouTube.
5. Cuando la operación termine, reinicia el servicio y comprueba que la demo siga en la biblioteca. Esto verifica el volumen y el arranque.
6. Prueba **Investigar temas de hoy** (consume API). Debe terminar en **Temas por aprobar**, sin crear audios, imágenes ni MP4.
7. Aprueba un tema para generar su video. Al terminar debe quedar **Por revisar**. Revisa el resultado completo y apruébalo. Solo se envía a YouTube al confirmar después **SUBIR**.

Puedes cerrar la pestaña: el proceso continúa en el servidor. El inicio de sesión utiliza autenticación HTTP Basic sobre HTTPS; el navegador conserva las credenciales durante su sesión. Usa un perfil personal o una ventana privada y ciérrala al terminar en equipos compartidos.

No despliegues cambios ni reinicies mientras se genera o sube un video. Un reinicio interrumpe esa operación; la actividad queda marcada para revisión y no se repite automáticamente. Los bloqueos y los estados inciertos se conservan. Verifica si sigue habiendo procesos antes de recuperar un trabajo; nunca fuerces una nueva subida si quedó en `UPLOADING` sin comprobar antes YouTube Studio.

### Si falla una ilustración o la voz

Abre el trabajo que quedó en **Necesita atención**. El panel y la actividad muestran la etapa y el número de escena; **Datos para soporte** incluye HTTP, códigos conocidos del proveedor, parámetro e ID de solicitud cuando estén disponibles. No se guarda el cuerpo ni el mensaje libre de OpenAI porque podrían incluir texto privado o credenciales. Los errores anteriores a esta mejora no permiten recuperar retroactivamente el código descartado.

- `moderation_blocked` / `content_policy_violation`: revisa el contenido de la escena y su adecuación a las políticas del proveedor antes de volver a solicitarla.
- `credit_balance_exhausted`: revisa los créditos de la organización en OpenAI. El gasto acumulado del proyecto no es el saldo disponible.
- `billing_hard_limit_reached`, `insufficient_quota` o códigos de límite de organización/proyecto: revisa Facturación y el límite correspondiente. Una alerta de gasto no prueba que los créditos estén agotados.
- `invalid_value` / `unsupported_parameter`: revisa el parámetro indicado y su compatibilidad con el modelo.
- `rate_limit_exceeded` / `slow_down`: espera antes de realizar otro intento.
- `BadRequestError` sin código reconocido: la causa no está confirmada; conserva el ID de solicitud para consultar al proveedor. No asumas que cambiar el presupuesto lo resolverá.

Cuando hayas revisado la causa, pulsa **Reintentar trabajo** sobre el mismo ID. Los audios e imágenes completos y válidos permanecen en `assets/` y se reutilizan si el guion, la voz y los parámetros correspondientes no cambiaron. La actividad distingue recursos reutilizados de nuevas solicitudes. Las escenas pendientes o modificadas consumen API; no se reintentan imágenes automáticamente ni se sustituye su contenido tras un rechazo. El montaje local de las escenas se vuelve a ejecutar. No crees un trabajo nuevo ni borres los recursos para recuperar el anterior. Al completarse, el video vuelve a **Por revisar** y requiere tu aprobación.

Referencias: [errores de generación de imágenes](https://developers.openai.com/api/docs/guides/image-generation#handling-blocked-requests-and-other-errors), [códigos de error de OpenAI](https://developers.openai.com/api/docs/guides/error-codes), [alertas de gasto](https://developers.openai.com/api/docs/guides/terraform/rate-limits-and-spend).

Para elegir una ilustración diferente tras un rechazo de contenido:

1. Pulsa **Editar imagen de escena N** o abre **Editar guion** y busca esa escena.
2. Completa **Imagen de esta escena (opcional)** con una representación apropiada: por ejemplo, el entorno, objetos o un paisaje relacionado, en lugar de una agresión descrita en una leyenda. Esta descripción visual define una nueva imagen y no cambia la narración. Los controles de moderación siguen activos.
3. Guarda el guion. Guardar no consume API y anula cualquier aprobación anterior.
4. En **Escena de la muestra**, selecciona la escena editada y pulsa **Probar voz e imagen**. Solo esa escena se solicita; sus recursos completos sin cambios se reutilizan. La muestra conserva el video completo y su estado.
5. Revisa la muestra. Cuando estés conforme, pulsa **Regenerar con este guion** para completar el video; después vuelve a revisarlo y aprobarlo antes de subirlo.

Deja vacía la descripción de las escenas que quieras mantener. Los guiones antiguos siguen funcionando y conservan sus claves de caché. Editar solo la descripción visual de una escena no solicita de nuevo su audio ni las imágenes de las otras escenas. Los recursos pendientes o modificados sí consumen API. Un rechazo detiene también la muestra; no se reintenta ni se reformula el contenido automáticamente.

## 4. Investigación diaria: trasladar el horario

El programador interno consulta la hora de **America/Lima** y, a partir de las **06:00**, ejecuta exclusivamente `agent.py diario` una vez por fecha. Si a esa hora está ocupado, espera a que termine. Si el servicio arranca más tarde, investiga el día actual; no recupera días anteriores.

1. Mantén `DAILY_RESEARCH_ENABLED=false` mientras pruebas Railway.
2. Cuando el servicio esté operativo, **pausa la automatización local de Codex “Propuestas diarias de actualidad e historia”**.
3. Cambia `DAILY_RESEARCH_ENABLED=true` y despliega cuando no haya trabajos en curso.

El programador conserva una reserva en el volumen antes de iniciar. Un fallo o reinicio no causa llamadas pagadas automáticas repetidas ese día. Si hace falta reintentar, revisa la actividad y usa la recuperación explícita del panel. Las propuestas aparecen en la biblioteca de Railway; este programador no envía mensajes al chat de Codex. La instalación local y Railway tienen bibliotecas separadas.

## 5. Autorizar YouTube

La primera autorización se hace desde tu PC con las credenciales OAuth de escritorio ya admitidas por el proyecto:

```powershell
.\.venv\Scripts\python.exe -X utf8 agent.py canal
```

Este comando abre Google y guarda `youtube_token.json`; no sube videos. Copia **el contenido completo de ese archivo JSON** en la variable privada `YOUTUBE_TOKEN_JSON` de Railway. No lo publiques en el repositorio ni en el chat. Luego despliega y pulsa **Verificar mi canal** en el panel de Railway. El ID debe coincidir con el canal que elijas al aprobar el video.

El servidor guarda y renueva la credencial en el volumen, sin abrir un navegador. Si Google revoca o hace caducar la autorización, vuelve a conectar desde tu PC y reemplaza `YOUTUBE_TOKEN_JSON`; se detectará el nuevo valor. Si tu aplicación de Google está en modo de pruebas, revisa sus límites y la vigencia de los permisos en Google Cloud.

## 6. Recursos, datos anteriores y validación

La investigación, imágenes y narración consumen tu API; Railway factura sus recursos por separado. Empieza con recursos que permitan el montaje de video y observa CPU, memoria y espacio durante la primera generación de diez minutos. El tiempo y consumo dependen del contenido. El servicio procesa un trabajo a la vez; no debe escalarse a varias réplicas.

Los videos locales existentes no se transfieren automáticamente. Si quieres migrarlos, hazlo con los procesos detenidos, conserva la estructura completa de `data/` y copia únicamente trabajos cuya situación conozcas. Comprueba los permisos del usuario del contenedor (UID 10001) y verifica los videos/aprobaciones desde el panel antes de publicar.

Pruebas automatizadas sin proveedores:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v -b
```

Con Docker instalado, puedes validar el build con `docker build -t video-agente:prd .`. No incluye credenciales, datos locales ni videos de ejemplo. El workflow de GitHub Actions también ejecuta las pruebas y construye el contenedor en Linux.

Referencias: [Dockerfiles en Railway](https://docs.railway.com/builds/dockerfiles), [volúmenes persistentes](https://docs.railway.com/volumes), [healthchecks y PORT](https://docs.railway.com/deployments/healthchecks), [Waitress para Flask](https://flask.palletsprojects.com/en/stable/deploying/waitress/), [OAuth de escritorio de Google](https://developers.google.com/identity/protocols/oauth2/native-app).
