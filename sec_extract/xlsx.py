"""최소 XLSX 작성기 (표준 라이브러리만 사용).

openpyxl 없이 .xlsx 파일을 생성한다. 여러 시트, 문자열/숫자 셀, 숫자 서식,
굵은 글꼴, 셀 배경색(검토 플래그 하이라이트), 셀 병합, 열 너비, 틀 고정을
지원한다. 문자열은 inlineStr 로 기록해 sharedStrings 파트를 생략한다.

이 모듈은 의존성이 없으므로 어떤 환경에서도 바로 동작한다.
"""

from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape


def _col_letter(col: int) -> str:
    """1-based 열 번호를 엑셀 열 문자로 변환한다 (1->A, 27->AA)."""
    s = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        s = chr(65 + rem) + s
    return s


def cell_ref(row: int, col: int) -> str:
    """1-based (row, col) -> 'A1' 형태의 셀 참조."""
    return f"{_col_letter(col)}{row}"


class _Style:
    """폰트/채움/숫자서식/정렬 조합을 xf 인덱스로 dedup 하는 레지스트리."""

    def __init__(self) -> None:
        # 키: (bold, fill_rgb, num_fmt, align) -> xf index
        self._xf: dict[tuple, int] = {}
        self._xf_order: list[tuple] = []
        self._fills: dict[str, int] = {}   # rgb -> fill index
        self._fill_order: list[str] = []
        self._numfmts: dict[str, int] = {}  # format code -> numFmtId
        self._numfmt_order: list[str] = []

    def xf(self, *, bold=False, fill=None, num_format=None, align=None) -> int:
        key = (bool(bold), fill, num_format, align)
        if key in self._xf:
            return self._xf[key]
        if fill is not None and fill not in self._fills:
            # fill 0/1 은 Excel 예약(none, gray125) -> 사용자 fill 은 2부터
            self._fills[fill] = len(self._fill_order) + 2
            self._fill_order.append(fill)
        if num_format is not None and num_format not in self._numfmts:
            self._numfmts[num_format] = 164 + len(self._numfmt_order)
            self._numfmt_order.append(num_format)
        idx = len(self._xf_order)
        self._xf[key] = idx
        self._xf_order.append(key)
        return idx

    def styles_xml(self) -> str:
        # numFmts
        numfmts = "".join(
            f'<numFmt numFmtId="{self._numfmts[code]}" formatCode="{escape(code)}"/>'
            for code in self._numfmt_order
        )
        numfmts_block = (
            f'<numFmts count="{len(self._numfmt_order)}">{numfmts}</numFmts>'
            if self._numfmt_order
            else ""
        )
        # fonts: 0=default, 1=bold
        fonts = (
            '<fonts count="2">'
            '<font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font>'
            "</fonts>"
        )
        # fills: 0=none, 1=gray125, 그 다음 사용자 solid fill
        fill_items = [
            '<fill><patternFill patternType="none"/></fill>',
            '<fill><patternFill patternType="gray125"/></fill>',
        ]
        for rgb in self._fill_order:
            fill_items.append(
                '<fill><patternFill patternType="solid">'
                f'<fgColor rgb="FF{rgb}"/></patternFill></fill>'
            )
        fills = f'<fills count="{len(fill_items)}">' + "".join(fill_items) + "</fills>"
        borders = '<borders count="1"><border/></borders>'
        cellstylexfs = (
            '<cellStyleXfs count="1">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            "</cellStyleXfs>"
        )
        # cellXfs
        xfs = []
        for (bold, fill, num_format, align) in self._xf_order:
            font_id = 1 if bold else 0
            fill_id = self._fills[fill] if fill is not None else 0
            num_id = self._numfmts[num_format] if num_format is not None else 0
            attrs = [
                f'numFmtId="{num_id}"',
                f'fontId="{font_id}"',
                f'fillId="{fill_id}"',
                'borderId="0"',
                'xfId="0"',
            ]
            if num_id:
                attrs.append('applyNumberFormat="1"')
            if font_id:
                attrs.append('applyFont="1"')
            if fill_id:
                attrs.append('applyFill="1"')
            if align:
                attrs.append('applyAlignment="1"')
                xfs.append(
                    f'<xf {" ".join(attrs)}>'
                    f'<alignment horizontal="{align}"/></xf>'
                )
            else:
                xfs.append(f'<xf {" ".join(attrs)}/>')
        cellxfs = f'<cellXfs count="{len(xfs)}">' + "".join(xfs) + "</cellXfs>"
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{numfmts_block}{fonts}{fills}{borders}{cellstylexfs}{cellxfs}"
            "</styleSheet>"
        )


