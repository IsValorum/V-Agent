# Organización de la interfaz

La revisión se hizo sobre la instalación local de Unsloth Studio: `C:/Users/SS/.unsloth/studio/unsloth_studio/Lib/site-packages/studio`.

Se leyeron los módulos distribuidos `settings-section`, `model-memory-section`, `model-config-draft` y `per-model-config`, además de los ejemplos `smoke-composer-settings-main.tsx` y `smoke-nonmodal-menus-main.tsx`. La instalación distribuye las funciones de interfaz como paquetes JS compilados; no incluye todos los componentes TSX originales.

Se adaptaron ideas generales con implementación propia: secciones por tarea, controles avanzados plegados, cabeceras con acciones próximas al ajuste y diferencia entre configuración seleccionada y aplicada. No se incorporaron dependencias ni componentes de Unsloth.

VAL usa pestañas Carga/Generación; Personalización separa Aspecto/Distribución/Historial. Los MCP conservan sus interruptores manuales y muestran conexiones en un desplegable. Filtrar el catálogo conserva la selección del modelo y no lo carga. Los menús tienen un límite de altura y barras de desplazamiento estables.

El catálogo GGUF comparte hechos mínimos entre registro, KV y MTP. La caché local usa ruta, tamaño y modificación del archivo; no contiene vocabulario ni datos de pesos. Modificar el GGUF invalida la caché. El lector completo mantiene su comportamiento por defecto para tokenización y otras funciones.

## Reorganización por tarea — 9 de noviembre de 2026

Se revisaron las opciones existentes y las referencias de OpenCode (Models/Providers), la instalación local de Unsloth Studio (ComposerSettings y navegación de ajustes) y la guía Web UI de DeepSeek Harness. Se mantuvo el diseño propio de VAL: composer compacto, ventanas flotantes, Carga/Generación, proyecto y modo junto a la escritura, navegador acoplado y consola independiente. No se copiaron componentes ni dependencias.

Cambios concretos:
- El selector de motor, compilación, conexión API y ajustes asociados está en el panel del modelo, bajo Motor y conexión. Cambiar motor ya no exige ir a otra ventana. Se mueven los nodos originales, no se duplican controles. Encendido/apagado permanece junto al modelo; ya no se traslada al visitar Sistema.
- Sistema conserva monitor de recursos y actualizaciones de motores, con acceso al panel de modelo/motor.
- Apariencia incluye tipografía, tamaños, distribución visual, colores, fondos y animaciones. Chat conserva los controles de posición de botones y del cuadro de escritura.
- Herramientas agrupa modo, alcance de acceso y límites de ejecución, incluida la cifra existente de rondas. Las capacidades siguen seleccionándose allí.
- Ajustes > MCPs configura los valores predeterminados de los servicios; Configurar MCPs abre esa página correctamente, sin enfocar contenido oculto en otra ventana. El Mercado conserva incorporación/compatibilidad y activación de extensiones; no se mezcló con activación cotidiana del chat.
- Buscar ajustes consulta etiquetas y contenido de las páginas y cambia a una categoría coincidente; muestra Sin resultados cuando procede.

No se alteraron permisos, modos, esquemas MCP, 50 rondas, parámetros ni valores por modelo. Se probaron siete categorías sin desbordamiento horizontal, acceso a MCPs, búsqueda por Región y ausencia de IDs duplicados. Referencias:
https://opencode.ai/docs/models/
https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/index.md
Instalación local: C:/Users/SS/.unsloth/studio/unsloth_studio/Lib/site-packages/studio/frontend
