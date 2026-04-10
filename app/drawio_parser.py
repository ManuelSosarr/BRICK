"""
drawio_parser.py
════════════════
Convierte un archivo .drawio (XML) al formato JSON que Agent.tsx entiende.

Formato de salida (ScriptNode):
{
  "INTRO": {
    "id": "INTRO",
    "section": "Introducción",
    "text": "Hola {name}, soy {agent}...",
    "hint": "",
    "terminal": false,
    "terminalType": null,
    "options": [
      {"label": "Sí es dueño", "next": "CALIFICAR", "style": "yes"},
      {"label": "No es dueño", "next": "END_NI",    "style": "no"}
    ]
  },
  ...
}

Reglas de conversión draw.io → BRICK:
- ellipse con texto "inicio" / "start"          → nodeType=start,   id=INTRO (primer nodo)
- ellipse con texto "SET" / "NI" / "CB" / etc.  → nodeType=end_*
- rhombus                                        → nodeType=decision
- rectangle / rounded                            → nodeType=message
- Edge con value "sí"/"yes"/"s"                 → style=yes
- Edge con value "no"/"n"                       → style=no
- Edge sin value                                → style=neutral
"""

import xml.etree.ElementTree as ET
import re
import json
from html import unescape


# ─── Helpers ─────────────────────────────────────────────────────────────────

_END_KEYWORDS = {"set", "ni", "cb", "callback", "wn", "wrong", "amd",
                 "máquina", "maquina", "end", "fin", "final"}

_YES_KEYWORDS  = {"si", "sí", "yes", "y", "s", "✓", "verdadero", "correcto"}
_NO_KEYWORDS   = {"no", "n", "x", "✗", "falso", "incorrecto"}


