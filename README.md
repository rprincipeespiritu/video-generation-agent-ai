# VideoAgenteIA — estudio local

Proyecto Python para investigar actualidad, redactar un guion educativo, crear un MP4 narrado y subirlo a tu canal de YouTube **solo después de tu aprobación explícita**. Incluye un panel web que funciona en tu PC y comandos de terminal.

## Qué hace

1. Busca en la web cinco temas de las últimas 48 horas; propone un ranking editorial por actualidad, impacto y valor educativo. No es una medición objetiva de las noticias más populares.
2. Conserva investigación, respuesta original de la API y enlaces citados.
3. Desarrolla el tema recomendado o uno elegido por ti en un guion para 10 minutos, con 12–20 escenas y 1300–1700 palabras narradas.
4. Produce ilustraciones realistas por escena con movimiento suave a 1280 × 720, voz sintética conversacional en español y un MP4 con FFmpeg. Comprueba y ajusta los nuevos videos reales a diez minutos dentro de los límites de ritmo descritos más abajo.
5. Te permite revisar, editar el guion, regenerar, rechazar o aprobar.
6. Comprueba aprobación, integridad y canal antes de subir el archivo mediante OAuth.

Esta versión genera un video educativo narrado con una ilustración por escena y un acercamiento o alejamiento suave. Las imágenes son recreaciones ilustrativas. Los videos se centran en el tema, sin avisos hablados ni rótulos sobre su producción con IA; la descripción incluye el resumen y las fuentes. No incorpora clips o música de terceros. Puedes elegir láminas de texto en Configuración. El modo demo conserva nueve segundos de láminas con audio silencioso y no se puede publicar; `demo --minutos 10` permite comprobar el montaje largo sin APIs.

## Instalación en Windows

Necesitas Python 3.11 o superior. La preparación instala las dependencias en `.venv`, incluido un FFmpeg local mediante [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg). No hace falta modificar el PATH del sistema. También puedes usar un FFmpeg existente en PATH o indicar su ejecutable con `FFMPEG_PATH` en `.env`.

Abre PowerShell en esta carpeta:

```powershell
.\preparar-local.ps1
.\probar-local.ps1
```

La preparación requiere internet para descargar dependencias, conserva tu `.env` si ya existe y no configura credenciales. Busca Python en PATH o en el runtime local de Codex; también acepta `-PythonPath "C:\ruta\python.exe"`. El entorno virtual depende de ese Python base: si se mueve o elimina, vuelve a crear `.venv` con un Python instalado desde https://www.python.org/downloads/.

`probar-local.ps1` comprueba el entorno, ejecuta la suite, repite las validaciones con `python -O` y genera una demo. Funciona sin claves y no llama a OpenAI ni a YouTube. Las pruebas de servicios usan objetos simulados. Usa `-SinDemo` para omitir el montaje. No es necesario activar el entorno virtual.

