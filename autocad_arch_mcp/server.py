#!/usr/bin/env python3
"""
AutoCAD Architectural MCP Server
Servidor MCP para dibujo arquitectónico en AutoCAD
Permite a Claude dibujar plantas, cortes, fachadas y más.

Autor: Generado con Claude (Anthropic)
Licencia: MIT
"""

import asyncio
import json
import math
import time
from typing import Any, Dict, List, Tuple

import pythoncom
import win32com.client

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions


# ═══════════════════════════════════════════════════════
#  CAPAS ARQUITECTÓNICAS ESTÁNDAR
# ═══════════════════════════════════════════════════════

ARCH_LAYERS: Dict[str, Dict] = {
    "A-MUROS":      {"color": 7,  "lw": 50,  "desc": "Muros y paredes"},
    "A-MUROS-SEC":  {"color": 8,  "lw": 25,  "desc": "Muros secundarios"},
    "A-PUERTAS":    {"color": 3,  "lw": 35,  "desc": "Puertas"},
    "A-VENTANAS":   {"color": 4,  "lw": 35,  "desc": "Ventanas"},
    "A-ESCALERAS":  {"color": 2,  "lw": 25,  "desc": "Escaleras"},
    "A-COLUMNAS":   {"color": 7,  "lw": 70,  "desc": "Columnas estructurales"},
    "A-LOSAS":      {"color": 9,  "lw": 35,  "desc": "Losas y techos"},
    "A-TEXTO":      {"color": 7,  "lw": 18,  "desc": "Anotaciones y textos"},
    "A-COTAS":      {"color": 2,  "lw": 18,  "desc": "Cotas y dimensiones"},
    "A-TRAMA":      {"color": 8,  "lw": 9,   "desc": "Tramas y sombreados"},
    "A-EJES":       {"color": 1,  "lw": 9,   "desc": "Ejes de referencia"},
    "A-CARATULA":   {"color": 7,  "lw": 50,  "desc": "Carátula del plano"},
    "A-CORTES":     {"color": 1,  "lw": 50,  "desc": "Líneas de corte"},
    "A-FACHADA":    {"color": 7,  "lw": 35,  "desc": "Elementos de fachada"},
    "A-MOBILIARIO": {"color": 5,  "lw": 18,  "desc": "Mobiliario y equipamiento"},
    "A-TERRENO":    {"color": 3,  "lw": 25,  "desc": "Terreno y topografía"},
}


# ═══════════════════════════════════════════════════════
#  SERVIDOR PRINCIPAL
# ═══════════════════════════════════════════════════════

