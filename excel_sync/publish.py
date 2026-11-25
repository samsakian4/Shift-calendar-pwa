#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
همگام‌ساز اکسل ← سایت (Supabase)

هر بار فایل اکسل را Save کنید، شیت‌های انتخاب‌شده خوانده می‌شوند (مقدارهای محاسبه‌شده‌ی خود Excel)
و در جدول‌های excel_sheets / excel_chunks در Supabase نوشته می‌شوند؛ صفحه‌ی «اکسل» سایت همان لحظه به‌روز می‌شود.

فقط کتابخانه‌ی استاندارد پایتون لازم است (Python 3.8 یا بالاتر).

  python publish.py --once                  یک بار منتشر کن و تمام
  python publish.py --watch                 فایل را زیر نظر بگیر و با هر Save منتشر کن (پیش‌فرض)
  python publish.py --dry-run خروجی        به‌جای ارسال، فایل‌های JSON را در پوشه‌ی داده‌شده بنویس
"""
import argparse, copy, datetime, hashlib, json, os, re, shutil, sys, tempfile, time, zipfile
import urllib.error, urllib.request
import xml.etree.ElementTree as ET

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PKG = '{http://schemas.openxmlformats.org/package/2006/relationships}'
SKIP_DEFAULT = ['data base', 'راهنما', 'تقویم']
TABLE_SHEETS = {  # شیت‌های ثبت (جدول داده). بقیه به‌صورت «گزارش» (عین خود شیت) منتشر می‌شوند.
    'رویدادهای سالن فویل': ['وزن'],
    'رویدادهای سالن برش': ['وزن'],
    'رویدادهای سالن آنیل': ['وزن'],
    'گزارش روزانه باسکول ضایعات': ['وزن'],
    'گام روغن': ['مقدار'],
    'علامت و پارگی کویل': ['شماره کویل', 'کد علامت'],
}
CHUNK_BYTES = 450_000

# ----------------------------------------------------------------- تاریخ شمسی
def g2j(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600: jy = 979; gy -= 1600
    else: jy = 0; gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053); days %= 12053
    jy += 4 * (days // 1461); days %= 1461
    if days > 365: jy += (days - 1) // 365; days = (days - 1) % 365
    if days < 186: jm = 1 + days // 31; jd = 1 + days % 31
    else: jm = 7 + (days - 186) // 30; jd = 1 + (days - 186) % 30
    return jy, jm, jd

def serial_to_jalali(v):
    d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))
    jy, jm, jd = g2j(d.year, d.month, d.day)
    return '%d/%02d/%02d' % (jy, jm, jd)

# ----------------------------------------------------------------- قالب‌بندی عدد
BUILTIN = {0: 'General', 1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00', 9: '0%', 10: '0.00%', 37: '#,##0;(#,##0)',
           38: '#,##0;(#,##0)', 39: '#,##0.00;(#,##0.00)', 40: '#,##0.00;(#,##0.00)', 49: '@'}
DATE_IDS = set(range(14, 23)) | {27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}

def _strip(code):
    code = re.sub(r'"[^"]*"', '', code)
    code = re.sub(r'\[[^\]]*\]', '', code)
    return code

def is_date_code(code):
    c = _strip(code).replace('\\', '')
    if re.search(r'[0#?]', c): return False
    return bool(re.search(r'[ymdhs]', c, re.I))

def fmt_number(v, code):
    """قالب‌بندی ساده‌ی عدد مثل Excel (کافی برای گزارش‌های این فایل)."""
    secs = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', code)
    sec = secs[0]
    neg = v < 0
    if len(secs) >= 2 and neg: sec = secs[1]
    if len(secs) >= 3 and v == 0:
        sec = secs[2]
        if sec.strip() == '': return ''
    body = sec
    pre = suf = ''
    m = re.search(r'[0#?][0#?,.]*', _strip_keep(body))
    pct = '%' in _strip(body)
    x = abs(v) * (100 if pct else 1)
    if not m:
        txt = fmt_general(x if not neg or len(secs) < 2 else x)
        return ('-' if neg and len(secs) < 2 else '') + txt
    core = m.group(0)
    dec = len(core.split('.')[1].replace(',', '')) if '.' in core else 0
    thou = ',' in core.split('.')[0]
    s = ('{:,.%df}' % dec).format(round(x + 1e-12, dec)) if thou else ('{:.%df}' % dec).format(round(x + 1e-12, dec))
    lits = re.findall(r'"([^"]*)"', body)
    before = body[:body.find(core)] if core in body else ''
    after = body[body.find(core) + len(core):] if core in body else ''
    pre = ''.join(re.findall(r'"([^"]*)"', before))
    suf = ''.join(re.findall(r'"([^"]*)"', after))
    if pct: suf = '%' + suf
    sign = '-' if neg and len(secs) < 2 else ''
    return sign + pre + s + suf

def _strip_keep(code):
    return re.sub(r'\[[^\]]*\]', '', re.sub(r'"[^"]*"', lambda m: ' ' * len(m.group(0)), code))

def fmt_general(v):
    if isinstance(v, int) or (isinstance(v, float) and v == int(v) and abs(v) < 1e15): return str(int(v))
    s = '%.10g' % v
    if 'e' in s or 'E' in s: s = ('%.10f' % v).rstrip('0').rstrip('.')
    return s

# ----------------------------------------------------------------- رنگ‌ها
INDEXED = ['000000', 'FFFFFF', 'FF0000', '00FF00', '0000FF', 'FFFF00', 'FF00FF', '00FFFF', '000000', 'FFFFFF', 'FF0000', '00FF00', '0000FF',
           'FFFF00', 'FF00FF', '00FFFF', '800000', '008000', '000080', '808000', '800080', '008080', 'C0C0C0', '808080', '9999FF', '993366',
           'FFFFCC', 'CCFFFF', '660066', 'FF8080', '0066CC', 'CCCCFF', '000080', 'FF00FF', 'FFFF00', '00FFFF', '800080', '800000', '008080',
           '0000FF', '00CCFF', 'CCFFFF', 'CCFFCC', 'FFFF99', '99CCFF', 'FF99CC', 'CC99FF', 'FFCC99', '3366FF', '33CCCC', '99CC00', 'FFCC00',
           'FF9900', 'FF6600', '666699', '969696', '003366', '339966', '003300', '333300', '993300', '993366', '333399', '333333']

def apply_tint(hexrgb, tint):
    r, g, b = int(hexrgb[0:2], 16), int(hexrgb[2:4], 16), int(hexrgb[4:6], 16)
    if tint > 0: r, g, b = [c + (255 - c) * tint for c in (r, g, b)]
    elif tint < 0: r, g, b = [c * (1 + tint) for c in (r, g, b)]
    return '#%02x%02x%02x' % (round(r), round(g), round(b))

def read_color(el, theme):
    if el is None: return None
    if el.get('rgb'): return '#' + el.get('rgb')[-6:].lower()
    tint = float(el.get('tint') or 0)
    if el.get('theme') is not None:
        i = int(el.get('theme'))
        if i < len(theme): return apply_tint(theme[i], tint)
    if el.get('indexed') is not None:
        i = int(el.get('indexed'))
        if i < len(INDEXED): return apply_tint(INDEXED[i], tint)
    return None

# ----------------------------------------------------------------- خواندن فایل اکسل
class Book:
    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        self.names = self.z.namelist()
        self._sheets()
        self._shared()
        self._styles()

    def _sheets(self):
        wb = ET.fromstring(self.z.read('xl/workbook.xml'))
        rels = ET.fromstring(self.z.read('xl/_rels/workbook.xml.rels'))
        tg = {r.get('Id'): r.get('Target') for r in rels.iter(PKG + 'Relationship')}
        self.sheets = []
        for s in wb.find(NS + 'sheets'):
            t = tg[s.get(RNS + 'id')]
            t = t.lstrip('/')
            path = t if t.startswith('xl/') else 'xl/' + t
            self.sheets.append(dict(name=s.get('name'), path=path, hidden=s.get('state') in ('hidden', 'veryHidden')))

    def _shared(self):
        self.ss = []
        if 'xl/sharedStrings.xml' not in self.names: return
        for _, el in ET.iterparse(self.z.open('xl/sharedStrings.xml'), events=('end',)):
            if el.tag == NS + 'si':
                parts = []
                for ch in el:
                    if ch.tag == NS + 't': parts.append(ch.text or '')
                    elif ch.tag == NS + 'r':
                        t = ch.find(NS + 't')
                        parts.append((t.text or '') if t is not None else '')
                self.ss.append(''.join(parts)); el.clear()

    def _styles(self):
        theme = ['FFFFFF', '000000', 'EEECE1', '1F497D', '4F81BD', 'C0504D', '9BBB59', '8064A2', '4BACC6', 'F79646']
        if 'xl/theme/theme1.xml' in self.names:
            try:
                th = ET.fromstring(self.z.read('xl/theme/theme1.xml'))
                A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
                cs = th.find('.//' + A + 'clrScheme')
                order = ['lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6']
                out = []
                for n in order:
                    e = cs.find(A + n)[0]
                    out.append((e.get('val') if e.tag.endswith('srgbClr') else e.get('lastClr')) or '000000')
                theme = out
            except Exception: pass
        st = ET.fromstring(self.z.read('xl/styles.xml'))
        self.numfmts = {}
        nf = st.find(NS + 'numFmts')
        if nf is not None:
            for e in nf: self.numfmts[int(e.get('numFmtId'))] = e.get('formatCode')
        fonts = []
        for f in st.find(NS + 'fonts'):
            sz = f.find(NS + 'sz')
            fonts.append(dict(b=f.find(NS + 'b') is not None, i=f.find(NS + 'i') is not None,
                              sz=float(sz.get('val')) if sz is not None else 11, color=read_color(f.find(NS + 'color'), theme)))
        fills = []
        for f in st.find(NS + 'fills'):
            pf = f.find(NS + 'patternFill')
            col = None
            if pf is not None and pf.get('patternType') == 'solid': col = read_color(pf.find(NS + 'fgColor'), theme)
            fills.append(col)
        borders = []
        for b in st.find(NS + 'borders'):
            borders.append(any(c is not None and c.get('style') for c in b if c.tag in (NS + 'left', NS + 'right', NS + 'top', NS + 'bottom')))
        self.xfs = []
        for xf in st.find(NS + 'cellXfs'):
            al = xf.find(NS + 'alignment')
            nid = int(xf.get('numFmtId') or 0)
            code = self.numfmts.get(nid) or BUILTIN.get(nid, 'General')
            self.xfs.append(dict(
                code=code, date=(nid in DATE_IDS and nid not in self.numfmts) or is_date_code(code),
                font=fonts[int(xf.get('fontId') or 0)], bg=fills[int(xf.get('fillId') or 0)] if int(xf.get('fillId') or 0) < len(fills) else None,
                bd=borders[int(xf.get('borderId') or 0)] if int(xf.get('borderId') or 0) < len(borders) else False,
                ha=al.get('horizontal') if al is not None else None, va=al.get('vertical') if al is not None else None,
                wr=(al.get('wrapText') in ('1', 'true')) if al is not None else False))

    def table_ref(self, sheet_path):
        rp = sheet_path.replace('worksheets/', 'worksheets/_rels/') + '.rels'
        if rp not in self.names: return None
        rels = ET.fromstring(self.z.read(rp))
        best = None
        for r in rels.iter(PKG + 'Relationship'):
            if r.get('Type', '').endswith('/table'):
                t = r.get('Target'); t = t.lstrip('/')
                p = 'xl/tables/' + t.split('/')[-1] if not t.startswith('xl/') else t
                try:
                    ref = ET.fromstring(self.z.read(p)).get('ref')
                except KeyError: continue
                m = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', ref)
                if m and m.group(2) == '1' and m.group(1) == 'A': return ref
                best = best or ref
        return best

def col_idx(s):
    n = 0
    for ch in s: n = n * 26 + ord(ch) - 64
    return n

def display(book, xf, kind, v, raw):
    """مقدار سلول → متن نمایشی"""
    if kind == 's': return book.ss[int(v)] if v != '' else ''
    if kind in ('str', 'inlineStr'): return v or ''
    if kind == 'b': return 'TRUE' if v == '1' else 'FALSE'
    if kind == 'e': return v or ''
    if v is None or v == '': return ''
    try: x = float(v)
    except ValueError: return v
    if xf and xf['date'] and 1 <= x < 2958466:
        t = serial_to_jalali(x)
        code = _strip(xf['code'])
        if re.search(r'h', code, re.I) and x != int(x):
            frac = x - int(x); mins = round(frac * 1440)
            t += ' %02d:%02d' % (mins // 60, mins % 60)
        return t
    code = xf['code'] if xf else 'General'
    if code == 'General' or code == '@': return fmt_general(x)
    try: return fmt_number(x, code)
    except Exception: return fmt_general(x)

def read_sheet(book, path):
    """کل سلول‌های یک شیت را می‌خواند: rows{r:{c:(text,xfIndex)}}, hidden rows, heights, cols, merges"""
    rows = {}; hidden_rows = set(); heights = {}; cols = {}; merges = []
    root_iter = ET.iterparse(book.z.open(path), events=('start', 'end'))
    in_sd = False
    for ev, el in root_iter:
        tag = el.tag
        if ev == 'end' and tag == NS + 'col':
            lo, hi = int(el.get('min')), int(el.get('max'))
            for c in range(lo, min(hi, lo + 200) + 1):
                cols[c] = dict(hidden=el.get('hidden') in ('1', 'true'), w=float(el.get('width') or 8.43))
        elif ev == 'end' and tag == NS + 'row':
            r = int(el.get('r'))
            if el.get('hidden') in ('1', 'true'): hidden_rows.add(r)
            if el.get('ht'): heights[r] = float(el.get('ht'))
            cells = {}
            for c in el:
                if c.tag != NS + 'c': continue
                m = re.match(r'([A-Z]+)', c.get('r'))
                ci = col_idx(m.group(1))
                t = c.get('t') or 'n'
                s = int(c.get('s') or 0)
                vv = c.find(NS + 'v')
                if t == 'inlineStr':
                    is_ = c.find(NS + 'is'); v = ''.join((x.text or '') for x in is_.iter(NS + 't')) if is_ is not None else ''
                else: v = vv.text if vv is not None and vv.text is not None else ''
                xf = book.xfs[s] if s < len(book.xfs) else None
                try: txt = display(book, xf, t, v, None)
                except Exception: txt = v
                cells[ci] = (txt, s)
            rows[r] = cells
            el.clear()
        elif ev == 'end' and tag == NS + 'mergeCell':
            m = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', el.get('ref'))
            if m: merges.append((int(m.group(2)), col_idx(m.group(1)), int(m.group(4)), col_idx(m.group(3))))
    return rows, hidden_rows, heights, cols, merges

# ----------------------------------------------------------------- ساخت خروجی هر شیت
def build_report(book, rows, hidden_rows, heights, cols, merges):
    def colhidden(c): return cols.get(c, {}).get('hidden', False)
    last_r = 0; last_c = 0
    for r, cs in rows.items():
        for c, (t, s) in cs.items():
            xf = book.xfs[s] if s < len(book.xfs) else None
            if t != '' or (xf and (xf['bg'] or xf['bd'])):
                if colhidden(c) or r in hidden_rows: continue
                if t != '': last_r = max(last_r, r)
                last_c = max(last_c, c)
    vis_cols = [c for c in range(1, last_c + 1) if not colhidden(c)]
    cmap = {c: i for i, c in enumerate(vis_cols)}
    vis_rows = [r for r in range(1, last_r + 1) if r not in hidden_rows]
    rmap = {r: i for i, r in enumerate(vis_rows)}
    styles = []; sidx = {}
    def style_id(s):
        xf = book.xfs[s] if s < len(book.xfs) else None
        if not xf: return 0
        d = {}
        if xf['bg'] and xf['bg'] != '#ffffff': d['bg'] = xf['bg']
        f = xf['font']
        if f['color'] and f['color'] not in ('#000000',): d['fg'] = f['color']
        if f['b']: d['b'] = 1
        if f['i']: d['i'] = 1
        if abs(f['sz'] - 11) > 0.6: d['sz'] = f['sz']
        if xf['ha'] in ('center', 'left', 'right'): d['ha'] = xf['ha'][0]
        if xf['va'] in ('center', 'top', 'bottom'): d['va'] = xf['va'][0]
        if xf['wr']: d['wr'] = 1
        if xf['bd']: d['bd'] = 1
        if not d: return 0
        k = json.dumps(d, sort_keys=True)
        if k not in sidx: styles.append(d); sidx[k] = len(styles)
        return sidx[k]
    cells = []
    for r in vis_rows:
        for c in vis_cols:
            cell = rows.get(r, {}).get(c)
            if not cell: continue
            t, s = cell
            sid = style_id(s)
            if t == '' and not sid: continue
            if t == '' and sid and 'bg' not in styles[sid - 1] and 'bd' not in styles[sid - 1]: continue
            cells.append([rmap[r], cmap[c], t, sid])
    mg = []
    for r1, c1, r2, c2 in merges:
        rs = [rmap[r] for r in range(r1, r2 + 1) if r in rmap]
        cs_ = [cmap[c] for c in range(c1, c2 + 1) if c in cmap]
        if rs and cs_ and (len(rs) > 1 or len(cs_) > 1): mg.append([min(rs), min(cs_), max(rs), max(cs_)])
    widths = [int(round(cols.get(c, {}).get('w', 8.43) * 7 + 5)) for c in vis_cols]
    hts = {str(rmap[r]): int(round(h * 1.333)) for r, h in heights.items() if r in rmap and abs(h - 15) > 1}
    return dict(w=widths, ht=hts, m=mg, st=styles, c=cells, nr=len(vis_rows), nc=len(vis_cols))

def build_table(book, sheet, rows, hidden_rows, cols, keys):
    ref = book.table_ref(sheet['path'])
    if ref:
        m = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', ref)
        c1, c2, r1, r2 = col_idx(m.group(1)), col_idx(m.group(3)), int(m.group(2)), int(m.group(4))
    else:
        c1, r1 = 1, 1
        c2 = max((max(cs) for cs in rows.values() if cs), default=1); r2 = max(rows) if rows else 1
    vis = [c for c in range(c1, c2 + 1) if not cols.get(c, {}).get('hidden')]
    hdr = [rows.get(r1, {}).get(c, ('', 0))[0].replace('\n', ' ') for c in vis]
    keycols = [i for i, h in enumerate(hdr) if any(k in h for k in keys)]
    out = []
    for r in range(r1 + 1, r2 + 1):
        if r in hidden_rows: continue
        cs = rows.get(r)
        if not cs: continue
        row = [cs.get(c, ('', 0))[0] for c in vis]
        if keycols:
            if not any(row[i] != '' for i in keycols): continue
        elif sum(1 for x in row if x != '') < 2: continue
        out.append(row)
    return dict(cols=hdr, rows=out)

def chunk_rows(rows):
    chunks = [[]]; size = 0
    for r in rows:
        s = len(json.dumps(r, ensure_ascii=False)) + 1
        if size + s > CHUNK_BYTES and chunks[-1]: chunks.append([]); size = 0
        chunks[-1].append(r); size += s
    return chunks

def make_payload(book, sheet, kind, keys, ord_):
    rows, hid, hts, cols, merges = read_sheet(book, sheet['path'])
    if kind == 'table':
        t = build_table(book, sheet, rows, hid, cols, keys)
        parts = [dict(cols=t['cols'], rows=r) if i == 0 else dict(rows=r) for i, r in enumerate(chunk_rows(t['rows']))]
        if not parts: parts = [dict(cols=t['cols'], rows=[])]
        meta_n = len(t['rows']); ncols = len(t['cols'])
    else:
        rep = build_report(book, rows, hid, hts, cols, merges)
        cl_ = chunk_rows(rep['c']) or [[]]
        parts = []
        for i, cc in enumerate(cl_):
            p = dict(c=cc)
            if i == 0: p.update(w=rep['w'], ht=rep['ht'], m=rep['m'], st=rep['st'], nr=rep['nr'], nc=rep['nc'])
            parts.append(p)
        meta_n = rep['nr']; ncols = rep['nc']
    h = hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode('utf8')).hexdigest()[:16]
    for p in parts: p['h'] = h
    sid = 'x' + hashlib.md5(sheet['name'].encode('utf8')).hexdigest()[:8]
    meta = dict(id=sid, title=sheet['name'], kind=kind, ord=ord_, nrows=meta_n, ncols=ncols, nchunks=len(parts), hash=h,
                bytes=sum(len(json.dumps(p, ensure_ascii=False)) for p in parts))
    return meta, parts

def build_all(path, cfg):
    book = Book(path)
    skip = set(cfg.get('skip', SKIP_DEFAULT))
    over = cfg.get('sheets', {})
    res = []
    for i, sh in enumerate(book.sheets):
        n = sh['name']
        if n in skip or (sh['hidden'] and n not in over): continue
        o = over.get(n, {})
        kind = o.get('kind') or ('table' if n in TABLE_SHEETS else 'report')
        if kind == 'skip': continue
        keys = o.get('keys') or TABLE_SHEETS.get(n, [])
        t0 = time.time()
        meta, parts = make_payload(book, sh, kind, keys, i)
        log('  %-32s %-6s %6d ردیف  %7.0f KB  %d تکه  (%.1fs)' % (n, kind, meta['nrows'], meta['bytes'] / 1024, meta['nchunks'], time.time() - t0))
        res.append((meta, parts))
    return res

# ----------------------------------------------------------------- Supabase
class Supa:
    def __init__(self, cfg):
        self.url = cfg['supabase_url'].rstrip('/'); self.key = cfg['supabase_anon_key']
        self.email = cfg['publisher_email']; self.pw = cfg['publisher_password']; self.tok = None

    def _req(self, method, path, body=None, extra=None, auth=True):
        h = {'apikey': self.key, 'Content-Type': 'application/json'}
        if auth and self.tok: h['Authorization'] = 'Bearer ' + self.tok
        if extra: h.update(extra)
        data = json.dumps(body, ensure_ascii=False).encode('utf8') if body is not None else None
        rq = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(rq, timeout=120) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, e.read()

    def login(self):
        st, b = self._req('POST', '/auth/v1/token?grant_type=password', dict(email=self.email, password=self.pw), auth=False)
        if st != 200: raise RuntimeError('ورود ناشر ناموفق بود (%s): %s' % (st, b[:200].decode('utf8', 'ignore')))
        self.tok = json.loads(b)['access_token']

    def remote_meta(self):
        st, b = self._req('GET', '/rest/v1/excel_sheets?select=id,hash,nchunks')
        if st != 200: raise RuntimeError('خواندن excel_sheets ناموفق (%s): %s' % (st, b[:200].decode('utf8', 'ignore')))
        return {r['id']: r for r in json.loads(b)}

    def push(self, meta, parts, info):
        for i, p in enumerate(parts):
            st, b = self._req('POST', '/rest/v1/excel_chunks?on_conflict=sheet_id,part', [dict(sheet_id=meta['id'], part=i, data=p)],
                              {'Prefer': 'resolution=merge-duplicates,return=minimal'})
            if st not in (200, 201, 204): raise RuntimeError('نوشتن تکه‌ی %d ناموفق (%s): %s' % (i, st, b[:300].decode('utf8', 'ignore')))
        self._req('DELETE', '/rest/v1/excel_chunks?sheet_id=eq.%s&part=gte.%d' % (meta['id'], len(parts)))
        row = dict(meta); row['info'] = info; row['updated_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
        st, b = self._req('POST', '/rest/v1/excel_sheets?on_conflict=id', [row], {'Prefer': 'resolution=merge-duplicates,return=minimal'})
        if st not in (200, 201, 204): raise RuntimeError('نوشتن excel_sheets ناموفق (%s): %s' % (st, b[:300].decode('utf8', 'ignore')))

    def prune(self, keep_ids):
        st, b = self._req('GET', '/rest/v1/excel_sheets?select=id')
        for r in json.loads(b) if st == 200 else []:
            if r['id'] not in keep_ids:
                self._req('DELETE', '/rest/v1/excel_chunks?sheet_id=eq.' + r['id'])
                self._req('DELETE', '/rest/v1/excel_sheets?id=eq.' + r['id'])

# ----------------------------------------------------------------- اجرا
def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)

def snapshot(src):
    """کپی از فایل (وقتی Excel باز است) تا خواندن مزاحمش نشود."""
    fd, tmp = tempfile.mkstemp(suffix='.xlsx'); os.close(fd)
    for i in range(15):
        try:
            shutil.copyfile(src, tmp); return tmp
        except (PermissionError, OSError):
            time.sleep(1)
    os.remove(tmp); raise RuntimeError('فایل قفل است و کپی نشد: ' + src)

def publish_once(cfg, dry=None, force=False):
    src = cfg['xlsx_path']
    log('خواندن', os.path.basename(src))
    tmp = snapshot(src)
    try:
        data = build_all(tmp, cfg)
    finally:
        try: os.remove(tmp)
        except OSError: pass
    info = dict(file=os.path.basename(src), published=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
    if dry:
        os.makedirs(dry, exist_ok=True)
        for meta, parts in data:
            json.dump(dict(meta=meta, parts=parts), open(os.path.join(dry, meta['id'] + '.json'), 'w', encoding='utf8'), ensure_ascii=False)
        log('نوشته شد در', dry); return
    sb = Supa(cfg); sb.login()
    remote = sb.remote_meta(); n = 0
    for meta, parts in data:
        r = remote.get(meta['id'])
        if not force and r and r['hash'] == meta['hash'] and r['nchunks'] == meta['nchunks']: continue
        log('ارسال', meta['title']); sb.push(meta, parts, info); n += 1
    sb.prune({m['id'] for m, _ in data})
    log('تمام شد؛ %d شیت تغییر کرده بود.' % n)

def watch(cfg):
    src = cfg['xlsx_path']; poll = cfg.get('poll_seconds', 5); settle = cfg.get('settle_seconds', 4)
    last = None
    log('زیر نظر گرفتن:', src, '(توقف: Ctrl+C)')
    while True:
        try:
            m = os.path.getmtime(src)
            if last is None or m != last:
                time.sleep(settle)
                if os.path.getmtime(src) == m:   # فایل آرام شد (ذخیره تمام شده)
                    try: publish_once(cfg)
                    except Exception as e: log('خطا:', e)
                    last = m
        except FileNotFoundError:
            log('فایل پیدا نشد:', src)
        time.sleep(poll)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json'))
    ap.add_argument('--once', action='store_true'); ap.add_argument('--watch', action='store_true')
    ap.add_argument('--force', action='store_true', help='همه‌ی شیت‌ها را دوباره بفرست')
    ap.add_argument('--dry-run', metavar='پوشه')
    ap.add_argument('--xlsx', help='مسیر فایل اکسل (روی config.json اولویت دارد)')
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding='utf8')) if os.path.exists(a.config) else {}
    if a.xlsx: cfg['xlsx_path'] = a.xlsx
    if 'xlsx_path' not in cfg: sys.exit('مسیر فایل اکسل (xlsx_path) در config.json نیست.')
    if a.dry_run: publish_once(cfg, dry=a.dry_run); return
    for k in ('supabase_url', 'supabase_anon_key', 'publisher_email', 'publisher_password'):
        if not cfg.get(k): sys.exit('در config.json مقدار %s را بنویسید.' % k)
    if a.once: publish_once(cfg, force=a.force)
    else: publish_once(cfg, force=a.force); watch(cfg)

if __name__ == '__main__':
    main()
