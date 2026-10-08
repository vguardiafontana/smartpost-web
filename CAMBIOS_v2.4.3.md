# Parche v2.4.3

- Corrige la apertura de **Más listas** en WhatsApp Web.
- Ya no considera exitoso un click si el desplegable no se abrió realmente.
- Soporta el DOM observado: `span > svg > title` con `ic-arrow-drop-down`.
- Prueba el control accesible, varios ancestros clickeables, eventos pointer/mouse y click por coordenadas como último recurso.
- Verifica la apertura por la presencia visible de `New list` / `Nueva lista` antes de buscar `Smart Post`.
