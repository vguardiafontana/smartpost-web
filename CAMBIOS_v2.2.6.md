# SmartPost v2.2.6

- Elimina por completo `setSizeGripEnabled` del `QMainWindow`.
- `QMainWindow` ya es redimensionable por bordes/esquinas en Windows; no necesita esa llamada.
- Evita el crash de arranque `AttributeError: MainWindow ... setSizeGripEnabled`.