class AutoCADArchServer:
    """
    Servidor MCP que conecta Claude con AutoCAD para dibujo arquitectónico.
    Soporta: plantas, cortes transversales/longitudinales, fachadas y más.
    """

    def __init__(self):
        self.server = Server("autocad-arch-mcp")
        self.acad_app = None
        self.doc = None
        self.model = None
        self.connected = False
        self._register_tools()

    # ───────────────────────────────────────────────────
    #  CONEXIÓN A AUTOCAD
    # ───────────────────────────────────────────────────

    def connect(self) -> bool:
        """Conectar a AutoCAD (abierto o iniciar uno nuevo)."""
        try:
            pythoncom.CoInitialize()
            try:
                # Conectar a AutoCAD ya abierto
                self.acad_app = win32com.client.GetActiveObject("AutoCAD.Application")
            except Exception:
                # Abrir AutoCAD si no está corriendo
                self.acad_app = win32com.client.Dispatch("AutoCAD.Application")
                self.acad_app.Visible = True
                time.sleep(3)

            # Obtener o crear documento
            if self.acad_app.Documents.Count == 0:
                self.doc = self.acad_app.Documents.Add()
            else:
                self.doc = self.acad_app.ActiveDocument

            self.model = self.doc.ModelSpace
            self.connected = True
            self._ensure_layers()
            return True
        except Exception as e:
            print(f"Error conectando a AutoCAD: {e}")
            return False

    def _ensure_connection(self) -> bool:
        if not self.connected:
            return self.connect()
        try:
            _ = self.doc.Name
            return True
        except Exception:
            self.connected = False
            return self.connect()

    def _safe(self, fn):
        """Ejecutar operación COM con manejo de errores."""
        if not self._ensure_connection():
            return {"error": "No se pudo conectar a AutoCAD. Asegúrate de que esté abierto."}
        try:
            return fn()
        except Exception as e:
            return {"error": str(e)}

    # ───────────────────────────────────────────────────
    #  GESTIÓN DE CAPAS
    # ───────────────────────────────────────────────────

    def _ensure_layers(self):
        """Crear capas arquitectónicas estándar si no existen."""
        for name, props in ARCH_LAYERS.items():
            try:
                layer = self.doc.Layers.Item(name)
            except Exception:
                layer = self.doc.Layers.Add(name)
            try:
                layer.Color = props["color"]
                layer.Lineweight = props["lw"]
            except Exception:
                pass

    def _set_layer(self, name: str):
        """Activar una capa por nombre."""
        if name not in ARCH_LAYERS:
            name = "A-TEXTO"
        try:
            layer = self.doc.Layers.Item(name)
            self.doc.ActiveLayer = layer
        except Exception:
            pass

    # ───────────────────────────────────────────────────
    #  HELPERS COM
    # ───────────────────────────────────────────────────

    def _pt(self, x: float, y: float, z: float = 0.0):
        """Crear punto COM 3D."""
        return win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [float(x), float(y), float(z)]
        )

    def _pts(self, coords: List[Tuple[float, float]]):
        """Crear array plano de puntos para polilíneas."""
        flat = []
        for pt in coords:
            flat += [float(pt[0]), float(pt[1]), 0.0]
        return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)

    def _perp_offset(self, x1, y1, x2, y2, dist):
        """Calcular offset perpendicular a una línea."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            return 0, 0
        return -dy / length * dist, dx / length * dist

    # ───────────────────────────────────────────────────
    #  PRIMITIVAS DE DIBUJO
    # ───────────────────────────────────────────────────

    def _line(self, x1, y1, x2, y2, layer="A-MUROS"):
        self._set_layer(layer)
        return self.model.AddLine(self._pt(x1, y1), self._pt(x2, y2))

    def _polyline(self, pts: List[Tuple], closed=False, layer="A-MUROS"):
        self._set_layer(layer)
        pl = self.model.AddLightWeightPolyline(self._pts(pts))
        pl.Closed = closed
        return pl

    def _circle(self, cx, cy, radius, layer="A-MUROS"):
        self._set_layer(layer)
        return self.model.AddCircle(self._pt(cx, cy), float(radius))

    def _arc(self, cx, cy, radius, start_deg, end_deg, layer="A-PUERTAS"):
        self._set_layer(layer)
        return self.model.AddArc(
            self._pt(cx, cy),
            float(radius),
            math.radians(start_deg),
            math.radians(end_deg)
        )

    def _text(self, x, y, text, height=0.25, layer="A-TEXTO"):
        self._set_layer(layer)
        return self.model.AddText(str(text), self._pt(x, y), float(height))

    # ═══════════════════════════════════════════════════════
    #  HERRAMIENTAS DE PLANTA ARQUITECTÓNICA
    # ═══════════════════════════════════════════════════════

    def dibujar_muro(self, x1: float, y1: float, x2: float, y2: float,
                     espesor: float = 0.15, layer: str = "A-MUROS") -> Dict:
        """Dibuja un muro como polilínea cerrada con espesor."""
        def op():
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 0.001:
                return {"error": "El muro tiene longitud cero"}

            px, py = self._perp_offset(x1, y1, x2, y2, espesor / 2)

            pts = [
                (x1 + px, y1 + py),
                (x2 + px, y2 + py),
                (x2 - px, y2 - py),
                (x1 - px, y1 - py),
            ]
            self._polyline(pts, closed=True, layer=layer)
            return {"ok": True, "tipo": "muro", "longitud": round(length, 3),
                    "espesor": espesor}
        return self._safe(op)

    def dibujar_puerta(self, x: float, y: float, ancho: float = 0.90,
                       angulo_deg: float = 0.0, apertura_deg: float = 90.0) -> Dict:
        """Dibuja símbolo de puerta (hoja + arco de apertura)."""
        def op():
            a = math.radians(angulo_deg)
            x2 = x + math.cos(a) * ancho
            y2 = y + math.sin(a) * ancho
            # Hoja de la puerta
            self._line(x, y, x2, y2, layer="A-PUERTAS")
            # Arco de apertura
            self._arc(x, y, ancho, angulo_deg, angulo_deg + apertura_deg,
                      layer="A-PUERTAS")
            return {"ok": True, "tipo": "puerta", "ancho": ancho}
        return self._safe(op)

    def dibujar_ventana(self, x1: float, y1: float, x2: float, y2: float,
                        espesor_muro: float = 0.15) -> Dict:
        """Dibuja símbolo de ventana (tres líneas en hueco del muro)."""
        def op():
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 0.001:
                return {"error": "La ventana tiene longitud cero"}

            px, py = self._perp_offset(x1, y1, x2, y2, espesor_muro / 2)

            # Línea exterior 1
            self._line(x1 + px, y1 + py, x2 + px, y2 + py, layer="A-VENTANAS")
            # Línea central
            self._line(x1, y1, x2, y2, layer="A-VENTANAS")
            # Línea exterior 2
            self._line(x1 - px, y1 - py, x2 - px, y2 - py, layer="A-VENTANAS")
            # Tapas
            self._line(x1 + px, y1 + py, x1 - px, y1 - py, layer="A-VENTANAS")
            self._line(x2 + px, y2 + py, x2 - px, y2 - py, layer="A-VENTANAS")
            return {"ok": True, "tipo": "ventana", "ancho": round(length, 3)}
        return self._safe(op)

    def dibujar_habitacion(self, x1: float, y1: float, x2: float, y2: float,
                           nombre: str = "", espesor: float = 0.15) -> Dict:
        """Dibuja una habitación completa con muros y etiqueta."""
        def op():
            lx, ly = min(x1, x2), min(y1, y2)
            rx, ry = max(x1, x2), max(y1, y2)
            w, h = rx - lx, ry - ly
            if w < 0.01 or h < 0.01:
                return {"error": "Dimensiones de habitación demasiado pequeñas"}

            t = espesor / 2
            # Rectángulo exterior
            self._polyline([
                (lx - t, ly - t), (rx + t, ly - t),
                (rx + t, ry + t), (lx - t, ry + t)
            ], closed=True, layer="A-MUROS")
            # Rectángulo interior
            self._polyline([
                (lx + t, ly + t), (rx - t, ly + t),
                (rx - t, ry - t), (lx + t, ry - t)
            ], closed=True, layer="A-MUROS")
            # Etiqueta centrada
            if nombre:
                cx = (lx + rx) / 2 - len(nombre) * 0.07
                cy = (ly + ry) / 2
                self._text(cx, cy, nombre, height=0.25, layer="A-TEXTO")
                # Área en m²
                area = round(w * h, 2)
                self._text(cx, cy - 0.35, f"{area} m²", height=0.18, layer="A-TEXTO")

            return {"ok": True, "tipo": "habitacion", "nombre": nombre,
                    "ancho": round(w, 3), "largo": round(h, 3),
                    "area": round(w * h, 2)}
        return self._safe(op)

    def dibujar_columna(self, cx: float, cy: float, tamano: float = 0.30,
                        forma: str = "cuadrada") -> Dict:
        """Dibuja una columna estructural (cuadrada o circular)."""
        def op():
            if forma == "circular":
                self._circle(cx, cy, tamano / 2, layer="A-COLUMNAS")
            else:
                h = tamano / 2
                self._polyline([
                    (cx - h, cy - h), (cx + h, cy - h),
                    (cx + h, cy + h), (cx - h, cy + h)
                ], closed=True, layer="A-COLUMNAS")
            return {"ok": True, "tipo": "columna", "forma": forma, "tamano": tamano}
        return self._safe(op)

    def dibujar_escalera(self, x: float, y: float, ancho: float = 1.20,
                         profundidad_huella: float = 0.28,
                         num_escalones: int = 12,
                         direccion: str = "vertical") -> Dict:
        """Dibuja una escalera en planta con huellas y flecha de subida."""
        def op():
            layer = "A-ESCALERAS"
            # Dibujar cada huella
            for i in range(num_escalones):
                if direccion == "vertical":
                    d = i * profundidad_huella
                    self._line(x, y + d, x + ancho, y + d, layer=layer)
                else:
                    d = i * profundidad_huella
                    self._line(x + d, y, x + d, y + ancho, layer=layer)

            # Línea de contorno
            total = num_escalones * profundidad_huella
            if direccion == "vertical":
                self._polyline([
                    (x, y), (x + ancho, y),
                    (x + ancho, y + total), (x, y + total)
                ], closed=True, layer=layer)
                # Flecha indicadora de subida
                mx = x + ancho / 2
                self._line(mx, y, mx, y + total * 0.7, layer="A-TEXTO")
                self._text(mx - 0.10, y + total * 0.75, "↑", height=0.30, layer="A-TEXTO")
                self._text(mx - 0.15, y + total * 0.82, "SUBE", height=0.20, layer="A-TEXTO")
            else:
                self._polyline([
                    (x, y), (x + total, y),
                    (x + total, y + ancho), (x, y + ancho)
                ], closed=True, layer=layer)
                my = y + ancho / 2
                self._line(x, my, x + total * 0.7, my, layer="A-TEXTO")
                self._text(x + total * 0.72, my - 0.10, "→", height=0.30, layer="A-TEXTO")

            return {"ok": True, "tipo": "escalera", "escalones": num_escalones,
                    "ancho": ancho, "largo": round(total, 3)}
        return self._safe(op)

    def dibujar_mobiliario_bano(self, x: float, y: float,
                                tipo: str = "inodoro") -> Dict:
        """Dibuja símbolo de mobiliario de baño (inodoro, lavabo, ducha, bañera)."""
        def op():
            layer = "A-MOBILIARIO"
            tipo_l = tipo.lower()

            if tipo_l == "inodoro":
                # Base rectangular
                self._polyline([
                    (x, y), (x + 0.40, y),
                    (x + 0.40, y + 0.65), (x, y + 0.65)
                ], closed=True, layer=layer)
                # Taza ovalada (aproximada con arco)
                self._circle(x + 0.20, y + 0.30, 0.18, layer=layer)

            elif tipo_l == "lavabo":
                self._polyline([
                    (x, y), (x + 0.60, y),
                    (x + 0.60, y + 0.50), (x, y + 0.50)
                ], closed=True, layer=layer)
                self._circle(x + 0.30, y + 0.25, 0.18, layer=layer)

            elif tipo_l == "ducha":
                self._polyline([
                    (x, y), (x + 0.90, y),
                    (x + 0.90, y + 0.90), (x, y + 0.90)
                ], closed=True, layer=layer)
                self._arc(x, y, 0.90, 0, 90, layer=layer)

            elif tipo_l == "banera":
                self._polyline([
                    (x, y), (x + 1.70, y),
                    (x + 1.70, y + 0.75), (x, y + 0.75)
                ], closed=True, layer=layer)
                self._circle(x + 1.35, y + 0.375, 0.30, layer=layer)

            return {"ok": True, "tipo": f"mobiliario_{tipo}", "posicion": (x, y)}
        return self._safe(op)

    def dibujar_eje(self, x1: float, y1: float, x2: float, y2: float,
                    etiqueta: str = "1") -> Dict:
        """Dibuja un eje de referencia con burbuja y etiqueta."""
        def op():
            layer = "A-EJES"
            # Extender el eje un poco más allá
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 0.001:
                return {"error": "Eje de longitud cero"}
            ex, ey = dx / length * 0.60, dy / length * 0.60

            self._line(x1 - ex, y1 - ey, x2 + ex, y2 + ey, layer=layer)
            # Burbuja al final
            r = 0.35
            self._circle(x2 + ex + r, y2 + ey, r, layer=layer)
            self._text(x2 + ex + r - len(str(etiqueta)) * 0.08,
                       y2 + ey - 0.12, str(etiqueta),
                       height=0.25, layer=layer)
            return {"ok": True, "tipo": "eje", "etiqueta": etiqueta}
        return self._safe(op)

    # ═══════════════════════════════════════════════════════
    #  CORTES Y SECCIONES
    # ═══════════════════════════════════════════════════════

    def dibujar_losa(self, x: float, y: float, ancho: float,
                     espesor: float = 0.20, layer: str = "A-LOSAS") -> Dict:
        """Dibuja una losa en corte (rectángulo sólido)."""
        def op():
            self._polyline([
                (x, y), (x + ancho, y),
                (x + ancho, y - espesor), (x, y - espesor)
            ], closed=True, layer=layer)
            return {"ok": True, "tipo": "losa", "ancho": ancho, "espesor": espesor}
        return self._safe(op)

    def dibujar_muro_corte(self, x: float, y: float, alto: float,
                           espesor: float = 0.15) -> Dict:
        """Dibuja un muro en corte (rectángulo)."""
        def op():
            self._polyline([
                (x, y), (x + espesor, y),
                (x + espesor, y + alto), (x, y + alto)
            ], closed=True, layer="A-MUROS")
            return {"ok": True, "tipo": "muro_corte", "alto": alto, "espesor": espesor}
        return self._safe(op)

    def dibujar_ventana_corte(self, x: float, y: float, ancho: float,
                              alto_antepecho: float = 0.90,
                              alto_ventana: float = 1.20,
                              espesor_muro: float = 0.15) -> Dict:
        """Dibuja una ventana en corte con antepecho y dintel."""
        def op():
            # Antepecho (muro hasta la ventana)
            self._polyline([
                (x, y), (x + espesor_muro, y),
                (x + espesor_muro, y + alto_antepecho), (x, y + alto_antepecho)
            ], closed=True, layer="A-MUROS")
            # Ventana (hueco con líneas)
            yv = y + alto_antepecho
            self._line(x, yv, x + espesor_muro, yv, layer="A-VENTANAS")
            self._line(x, yv + alto_ventana, x + espesor_muro,
                       yv + alto_ventana, layer="A-VENTANAS")
            self._line(x, yv, x, yv + alto_ventana, layer="A-VENTANAS")
            self._line(x + espesor_muro, yv, x + espesor_muro,
                       yv + alto_ventana, layer="A-VENTANAS")
            # Vidrio (línea central)
            self._line(x + espesor_muro / 2, yv,
                       x + espesor_muro / 2, yv + alto_ventana,
                       layer="A-VENTANAS")
            return {"ok": True, "tipo": "ventana_corte"}
        return self._safe(op)

    def dibujar_puerta_corte(self, x: float, y: float, ancho: float = 0.90,
                             alto: float = 2.10,
                             espesor_muro: float = 0.15) -> Dict:
        """Dibuja una puerta en corte."""
        def op():
            # Hueco de puerta
            self._line(x, y, x, y + alto, layer="A-PUERTAS")
            self._line(x + espesor_muro, y, x + espesor_muro,
                       y + alto, layer="A-PUERTAS")
            self._line(x, y + alto, x + espesor_muro,
                       y + alto, layer="A-PUERTAS")
            # Hoja de puerta
            self._line(x, y, x + ancho, y, layer="A-PUERTAS")
            return {"ok": True, "tipo": "puerta_corte", "ancho": ancho, "alto": alto}
        return self._safe(op)

    def dibujar_terreno_corte(self, x: float, y: float, ancho: float,
                              nivel_piso: float = 0.0) -> Dict:
        """Dibuja línea de terreno en corte con sombreado."""
        def op():
            # Línea de terreno
            self._line(x - 1.0, y, x + ancho + 1.0, y, layer="A-TERRENO")
            # Línea de nivel de piso terminado
            self._line(x, y + nivel_piso, x + ancho,
                       y + nivel_piso, layer="A-TERRENO")
            # Rayado diagonal de terreno (cada 0.5m)
            paso = 0.5
            prof = 0.8
            for i in range(int((ancho + 2) / paso) + 1):
                xi = x - 1.0 + i * paso
                self._line(xi, y, xi - prof * 0.5, y - prof, layer="A-TRAMA")
            return {"ok": True, "tipo": "terreno"}
        return self._safe(op)

    def dibujar_linea_corte(self, x1: float, y1: float, x2: float, y2: float,
                            etiqueta: str = "A-A'") -> Dict:
        """Dibuja la línea de corte en planta con sus marcadores."""
        def op():
            layer = "A-CORTES"
            # Línea de corte
            self._line(x1, y1, x2, y2, layer=layer)
            # Marcadores en los extremos (cruces)
            r = 0.40
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length > 0:
                nx, ny = -dy / length, dx / length
                # Cruz inicio
                self._line(x1 - nx * r, y1 - ny * r,
                           x1 + nx * r, y1 + ny * r, layer=layer)
                # Cruz fin
                self._line(x2 - nx * r, y2 - ny * r,
                           x2 + nx * r, y2 + ny * r, layer=layer)
                # Etiquetas
                self._text(x1 - nx * r - 0.5, y1 - ny * r - 0.15,
                           etiqueta.split("-")[0] if "-" in etiqueta else etiqueta,
                           height=0.25, layer=layer)
                self._text(x2 + nx * r + 0.1, y2 + ny * r + 0.1,
                           etiqueta.split("-")[1] if "-" in etiqueta else etiqueta + "'",
                           height=0.25, layer=layer)
            return {"ok": True, "tipo": "linea_corte", "etiqueta": etiqueta}
        return self._safe(op)

    # ═══════════════════════════════════════════════════════
    #  FACHADA
    # ═══════════════════════════════════════════════════════

    def dibujar_ventana_fachada(self, x: float, y: float, ancho: float = 1.20,
                                alto: float = 1.10) -> Dict:
        """Dibuja una ventana en alzado/fachada."""
        def op():
            layer = "A-FACHADA"
            # Marco exterior
            self._polyline([
                (x, y), (x + ancho, y),
                (x + ancho, y + alto), (x, y + alto)
            ], closed=True, layer=layer)
            # Cruz de vidriería
            self._line(x + ancho / 2, y, x + ancho / 2, y + alto, layer=layer)
            self._line(x, y + alto / 2, x + ancho, y + alto / 2, layer=layer)
            # Alféizar
            self._line(x - 0.05, y, x + ancho + 0.05, y, layer=layer)
            return {"ok": True, "tipo": "ventana_fachada", "ancho": ancho, "alto": alto}
        return self._safe(op)

    def dibujar_puerta_fachada(self, x: float, y: float, ancho: float = 1.00,
                               alto: float = 2.10,
                               tipo: str = "simple") -> Dict:
        """Dibuja una puerta en alzado/fachada."""
        def op():
            layer = "A-FACHADA"
            # Marco y hoja
            self._polyline([
                (x, y), (x + ancho, y),
                (x + ancho, y + alto), (x, y + alto)
            ], closed=True, layer=layer)
            if tipo == "doble":
                self._line(x + ancho / 2, y, x + ancho / 2, y + alto, layer=layer)
                # Manijas
                self._line(x + ancho / 2 - 0.05, y + alto * 0.45,
                           x + ancho / 2 - 0.05, y + alto * 0.55, layer=layer)
                self._line(x + ancho / 2 + 0.05, y + alto * 0.45,
                           x + ancho / 2 + 0.05, y + alto * 0.55, layer=layer)
            else:
                # Manija simple
                self._circle(x + ancho * 0.80, y + alto * 0.50, 0.04, layer=layer)
            # Umbral
            self._line(x - 0.05, y, x + ancho + 0.05, y, layer=layer)
            return {"ok": True, "tipo": f"puerta_fachada_{tipo}",
                    "ancho": ancho, "alto": alto}
        return self._safe(op)

    def dibujar_muro_fachada(self, x: float, y: float, ancho: float,
                             alto: float) -> Dict:
        """Dibuja el contorno de un muro de fachada."""
        def op():
            self._polyline([
                (x, y), (x + ancho, y),
                (x + ancho, y + alto), (x, y + alto)
            ], closed=True, layer="A-FACHADA")
            return {"ok": True, "tipo": "muro_fachada", "ancho": ancho, "alto": alto}
        return self._safe(op)

    def dibujar_cubierta_fachada(self, x: float, y: float, ancho: float,
                                 pendiente: float = 0.30,
                                 tipo: str = "dos_aguas") -> Dict:
        """Dibuja cubierta en fachada (a dos aguas o plana)."""
        def op():
            layer = "A-FACHADA"
            if tipo == "dos_aguas":
                altura_cumbrera = ancho / 2 * pendiente
                # Triángulo
                self._polyline([
                    (x - 0.30, y),
                    (x + ancho / 2, y + altura_cumbrera),
                    (x + ancho + 0.30, y)
                ], closed=True, layer=layer)
            else:
                # Cubierta plana con pretil
                h_pretil = 0.60
                self._polyline([
                    (x, y), (x + ancho, y),
                    (x + ancho, y + h_pretil), (x, y + h_pretil)
                ], closed=True, layer=layer)
            return {"ok": True, "tipo": f"cubierta_{tipo}"}
        return self._safe(op)

    # ═══════════════════════════════════════════════════════
    #  ANOTACIONES Y TÍTULO
    # ═══════════════════════════════════════════════════════

    def agregar_cota(self, x1: float, y1: float, x2: float, y2: float,
                     offset: float = 0.80) -> Dict:
        """Agrega una cota alineada entre dos puntos."""
        def op():
            self._set_layer("A-COTAS")
            try:
                mx = (x1 + x2) / 2
                my = (y1 + y2) / 2

                # Dirección perpendicular para el offset
                dx, dy = x2 - x1, y2 - y1
                length = math.hypot(dx, dy)
                if length < 0.001:
                    return {"error": "Puntos idénticos para cota"}
                px, py = -dy / length * offset, dx / length * offset

                dim = self.model.AddDimAligned(
                    self._pt(x1, y1),
                    self._pt(x2, y2),
                    self._pt(mx + px, my + py)
                )
                return {"ok": True, "tipo": "cota",
                        "distancia": round(length, 3)}
            except Exception as e:
                return {"error": f"Error al crear cota: {e}"}
        return self._safe(op)

    def agregar_texto(self, x: float, y: float, texto: str,
                      altura: float = 0.25, layer: str = "A-TEXTO") -> Dict:
        """Agrega texto en el dibujo."""
        def op():
            if layer not in ARCH_LAYERS:
                lyr = "A-TEXTO"
            else:
                lyr = layer
            self._text(x, y, texto, height=altura, layer=lyr)
            return {"ok": True, "tipo": "texto", "contenido": texto}
        return self._safe(op)

    def dibujar_caratula(self, x: float = 0.0, y: float = -5.0,
                         titulo: str = "PROYECTO ARQUITECTÓNICO",
                         escala: str = "1:100",
                         hoja: str = "01",
                         autor: str = "",
                         fecha: str = "") -> Dict:
        """Dibuja la carátula del plano."""
        def op():
            layer = "A-CARATULA"
            w, h = 29.0, 4.0

            # Marco exterior
            self._polyline([
                (x, y), (x + w, y),
                (x + w, y + h), (x, y + h)
            ], closed=True, layer=layer)

            # Divisiones verticales
            self._line(x + 16, y, x + 16, y + h, layer=layer)
            self._line(x + 22, y, x + 22, y + h, layer=layer)
            self._line(x + 16, y + h / 2, x + w, y + h / 2, layer=layer)

            # Título principal
            self._text(x + 0.5, y + 2.0, titulo, height=0.80, layer=layer)

            # Datos del cuadro derecho
            self._text(x + 16.3, y + h * 0.70, "ESCALA:", height=0.22, layer=layer)
            self._text(x + 16.3, y + h * 0.40, escala, height=0.45, layer=layer)

            self._text(x + 22.3, y + h * 0.70, "HOJA:", height=0.22, layer=layer)
            self._text(x + 22.3, y + h * 0.40, hoja, height=0.45, layer=layer)

            if autor:
                self._text(x + 16.3, y + 0.3, f"Autor: {autor}",
                           height=0.22, layer=layer)
            if fecha:
                self._text(x + 22.3, y + 0.3, f"Fecha: {fecha}",
                           height=0.22, layer=layer)

            return {"ok": True, "tipo": "caratula", "titulo": titulo}
        return self._safe(op)

    # ═══════════════════════════════════════════════════════
    #  UTILIDADES
    # ═══════════════════════════════════════════════════════

    def info_dibujo(self) -> Dict:
        """Obtiene información del dibujo activo."""
        def op():
            capas = []
            for i in range(self.doc.Layers.Count):
                layer = self.doc.Layers.Item(i)
                capas.append(layer.Name)
            return {
                "archivo": self.doc.Name,
                "entidades": self.model.Count,
                "capa_activa": self.doc.ActiveLayer.Name,
                "guardado": self.doc.Saved,
                "total_capas": len(capas),
            }
        return self._safe(op)

    def zoom_total(self) -> Dict:
        """Zoom para ver todas las entidades."""
        def op():
            self.acad_app.ZoomExtents()
            return {"ok": True}
        return self._safe(op)

    def deshacer(self) -> Dict:
        """Deshace la última operación."""
        def op():
            self.doc.SendCommand("U ")
            return {"ok": True}
        return self._safe(op)

    def configurar_capas(self) -> Dict:
        """Crea todas las capas arquitectónicas estándar."""
        def op():
            self._ensure_layers()
            return {"ok": True, "capas_creadas": list(ARCH_LAYERS.keys())}
        return self._safe(op)

    # ═══════════════════════════════════════════════════════
    #  REGISTRO DE HERRAMIENTAS MCP
    # ═══════════════════════════════════════════════════════

    def _register_tools(self):
        """Registrar todas las herramientas en el servidor MCP."""

        @self.server.list_tools()
        async def list_tools() -> List[types.Tool]:
            return [
                types.Tool(
                    name="info_dibujo",
                    description="Obtiene información del dibujo AutoCAD activo (capas, entidades, nombre del archivo).",
                    inputSchema={"type": "object", "properties": {}, "required": []}
                ),
                types.Tool(
                    name="configurar_capas",
                    description="Crea las capas arquitectónicas estándar (muros, puertas, ventanas, cotas, etc.) en AutoCAD.",
                    inputSchema={"type": "object", "properties": {}, "required": []}
                ),
                types.Tool(
                    name="zoom_total",
                    description="Aplica zoom para ver todos los elementos del dibujo.",
                    inputSchema={"type": "object", "properties": {}, "required": []}
                ),
                types.Tool(
                    name="deshacer",
                    description="Deshace la última operación en AutoCAD (equivalente a Ctrl+Z).",
                    inputSchema={"type": "object", "properties": {}, "required": []}
                ),
                # ── PLANTA ──────────────────────────────────────
                types.Tool(
                    name="dibujar_muro",
                    description="Dibuja un muro en planta entre dos puntos con espesor definido. Usar para plantas arquitectónicas.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x1": {"type": "number", "description": "Coordenada X del punto inicial (metros)"},
                            "y1": {"type": "number", "description": "Coordenada Y del punto inicial (metros)"},
                            "x2": {"type": "number", "description": "Coordenada X del punto final (metros)"},
                            "y2": {"type": "number", "description": "Coordenada Y del punto final (metros)"},
                            "espesor": {"type": "number", "description": "Espesor del muro en metros (por defecto 0.15)", "default": 0.15},
                            "layer": {"type": "string", "description": "Capa ('A-MUROS' o 'A-MUROS-SEC')", "default": "A-MUROS"}
                        },
                        "required": ["x1", "y1", "x2", "y2"]
                    }
                ),
                types.Tool(
                    name="dibujar_puerta",
                    description="Dibuja símbolo de puerta en planta (hoja + arco de apertura).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "Coordenada X del punto de bisagra"},
                            "y": {"type": "number", "description": "Coordenada Y del punto de bisagra"},
                            "ancho": {"type": "number", "description": "Ancho de la puerta en metros (por defecto 0.90)", "default": 0.90},
                            "angulo_deg": {"type": "number", "description": "Ángulo de orientación de la puerta en grados (0=hacia la derecha)", "default": 0.0},
                            "apertura_deg": {"type": "number", "description": "Ángulo de apertura del arco en grados (por defecto 90)", "default": 90.0}
                        },
                        "required": ["x", "y"]
                    }
                ),
                types.Tool(
                    name="dibujar_ventana",
                    description="Dibuja símbolo de ventana en planta (tres líneas en el hueco del muro).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x1": {"type": "number", "description": "Coordenada X del extremo izquierdo de la ventana"},
                            "y1": {"type": "number", "description": "Coordenada Y del extremo izquierdo"},
                            "x2": {"type": "number", "description": "Coordenada X del extremo derecho"},
                            "y2": {"type": "number", "description": "Coordenada Y del extremo derecho"},
                            "espesor_muro": {"type": "number", "description": "Espesor del muro donde va la ventana (m)", "default": 0.15}
                        },
                        "required": ["x1", "y1", "x2", "y2"]
                    }
                ),
                types.Tool(
                    name="dibujar_habitacion",
                    description="Dibuja una habitación completa con muros dobles y etiqueta de nombre y área.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x1": {"type": "number", "description": "Coordenada X de la esquina 1"},
                            "y1": {"type": "number", "description": "Coordenada Y de la esquina 1"},
                            "x2": {"type": "number", "description": "Coordenada X de la esquina opuesta"},
                            "y2": {"type": "number", "description": "Coordenada Y de la esquina opuesta"},
                            "nombre": {"type": "string", "description": "Nombre de la habitación (ej: 'SALA', 'RECÁMARA 1')", "default": ""},
                            "espesor": {"type": "number", "description": "Espesor de muros en metros", "default": 0.15}
                        },
                        "required": ["x1", "y1", "x2", "y2"]
                    }
                ),
                types.Tool(
                    name="dibujar_columna",
                    description="Dibuja una columna estructural en planta (cuadrada o circular).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cx": {"type": "number", "description": "Coordenada X del centro de la columna"},
                            "cy": {"type": "number", "description": "Coordenada Y del centro"},
                            "tamano": {"type": "number", "description": "Tamaño de la columna en metros (por defecto 0.30)", "default": 0.30},
                            "forma": {"type": "string", "description": "'cuadrada' o 'circular'", "default": "cuadrada"}
                        },
                        "required": ["cx", "cy"]
                    }
                ),
                types.Tool(
                    name="dibujar_escalera",
                    description="Dibuja una escalera en planta con huellas, contorno y flecha de subida.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "Coordenada X del inicio de la escalera"},
                            "y": {"type": "number", "description": "Coordenada Y del inicio"},
                            "ancho": {"type": "number", "description": "Ancho de la escalera en metros", "default": 1.20},
                            "profundidad_huella": {"type": "number", "description": "Profundidad de cada huella en metros", "default": 0.28},
                            "num_escalones": {"type": "integer", "description": "Número de escalones", "default": 12},
                            "direccion": {"type": "string", "description": "'vertical' u 'horizontal'", "default": "vertical"}
                        },
                        "required": ["x", "y"]
                    }
                ),
                types.Tool(
                    name="dibujar_mobiliario_bano",
                    description="Dibuja símbolo de mobiliario de baño: inodoro, lavabo, ducha o bañera.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "Coordenada X de la esquina inferior izquierda"},
                            "y": {"type": "number", "description": "Coordenada Y"},
                            "tipo": {"type": "string", "description": "'inodoro', 'lavabo', 'ducha' o 'banera'", "default": "inodoro"}
                        },
                        "required": ["x", "y"]
                    }
                ),
                types.Tool(
                    name="dibujar_eje",
                    description="Dibuja un eje de referencia con burbuja y etiqueta para la cuadrícula estructural.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x1": {"type": "number", "description": "Coordenada X del inicio del eje"},
                            "y1": {"type": "number", "description": "Coordenada Y del inicio"},
                            "x2": {"type": "number", "description": "Coordenada X del final"},
                            "y2": {"type": "number", "description": "Coordenada Y del final"},
                            "etiqueta": {"type": "string", "description": "Etiqueta del eje (ej: '1', 'A', 'B')", "default": "1"}
                        },
                        "required": ["x1", "y1", "x2", "y2"]
                    }
                ),
                types.Tool(
                    name="dibujar_linea_corte",
                    description="Dibuja la línea de corte en planta con marcadores y etiqueta (ej: A-A').",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x1": {"type": "number"}, "y1": {"type": "number"},
                            "x2": {"type": "number"}, "y2": {"type": "number"},
                            "etiqueta": {"type": "string", "default": "A-A'"}
                        },
                        "required": ["x1", "y1", "x2", "y2"]
                    }
                ),
                # ── CORTES ──────────────────────────────────────
                types.Tool(
                    name="dibujar_losa",
                    description="Dibuja una losa (forjado o cubierta) en corte/sección transversal.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "Coordenada X del extremo izquierdo"},
                            "y": {"type": "number", "description": "Coordenada Y de la cara superior de la losa"},
                            "ancho": {"type": "number", "description": "Ancho de la losa en metros"},
                            "espesor": {"type": "number", "description": "Espesor de la losa en metros", "default": 0.20},
                            "layer": {"type": "string", "default": "A-LOSAS"}
                        },
                        "required": ["x", "y", "ancho"]
                    }
                ),
                types.Tool(
                    name="dibujar_muro_corte",
                    description="Dibuja un muro en corte/sección (rectángulo).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "Coordenada X del extremo izquierdo del muro"},
                            "y": {"type": "number", "description": "Coordenada Y de la base del muro"},
                            "alto": {"type": "number", "description": "Altura del muro en metros"},
                            "espesor": {"type": "number", "description": "Espesor del muro en metros", "default": 0.15}
                        },
                        "required": ["x", "y", "alto"]
                    }
                ),
                types.Tool(
                    name="dibujar_ventana_corte",
                    description="Dibuja una ventana en corte con antepecho y dintel.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "ancho": {"type": "number", "default": 1.20},
                            "alto_antepecho": {"type": "number", "description": "Altura del antepecho desde el piso (m)", "default": 0.90},
                            "alto_ventana": {"type": "number", "description": "Altura de la ventana (m)", "default": 1.20},
                            "espesor_muro": {"type": "number", "default": 0.15}
                        },
                        "required": ["x", "y"]
                    }
                ),
                types.Tool(
                    name="dibujar_puerta_corte",
                    description="Dibuja una puerta en corte/sección.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "ancho": {"type": "number", "default": 0.90},
                            "alto": {"type": "number", "description": "Altura de la puerta (m)", "default": 2.10},
                            "espesor_muro": {"type": "number", "default": 0.15}
                        },
                        "required": ["x", "y"]
                    }
                ),
                types.Tool(
                    name="dibujar_terreno_corte",
                    description="Dibuja la línea de terreno y nivel de piso terminado en corte.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "ancho": {"type": "number", "description": "Ancho del terreno a mostrar"},
                            "nivel_piso": {"type": "number", "description": "Nivel del piso terminado sobre el terreno (m)", "default": 0.0}
                        },
                        "required": ["x", "y", "ancho"]
                    }
                ),
                # ── FACHADA ─────────────────────────────────────
                types.Tool(
                    name="dibujar_ventana_fachada",
                    description="Dibuja una ventana en alzado/fachada con marco y división de cristal.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "Coordenada X esquina inferior izquierda"},
                            "y": {"type": "number", "description": "Coordenada Y esquina inferior"},
                            "ancho": {"type": "number", "description": "Ancho de la ventana (m)", "default": 1.20},
                            "alto": {"type": "number", "description": "Alto de la ventana (m)", "default": 1.10}
                        },
                        "required": ["x", "y"]
                    }
                ),
                types.Tool(
                    name="dibujar_puerta_fachada",
                    description="Dibuja una puerta en alzado/fachada (simple o doble hoja).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "ancho": {"type": "number", "default": 1.00},
                            "alto": {"type": "number", "default": 2.10},
                            "tipo": {"type": "string", "description": "'simple' o 'doble'", "default": "simple"}
                        },
                        "required": ["x", "y"]
                    }
                ),
                types.Tool(
                    name="dibujar_muro_fachada",
                    description="Dibuja el contorno de un paño de muro en fachada/alzado.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "ancho": {"type": "number"}, "alto": {"type": "number"}
                        },
                        "required": ["x", "y", "ancho", "alto"]
                    }
                ),
                types.Tool(
                    name="dibujar_cubierta_fachada",
                    description="Dibuja la cubierta en fachada: a dos aguas o plana con pretil.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "ancho": {"type": "number"},
                            "pendiente": {"type": "number", "description": "Pendiente de cubierta (0.30 = 30%)", "default": 0.30},
                            "tipo": {"type": "string", "description": "'dos_aguas' o 'plana'", "default": "dos_aguas"}
                        },
                        "required": ["x", "y", "ancho"]
                    }
                ),
                # ── ANOTACIONES ─────────────────────────────────
                types.Tool(
                    name="agregar_cota",
                    description="Agrega una cota/dimensión alineada entre dos puntos en el dibujo.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x1": {"type": "number"}, "y1": {"type": "number"},
                            "x2": {"type": "number"}, "y2": {"type": "number"},
                            "offset": {"type": "number", "description": "Separación de la línea de cota respecto al elemento (m)", "default": 0.80}
                        },
                        "required": ["x1", "y1", "x2", "y2"]
                    }
                ),
                types.Tool(
                    name="agregar_texto",
                    description="Agrega una etiqueta de texto en cualquier posición del dibujo.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "texto": {"type": "string"},
                            "altura": {"type": "number", "description": "Altura del texto en metros", "default": 0.25},
                            "layer": {"type": "string", "default": "A-TEXTO"}
                        },
                        "required": ["x", "y", "texto"]
                    }
                ),
                types.Tool(
                    name="dibujar_caratula",
                    description="Dibuja la carátula del plano con título, escala, número de hoja, autor y fecha.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "default": 0.0},
                            "y": {"type": "number", "default": -5.0},
                            "titulo": {"type": "string", "description": "Título del plano"},
                            "escala": {"type": "string", "description": "Escala del dibujo (ej: '1:100')", "default": "1:100"},
                            "hoja": {"type": "string", "description": "Número de hoja (ej: '01')", "default": "01"},
                            "autor": {"type": "string", "default": ""},
                            "fecha": {"type": "string", "default": ""}
                        },
                        "required": []
                    }
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict) -> List[types.TextContent]:
            """Dispatcher de herramientas."""
            args = arguments or {}
            result = None

            # Utilidades
            if name == "info_dibujo":
                result = self.info_dibujo()
            elif name == "configurar_capas":
                result = self.configurar_capas()
            elif name == "zoom_total":
                result = self.zoom_total()
            elif name == "deshacer":
                result = self.deshacer()

            # Planta
            elif name == "dibujar_muro":
                result = self.dibujar_muro(
                    args["x1"], args["y1"], args["x2"], args["y2"],
                    args.get("espesor", 0.15), args.get("layer", "A-MUROS")
                )
            elif name == "dibujar_puerta":
                result = self.dibujar_puerta(
                    args["x"], args["y"],
                    args.get("ancho", 0.90),
                    args.get("angulo_deg", 0.0),
                    args.get("apertura_deg", 90.0)
                )
            elif name == "dibujar_ventana":
                result = self.dibujar_ventana(
                    args["x1"], args["y1"], args["x2"], args["y2"],
                    args.get("espesor_muro", 0.15)
                )
            elif name == "dibujar_habitacion":
                result = self.dibujar_habitacion(
                    args["x1"], args["y1"], args["x2"], args["y2"],
                    args.get("nombre", ""), args.get("espesor", 0.15)
                )
            elif name == "dibujar_columna":
                result = self.dibujar_columna(
                    args["cx"], args["cy"],
                    args.get("tamano", 0.30),
                    args.get("forma", "cuadrada")
                )
            elif name == "dibujar_escalera":
                result = self.dibujar_escalera(
                    args["x"], args["y"],
                    args.get("ancho", 1.20),
                    args.get("profundidad_huella", 0.28),
                    args.get("num_escalones", 12),
                    args.get("direccion", "vertical")
                )
            elif name == "dibujar_mobiliario_bano":
                result = self.dibujar_mobiliario_bano(
                    args["x"], args["y"], args.get("tipo", "inodoro")
                )
            elif name == "dibujar_eje":
                result = self.dibujar_eje(
                    args["x1"], args["y1"], args["x2"], args["y2"],
                    args.get("etiqueta", "1")
                )
            elif name == "dibujar_linea_corte":
                result = self.dibujar_linea_corte(
                    args["x1"], args["y1"], args["x2"], args["y2"],
                    args.get("etiqueta", "A-A'")
                )

            # Cortes
            elif name == "dibujar_losa":
                result = self.dibujar_losa(
                    args["x"], args["y"], args["ancho"],
                    args.get("espesor", 0.20), args.get("layer", "A-LOSAS")
                )
            elif name == "dibujar_muro_corte":
                result = self.dibujar_muro_corte(
                    args["x"], args["y"], args["alto"],
                    args.get("espesor", 0.15)
                )
            elif name == "dibujar_ventana_corte":
                result = self.dibujar_ventana_corte(
                    args["x"], args["y"],
                    args.get("ancho", 1.20),
                    args.get("alto_antepecho", 0.90),
                    args.get("alto_ventana", 1.20),
                    args.get("espesor_muro", 0.15)
                )
            elif name == "dibujar_puerta_corte":
                result = self.dibujar_puerta_corte(
                    args["x"], args["y"],
                    args.get("ancho", 0.90),
                    args.get("alto", 2.10),
                    args.get("espesor_muro", 0.15)
                )
            elif name == "dibujar_terreno_corte":
                result = self.dibujar_terreno_corte(
                    args["x"], args["y"], args["ancho"],
                    args.get("nivel_piso", 0.0)
                )

            # Fachada
            elif name == "dibujar_ventana_fachada":
                result = self.dibujar_ventana_fachada(
                    args["x"], args["y"],
                    args.get("ancho", 1.20), args.get("alto", 1.10)
                )
            elif name == "dibujar_puerta_fachada":
                result = self.dibujar_puerta_fachada(
                    args["x"], args["y"],
                    args.get("ancho", 1.00), args.get("alto", 2.10),
                    args.get("tipo", "simple")
                )
            elif name == "dibujar_muro_fachada":
                result = self.dibujar_muro_fachada(
                    args["x"], args["y"], args["ancho"], args["alto"]
                )
            elif name == "dibujar_cubierta_fachada":
                result = self.dibujar_cubierta_fachada(
                    args["x"], args["y"], args["ancho"],
                    args.get("pendiente", 0.30), args.get("tipo", "dos_aguas")
                )

            # Anotaciones
            elif name == "agregar_cota":
                result = self.agregar_cota(
                    args["x1"], args["y1"], args["x2"], args["y2"],
                    args.get("offset", 0.80)
                )
            elif name == "agregar_texto":
                result = self.agregar_texto(
                    args["x"], args["y"], args["texto"],
                    args.get("altura", 0.25), args.get("layer", "A-TEXTO")
                )
            elif name == "dibujar_caratula":
                result = self.dibujar_caratula(
                    args.get("x", 0.0), args.get("y", -5.0),
                    args.get("titulo", "PROYECTO ARQUITECTÔ�ICO"),
                    args.get("escala", "1:100"),
                    args.get("hoja", "01"),
                    args.get("autor", ""),
                    args.get("fecha", "")
                )
            else:
                result = {"error": f"Herramienta desconocida: {name}"}

            return [types.TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2)
            )]

    # ═══════════════════════════════════════════════════════
    #  PUNTO DE ENTRADA
    # ═══════════════════════════════════════════════════════

    async def main(self):
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="autocad-arch-mcp",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={}
                    )
                )
            )


def main():
    server = AutoCADArchServer()
    asyncio.run(server.main())


if __name__ == "__main__":
    main()
