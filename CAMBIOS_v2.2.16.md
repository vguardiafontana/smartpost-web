# Parche v2.2.16

- Denuncias GBA ahora abre un navegador/contexto nuevo en cada ejecución en lugar de reutilizar un perfil persistente.
- Evita bloqueos silenciosos por perfiles Chromium que quedaron abiertos o bloqueados tras una prueba anterior.
- Agrega mensajes inmediatos al log al iniciar y al abrir el navegador.
- El navegador de Denuncias tiene timeout de 30 s al iniciar, para que un fallo no quede colgado indefinidamente.
