#!/usr/bin/env python3
"""
Script de prueba para AutoCAD Architectural MCP Server
Ejecuta este archivo para verificar la conexión y hacer un dibujo de prueba.

Uso:
    python test_script.py
"""

import asyncio
import sys
from autocad_arch_mcp.server import AutoCADArchServer


def test_conexion():
    """Prueba la conexión a AutoCAD y dibuja elementos de prueba."""
    print("=" * 55)
    print("  AutoCAD Architectural MCP Server — Prueba")
    print("=" * 55)
    print()

    server = AutoCADArchServer()

    print("⟳  Conectando a AutoCAD...")
    if not server.connect():
        print("✗  No se pudo conectar a AutoCAD.")
        print("   Asegúrate de tener AutoCAD abierto.")
        sys.exit(1)

    print("✓  Conexión exitosa")
    print()

    # Info del dibujo
    info = server.info_dibujo()
    if "error" not in info:
        print(f"   Archivo : {info.get('archivo', 'N/A')}")
        print(f"   Entidades: {info.get('entidades', 0)}")
    print()

    # Configurar capas
    print("⟳  Creando capas arquitectónicas...")
    result = server.configurar_capas()
    if "ok" in result:
        print(f"✓  {len(result['capas_creadas'])} capas creadas")
    print()

    # Dibujo de prueba: habitación simple con puerta y ventana
    print("⟳  Dibujando habitación de prueba (5×4 m)...")
    r = server.dibujar_habitacion(0, 0, 5, 4, nombre="SALA DE PRUEBA")
    print(f"✓  Habitación: {r}")

    print("⟳  Dibujando puerta de prueba...")
    r = server.dibujar_puerta(1.0, 0.075, ancho=0.90, angulo_deg=90)
    print(f"✓  Puerta: {r}")

    print("⟳  Dibujando ventana de prueba...")
    r = server.dibujar_ventana(3.0, 3.925, 4.5, 3.925)
    print(f"✓  Ventana: {r}")

    print("⟳  Agregando cota de prueba...")
    r = server.agregar_cota(0, 0, 5, 0, offset=0.80)
    print(f"✓  Cota: {r}")

    print("⟳  Dibujando carátula...")
    r = server.dibujar_caratula(
        titulo="PLANO DE PRUEBA",
        escala="1:50",
        hoja="01"
    )
    print(f"✓  Carátula: {r}")

    # Zoom para ver todo
    server.zoom_total()
    print()
    print("=" * 55)
    print("✓  Prueba completada — revisa AutoCAD")
    print("=" * 55)
    print()
    print("Para iniciar el servidor MCP ejecuta:")
    print("    python -m autocad_arch_mcp.server")
    print()


def iniciar_servidor():
    """Inicia el servidor MCP (modo producción para Claude Desktop)."""
    from autocad_arch_mcp.server import main
    main()


if __name__ == "__main__":
    if "--servidor" in sys.argv:
        iniciar_servidor()
    else:
        test_conexion()
