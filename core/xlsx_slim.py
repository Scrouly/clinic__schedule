"""Чтение ОДНОГО листа из книги с многими листами без разбора остальных.

Сводный график — книга из ~14 листов по 5–9 МБ XML каждый (почти всё — пустые ячейки с оформлением).
openpyxl разбирает все листы, даже когда нужен один (около 20 с), хотя на один лист уходит ~1,5 с.
Выбрать листы при открытии openpyxl не умеет, поэтому здесь из архива .xlsx в памяти собирается
копия книги, где остался только нужный лист (остальные части файла не трогаются), и открывается
обычным load_workbook. Значения и объединённые ячейки получаются те же, что при полной загрузке.

Любая неожиданность в устройстве файла (нестандартные префиксы XML, не .xlsx и т. п.) не ошибка:
откат на обычное полное открытие, просто медленнее."""
from __future__ import annotations

import io
import logging
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Optional

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _sheets(z: zipfile.ZipFile) -> List[tuple]:
    """[(имя листа, r:id)] в порядке книги."""
    root = ET.fromstring(z.read("xl/workbook.xml"))
    return [(s.get("name"), s.get(_NS_REL + "id")) for s in root.iter(_NS_MAIN + "sheet")]


def _targets(z: zipfile.ZipFile) -> dict:
    """r:id → путь части внутри архива."""
    root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    out = {}
    for rel in root.iter(_NS_PKG + "Relationship"):
        target = rel.get("Target")
        out[rel.get("Id")] = target.lstrip("/") if target.startswith("/") else \
            posixpath.normpath(posixpath.join("xl", target))
    return out


def sheet_names(path: str) -> Optional[List[str]]:
    """Имена листов, не разбирая сами листы. None — не удалось (не .xlsx и т. п.)."""
    try:
        with zipfile.ZipFile(path) as z:
            return [name for name, _ in _sheets(z)]
    except Exception:
        return None


def _slim_bytes(path: str, sheet_name: str) -> io.BytesIO:
    """Копия книги в памяти, в которой остался только лист sheet_name."""
    with zipfile.ZipFile(path) as z:
        sheets, targets = _sheets(z), _targets(z)
        keep = [rid for name, rid in sheets if name == sheet_name]
        if len(keep) != 1:
            raise KeyError(sheet_name)
        keep_rid = keep[0]

        drop = set()
        for _, rid in sheets:
            if rid != keep_rid:
                part = targets[rid]
                drop.add(part)
                drop.add(posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"))

        workbook_xml = z.read("xl/workbook.xml").decode("utf-8")
        workbook_xml = re.sub(
            r"<sheet\b[^>]*?/>",
            lambda m: m.group(0) if re.search(r'[:\s]id="%s"' % re.escape(keep_rid), m.group(0)) else "",
            workbook_xml)
        # Имена с привязкой к листам (область печати и т. п.) ссылаются на удалённые листы
        workbook_xml = re.sub(r"<definedNames>.*?</definedNames>", "", workbook_xml, flags=re.S)
        workbook_xml = re.sub(r'\s(?:activeTab|firstSheet)="\d+"', "", workbook_xml)
        if len(_sheets_of(workbook_xml)) != 1:       # не тот вид XML, на который рассчитан разбор
            raise ValueError("workbook.xml в неожиданном виде")

        content_types = z.read("[Content_Types].xml").decode("utf-8")
        for part in drop:
            content_types = re.sub(r'<Override\b[^>]*PartName="/%s"[^>]*/>' % re.escape(part), "", content_types)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as out:
            for info in z.infolist():
                if info.filename in drop:
                    continue
                if info.filename == "xl/workbook.xml":
                    data = workbook_xml.encode("utf-8")
                elif info.filename == "[Content_Types].xml":
                    data = content_types.encode("utf-8")
                else:
                    data = z.read(info.filename)
                out.writestr(info.filename, data)
    buf.seek(0)
    return buf


def _sheets_of(workbook_xml: str) -> list:
    return list(ET.fromstring(workbook_xml).iter(_NS_MAIN + "sheet"))


def load_sheet_workbook(path: str, sheet_name: str, data_only: bool = True):
    """Книга, в которой гарантированно есть лист sheet_name (в ускоренном случае — только он).

    Нет такого листа — ValueError с понятным текстом (до всякого разбора файла)."""
    names = sheet_names(path)
    if names is not None and sheet_name not in names:
        shown = ", ".join(f"«{n.strip()}»" for n in names)
        raise ValueError(f"В файле нет листа «{sheet_name}». Листы в файле: {shown}.")
    if names is not None and len(names) > 1:
        try:
            return load_workbook(_slim_bytes(path, sheet_name), data_only=data_only)
        except Exception as e:
            logger.debug(f"Ускоренное чтение листа не удалось ({e!r}), открываю книгу целиком.")
    return load_workbook(path, data_only=data_only)
