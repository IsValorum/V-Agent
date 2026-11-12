<div align="center">

# V-Agent

**Un agente de IA local para Windows.**
Ejecuta modelos GGUF en tu propio PC —o conecta una API compatible con OpenAI o Claude— y dales
herramientas reales con permisos claros.

[![Tests](https://github.com/IsValorum/V-Agent/actions/workflows/tests.yml/badge.svg)](https://github.com/IsValorum/V-Agent/actions/workflows/tests.yml) [![Latest release](https://img.shields.io/github/v/release/IsValorum/V-Agent)](https://github.com/IsValorum/V-Agent/releases/latest) [![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

[Descargar](../../releases/latest) · [Arquitectura](docs/ARCHITECTURE.md) · [Calidad](docs/QUALITY.md) · [Cambios](CHANGELOG.md) · [Read in English](README.md)

![V-Agent](docs/images/main.png)

</div>

<a href="https://ko-fi.com/isvalorum"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Apoyar en Ko-fi" height="36"></a>

> [!IMPORTANT]
> **Desarrollado y probado de forma independiente, financiado al 100 % de mi bolsillo.**
>
> V-Agent no tiene anuncios, cuentas ni telemetría. Si te ayuda en tu día a día, considera
> [apoyarlo en Ko-fi](https://ko-fi.com/isvalorum). Cada aporte se destina al hardware y al tiempo de
> cómputo con que se prueban nuevos modelos, motores y versiones, y ayuda a sostener mis estudios
> universitarios.

## Tres motores locales, integrados

V-Agent no se limita a apuntar a un motor que configuras tú: **llama.cpp, Strata y Strata Rust están
integrados de forma nativa**. Los instala, los arranca, habla con sus servidores privados y lee sus
propias cifras, y cambias de uno a otro desde la ventana del modelo con un clic.

| | Qué hace V-Agent con él |
|---|---|
| **Strata** (por defecto) | Su servidor y su hub MCP forman parte del núcleo de V-Agent. Ejecuta modelos **Mixture-of-Experts** grandes en GPU pequeñas manteniendo en VRAM los expertos más usados, y antes de cada respuesta V-Agent reajusta esa caché de expertos a la conversación: más expertos (escribe más rápido) en una charla corta, sitio para la caché KV en una larga, sin reiniciar nada. Cabezas MTP para decodificación especulativa. |
| **Strata Rust** | Arranca en la GPU con una clave privada por sesión y caché KV f16/q8/q4. Su contexto, velocidad y estado se leen del propio motor. |
| **llama.cpp** | La compilación oficial CUDA, Vulkan o CPU adecuada a tu equipo. Ajuste automático de capas y contexto, formatos de caché KV, drafts especulativos, visión (mmproj). |

En los tres: se instalan y actualizan desde sus **releases oficiales de GitHub** con verificación de
checksum y una prueba antes de activarse, conservando la versión anterior para volver atrás; un modelo
solo cuenta como cargado cuando el motor lo sirve de verdad; las velocidades se miden, no se estiman;
los ajustes se conservan al cambiar de motor; y un motor que no puede ejecutar la arquitectura de un
modelo lo dice al momento y te indica uno que sí. Antes de cada versión se ejecutan modelos reales en
los tres ([resultados](docs/test-reports/1.0.6.md)).

## Qué hace

- **Ejecuta modelos en tu equipo** con las compilaciones oficiales de **llama.cpp** (CUDA, Vulkan o CPU,
  según tu hardware, descargadas de sus releases de GitHub), **Strata** o **Strata Rust**. También
  funciona con APIs remotas compatibles con OpenAI y Claude.
- **Le da herramientas al modelo**: archivos (con versiones y deshacer), comandos, búsqueda web y
  lectura de páginas, un navegador autónomo, peticiones HTTP, Hugging Face y cualquier servidor MCP,
  dentro de una **carpeta aislada por chat** o en todo el PC, con aprobación por acción.
- **Te ayuda a encontrar modelos**: la ventana *Modelos* explora Hugging Face (descargas, likes,
  contexto, licencia, la ficha renderizada y si cada cuantización cabe en tu GPU), descarga verificando
  el SHA-256 e importa modelos y sus ajustes desde **LM Studio** y **Unsloth Studio**.
- **Revisa el código que escribe**: Python (compilado), JavaScript, CSS, PowerShell, JSON, YAML, TOML,
  XML/SVG y Java, además de TypeScript, C/C++, Rust, Go, PHP, Ruby y Lua si su compilador está
  instalado. Las páginas HTML se ejecutan en un navegador sin interfaz con el mismo aislamiento que la
  vista previa y reportan los errores con su línea.
- **Sigue siendo tuyo**: sin cuenta y sin telemetría. Las actualizaciones van firmadas y la app solo
  acepta lo que firma el autor.

![Ventana Modelos](docs/images/models.png)

## Calidad y pruebas

- **Más de 200 pruebas automáticas** en cada cambio (núcleo, lógica de la interfaz, actualizaciones,
  seguridad), además de análisis estático con ruff, bandit y ESLint.
- **Pruebas con modelos reales** en llama.cpp, Strata y Strata Rust: se crean y comprueban archivos,
  se respetan las aprobaciones, las respuestas se detienen limpiamente y un motor que no puede ejecutar
  un modelo lo dice.
- **Un recorrido automático por toda la interfaz** en un navegador sin ventana (cada ventana y página
  de ajustes, tema claro y oscuro, ventanas pequeñas y grandes), y una sonda que detecta ventanas que
  parpadean.
- **Cada versión se comprueba** antes y después de publicarla: se arranca la aplicación empaquetada y
  se verifica la actualización firmada tal como la verificará la versión anterior.

Resultados de cada comprobación de esta versión, con capturas de su interfaz real:
[docs/test-reports/1.0.6.md](docs/test-reports/1.0.6.md). Métodos, herramientas y lo que aún no se cubre:
[docs/QUALITY.md](docs/QUALITY.md) (en inglés).

## Instalar

1. Descarga `V-Agent_<versión>_x64-setup.exe` desde [Releases](../../releases/latest) (Windows 10/11, x64).
2. Ábrelo. Lo más probable es que Windows muestre una pantalla azul **"Windows protegió tu PC"**: mira la nota de abajo.
3. Elige idioma (Español, English, Português, Français, Deutsch) y carpeta. No hace falta ser administrador.
4. Al abrirlo por primera vez te recomienda un motor para tu hardware y lo instala cuando confirmas.
5. Añade un modelo GGUF o abre **Modelos** para buscar uno, y empieza a chatear. Un tutorial breve explica el resto.

> [!IMPORTANT]
> **Sobre el aviso "Windows protegió tu PC".** El instalador todavía no está firmado con un
> certificado de firma de código de Microsoft (es de pago), así que Windows SmartScreen no reconoce al
> autor y muestra este aviso con las descargas nuevas. Para continuar, pulsa **Más información →
> Ejecutar de todas formas**.
>
> Hazlo solo con el instalador descargado de los [Releases](../../releases/latest) de este
> repositorio. Puedes comprobar que tu archivo es el publicado: ejecuta
> `Get-FileHash .\V-Agent_<versión>_x64-setup.exe` en PowerShell y compara el resultado con el valor
> `sha256` del archivo `v-agent-update.json` de la versión (da igual que esté en mayúsculas o minúsculas; ese archivo lo firma el autor, y V-Agent
> verifica esa misma firma antes de instalar cualquier actualización).

V-Agent se mantiene al día solo: al poco de abrirse aplica la **actualización menor** firmada más
reciente (numeradas *1.0.0 C1, C2…*, sin instalador) y descarga un instalador más nuevo si existe, que
solo instala cuando tú lo indicas.

## Mapa del repositorio

| Carpeta | Qué contiene |
|---|---|
| [`agent/`](agent/) | El núcleo: bucle del agente, API local, motores, herramientas (servidores MCP), actualizaciones y el código de la interfaz en [`agent/ui/`](agent/ui/). |
| [`serve/`](serve/) | Capa de peticiones compatible con OpenAI/Anthropic y el hub MCP, tomados de PolyStrata. |
| [`web_mcp/`](web_mcp/) | Búsqueda web, lectura de páginas y herramientas HTTP (servidores MCP). |
| [`tools/`](tools/) | Lector de cabeceras GGUF y tokenizador usados al importar modelos. |
| [`desktop/`](desktop/) | La aplicación de Windows (Tauri 2, Rust) y la configuración del instalador. |
| [`scripts/`](scripts/) | Compilación, empaquetado, sincronización de la interfaz y firma de versiones. |
| [`tests/`](tests/) | Pruebas automáticas (Python + interfaz) y pruebas manuales con modelo real. |
| [`docs/`](docs/) | Arquitectura, API local, guía de usuario, capturas y notas de diseño. |

## Compilar y probar

Requisitos: Windows 10/11 x64, Python 3.13, Node.js 20+, Rust (stable, MSVC) y Visual Studio Build Tools.
Los comandos están en el [README en inglés](README.md#build-and-test) y en [CONTRIBUTING.md](CONTRIBUTING.md).

## Seguridad y privacidad

- Todo escucha solo en `127.0.0.1` y responde únicamente a nombres locales, así que las páginas web no
  pueden alcanzarlo. Los servidores de los motores exigen una clave privada en cada sesión.
- Los archivos de modelo nunca se copian ni se modifican.
- Los comandos se ejecutan en un contenedor de procesos de Windows en modo aislado; el acceso a todo el
  PC es opcional.
- Las herramientas que escriben archivos, restauran versiones, ejecutan comandos o usan la red piden
  permiso en el modo «Preguntar»; las aprobaciones las aplica el núcleo, no solo la interfaz.
- Las actualizaciones (instaladores, actualizaciones menores y motores) se verifican antes de usarse:
  firma Ed25519 del autor para V-Agent, release oficial de GitHub y SHA-256 para motores y descargas de
  Hugging Face.

Lee [SECURITY.md](SECURITY.md) para informar de una vulnerabilidad y [PRIVACY.md](PRIVACY.md) para saber
qué se guarda y dónde.

## Licencia

[Apache License 2.0](LICENSE). Los componentes incluidos conservan sus licencias: ver [NOTICE](NOTICE),
[LICENSE.Strata](LICENSE.Strata) y [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