class Sheet:
    def __init__(self, workbook: "Workbook", title: str) -> None:
        self.wb = workbook
        self.title = title
        self._cells: dict[tuple, tuple] = {}   # (row, col) -> (value, xf)
        self._merges: list[str] = []
        self._col_width: dict[int, float] = {}
        self._freeze: tuple | None = None
        self._max_row = 0
        self._max_col = 0

    def write(self, row, col, value, *, bold=False, fill=None,
              num_format=None, align=None):
        xf = self.wb.style.xf(bold=bold, fill=fill, num_format=num_format,
                              align=align)
        self._cells[(row, col)] = (value, xf)
        self._max_row = max(self._max_row, row)
        self._max_col = max(self._max_col, col)

    def merge(self, r1, c1, r2, c2):
        self._merges.append(f"{cell_ref(r1, c1)}:{cell_ref(r2, c2)}")

    def set_col_width(self, col, width):
        self._col_width[col] = width

    def freeze(self, row, col):
        """(row, col) 부터 스크롤 영역. 그 위/왼쪽이 고정된다."""
        self._freeze = (row, col)

    def _xml(self) -> str:
        out = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        ]
        # sheetViews (freeze panes)
        if self._freeze:
            r, c = self._freeze
            top_left = cell_ref(r, c)
            out.append(
                '<sheetViews><sheetView workbookViewId="0">'
                f'<pane xSplit="{c - 1}" ySplit="{r - 1}" topLeftCell="{top_left}" '
                'activePane="bottomRight" state="frozen"/>'
                f'<selection pane="bottomRight" activeCell="{top_left}" '
                f'sqref="{top_left}"/>'
                "</sheetView></sheetViews>"
            )
        # cols
        if self._col_width:
            cols = "".join(
                f'<col min="{c}" max="{c}" width="{w:.1f}" customWidth="1"/>'
                for c, w in sorted(self._col_width.items())
            )
            out.append(f"<cols>{cols}</cols>")
        # sheetData
        out.append("<sheetData>")
        rows: dict[int, list] = {}
        for (r, c), payload in self._cells.items():
            rows.setdefault(r, []).append((c, payload))
        for r in sorted(rows):
            out.append(f'<row r="{r}">')
            for c, (value, xf) in sorted(rows[r], key=lambda x: x[0]):
                ref = cell_ref(r, c)
                out.append(self._cell_xml(ref, value, xf))
            out.append("</row>")
        out.append("</sheetData>")
        # mergeCells (sheetData 뒤)
        if self._merges:
            merges = "".join(f'<mergeCell ref="{m}"/>' for m in self._merges)
            out.append(f'<mergeCells count="{len(self._merges)}">{merges}</mergeCells>')
        out.append("</worksheet>")
        return "".join(out)

    @staticmethod
    def _cell_xml(ref, value, xf) -> str:
        s = f' s="{xf}"' if xf else ""
        if value is None or value == "":
            return f'<c r="{ref}"{s}/>'
        if isinstance(value, bool):
            value = str(value)  # bool 은 문자열로
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"{s}><v>{value}</v></c>'
        text = escape(str(value))
        # 앞뒤 공백 보존
        return (
            f'<c r="{ref}"{s} t="inlineStr"><is>'
            f'<t xml:space="preserve">{text}</t></is></c>'
        )


def _safe_sheet_name(name: str, used: set) -> str:
    """엑셀 시트명 규칙: 31자 이하, : \\ / ? * [ ] 금지, 중복 불가."""
    for ch in r':\/?*[]':
        name = name.replace(ch, " ")
    name = name.strip()[:31] or "Sheet"
    base = name
    i = 2
    while name.lower() in used:
        suffix = f" ({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name


class Workbook:
    def __init__(self) -> None:
        self.style = _Style()
        self._sheets: list[Sheet] = []
        self._used_names: set = set()

    def add_sheet(self, title: str) -> Sheet:
        title = _safe_sheet_name(title, self._used_names)
        sh = Sheet(self, title)
        self._sheets.append(sh)
        return sh

    def save(self, path: str) -> None:
        if not self._sheets:
            self.add_sheet("Sheet1")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", self._content_types())
            z.writestr("_rels/.rels", self._root_rels())
            z.writestr("xl/workbook.xml", self._workbook_xml())
            z.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels())
            z.writestr("xl/styles.xml", self.style.styles_xml())
            for i, sh in enumerate(self._sheets, start=1):
                z.writestr(f"xl/worksheets/sheet{i}.xml", sh._xml())

    def _content_types(self) -> str:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(self._sheets) + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}"
            "</Types>"
        )

    @staticmethod
    def _root_rels() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    def _workbook_xml(self) -> str:
        sheets = "".join(
            f'<sheet name="{escape(sh.title)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, sh in enumerate(self._sheets, start=1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheets}</sheets></workbook>"
        )

    def _workbook_rels(self) -> str:
        rels = "".join(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(self._sheets) + 1)
        )
        style_rel_id = len(self._sheets) + 1
        rels += (
            f'<Relationship Id="rId{style_rel_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}</Relationships>"
        )
