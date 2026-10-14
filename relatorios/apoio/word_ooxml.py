"""Write a formatted Word document without python-docx or Word automation.

Public API::

    build_docx([
        {"type": "title", "text": "Título"},
        {"type": "heading1", "text": "1. Introdução"},
        {"type": "paragraph", "text": "Texto do documento."},
        {"type": "table", "headers": ["Item", "Valor"],
         "rows": [["Exemplo", "1"]], "widths": [2, 1]},
        {"type": "image", "path": "figura.png", "width_cm": 16},
        {"type": "caption", "text": "Figura 1. Legenda."},
    ], "documento.docx", title="Título")

Supported blocks: title, subtitle, paragraph, heading1, heading2, caption,
note, pagebreak, table and image. A plain string is a paragraph. Table
widths are relative column weights; widths_cm specifies physical widths.
Paragraph blocks accept optional
align (left/center/right/justify), bold, italic, keep_next and font_size.
Image paths are resolved from the working directory, or from the JSON
file directory when using the CLI. Pillow is used only to read image sizes.

Visible text containing U+2013 or U+2014 is rejected. Existing output files
are never overwritten. No macros, external links or Word COM are used.

CLI: python word_ooxml.py blocks.json documento.docx --title "Título"
JSON may be a list of blocks or an object with blocks/title/author fields.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterable, Mapping
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}
for _prefix, _uri in NS.items():
    ET.register_namespace(_prefix, _uri)

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
OFFICE_REL = NS["r"] + "/"
PAGE_WIDTH = 11906
PAGE_HEIGHT = 16838
MARGIN = round(2.3 * 1440 / 2.54)
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
GREEN = "176B56"
DARK_GREEN = "164A3E"
MUTED = "5C6C65"


def _q(name: str) -> str:
    prefix, local = name.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


def _el(parent: ET.Element, name: str, attributes=None, text=None):
    attrs = {_q(k) if ":" in k else k: str(v) for k, v in (attributes or {}).items()}
    child = ET.SubElement(parent, _q(name), attrs)
    if text is not None:
        child.text = str(text)
    return child


def _xml(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _text(value, context="texto") -> str:
    result = "" if value is None else str(value)
    if "\u2013" in result or "\u2014" in result:
        raise ValueError(f"{context}: substitua os caracteres U+2013/U+2014 por pontuação portuguesa.")
    # XML 1.0 rejects these controls even when the ZIP itself is valid.
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", result):
        raise ValueError(f"{context}: o texto contém um caractere de controle inválido para XML.")
    return result


def _rpr(parent, *, bold=False, italic=False, color=None, size=None):
    if not (bold or italic or color or size):
        return
    pr = _el(parent, "w:rPr")
    if bold:
        _el(pr, "w:b")
    if italic:
        _el(pr, "w:i")
    if color:
        _el(pr, "w:color", {"w:val": color})
    if size is not None:
        _el(pr, "w:sz", {"w:val": round(float(size) * 2)})
        _el(pr, "w:szCs", {"w:val": round(float(size) * 2)})


def _run(parent, value, **formatting):
    run = _el(parent, "w:r")
    _rpr(run, **formatting)
    for index, line in enumerate(_text(value).split("\n")):
        if index:
            _el(run, "w:br")
        parts = line.split("\t")
        for tab_index, part in enumerate(parts):
            if tab_index:
                _el(run, "w:tab")
            node = _el(run, "w:t", text=part)
            node.set(XML_SPACE, "preserve")
    return run


def _paragraph(parent, value="", *, style="Normal", align=None,
               keep_next=None, bold=False, italic=False, font_size=None):
    paragraph = _el(parent, "w:p")
    pr = _el(paragraph, "w:pPr")
    _el(pr, "w:pStyle", {"w:val": style})
    if keep_next is not None:
        _el(pr, "w:keepNext", {"w:val": "1" if keep_next else "0"})
    if align:
        if align not in {"left", "right", "center", "justify"}:
            raise ValueError(f"Alinhamento desconhecido: {align}")
        _el(pr, "w:jc", {"w:val": "both" if align == "justify" else align})
    _run(paragraph, value, bold=bold, italic=italic, size=font_size)
    return paragraph


def _styles():
    root = ET.Element(_q("w:styles"))
    defaults = _el(root, "w:docDefaults")
    rdef = _el(_el(defaults, "w:rPrDefault"), "w:rPr")
    _el(rdef, "w:rFonts", {"w:ascii": "Times New Roman", "w:hAnsi": "Times New Roman",
                           "w:eastAsia": "Times New Roman", "w:cs": "Times New Roman"})
    _el(rdef, "w:color", {"w:val": "24332C"})
    _el(rdef, "w:sz", {"w:val": "24"})
    _el(rdef, "w:szCs", {"w:val": "24"})
    _el(rdef, "w:lang", {"w:val": "pt-BR", "w:eastAsia": "pt-BR", "w:bidi": "pt-BR"})
    pdef = _el(_el(defaults, "w:pPrDefault"), "w:pPr")
    _el(pdef, "w:widowControl")
    _el(pdef, "w:spacing", {"w:after": "140", "w:line": "276", "w:lineRule": "auto"})
    _el(pdef, "w:jc", {"w:val": "both"})

    specs = [
        ("Normal", "Normal", 24, None, False, False, "both", 0, 140, None),
        ("Title", "Título", 52, DARK_GREEN, True, False, "center", 200, 260, None),
        ("Subtitle", "Subtítulo", 28, MUTED, False, False, "center", 0, 220, None),
        ("Heading1", "Título 1", 32, GREEN, True, False, "left", 320, 140, 0),
        ("Heading2", "Título 2", 27, GREEN, True, False, "left", 240, 100, 1),
        ("Caption", "Legenda", 20, MUTED, False, True, "center", 60, 180, None),
        ("Note", "Nota técnica", 21, MUTED, False, True, "both", 80, 160, None),
        ("Header", "Cabeçalho", 18, MUTED, False, False, "left", 0, 80, None),
        ("Footer", "Rodapé", 18, MUTED, False, False, "center", 60, 0, None),
        ("TableText", "Texto de tabela", 21, "24332C", False, False, "left", 0, 35, None),
        ("TableHeader", "Cabeçalho de tabela", 21, "FFFFFF", True, False, "left", 0, 35, None),
    ]
    for sid, name, size, color, bold, italic, align, before, after, outline in specs:
        attrs = {"w:type": "paragraph", "w:styleId": sid}
        if sid == "Normal":
            attrs["w:default"] = "1"
        style = _el(root, "w:style", attrs)
        _el(style, "w:name", {"w:val": name})
        if sid != "Normal":
            _el(style, "w:basedOn", {"w:val": "Normal"})
        _el(style, "w:next", {"w:val": "Normal"})
        _el(style, "w:qFormat")
        ppr = _el(style, "w:pPr")
        if sid in {"Title", "Subtitle", "Heading1", "Heading2"}:
            _el(ppr, "w:keepNext")
            _el(ppr, "w:keepLines")
        if sid == "Note":
            borders = _el(ppr, "w:pBdr")
            _el(borders, "w:left", {"w:val": "single", "w:sz": "12", "w:space": "8", "w:color": "A5C8B9"})
            _el(ppr, "w:shd", {"w:val": "clear", "w:fill": "F2F7F4"})
        _el(ppr, "w:spacing", {"w:before": before, "w:after": after,
                                "w:line": "276" if sid == "Normal" else "240", "w:lineRule": "auto"})
        if sid == "Note":
            _el(ppr, "w:ind", {"w:left": "140", "w:right": "100"})
        _el(ppr, "w:jc", {"w:val": align})
        if outline is not None:
            _el(ppr, "w:outlineLvl", {"w:val": outline})
        rpr = _el(style, "w:rPr")
        if bold:
            _el(rpr, "w:b")
        if italic:
            _el(rpr, "w:i")
        if color:
            _el(rpr, "w:color", {"w:val": color})
        _el(rpr, "w:sz", {"w:val": size})
        _el(rpr, "w:szCs", {"w:val": size})
        _el(rpr, "w:lang", {"w:val": "pt-BR"})
    return root


def _table(parent, block):
    headers = list(block.get("headers", []))
    rows = [list(row) for row in block.get("rows", [])]
    ncols = len(headers) if headers else (len(rows[0]) if rows else 0)
    if not ncols or any(len(row) != ncols for row in rows):
        raise ValueError("Tabela vazia ou com quantidade inconsistente de colunas.")
    explicit_cm = "widths_cm" in block
    weights = [float(x) for x in block.get("widths_cm", block.get("widths", [1] * ncols))]
    if len(weights) != ncols or any(x <= 0 or x == float("inf") or x != x for x in weights):
        raise ValueError("widths deve conter um peso positivo e finito por coluna.")
    total = sum(weights)
    table_width = min(CONTENT_WIDTH, round(total * 1440 / 2.54)) if explicit_cm else CONTENT_WIDTH
    widths = [round(table_width * weight / total) for weight in weights]
    widths[-1] += table_width - sum(widths)
    if min(widths) < 100:
        raise ValueError("A largura de uma coluna ficou pequena demais.")
    table = _el(parent, "w:tbl")
    props = _el(table, "w:tblPr")
    _el(props, "w:tblW", {"w:w": table_width, "w:type": "dxa"})
    _el(props, "w:jc", {"w:val": "center"})
    borders = _el(props, "w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _el(borders, "w:" + edge, {"w:val": "single", "w:sz": "4", "w:color": "DCE8E1"})
    _el(props, "w:tblLayout", {"w:type": "fixed"})
    margins = _el(props, "w:tblCellMar")
    for edge in ("top", "left", "bottom", "right"):
        _el(margins, "w:" + edge, {"w:w": "95", "w:type": "dxa"})
    grid = _el(table, "w:tblGrid")
    for width in widths:
        _el(grid, "w:gridCol", {"w:w": width})
    all_rows = ([headers] if headers else []) + rows
    for index, values in enumerate(all_rows):
        is_header = bool(headers) and index == 0
        row = _el(table, "w:tr")
        trpr = _el(row, "w:trPr")
        _el(trpr, "w:cantSplit")
        if is_header:
            _el(trpr, "w:tblHeader")
        body_index = index - int(bool(headers))
        fill = GREEN if is_header else ("F0F6F2" if body_index % 2 else "FFFFFF")
        for column, value in enumerate(values):
            cell = _el(row, "w:tc")
            tcpr = _el(cell, "w:tcPr")
            _el(tcpr, "w:tcW", {"w:w": widths[column], "w:type": "dxa"})
            _el(tcpr, "w:shd", {"w:val": "clear", "w:fill": fill})
            _el(tcpr, "w:vAlign", {"w:val": "center"})
            _paragraph(cell, _text(value, f"tabela, linha {index + 1}, coluna {column + 1}"),
                       style="TableHeader" if is_header else "TableText")
    # A small spacer also separates consecutive tables in Word.
    p = _paragraph(parent, "")
    _el(p.find(_q("w:pPr")), "w:spacing", {"w:before": "0", "w:after": "60", "w:line": "40", "w:lineRule": "exact"})


def _image(parent, block, rid, index):
    path = Path(block["path"])
    if not path.is_file():
        raise FileNotFoundError(f"Imagem ausente: {path}")
    with Image.open(path) as source:
        width_px, height_px = source.size
        fmt = source.format
    formats = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"),
               "GIF": ("gif", "image/gif"), "BMP": ("bmp", "image/bmp"),
               "TIFF": ("tif", "image/tiff")}
    if fmt not in formats:
        raise ValueError(f"Formato de imagem não suportado no Word: {fmt}. Use PNG ou JPEG.")
    requested = float(block.get("width_cm", CONTENT_WIDTH * 2.54 / 1440))
    if not requested > 0 or requested == float("inf"):
        raise ValueError("width_cm deve ser positivo e finito.")
    width_emu = min(round(requested * 360000), round(CONTENT_WIDTH * 635))
    height_emu = round(width_emu * height_px / width_px)
    maximum_height = round(23.5 * 360000)
    if height_emu > maximum_height:
        width_emu = round(width_emu * maximum_height / height_emu)
        height_emu = maximum_height
    alt = _text(block.get("alt", "Figura do relatório"), "texto alternativo da imagem")
    paragraph = _paragraph(parent, "", align="center", keep_next=True)
    drawing = _el(_el(paragraph, "w:r"), "w:drawing")
    inline = _el(drawing, "wp:inline", {"distT": "0", "distB": "0", "distL": "0", "distR": "0"})
    _el(inline, "wp:extent", {"cx": width_emu, "cy": height_emu})
    _el(inline, "wp:effectExtent", {"l": "0", "t": "0", "r": "0", "b": "0"})
    _el(inline, "wp:docPr", {"id": index, "name": f"Figura {index}", "descr": alt})
    locks = _el(inline, "wp:cNvGraphicFramePr")
    _el(locks, "a:graphicFrameLocks", {"noChangeAspect": "1"})
    graphic = _el(inline, "a:graphic")
    data = _el(graphic, "a:graphicData", {"uri": NS["pic"]})
    pic = _el(data, "pic:pic")
    nvpr = _el(pic, "pic:nvPicPr")
    _el(nvpr, "pic:cNvPr", {"id": "0", "name": f"imagem_{index}.{formats[fmt][0]}"})
    _el(nvpr, "pic:cNvPicPr")
    fill = _el(pic, "pic:blipFill")
    _el(fill, "a:blip", {"r:embed": rid})
    _el(_el(fill, "a:stretch"), "a:fillRect")
    sppr = _el(pic, "pic:spPr")
    xfrm = _el(sppr, "a:xfrm")
    _el(xfrm, "a:off", {"x": "0", "y": "0"})
    _el(xfrm, "a:ext", {"cx": width_emu, "cy": height_emu})
    _el(_el(sppr, "a:prstGeom", {"prst": "rect"}), "a:avLst")
    return path.read_bytes(), formats[fmt]


def _header():
    root = ET.Element(_q("w:hdr"))
    p = _paragraph(root, "EVAPO  |  Relatório técnico", style="Header")
    borders = _el(p.find(_q("w:pPr")), "w:pBdr")
    _el(borders, "w:bottom", {"w:val": "single", "w:sz": "4", "w:space": "5", "w:color": "C4D9CE"})
    return root


def _footer():
    root = ET.Element(_q("w:ftr"))
    p = _paragraph(root, "Página ", style="Footer")
    for kind, value in (("begin", None), (None, " PAGE "), ("separate", None)):
        run = _el(p, "w:r")
        if kind:
            _el(run, "w:fldChar", {"w:fldCharType": kind})
        else:
            node = _el(run, "w:instrText", text=value)
            node.set(XML_SPACE, "preserve")
    _run(p, "1")
    _el(_el(p, "w:r"), "w:fldChar", {"w:fldCharType": "end"})
    return root


def _relationships(entries):
    root = ET.Element(f"{{{REL_NS}}}Relationships")
    for rid, kind, target in entries:
        ET.SubElement(root, f"{{{REL_NS}}}Relationship", {"Id": rid, "Type": kind, "Target": target})
    return root


def build_docx(blocks: Iterable[Mapping | str], output_path, *,
               title="Relatório técnico Evapo", author="Projeto Evapo") -> Path:
    """Create a new DOCX and return its absolute path. Refuse to overwrite.

    Visible text is validated before the output ZIP is opened. ``title`` is
    metadata; add a title block when it should also appear on the page.
    """
    output = Path(output_path).resolve()
    if output.suffix.lower() != ".docx":
        raise ValueError("O arquivo de saída deve usar a extensão .docx.")
    if output.exists():
        raise FileExistsError(f"O arquivo já existe e foi preservado: {output}")
    title = _text(title, "título do documento")
    author = _text(author, "autor do documento")
    root = ET.Element(_q("w:document"))
    body = _el(root, "w:body")
    document_rels = [("rId1", OFFICE_REL + "styles", "styles.xml"),
                     ("rId2", OFFICE_REL + "settings", "settings.xml"),
                     ("rId3", OFFICE_REL + "header", "header1.xml"),
                     ("rId4", OFFICE_REL + "footer", "footer1.xml")]
    media = []
    paragraph_styles = {"title": "Title", "subtitle": "Subtitle", "paragraph": "Normal",
                        "heading1": "Heading1", "heading2": "Heading2", "caption": "Caption", "note": "Note"}
    for index, raw in enumerate(blocks, start=1):
        block = {"type": "paragraph", "text": raw} if isinstance(raw, str) else dict(raw)
        kind = block.get("type", "paragraph")
        if kind in paragraph_styles:
            _paragraph(body, _text(block.get("text", ""), f"bloco {index}"),
                       style=paragraph_styles[kind], align=block.get("align"),
                       keep_next=block.get("keep_next"), bold=block.get("bold", False),
                       italic=block.get("italic", False), font_size=block.get("font_size"))
        elif kind == "pagebreak":
            p = _el(body, "w:p")
            _el(_el(p, "w:r"), "w:br", {"w:type": "page"})
        elif kind == "table":
            _table(body, block)
        elif kind == "image":
            image_index = len(media) + 1
            rid = f"rId{len(document_rels) + 1}"
            payload, (extension, mime) = _image(body, block, rid, image_index)
            filename = f"imagem_{image_index}.{extension}"
            media.append((filename, mime, payload))
            document_rels.append((rid, OFFICE_REL + "image", "media/" + filename))
        else:
            raise ValueError(f"Tipo de bloco desconhecido no bloco {index}: {kind}")
    if not len(body):
        _paragraph(body, "")
    section = _el(body, "w:sectPr")
    _el(section, "w:headerReference", {"w:type": "default", "r:id": "rId3"})
    _el(section, "w:footerReference", {"w:type": "default", "r:id": "rId4"})
    _el(section, "w:pgSz", {"w:w": PAGE_WIDTH, "w:h": PAGE_HEIGHT})
    _el(section, "w:pgMar", {"w:top": MARGIN, "w:right": MARGIN, "w:bottom": MARGIN,
                             "w:left": MARGIN, "w:header": "600", "w:footer": "600", "w:gutter": "0"})
    _el(section, "w:cols", {"w:space": "708"})

    settings = ET.Element(_q("w:settings"))
    _el(settings, "w:zoom", {"w:percent": "100"})
    _el(settings, "w:defaultTabStop", {"w:val": "708"})
    _el(settings, "w:updateFields", {"w:val": "true"})
    compatibility = _el(settings, "w:compat")
    _el(compatibility, "w:compatSetting", {"w:name": "compatibilityMode",
                                         "w:uri": "http://schemas.microsoft.com/office/word", "w:val": "15"})

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    core = ET.Element(_q("cp:coreProperties"))
    _el(core, "dc:title", text=title)
    _el(core, "dc:subject", text="Projeto Evapo")
    _el(core, "dc:creator", text=author)
    _el(core, "cp:lastModifiedBy", text=author)
    _el(core, "dc:language", text="pt-BR")
    for field in ("created", "modified"):
        _el(core, "dcterms:" + field, {"xsi:type": "dcterms:W3CDTF"}, text=now)
    app = ET.Element(_q("ep:Properties"))
    _el(app, "ep:Application", text="Evapo OOXML")
    _el(app, "ep:AppVersion", text="1.0")

    content_types = ET.Element(f"{{{CT_NS}}}Types")
    defaults = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
    defaults.update({name.rsplit(".", 1)[1]: mime for name, mime, _ in media})
    for extension, mime in defaults.items():
        ET.SubElement(content_types, f"{{{CT_NS}}}Default", {"Extension": extension, "ContentType": mime})
    overrides = {
        "/word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "/word/styles.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
        "/word/settings.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
        "/word/header1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
        "/word/footer1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    }
    for name, mime in overrides.items():
        ET.SubElement(content_types, f"{{{CT_NS}}}Override", {"PartName": name, "ContentType": mime})
    package_rels = _relationships([
        ("rId1", OFFICE_REL + "officeDocument", "word/document.xml"),
        ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
        ("rId3", OFFICE_REL + "extended-properties", "docProps/app.xml"),
    ])
    parts = {"[Content_Types].xml": content_types, "_rels/.rels": package_rels,
             "word/document.xml": root, "word/styles.xml": _styles(), "word/settings.xml": settings,
             "word/_rels/document.xml.rels": _relationships(document_rels),
             "word/header1.xml": _header(), "word/footer1.xml": _footer(),
             "docProps/core.xml": core, "docProps/app.xml": app}
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, mode="x", compression=ZIP_DEFLATED) as archive:
        for name, tree in parts.items():
            archive.writestr(name, _xml(tree))
        for name, _, payload in media:
            archive.writestr("word/media/" + name, payload)
    return output


def main():
    parser = argparse.ArgumentParser(description="Gera documento Word com blocos JSON.")
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_docx", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--author")
    args = parser.parse_args()
    payload = json.loads(args.input_json.read_text(encoding="utf-8-sig"))
    options = payload if isinstance(payload, dict) else {}
    blocks = options.get("blocks", []) if options else payload
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "image":
            path = Path(block["path"])
            if not path.is_absolute():
                block["path"] = str(args.input_json.parent / path)
    output = build_docx(blocks, args.output_docx,
                        title=args.title or options.get("title", "Relatório técnico Evapo"),
                        author=args.author or options.get("author", "Projeto Evapo"))
    print(output)


if __name__ == "__main__":
    main()