def _clean(text: str) -> str:
    """Elimina HTML básico y normaliza espacios."""
    text = unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _split_hint(text: str) -> tuple[str, str]:
    """
    Separa el hint del texto principal.
    Formato soportado: [HINT: texto del hint]
    Retorna (texto_limpio, hint)
    """
    match = re.search(r'\[HINT:\s*(.*?)\]', text, re.IGNORECASE | re.DOTALL)
    if match:
        hint = match.group(1).strip()
        clean = re.sub(r'\[HINT:.*?\]', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
        return clean, hint
    return text, ""


def _slug(text: str) -> str:
    """Genera un ID limpio en mayúsculas desde el texto del nodo."""
    s = re.sub(r"[^a-zA-Z0-9 ]", "", text).strip().upper()
    s = re.sub(r"\s+", "_", s)
    return s[:30] or "NODE"


def _node_type(style: str, label: str) -> str:
    """Detecta el tipo de nodo por estilo y texto."""
    style_l = style.lower()
    label_l = label.lower().strip()

    if "ellipse" in style_l or "shape=ellipse" in style_l:
        if label_l in ("inicio", "start", "begin", "▶"):
            return "start"
        # Detectar end por texto
        for kw in _END_KEYWORDS:
            if kw == label_l or label_l.startswith(kw):
                end_map = {
                    "set": "end_set", "ni": "end_ni",
                    "cb": "end_cb", "callback": "end_cb",
                    "wn": "end_wn", "wrong": "end_wn",
                    "amd": "end_amd", "máquina": "end_amd", "maquina": "end_amd",
                }
                return end_map.get(kw, "end_ni")
        return "end_ni"  # ellipse sin match → end genérico

    if "rhombus" in style_l or "shape=rhombus" in style_l:
        return "decision"

    return "message"


def _edge_style(label: str) -> str:
    l = label.lower().strip()
    if l in _YES_KEYWORDS:
        return "yes"
    if l in _NO_KEYWORDS:
        return "no"
    return "neutral"


# ─── Parser principal ─────────────────────────────────────────────────────────

def parse_drawio(xml_content: str) -> dict:
    """
    Parsea XML de draw.io y retorna el dict de ScriptNodes.
    Lanza ValueError si el XML es inválido o no tiene nodos.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f"XML inválido: {e}")

    # Soporta tanto <mxfile><diagram><mxGraphModel> como <mxGraphModel> directo
    graph_model = root.find(".//mxGraphModel")
    if graph_model is None:
        raise ValueError("No se encontró mxGraphModel en el XML")

    cells = graph_model.findall(".//mxCell")

    # ── Separar vértices y aristas ────────────────────────────────────────────
    vertices: dict[str, dict] = {}  # id → {label, style, node_type}
    edges:    list[dict]      = []  # {id, source, target, label}

    for cell in cells:
        cid    = cell.get("id", "")
        value  = _clean(cell.get("value", ""))
        style  = cell.get("style", "")

        if cell.get("vertex") == "1" and cid not in ("0", "1"):
            nt = _node_type(style, value)
            vertices[cid] = {
                "raw_id":    cid,
                "label":     value,
                "style":     style,
                "node_type": nt,
            }

        elif cell.get("edge") == "1":
            src = cell.get("source", "")
            tgt = cell.get("target", "")
            if src and tgt:
                edges.append({
                    "source": src,
                    "target": tgt,
                    "label":  value,
                })

    if not vertices:
        raise ValueError("El diagrama no tiene nodos (vértices)")

    # ── Asignar IDs legibles ──────────────────────────────────────────────────
    # Encontrar nodo start — si no hay ellipse de inicio, usar el que no tiene
    # incoming edges como punto de entrada
    start_raw_id = None
    for v in vertices.values():
        if v["node_type"] == "start":
            start_raw_id = v["raw_id"]
            break

    if start_raw_id is None:
        # Sin nodo start explícito → el nodo sin aristas entrantes es el inicio
        targets = {e["target"] for e in edges}
        for v in vertices.values():
            if v["raw_id"] not in targets:
                start_raw_id = v["raw_id"]
                v["node_type"] = "start"
                break

    # Mapeo raw_id → slug ID único
    used_ids: set[str] = set()
    id_map: dict[str, str] = {}

    def make_id(raw_id: str, label: str, node_type: str) -> str:
        if node_type == "start":
            return "INTRO"
        base = _slug(label) if label else f"NODE_{raw_id}"
        if not base:
            base = f"NODE_{raw_id}"
        candidate = base
        counter = 2
        while candidate in used_ids:
            candidate = f"{base}_{counter}"
            counter += 1
        used_ids.add(candidate)
        return candidate

    # Primero asignar INTRO al start
    if start_raw_id:
        id_map[start_raw_id] = "INTRO"
        used_ids.add("INTRO")

    for v in vertices.values():
        if v["raw_id"] not in id_map:
            bid = make_id(v["raw_id"], v["label"], v["node_type"])
            id_map[v["raw_id"]] = bid

    # ── Construir options por nodo ────────────────────────────────────────────
    options_map: dict[str, list] = {v["raw_id"]: [] for v in vertices.values()}

    for e in edges:
        src_id = id_map.get(e["source"])
        tgt_id = id_map.get(e["target"])
        if not src_id or not tgt_id:
            continue
        options_map[e["source"]].append({
            "label": e["label"] or "→",
            "next":  tgt_id,
            "style": _edge_style(e["label"]),
        })

    # ── Construir ScriptNode dict ─────────────────────────────────────────────
    script: dict = {}

    for raw_id, v in vertices.items():
        brick_id  = id_map[raw_id]
        nt        = v["node_type"]
        is_end    = nt.startswith("end_") or nt == "start" and brick_id != "INTRO"
        terminal  = nt.startswith("end_")
        term_type = nt.replace("end_", "") if terminal else None

        # Para nodos start/end el label ya es el nombre de sección
        section = v["label"] if nt in ("start",) else v["label"]

        # Para message/decision el texto va en "text", para end/start va vacío
        raw_text = v["label"] if nt in ("message", "decision") else ""
        text, hint = _split_hint(raw_text) if raw_text else ("", "")

        script[brick_id] = {
            "id":           brick_id,
            "section":      section,
            "text":         text,
            "hint":         hint,
            "terminal":     terminal,
            "terminalType": term_type,
            "options":      options_map[raw_id] if not terminal else [],
        }

    if not script:
        raise ValueError("No se pudo construir ningún nodo del diagrama")

    return script