Alternativa manual si tu equipo no permite ejecutar scripts PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe agent.py diagnostico
.\.venv\Scripts\python.exe -m unittest discover -s tests -v -b
.\.venv\Scripts\python.exe agent.py demo
```

El último comando indica dónde se encuentra `data/ID/video.mp4`. Puedes abrirlo con tu reproductor. Para Linux/macOS usa `.venv/bin/python` y `cp .env.example .env`.

## Abrir la interfaz

Desde PowerShell, en la carpeta `video-agente-ia`:

```powershell
.\abrir-panel.ps1
```

Se abre tu navegador en **http://127.0.0.1:8765**. Mantén esa ventana de PowerShell abierta mientras uses el panel. Si el puerto está ocupado, usa `.\abrir-panel.ps1 -Puerto 8766`. Sin scripts PowerShell, ejecuta `.\.venv\Scripts\python.exe -X utf8 ui.py --open`.

El panel permite:

- Escribir un tema y generar su video de diez minutos, o iniciar la edición de actualidad del día.
- Consultar tu biblioteca, buscar videos y filtrar pendientes, aprobados y publicados.
- Reproducir el MP4, leer las fuentes y la investigación, editar el guion y regenerar.
- Aprobar con las opciones de canal y visibilidad; subir después con una confirmación separada.
- Guardar la clave de OpenAI localmente y conectar YouTube mediante OAuth.
- Elegir voz y estilo visual, y generar una muestra de la primera escena antes de regenerar todo el video.

La generación funciona en segundo plano y muestra su progreso. El panel inicia una operación a la vez. Puedes cerrar la pestaña y volver a abrirla mientras el servidor siga activo. Para cerrarlo, espera a que termine la operación y pulsa Ctrl+C en PowerShell. Evita cerrar la terminal durante una generación o subida.

El horario de las 6:00 a. m. se administra en **Codex**. El panel muestra el estado que encuentra en la configuración local de esa automatización; «Sin verificar» significa que no pudo encontrarla. Abrir el panel por sí solo no programa el trabajo diario.

### Prueba rápida del panel sin claves

1. Pulsa **Crear una demo gratis**. Espera a que aparezca en la biblioteca como **Por revisar**.
2. Abre la demo y reproduce sus nueve segundos. Consulta **Guion**, **Fuentes** e **Investigación**.
3. En **Editar guion**, cambia el título y pulsa **Guardar guion**. El estado pasa a **Listo para generar**.
4. Pulsa **Regenerar con este guion**. Al terminar, vuelve a **Por revisar** y conserva tu cambio.
5. Comprueba los filtros y la búsqueda. Las demos no muestran opciones para aprobar ni subir a YouTube.

Para un video real, configura OpenAI y escribe el tema. Al terminar, revisa el video completo y sus fuentes. Pulsa **Revisar aprobación**, indica el ID de canal, la privacidad y las declaraciones solicitadas, marca la revisión y escribe **APROBAR**. Esto solo guarda la aprobación. **Subir a YouTube** requiere escribir **SUBIR** y la conexión OAuth. La privacidad inicial es **Privado**.

Guardar un guion anula cualquier aprobación y exige regenerar. Si el contenido cambia después de abrir la revisión, el servidor bloquea la aprobación de esa versión desactualizada. Si cambia después de aprobar, bloquea la subida.

El servidor escucha exclusivamente en `127.0.0.1`, valida el origen de las solicitudes y usa un token de sesión para las acciones. Solo sirve la interfaz, los videos y sus láminas; nunca sirve `.env` ni archivos OAuth. La clave se conserva en `.env` y no se devuelve al navegador. No está diseñado para acceso desde internet ni para varios usuarios.

## Configurar la IA

Puedes guardar tu clave desde **Configuración** en el panel o editar `.env` y colocarla en `OPENAI_API_KEY`. Mantén las claves en tu equipo; no las pegues en chats ni las subas a GitHub. Las llamadas de búsqueda, escritura, voz e imágenes consumen API; configura un presupuesto en tu cuenta. Esta entrega no incluye créditos.

Se usa Responses API con la herramienta `web_search`, una segunda llamada para el guion con Structured Outputs (`json_schema`), Speech API para la voz e Images API para las ilustraciones. El formato del guion restringe las referencias a las URLs del catálogo investigado. El modelo de texto por defecto es `gpt-4.1`, configurable en `OPENAI_MODEL`; requiere acceso en tu cuenta y compatibilidad con búsqueda web y Structured Outputs. Voz por defecto: `gpt-4o-mini-tts` / `cedar`; imágenes: `gpt-image-2`, calidad media, 1536 × 864. Consulta la [documentación de voz](https://developers.openai.com/api/docs/guides/text-to-speech) y de [generación de imágenes](https://developers.openai.com/api/reference/resources/images/methods/generate).

### Voz e imágenes

En **Configuración → Voz y estilo visual** elige la voz y **Ilustraciones realistas de IA** o **Láminas de texto**. Guarda las preferencias. Se aplican a los próximos videos, incluidos los diarios, y a las regeneraciones; los MP4 existentes se conservan hasta regenerarlos.

Para escuchar y ver una muestra, abre un trabajo real y pulsa **Probar voz e imagen · una escena**. Al finalizar, abre **Ver última muestra**. Solo genera la primera escena, a su ritmo original; no reemplaza el video completo ni cambia su aprobación. Para aplicar las preferencias al video completo, pulsa **Regenerar con este guion**; vuelve a quedar pendiente de aprobación.

Equivalente en PowerShell:

```powershell
.\.venv\Scripts\python.exe agent.py muestra ID
.\.venv\Scripts\python.exe agent.py generar ID --usar-guion
```

También puedes editar `TTS_VOICE=cedar`, `VISUAL_MODE=images` e `IMAGE_MODEL=gpt-image-2` en `.env`. La muestra se guarda en `data/ID/preview.mp4`. Cada audio e imagen se conserva en `assets/`, junto con sus parámetros, prompt y hash. Los reintentos reutilizan archivos íntegros si el contenido y los ajustes coinciden; una voz, narración o imagen distinta puede consumir API. Un fallo de imágenes detiene el montaje, conserva los audios y no sustituye el MP4 anterior por láminas sin avisar.

La voz se solicita en WAV sin compresión, con indicaciones de tono conversacional. Se unen las escenas y se codifica el audio a AAC una sola vez. Si hay que ajustar los diez minutos, FFmpeg usa Rubber Band conservando formantes y tono; la muestra permite escuchar la voz sin ajuste. Esto mejora el tratamiento del audio, pero la naturalidad sigue dependiendo de la voz, el texto y la pronunciación. El FFmpeg incluido en la preparación local de Windows dispone de ese filtro.

## Tu primer video real

Para investigar y generar un video completo de diez minutos sobre un tema elegido:

```powershell
.\.venv\Scripts\python.exe agent.py crear --tema "Cómo está cambiando la inteligencia artificial la educación en Perú"
```

Este comando investiga exclusivamente tu tema, incluso si es educativo o histórico, y termina en `REVIEW`. No abre YouTube ni publica. La selección automática de actualidad y la aprobación se explican más abajo.

En los siguientes comandos sustituye `ID` por el identificador que devuelve investigar:

```powershell
.\.venv\Scripts\python.exe agent.py investigar --enfoque "Ciencia, tecnología y noticias relevantes para Perú"
.\.venv\Scripts\python.exe agent.py generar ID
.\.venv\Scripts\python.exe agent.py revisar ID
```

`revisar` abre el MP4 con la aplicación asociada o navegador e imprime el guion. Si no abre, usa el archivo directamente. Lee también `research.md` y `sources.json`. Comprueba fechas, nombres, cifras y que las fuentes realmente respalden lo narrado. La comprobación automática confirma que las URLs del guion provienen del catálogo; no garantiza la veracidad ni la independencia de las fuentes.

Para elegir un tema del informe:

```powershell
.\.venv\Scripts\python.exe agent.py generar ID --tema "Escribe aquí el tema elegido"
```

Para corregir el guion, edita `data/ID/script.json`, conserva su estructura y ejecuta:

```powershell
.\.venv\Scripts\python.exe agent.py generar ID --usar-guion
.\.venv\Scripts\python.exe agent.py revisar ID
```

Toda regeneración real invalida la aprobación previa. Reutiliza voz e imágenes guardadas cuando coinciden sus parámetros y contenido; generar recursos nuevos consume API. Si solo quieres descartar el video: `agent.py rechazar ID`. Puedes regenerar un trabajo rechazado. Las demos se pueden regenerar con `generar ID`; conservan audio silencioso y nunca se pueden publicar.

La validación comprueba estructura, tipos, límites y URLs incluso con Python optimizado. Para los nuevos videos reales exige 12–20 escenas y 1300–1700 palabras antes de sintetizar la voz. `script_response.txt` conserva la respuesta del guion antes de validarla, incluso si está incompleta. Si el guion tiene estructura válida pero resulta demasiado corto o largo, se permiten hasta dos correcciones automáticas por ejecución con OpenAI. Solo se ajustan las narraciones, conservando título, escenas y fuentes. El original y cada respuesta quedan en `script_repairs/`. Si ninguna corrección pasa la validación, la operación se detiene antes de generar voz y conserva `script.json` para revisión.

**Reintentar trabajo** también permite corregir la longitud de un guion guardado. **Regenerar con este guion** y `--usar-guion` sin opciones adicionales respetan tu edición y no la reescriben automáticamente. Las correcciones consumen API; un guion con longitud válida no necesita llamadas adicionales.

Al terminar, FFmpeg decodifica el MP4 para comprobar audio y video y mide su duración. Si la narración está entre 8 y 12,5 minutos, distribuye los fotogramas a 600 segundos y ajusta el audio original con Rubber Band, con tolerancia técnica de 0,15 segundos. Fuera de ese intervalo el trabajo queda en `ERROR`: se debe ampliar o acortar el guion. El archivo definitivo se reemplaza después de pasar la comprobación. `render_report.json` guarda duración original, objetivo, resultado, voz, estilo visual y factor de ritmo. Los trabajos antiguos sin `target_seconds` conservan la duración natural de su narración.

## Generación diaria a las 6:00 a. m.

El comando para una ejecución diaria es:

```powershell
.\.venv\Scripts\python.exe agent.py diario
```

Investiga noticias de las últimas 48 horas sobre **ciencia, tecnología y actualidad relevante para Perú**, elige un tema, desarrolla evidencia para diez minutos y deja el video en `REVIEW`. Usa los últimos siete títulos terminados para pedir variedad; esto no garantiza que nunca se repita un tema.

Cada fecha de Perú tiene una carpeta `data/diario-AAAA-MM-DD`. Si se ejecuta dos veces, la segunda no repite llamadas ni crea otro video. Un fallo tampoco provoca un segundo intento automático el mismo día: usa los comandos de recuperación por ID. Si falta la clave, no se reserva la fecha. El horario corresponde al inicio del proceso; el video estará listo cuando termine la generación.

La programación se administra en la automatización de este chat en Codex: **todos los días a las 6:00 a. m., America/Lima**. Requiere el equipo encendido, sin suspensión, la app abierta, acceso a esta carpeta e internet. Configura `OPENAI_API_KEY` en `.env` para investigación, guion y voz. Las llamadas consumen API. La automatización genera y avisa cuando hay un video nuevo para revisar; nunca ejecuta `aprobar` ni `publicar`. Puedes pausarla desde las tareas programadas de la app.

Para comprobar el flujo diario sin claves ni consumo:

```powershell
.\.venv\Scripts\python.exe agent.py diario --simular
.\.venv\Scripts\python.exe agent.py diario --simular
.\.venv\Scripts\python.exe agent.py listar --pendientes
```

La simulación crea una demo corta en `demo-diario-AAAA-MM-DD`, separada del trabajo real; la segunda llamada indica que ya existe. Para probar específicamente diez minutos:

```powershell
.\.venv\Scripts\python.exe agent.py demo --minutos 10
```

Después de una generación real, revisa `revisar ID`, `research.md`, `sources.json` y el MP4 completo. Usa `aprobar` y luego `publicar` como se explica a continuación. La aprobación nunca se infiere de la programación diaria.

## Conectar tu canal de YouTube

1. En https://console.cloud.google.com/ crea o selecciona un proyecto.
2. Habilita **YouTube Data API v3**.
3. Configura la pantalla de consentimiento OAuth. Si está en pruebas, agrega tu cuenta de Google como usuario de prueba.
4. Crea un cliente OAuth de tipo **Aplicación de escritorio**.
5. Descarga su JSON como `client_secret.json` en esta carpeta.
6. Ejecuta `.\.venv\Scripts\python.exe agent.py canal`.
7. Se abrirá el consentimiento de Google. Elige la cuenta y el canal correctos. Copia el ID `UC…` que devuelve el comando. Se solicitan permisos para subir videos y leer la identidad del canal.

El token se guarda localmente en `youtube_token.json`. No lo compartas. Puedes desconectar el proyecto revocando su acceso desde tu cuenta de Google y eliminando ese archivo. Si autorizaste el canal incorrecto, revoca/elimina el token y repite.

## Aprobar y subir

Después de ver el video completo y revisar sus fuentes:

```powershell
.\.venv\Scripts\python.exe agent.py aprobar ID --canal UC_TU_ID_REAL --privacidad private --para-ninos no --contenido-sintetico no
.\.venv\Scripts\python.exe agent.py publicar ID
```

El primer comando muestra los metadatos y exige escribir `APROBAR`. El segundo sube únicamente esa versión aprobada. Para publicar abiertamente, usa `--privacidad public` al aprobar; también existe `unlisted`. El valor predeterminado es privado.

Elige `--para-ninos si` solo si el video está dirigido a niños; educativo no significa automáticamente infantil. `--contenido-sintetico` declara contenido alterado o sintético realista según las reglas de YouTube: decide a partir de tu video; una lámina con voz sintética no equivale automáticamente a una representación realista de un suceso. Esta opción se envía como metadato a YouTube y no agrega avisos al audio, a las imágenes ni a la descripción. Los avisos de versiones anteriores requieren editar el guion y regenerar el MP4 para retirarlos.

YouTube puede restringir a **privado** los videos subidos desde proyectos API no auditados, aunque solicites publicación pública. Completar OAuth no sustituye la auditoría de API. Consulta https://developers.google.com/youtube/v3/docs/videos/insert

## Estados y protección de publicación

`RESEARCHING → RESEARCHED → GENERATING → REVIEW → APPROVED → UPLOADING → UPLOADED`

También existen `REJECTED` y `ERROR`. Cada trabajo tiene una carpeta y `state.json`, escrito de forma atómica. El hash SHA-256 aprobado cubre el MP4, guion, fuentes y opciones de publicación. Modificar cualquiera bloquea la subida hasta una nueva aprobación. Además, se registra un hash al montar: editar el guion, las fuentes o el MP4 exige regenerar antes de aprobar. Los trabajos de versiones anteriores sin `render_hash` también requieren regeneración. Cancelar una nueva aprobación deja el trabajo en `REVIEW` sin aprobación vigente.

El comando comprueba además que el canal autorizado coincide con el aprobado. Un bloqueo por carpeta evita dos operaciones simultáneas. No edites los archivos mientras se genera el video.

Los fallos e interrupciones con Ctrl+C durante investigación o generación quedan en `ERROR`, con fase, tipo de excepción y hora en `last_error`. Para errores conocidos se añade una explicación local y, si existe, el código HTTP; no se guardan mensajes completos de proveedores que puedan contener datos sensibles. El panel muestra esa explicación y la consola indica el avance por escena. `listar` muestra los errores y detecta carpetas sin estado o con JSON inválido.

Para reintentar después de corregir configuración, conexión o guion:

```powershell
# Conserva el enfoque y la carpeta de una investigación fallida.
.\.venv\Scripts\python.exe agent.py investigar --reanudar ID
# Reutiliza el guion disponible tras un fallo de generación.
.\.venv\Scripts\python.exe agent.py generar ID --usar-guion
```

Para corregir automáticamente un guion guardado que no alcanza la longitud necesaria:

```powershell
.\.venv\Scripts\python.exe agent.py generar ID --usar-guion --corregir-guion
```

Si no llegó a guardarse un guion válido, usa `generar ID` sin `--usar-guion`. Los reintentos reales pueden consumir API. Tras un cierre forzado del proceso pueden quedar `RESEARCHING` o `GENERATING`: se reintentan con los mismos comandos después de comprobar el bloqueo descrito abajo. Esta recuperación no se aplica a subidas inciertas.

No es una protección contra alguien que controle tu PC y edite el programa o su estado; está diseñado para un único usuario local. No expongas esta carpeta o los comandos como un servidor público.

Si se interrumpe la subida, el trabajo queda en `UPLOADING`: no reintentes a ciegas, porque YouTube podría haber recibido el video. Revisa primero YouTube Studio. Si existe, conserva su enlace y no vuelvas a subirlo. Si confirmas que no se creó, cambia manualmente el estado a `REVIEW` en `state.json`, elimina `approved_hash` y aprueba otra vez. Esta recuperación es manual para evitar duplicados. Si queda `.lock` tras cerrar abruptamente el programa, elimínalo solo después de comprobar que no hay otra ejecución activa.

## Archivos y comandos

- `agent.py`: investigación, guion, montaje, aprobación y YouTube.
- `production.py`: voz WAV, ilustraciones, caché de recursos y montaje audiovisual.
- `ui.py` y `web/`: servidor local e interfaz del estudio.
- `abrir-panel.ps1`: abre el panel en el navegador.
- `tests/`: validación, aprobación, recuperación, publicación simulada y pruebas HTTP del panel.
- `preparar-local.ps1`: crea el entorno e instala dependencias.
- `probar-local.ps1`: diagnóstico, pruebas y demo sin APIs.
- `requirements.txt`: dependencias con rangos de versión; no es un lockfile reproducible.
- `.env.example`: configuración sin secretos.
- `data/ID/`: video, láminas, audio, guion, fuentes y estado de cada trabajo.
- `agent.py listar`: ver trabajos y estados.
- `agent.py diagnostico`: comprobar dependencias y FFmpeg sin conexión a proveedores.
- `agent.py --help`: ayuda.

Pruebas locales sin claves ni publicaciones:

```powershell
.\probar-local.ps1
```

## Alcance comprobado de la entrega

La comprobación local incluye 78 pruebas de validación, corrección de longitud, aprobación, bloqueo por cambios, recuperación, publicación simulada, producción audiovisual y HTTP del panel; seis validaciones adicionales con Python optimizado; y una demo generada, editada y regenerada desde el navegador. Las pruebas de producción incluyen montaje real con FFmpeg, conservación del MP4 anterior ante fallos, reutilización de recursos y WAV con cabecera provisional de streaming.

Se completaron videos reales de seres mitológicos y de la Guerra del Guano y Salitre, ambos de 600 segundos, en el formato anterior de láminas. El primero fue rechazado. Para el segundo se verificó una nueva muestra real de 48,71 segundos, con Cedar, audio WAV a velocidad original e ilustración de GPT Image 2 con movimiento, sin aviso hablado ni rótulo de producción con IA. Su guion actualizado tiene 1309 palabras y el estado es `RESEARCHED`: requiere regenerar el video completo y revisarlo antes de aprobar. El MP4 anterior se conserva; la muestra no lo reemplaza. Los originales del guion, estado y muestra se guardaron en `content_edit_backups/20261011-remove-notices/` dentro del trabajo. Las 78 pruebas se comprobaron; una conexión HTTP interrumpida por Windows pasó al repetir las 16 pruebas del panel. La comprobación visual del panel mediante el navegador integrado quedó pendiente por un tiempo de espera; sus rutas HTTP y JavaScript se validaron localmente. La conexión OAuth y la subida real a YouTube siguen pendientes; no se ha conectado ni publicado nada en tu canal.

El flujo puede iniciarse por tema o por el comando diario, conservando siempre la aprobación humana. Extensiones posibles: cola de trabajos, base de datos, subtítulos sincronizados y recursos visuales originales.

## Documentación técnica consultada

- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/text-to-speech
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/guides/auth/installed-apps
- https://learn.chatgpt.com/docs/automations
- https://ffmpeg.org/ffmpeg-filters.html

Las noticias se consultan al ejecutar investigar, no vienen precargadas en el proyecto.
