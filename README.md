# AutoCAD Architectural MCP Server 🏛️

Servidor MCP que conecta **Claude** con **AutoCAD** para dibujar planos arquitectónicos mediante lenguaje natural. Dibuja plantas, cortes transversales, cortes longitudinales y fachadas directamente desde Claude.

> **Solo Windows** — Usa la interfaz COM de AutoCAD (requiere AutoCAD instalado con licencia válida)

---

## ¿Qué puedes hacer?

Habla con Claude en lenguaje natural y él dibujará en AutoCAD:

- 🏠 **Plantas arquitectónicas** — muros, puertas, ventanas, habitaciones, escaleras, columnas
- ✂️ **Cortes transversales y longitudinales** — muros en sección, losas, ventanas y puertas en corte, terreno
- 🏗️ **Fachadas / alzados** — muros, ventanas, puertas, cubiertas a dos aguas o planas
- 📐 **Anotaciones** — cotas, textos, ejes de referencia, líneas de corte, carátula del plano
- 🚿 **Mobiliario** — inodoro, lavabo, ducha, bañera

---

## Requisitos

| Componente | Versión mínima |
|---|---|
| Windows | 10 / 11 |
| AutoCAD | 2000 o superior (cualquier versión con COM) |
| Python | 3.8+ |
| Claude Desktop | Última versión |

---

## Instalación

### 1. Clona el repositorio

```bash
git clone https://github.com/AntiApus/autocad-arch-mcp.git
cd autocad-arch-mcp
```

### 2. Crea un entorno virtual

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Instala el paquete

```bash
pip install -e .
```

### 4. Verifica la instalación

Abre AutoCAD primero, luego ejecuta:

```bash
python test_script.py
```

Deberías ver una habitación de prueba con puerta, ventana y cota en AutoCAD.

---

## Configuración con Claude Desktop

Edita el archivo de configuración de Claude Desktop:

**Ruta:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "autocad-arch": {
      "command": "python",
      "args": [
        "C:\\RUTA\\COMPLETA\\autocad-arch-mcp\\test_script.py",
        "--servidor"
      ],
      "env": {
        "PYTHONPATH": "C:\\RUTA\\COMPLETA\\autocad-arch-mcp"
      }
    }
  }
}
```

> ⚠️ Reemplaza `C:\\RUTA\\COMPLETA\\autocad-arch-mcp` con la ruta real donde clonaste el repositorio.

Después reinicia Claude Desktop completamente.

---

## Licencia

MIT 
