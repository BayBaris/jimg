r"""samples/ altindaki tum JSON belgeleri icin kesif + duzlestirme dogrulamasi.

Betik hicbir belgeye ozel yazilmamistir: alan adi, veri kumesi adi veya deger
sabitlemez. samples/ git ile izlenmez; klasor bossa betik cokmeden gecer.

Calistirma:  .\.venv\Scripts\python.exe tools\check.py
"""

from __future__ import annotations

import base64
import contextlib
import functools
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Cikti UTF-8'e sabitlenir. Konsol kod sayfasi cp1254 oldugunda (PowerShell'in
# ve Git Bash'in Turkce Windows'taki varsayilani) rapordaki `→` ve `·` gibi
# isaretler `UnicodeEncodeError` firlatiyor ve dogrulama, belgede bir sorun
# olmadigi halde cokuyordu. `errors="replace"` son savunma: yeni bir isaret
# eklenirse betik yine de sonuna kadar kosar.
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")

from jsonimager import chart_data as CD     # noqa: E402
from jsonimager import columns as COL       # noqa: E402
from jsonimager import discover as D        # noqa: E402
from jsonimager import draw as DRAW         # noqa: E402
from jsonimager import edit_core as EC      # noqa: E402
from jsonimager import edit_map as EM       # noqa: E402
from jsonimager import json_write as JW     # noqa: E402
from jsonimager import export_text as T     # noqa: E402
from jsonimager import flatten as F         # noqa: E402
from jsonimager import img_chart as ICH     # noqa: E402
from jsonimager import img_table as ITB     # noqa: E402
from jsonimager import img_tree as ITR      # noqa: E402
from jsonimager import schema as SCHEMA     # noqa: E402
from jsonimager import theme as TH          # noqa: E402
from jsonimager import vector as VEC        # noqa: E402

SAMPLES = ROOT / "samples"      # ozel, izlenmez (K-09)
EXAMPLES = ROOT / "examples"    # izlenir, depoyla gelir (Faz 9.1)


def check_document(path: Path) -> int:
    """Tek belgeyi dogrular. Donen deger: basarisiz kontrol sayisi."""
    fail = 0

    t0 = time.perf_counter()
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! okunamadi — {type(exc).__name__}: {exc}")
        return 1
    t1 = time.perf_counter()
    datasets = D.discover(root)
    t2 = time.perf_counter()

    print(f"  {len(datasets)} veri kumesi · ayristirma {t1 - t0:.3f}s · kesif {t2 - t1:.3f}s")

    worst, worst_name = 0.0, "-"
    variant_count = 0

    for ds in datasets:
        # 1) Kesif sayilari ile kurulan tablo boyutlari tutmali.
        t3 = time.perf_counter()
        try:
            t = F.build_table(root, ds)
        except Exception as exc:
            print(f"  ! {ds.id}: {type(exc).__name__}: {exc}")
            fail += 1
            continue
        dt = time.perf_counter() - t3
        if dt > worst:
            worst, worst_name = dt, f"{ds.id} {len(t['rows'])}x{len(t['columns'])}"

        if len(t["rows"]) != ds.row_count or len(t["columns"]) != ds.col_count:
            print(f"  ! {ds.id}: kesif {ds.row_count}x{ds.col_count}"
                  f" != tablo {len(t['rows'])}x{len(t['columns'])}")
            fail += 1

        # 2) Bilinmeyen sutun grubu olmamali.
        bad = [c["label"] for c in t["columns"] if c.get("group") not in COL.GROUP_ORDER]
        if bad:
            print(f"  ! {ds.id}: bilinmeyen sutun grubu — {bad}")
            fail += 1

        # 3) Transpoze satir/sutun sayilarini tam olarak degistirmeli.
        tr = F.build_table(root, ds, transpose=True)
        if len(tr["rows"]) != len(t["columns"]) or len(tr["columns"]) != len(t["rows"]) + 1:
            print(f"  ! {ds.id}: transpoze {len(t['rows'])}x{len(t['columns'])}"
                  f" -> {len(tr['rows'])}x{len(tr['columns'])} beklenmedik")
            fail += 1

        # 4) Sema varyantlarinda bos hucre KALMAMALI — varyant bolmenin amaci budur.
        for v in ds.variants:
            variant_count += 1
            vt = F.build_table(root, ds, v.id)
            sparse = [c["label"] for c in vt["columns"] if c["sparse"]]
            if sparse:
                print(f"  ! {ds.id} / {v.label}: varyantta seyrek sutun kaldi — {sparse}")
                fail += 1

    print(f"  {variant_count} sema varyanti · en yavas tablo: {worst_name} ({worst:.3f}s)")

    # Metin sutunlarinin grup atamasi. Sutun grubu esigi (AK-09) bu satirdan
    # izlenir: benzersiz deger sayisi parantez icinde, atanan grup okla.
    if datasets:
        big = max(datasets, key=lambda d: d.row_count * d.col_count)
        bt = F.build_table(root, big)
        marks = []
        for i, c in enumerate(bt["columns"]):
            if c["kind"] != F.C_SCALAR or c["dtype"] != "str":
                continue
            uniq = len({r[i].get("d") for r in bt["rows"] if i < len(r) and r[i]})
            marks.append(f"{c['label']}({uniq})→{c['group']}")
        if marks:
            print("  metin sutunlari: " + " · ".join(marks[:8]))

    # 5) JSONtoText — dort bicim de hatasiz ve bos olmayan cikti vermeli.
    fail += check_text(path.name, root, datasets)

    # 6) JSONtoIMG — tablo / agac / grafik cizilebilmeli.
    fail += check_images(path.name, root, datasets)

    # 7) Faz 6 semasi — hucre DEGERI sizmamali.
    fail += check_schema(root, datasets)

    # 8) Faz 7.3 — sarilan sutun cizimde de sarilmali.
    fail += check_wrap(root, datasets)

    # 9) Faz 7.4 — grafik sutun rolleri ve otomatik oneriler.
    fail += check_chart_roles(root, datasets)

    # 10) Faz 10.1 — her duzenlenebilir hucrenin adresi geri cozulunce kendisi.
    fail += check_edit_map(root, datasets)

    # 11) Faz 10.2 — gercek hucrelerde duzenle -> geri al: belge birebir ayni.
    fail += check_edit_roundtrip(root, datasets)

    # 12) Faz 10.3 — tek degisiklikten sonra baska hicbir bayt degismez.
    fail += check_json_write(path, root, datasets)

    kinds: dict[str, int] = {}
    for ds in datasets:
        kinds[ds.kind_label] = kinds.get(ds.kind_label, 0) + 1
    print("  " + " · ".join(f"{k}: {v}" for k, v in sorted(kinds.items())))

    if "--datasets" in sys.argv:
        dump_datasets(root, datasets)
    return fail


def check_edit_map(root, datasets: list[D.Dataset]) -> int:
    """Kaynak eslemesi tabloyla ayni sirada mi (Faz 10.1).

    Her veri kumesi ve varyantta, isaretsiz (duzenlenebilir) her hucrenin
    adresi `edit_map.locate` ile geri cozulur: deger hedefinde degerin
    gosterimi, anahtar hedefinde anahtarin kendisi hucrenin `d`sine esit
    olmali. Esit degilse duzenleme BASKA bir hucreye yazardi. Transpoze
    tablo da sinanir: arayuzun kurali (satir j <-> ozgun sutun j, `_r{i}` <->
    ozgun satir i) ayni hucreyi gostermeli. Yalnizca sayi basilir, deger ya
    da ad basilmaz (gizlilik).
    """
    bad: list[str] = []
    edit = total = 0
    why: dict[str, int] = {}
    for ds in datasets:
        for vid in [None] + [v.id for v in ds.variants]:
            t = F.build_table(root, ds, vid)
            tt = F.build_table(root, ds, vid, transpose=True)
            for ri, row in enumerate(t["rows"]):
                for ci, cell in enumerate(row):
                    total += 1
                    if tt["rows"][ci][ri + 1].get("x") != cell.get("x") \
                            or tt["rows"][ci][ri + 1].get("d") != cell.get("d"):
                        bad.append(f"{ds.kind}: transpoze hucre ({ri},{ci}) ayrisiyor")
                    if cell.get("x") == EM.WHY_UNMAPPED:
                        bad.append(f"{ds.kind}: esleme tabloyla ayni boyutta degil")
                    if "x" in cell:
                        why[cell["x"]] = why.get(cell["x"], 0) + 1
                        continue
                    loc = EM.locate(root, ds, vid, ri, ci)
                    if isinstance(loc, str):
                        bad.append(f"{ds.kind}: ({ri},{ci}) isaretsiz ama locate '{loc}'")
                        continue
                    path, target = loc
                    if target in (EM.KEY, EM.SHARED):
                        got = str(path[-1])
                    else:
                        got = F.make_cell(D.resolve(root, path))["d"]
                    if got != cell["d"]:
                        bad.append(f"{ds.kind}: ({ri},{ci}) adres baska hucreyi gosteriyor")
                    edit += 1
    if bad:
        for b in sorted(set(bad))[:5]:
            print(f"  ! kaynak eslemesi: {b}")
        return len(set(bad))
    reasons = " · ".join(f"{k} {v}" for k, v in sorted(why.items()))
    print(f"  kaynak eslemesi: {edit}/{total} hucre duzenlenebilir, adresleri geri cozuluyor"
          + (f" · {reasons}" if reasons else ""))
    return 0


EDIT_SAMPLE = 3   # veri kumesi basina sinanan duzenlenebilir hucre


def _probe_op(root, ds: D.Dataset, path: list, target: str):
    """Hucreyi DEGISTIRECEK bir islem: turu koruyan en kucuk degisiklik."""
    if target == EM.SHARED:
        paths = EM.pivot_key_paths(root, ds, path[-1])
        new = str(path[-1]) + "~"
        while any(new in D.resolve(root, p[:-1]) for p in paths):
            new += "~"
        return EC.rename_many_op(root, paths, new)
    if target == EM.KEY:
        parent = D.resolve(root, path[:-1])
        new = str(path[-1]) + "~"
        while new in parent:
            new += "~"
        return EC.rename_op(root, path, new)
    old = D.resolve(root, path)
    if isinstance(old, bool):
        new = not old
    elif isinstance(old, (int, float)):
        new = old + 1
    elif isinstance(old, str):
        new = old + "·"
    else:
        new = "x"
    return EC.set_value_op(root, path, new)


def check_edit_roundtrip(root, datasets: list[D.Dataset]) -> int:
    """Gercek hucrelerde cekirdek (Faz 10.2): uygula -> geri al -> yinele -> geri al.

    Her veri kumesinde ilk birkac duzenlenebilir hucre (deger ve anahtar)
    degistirilir; hepsi uygulandiktan sonra her hedef yeni degeri gostermeli,
    hepsi geri alininca belge (sira dahil) BIREBIR ozgun olmali. Satir
    sirasiyla secildigi icin anahtarli tabloda once satirin anahtari, sonra
    ayni satirin degeri degisir: deger yeni adin altindan yazilir ve LIFO geri
    alma once degeri, sonra adi dondurur.

    ⚠ Veri kumesi basina KAPATILIR: kok veri kumesinde yeniden adlandirilan
    ust duzey bir anahtar, sonraki veri kumesinin `ds.path`ini gecersiz kilar.
    Karsilastirma veri kumesinin DUGUMUNDE yapilir (islemler yalnizca onun
    icine dokunur); tum belge en sonda bir kez — 5 MB'lik belgede her veri
    kumesinde tum belgeyi serilestirmek kapiyi 8,5 s'ye cikariyordu.
    """
    before = json.dumps(root, ensure_ascii=False)
    bad = []
    n = 0
    for ds in datasets:
        h = EC.History()
        snap = json.dumps(D.resolve(root, ds.path), ensure_ascii=False)
        same_node = lambda: json.dumps(D.resolve(root, ds.path), ensure_ascii=False) == snap  # noqa: E731
        t = F.build_table(root, ds)
        picked = 0
        for ri, row in enumerate(t["rows"]):
            for ci, cell in enumerate(row):
                if picked >= EDIT_SAMPLE or "x" in cell:
                    continue
                loc = EM.locate(root, ds, None, ri, ci)
                if isinstance(loc, str):
                    continue
                path, target = loc
                op = _probe_op(root, ds, path, target)
                if not EC.apply(root, h, op):
                    bad.append(f"{ds.kind}: degisiklik uygulanmadi")
                    continue
                new_path = path[:-1] + [op[3]] if target == EM.KEY else path
                if target == EM.VALUE and not EC.same(D.resolve(root, new_path), op[3]):
                    bad.append(f"{ds.kind}: deger yazilmadi")
                picked += 1
                n += 1
        if picked and not EC.dirty(h):
            bad.append(f"{ds.kind}: islem sonrasi belge kirli degil")
        while EC.undo(root, h):
            pass
        if not same_node():
            bad.append(f"{ds.kind}: geri alinca veri kumesi ozgunle ayni degil")
        while EC.redo(root, h):
            pass
        while EC.undo(root, h):
            pass
        if not same_node():
            bad.append(f"{ds.kind}: yinele + geri al sonrasi veri kumesi ozgunle ayni degil")
            break      # kok bozuldu: sonraki veri kumeleri anlamsiz
        if EC.dirty(h):
            bad.append(f"{ds.kind}: tum islemler geri alininca belge hala kirli")
    if json.dumps(root, ensure_ascii=False) != before:
        bad.append("sinama sonunda belge ozgunle ayni degil")
    if bad:
        for b in sorted(set(bad))[:5]:
            print(f"  ! duzenleme cekirdegi: {b}")
        return len(set(bad))
    print(f"  duzenleme cekirdegi: {n} islem uygulandi, geri alinca ve yinele/geri al sonrasi belge birebir")
    return 0


WRITE_DATASETS = 4   # belge basina yazicinin sinandigi veri kumesi (esit aralikla)


def _changed_span(a: bytes, b: bytes) -> tuple[int, int, int]:
    """(ortak on ek, a'daki degisen uzunluk, b'deki degisen uzunluk).

    Ikili arama: dilim karsilastirmasi C'de kosar; 5 MB'lik belgede bayt bayt
    Python dongusu her olcumde yarim saniye surerdi.
    """
    n = min(len(a), len(b))

    def longest(ok) -> int:
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if ok(mid) else (lo, mid - 1)
        return lo

    pre = longest(lambda k: a[:k] == b[:k])
    suf = longest(lambda k: k <= n - pre and a[len(a) - k:] == b[len(b) - k:])
    return pre, len(a) - pre - suf, len(b) - pre - suf


def check_json_write(path: Path, root, datasets: list[D.Dataset]) -> int:
    """Yazici (Faz 10.3): tek degisiklik -> dosyada yalnizca o belirtec degisir.

    Olcut yazicinin belirtec ayiricisindan BAGIMSIZ: ozgun ve yeni baytlarin
    ortak on ve son eki disinda kalan bolge, degisen degerin (ya da anahtarin)
    yaziminin en uzun bicimini asamaz; CR ve satir sayisi ayni kalir. Yazici
    dosyanin tamamini yeniden bicimlendirseydi bolge dosya boyunda olurdu.
    Veri kumesi basina islem kurulur, olculur ve geri alinir.
    """
    raw = path.read_bytes()
    bad = []
    n = 0
    step = max(1, len(datasets) // WRITE_DATASETS)
    for ds in datasets[::step][:WRITE_DATASETS]:
        t = F.build_table(root, ds)
        done_targets: set[str] = set()
        for ri, row in enumerate(t["rows"]):
            for ci, cell in enumerate(row):
                if "x" in cell or len(done_targets) == 2:
                    continue
                loc = EM.locate(root, ds, None, ri, ci)
                # Olcut TEK belirtec: pivot ic anahtari birden cok belirteci birlikte
                # degistirir (10.7) ve aradaki degismeyen baytlar da bolgeye girer.
                # Cok belirtecli yazim `check_rename_column`da bayt bayt sinanir.
                if isinstance(loc, str) or loc[1] in done_targets or loc[1] == EM.SHARED:
                    continue
                done_targets.add(loc[1])
                h = EC.History()
                op = _probe_op(root, ds, *loc)
                EC.apply(root, h, op)
                try:
                    out = JW.render(raw, root)
                except JW.WriteError as e:
                    bad.append(f"{ds.kind}/{loc[1]}: yazilamadi ({e.reason})")
                    EC.undo(root, h)
                    continue
                EC.undo(root, h)
                _, old_len, new_len = _changed_span(raw, out)
                limit = lambda v: max(len(json.dumps(v).encode()),  # noqa: E731
                                      len(json.dumps(v, ensure_ascii=False).encode()))
                if old_len > limit(op[2]) or new_len > limit(op[3]):
                    bad.append(f"{ds.kind}/{loc[1]}: degisen bolge belirtecten buyuk "
                               f"({old_len} -> {new_len} bayt)")
                if out.count(b"\r") != raw.count(b"\r") or out.count(b"\n") != raw.count(b"\n"):
                    bad.append(f"{ds.kind}/{loc[1]}: satir sonlari degisti")
                n += 1
    if JW.render(raw, root) is not raw:
        bad.append("geri alininca yazici ozgun baytlari dondurmuyor")
    if bad:
        for b in sorted(set(bad))[:5]:
            print(f"  ! yazici: {b}")
        return len(set(bad))
    print(f"  yazici: {n} tek degisiklik · her birinde yalnizca o belirtec degisti · "
          f"satir sonlari korundu ({raw.count(b'\r')} CR)")
    return 0


def check_edit_messages() -> int:
    """Duzenleme nedenleri ve hata kodlari iki dilde ileti tasiyor mu (Faz 10.5).

    Arayuz iletiyi anahtardan KURUYOR (`t('edit.why_' + cell.x)`), yani dinamik:
    `check_ui_strings` bu cagriyi goremez. Eksik anahtar ekranda ham
    `edit.why_...` olarak gorunurdu. Kaynak sabitleri tek dogru liste:
    `edit_map.WHY_*` · `edit_core.ERR_*` · `json_write.ERR_*`.
    """
    from jsonimager import i18n as I18N
    wanted = (
        [f"edit.why_{getattr(EM, n)}" for n in dir(EM) if n.startswith("WHY_")]
        + [f"edit.err_{getattr(EC, n)}" for n in dir(EC) if n.startswith("ERR_")]
        + [f"edit.save_{getattr(JW, n)}" for n in dir(JW) if n.startswith("ERR_")]
        + ["edit.save_failed", "edit.saved"]
    )
    missing = [f"{lang}:{k}" for lang in I18N.STRINGS for k in wanted
               if k not in I18N.STRINGS[lang]]
    if missing:
        print(f"  ! duzenleme iletileri eksik: {' · '.join(sorted(missing))}")
        return len(missing)
    print(f"  duzenleme iletileri: {len(wanted)} anahtar × {len(I18N.STRINGS)} dil")
    return 0


# Diske yazan moduller ve ne yazdiklari (10.8). Liste bir IZIN listesidir:
# yeni bir modul diske yazmaya baslarsa kapi kirmizi yanar ve yazdigi seyin
# `SECURITY.md`de bir siniri olup olmadigi sorulur.
DISK_WRITERS = {
    "json_write.py": "acik belge (yalnizca kayitla)",
    "api_export.py": "disa aktarim (kullanicinin sectigi yol)",
    "settings.py": "ayar dosyasi · son oturumun yollari (yalnizca ayar acikken, 9.19.5)",
    "keys.py": "sifreli anahtar deposu",
    "paths.py": "ornek belgelerin kullanici klasorune kopyasi",
}
_DISK_WRITE = re.compile(
    r"\.write_bytes\(|\.write_text\(|open\([^)\n]*[\"'][wax]b?\+?[\"']|os\.replace\("
    r"|shutil\.(?:copy\w*|move)\(")


def check_doc_write() -> int:
    """Belge yazma siniri (10.8, `SECURITY.md` "Editing documents").

    Kaynak: diske yazan kod yalnizca izinli modullerde · belgeyi yazan
    `json_write.save` yalnizca `save_doc`tan cagrilir ve yolu ACIK BELGENIN
    kaydindan alir (arayuz yol gonderemez).
    Davranis (gecici klasor): duzenleme tek basina diske dokunmaz · acik
    olmayan belge kimligi hicbir sey yazmaz · dogrulama tutmazsa ne belge ne
    yedek yazilir · kayit yalnizca belgenin kendi yoluna ve yanindaki `.bak`a.
    """
    import tempfile
    from jsonimager.app import Api
    out = []
    pkg = ROOT / "src" / "jsonimager"

    writers = {p.name for p in sorted(pkg.rglob("*.py"))
               if _DISK_WRITE.search(p.read_text(encoding="utf-8"))}
    for name in sorted(writers - set(DISK_WRITERS)):
        out.append(f"{name} diske yaziyor ama izin listesinde yok")
    for name in sorted(set(DISK_WRITERS) - writers):
        out.append(f"{name} izin listesinde ama artik diske yazmiyor (liste bayat)")
    callers = sorted(p.name for p in pkg.rglob("*.py")
                     if re.search(r"\bJW\.save\(|json_write\.save\(", p.read_text(encoding="utf-8")))
    if callers != ["api_edit.py"]:
        out.append(f"belge yazicisi beklenmeyen yerden cagriliyor: {callers}")
    edit_src = (pkg / "api_edit.py").read_text(encoding="utf-8")
    if 'JW.save(Path(doc["path"]), doc["raw"]' not in edit_src:
        out.append("save_doc yolu acik belgenin kaydindan almiyor")
    sig = re.search(r"def save_doc\(self, ([^)]*)\)", edit_src)
    if not sig or re.search(r"\bpath\b|\btarget\b|\bfile\b", sig.group(1)):
        out.append("save_doc arayuzden yol aliyor")

    raw = json.dumps({"a": 1, "b": "x", "c": True}, indent=2).encode()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "belge.json"
        p.write_bytes(raw)
        api = Api()
        api._settings = {**api._settings, "documents": {"backup": True}}
        api._load_one(p)
        doc_id = str(p)
        t = api.table(doc_id, "$")["table"]
        row = [r[0]["d"] for r in t["rows"]].index("a")
        api.edit_cell(doc_id, "$", None, row, 1, "2")
        if p.read_bytes() != raw or len(list(Path(tmp).iterdir())) != 1:
            out.append("duzenleme kayit olmadan diske dokundu")
        other = Path(tmp) / "baska.json"
        r = api.save_doc(str(other))
        if r.get("ok") or other.exists():
            out.append("acik olmayan belge kimligiyle yazildi")
        good = JW.render

        def broken(data, root):
            raise JW.WriteError(JW.ERR_VERIFY)
        JW.render = broken
        try:
            r = api.save_doc(doc_id)
        finally:
            JW.render = good
        if r.get("ok") or r.get("reason") != JW.ERR_VERIFY or p.read_bytes() != raw \
                or len(list(Path(tmp).iterdir())) != 1:
            out.append("dogrulama tutmadigi halde diske dokunuldu")
        api.save_doc(doc_id)
        names = sorted(f.name for f in Path(tmp).iterdir())
        if names != ["belge.json", "belge.json.bak"] or (Path(tmp) / "belge.json.bak").read_bytes() != raw:
            out.append(f"kayit beklenmeyen dosya yazdi: {names}")
    if out:
        for o in out:
            print(f"  ! belge yazma siniri: {o}")
        return len(out)
    print(f"  belge yazma siniri: diske yazan {len(DISK_WRITERS)} modul izinli · belge yalnizca "
          f"save_doc ile, yolu kayittan · duzenleme diske dokunmuyor · acik olmayan kimlik ve "
          f"tutmayan dogrulama yazmiyor · yalnizca kendi yolu + .bak")
    return 0


def check_rename_dataset() -> int:
    """Tablo adi (10.6) — gecici klasorde sentetik belgeyle.

    Ad ust nesnedeki anahtardir: degisince veri kumesi kimligi, gorunum
    durumu ve ALTINDAKI veri kumelerinin kimligi birlikte tasinir; yanit
    `renamed` eslemesini tasir. Kok tablo ve varyant cevrilmis nedenle
    reddedilir, belge degismez. Geri alma adi ve gorunumu geri getirir.
    """
    import tempfile
    from jsonimager import i18n as I18N
    from jsonimager.app import Api
    out = []
    src = {"title": "x", "count": 3, "flag": True,
           "users": {f"u{i}": {"name": f"n{i}", "age": 30 + i} for i in range(4)},
           # `org` anahtar-deger tablosu, `org.people` onun ALTINDA kayit tablosu.
           "org": {"title": "x", "count": 3, "flag": True,
                   "people": [{"id": i, "role": "r"} for i in range(3)]}}
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "belge.json"
        p.write_text(json.dumps(src, indent=2), encoding="utf-8")
        api = Api()
        api._load_one(p)
        doc_id = str(p)
        ids0 = sorted(d.id for d in api._docs[doc_id]["datasets"])
        api.set_transpose(doc_id, "users", None, True)
        r = api.rename_dataset(doc_id, "users", None, "people")
        if not r.get("ok") or r.get("ds_id") != "people" or r.get("renamed") != {"users": "people"}:
            out.append(f"ad degismedi ya da yanit eksik: {r.get('ds_id')} {r.get('renamed')}")
        if api._key(doc_id, "people", None) not in api._transposed:
            out.append("gorunum durumu tasinmadi")
        if r.get("table", {}).get("label") != "people":
            out.append("donen tablonun etiketi yeni ad degil")
        # Ad degisikligi isareti: baslik (`name_edited`) ve agac (`edited`).
        marks = {d["id"]: d["edited"] for d in api.tree()["docs"][0]["datasets"]}
        if not r.get("table", {}).get("name_edited") or not marks.get("people") \
                or any(v for k, v in marks.items() if k != "people"):
            out.append(f"ad degisikligi isareti yanlis: {marks}")
        # Alt veri kumesi: `org` yeniden adlandirilinca altindaki `org.people` de tasinmali.
        r2 = api.rename_dataset(doc_id, "org", None, "firm")
        if r2.get("renamed") != {"org": "firm", "org.people": "firm.people"}:
            out.append(f"alttaki veri kumesi kimligi tasinmadi: {r2.get('renamed')}")
        api.undo_edit(doc_id)
        for label, args, why in [
            ("kok", ("$", None, "z"), "edit.err_root_name"),
            ("varyant", ("people", "people#v0", "z"), "edit.err_variant_name"),
            ("var olan ad", ("people", None, "title"), "edit.err_key_exists"),
        ]:
            r = api.rename_dataset(doc_id, *args)
            if r.get("ok") or r.get("error") != I18N.t(why):
                out.append(f"{label}: nedenle reddedilmedi ({r.get('error')})")
        api.undo_edit(doc_id)
        if sorted(d.id for d in api._docs[doc_id]["datasets"]) != ids0 \
                or api._key(doc_id, "users", None) not in api._transposed:
            out.append("geri alma adi ya da gorunumu geri getirmedi")
        if api.edit_state(doc_id)["edit"]["dirty"]:
            out.append("hepsi geri alininca belge hala kirli")
        if any(d["edited"] for d in api.tree()["docs"][0]["datasets"]) \
                or api.table(doc_id, "users")["table"]["name_edited"]:
            out.append("geri alininca ad isareti kalkmadi")
    if out:
        for o in out:
            print(f"  ! tablo adi: {o}")
        return len(out)
    print("  tablo adi: kimlik, gorunum ve alt veri kumeleri tasiniyor · kok/varyant/var olan "
          "ad cevrilmis nedenle reddediliyor · geri alma geri getiriyor")
    return 0


def check_rename_column() -> int:
    """Sutun adi (10.7.1) — gecici klasorde sentetik belgeyle, uctan uca.

    Kayit tablosu (iki varyant), anahtarli tablo ve pivot bir arada. Sinanan:
    ad TUM satirlarda degisir, varyant gorunumunden yapilsa bile · tek islem,
    geri al tek adimda hepsini dondurur · varyant kimlikleri degismez ·
    gorunum durumu (sira, genislik, gizlilik, siralama) yeni ada tasinir ve
    geri alininca geri doner · catisan ad ve uygulamanin urettigi sutun
    cevrilmis nedenle reddedilir · pivot sutunu ve pivot ic anahtari (hucre)
    yeniden adlandirilir · kayit dosyada yalnizca anahtar belirteclerini degistirir.
    """
    import tempfile
    from jsonimager import i18n as I18N
    from jsonimager.app import Api
    out = []
    src = {"rows": [{"id": 1, "kind": "a", "v": 1}, {"id": 2, "kind": "a", "v": 2},
                    {"id": 3, "kind": "b", "w": 5}, {"id": 4, "kind": "b", "w": 6}],
           "users": {f"u{i}": {"name": f"n{i}", "age": 30 + i} for i in range(4)},
           "grid": {"cpu": {"warn": 70, "crit": 90, "idle": 5},
                    "mem": {"warn": 75, "crit": 92, "idle": 3}}}
    raw = json.dumps(src, indent=2).encode()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "belge.json"
        p.write_bytes(raw)
        api = Api()
        api._settings = {**api._settings, "documents": {"backup": False}}
        api._load_one(p)
        doc_id = str(p)
        doc = api._docs[doc_id]
        col = lambda ds, key, var=None: [c["key"] for c in api.table(doc_id, ds, var)["table"]["columns"]].index(key)  # noqa: E731
        variants0 = [v.id for d in doc["datasets"] if d.id == "rows" for v in d.variants]

        # 1) Varyant gorunumunden `id` -> `no`: diger varyanttaki satirlar dahil hepsi.
        r = api.rename_column(doc_id, "rows", "rows#v0", col("rows", "id", "rows#v0"), "no")
        if not r.get("ok") or any("no" not in row or "id" in row for row in doc["root"]["rows"]):
            out.append("kayit tablosunda ad tum satirlarda degismedi")
        if [v.id for d in doc["datasets"] if d.id == "rows" for v in d.variants] != variants0:
            out.append("varyant kimlikleri degisti")
        api.undo_edit(doc_id)
        if any("id" not in row for row in doc["root"]["rows"]) or api.edit_state(doc_id)["edit"]["can_undo"]:
            out.append("geri al tek adimda hepsini dondurmedi")

        # 2) Catisan ad: `kind` -> `v` (ilk iki satirda `v` var).
        r = api.rename_column(doc_id, "rows", None, col("rows", "kind"), "v")
        if r.get("ok") or r.get("error") != I18N.t("edit.err_key_exists"):
            out.append("catisan ad reddedilmedi")

        # 3) Anahtarli tablo + gorunum tasimasi.
        view = api.table(doc_id, "users")["view"]
        view.update({"widths": {"age": 123}, "hidden": ["age"], "sort": {"key": "age", "dir": 1}})
        api.set_view(doc_id, "users", None, view)
        api.rename_column(doc_id, "users", None, col("users", "age"), "yas")
        v = api._views[api._key(doc_id, "users", None) + "|N"]
        if any("yas" not in row for row in doc["root"]["users"].values()):
            out.append("anahtarli tabloda ad tum satirlarda degismedi")
        if "yas" not in v["order"] or v["widths"] != {"yas": 123} or v["hidden"] != ["yas"] \
                or v["sort"] != {"key": "yas", "dir": 1}:
            out.append(f"gorunum durumu tasinmadi: {v}")
        # 10.7.2 — isaret: bu tabloda `yas` basligi, baska tabloda hicbir baslik.
        if api.table(doc_id, "users")["table"]["cols_edited"] != ["yas"] \
                or api.table(doc_id, "rows")["table"]["cols_edited"]:
            out.append("sutun adi isareti yanlis")
        api.undo_edit(doc_id)
        if api.table(doc_id, "users")["table"]["cols_edited"]:
            out.append("geri alininca sutun adi isareti kalkmadi")
        v = api._views[api._key(doc_id, "users", None) + "|N"]
        if v["widths"] != {"age": 123} or v["sort"].get("key") != "age":
            out.append("geri alininca gorunum geri donmedi")
        r = api.rename_column(doc_id, "users", None, 0, "x")
        if r.get("ok") or r.get("error") != I18N.t("edit.why_synthetic"):
            out.append("uygulamanin urettigi sutun reddedilmedi")
        # Transpozede alan adi hucresi ayni nedeni tasir (flatten'daki dize
        # `edit_map.WHY_SYNTHETIC` ile ELLE esleniyor; burada kilitli).
        tt = F.build_table(doc["root"], next(d for d in doc["datasets"] if d.id == "users"),
                           None, transpose=True)
        if [row[0].get("x") for row in tt["rows"]] != [EM.WHY_SYNTHETIC, None, None]:
            out.append("transpozede uretilmis sutunun alan adi nedensiz")

        # 10.7.2 — gorunum KIPIYLE yazilir: transpoze acikken gecikmeli gelen
        # normal gorunum N anahtarina gitmeli (once T'ye yazilip tabloyu
        # bosaltiyordu; duzenleme kipindeki siralama gecikmesi pencereyi acti).
        api.set_transpose(doc_id, "users", None, True)
        t_view = api.table(doc_id, "users")["view"]
        n_key = api._key(doc_id, "users", None)
        api.set_view(doc_id, "users", None, {**v, "order": ["_key", "name", "age"]}, False)
        if api._views[n_key + "|T"] is not t_view or api._views[n_key + "|N"]["order"] != ["_key", "name", "age"]:
            out.append("gorunum kipiyle yazilmadi (N gorunumu T anahtarina gitti)")
        api.set_transpose(doc_id, "users", None, False)

        # 4) Pivot: sutun (dis anahtar) ve ic anahtar hucresi.
        api.rename_column(doc_id, "grid", None, col("grid", "cpu"), "islemci")
        if list(doc["root"]["grid"]) != ["islemci", "mem"]:
            out.append("pivot sutunu yeniden adlandirilmadi")
        t = api.table(doc_id, "grid")["table"]
        ri = [row[0]["d"] for row in t["rows"]].index("warn")
        r = api.edit_cell(doc_id, "grid", None, ri, 0, "uyari")
        if not r.get("ok") or any("uyari" not in doc["root"]["grid"][c] for c in ("islemci", "mem")):
            out.append("pivot ic anahtari tum sutunlarda degismedi")
        # Pivot: ic anahtar HUCRE olarak, sutun adi BASLIK olarak isaretlenir.
        t = api.table(doc_id, "grid")["table"]
        ri = [row[0]["d"] for row in t["rows"]].index("uyari")
        if [ri, 0] not in t["edited"] or t["cols_edited"] != ["islemci"]:
            out.append(f"pivot isaretleri yanlis: {t['edited']} {t['cols_edited']}")

        # 5) Kayit: dosyada yalnizca anahtar belirtecleri degisir.
        api.save_doc(doc_id)
        new = p.read_bytes()
        expect = raw.replace(b'"cpu"', b'"islemci"').replace(b'"warn"', b'"uyari"')
        if new != expect:
            out.append("kayit anahtar belirteclerinden fazlasini degistirdi")
    if out:
        for o in out:
            print(f"  ! sutun adi: {o}")
        return len(out)
    print("  sutun adi: tum satirlarda, varyanttan da · tek adimda geri al · varyant kimlikleri "
          "sabit · gorunum tasiniyor ve donuyor · catisan ad ve uretilmis sutun reddi · "
          "pivot sutunu ve ic anahtari · kayit yalnizca anahtar belirtecleri")
    return 0


def check_exit_flow() -> int:
    """Cikis sorusu (10.5.3) — pencere acilmadan, sahte pencereyle.

    `app._on_closing` kapanisi yalnizca kaydedilmemis belge varken ve cikis
    henuz onaylanmamisken iptal etmeli (`False`), soruyu AYRI is parcacigindan
    acmali (UI is parcacigini beklemek kilitlenirdi) ve JS'in cagirdigi
    `askQuit` gercekten var olmali. `quit_app` bayragi koyup pencereyi kapatmali.
    """
    import threading
    from jsonimager import app as APP
    out = []

    class Win:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.thread = ""
            self.done = threading.Event()
            self.destroyed = False

        def evaluate_js(self, code: str) -> None:
            self.calls.append(code)
            self.thread = threading.current_thread().name
            self.done.set()

        def destroy(self) -> None:
            self.destroyed = True

    api = APP.Api()
    win = Win()
    if APP._on_closing(api, win) is not None:
        out.append("belge yokken kapanis iptal edildi")
    api._docs["x"] = {"path": "x", "name": "x.json", "history": EC.History()}
    root = {"a": 1}
    EC.apply(root, api._docs["x"]["history"], EC.set_value_op(root, ["a"], 2))
    if APP._on_closing(api, win) is not False:
        out.append("kaydedilmemis belgeyle kapanis iptal edilmedi")
    if not win.done.wait(2) or win.calls != ["askQuit()"]:
        out.append(f"soru acilmadi: {win.calls}")
    elif win.thread == threading.current_thread().name:
        out.append("soru ayni is parcaciginda acildi (UI kilitlenirdi)")
    if not re.search(r"^async function askQuit\(", (WEB / "js" / "edit.js").read_text(encoding="utf-8"), re.M):
        out.append("askQuit JS'te yok")
    api._window = win
    api.quit_app()
    if not (api._quit_ok and win.destroyed):
        out.append("quit_app bayrak koymadi ya da pencereyi kapatmadi")
    if APP._on_closing(api, Win()) is not None:
        out.append("onaydan sonra kapanis yine iptal edildi")
    src = (ROOT / "src" / "jsonimager" / "app.py").read_text(encoding="utf-8")
    if "window.events.closing += lambda: _on_closing(api, window)" not in src:
        out.append("_on_closing kapanis olayina bagli degil")
    if out:
        for o in out:
            print(f"  ! cikis sorusu: {o}")
        return len(out)
    print("  cikis sorusu: temizken gecer · kirliyken iptal + ayri is parcaciginda askQuit · "
          "onaydan sonra gecer · closing'e bagli")
    return 0


def check_edit_bridge() -> int:
    """Duzenleme koprusu (Faz 10.4) — gecici klasorde sentetik belgeyle uctan uca.

    Sinanan: deger duzenleme ve cevrilmis red iletisi · kok tablosunda bir
    veri kumesinin adini degistirmek o veri kumesinin gorunum durumunu
    (transpoze) yeni kimlige TASIR, geri alma geri tasir · geri al/yinele ve
    kirli durum · agactaki `dirty` · kaydetme dosyada yalnizca degisen
    belirteci degistirir ve ilk kayitta `.bak` yazar (KB-4), ikincide yazmaz ·
    diskte degismis dosya `changed_on_disk` doner, `force` ile yazilir (KB-3).
    Ayar yalnizca BELLEKTE degistirilir.
    """
    import tempfile
    from jsonimager import i18n as I18N
    from jsonimager.app import Api
    out = []
    src = {"title": "x", "count": 3, "flag": True,
           "users": {f"u{i}": {"name": f"n{i}", "age": 30 + i} for i in range(4)}}
    raw = json.dumps(src, indent=2).replace("\n", "\r\n").encode()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "belge.json"
        p.write_bytes(raw)
        api = Api()
        api._settings = {**api._settings, "documents": {"backup": True}}
        if (err := api._load_one(p)):
            print(f"  ! duzenleme koprusu: belge yuklenemedi — {err}")
            return 1
        doc_id = str(p)
        tbl = api.table(doc_id, "users")["table"]
        age = [c["key"] for c in tbl["columns"]].index("age")

        r = api.edit_cell(doc_id, "users", None, 0, age, "99")
        if not r.get("ok") or r["table"]["rows"][0][age]["d"] != "99" or not r["edit"]["dirty"]:
            out.append("deger duzenlenmedi ya da tablo/durum donmedi")
        r = api.edit_cell(doc_id, "users", None, 0, age, "abc")
        if r.get("ok") or r.get("error") != I18N.t("edit.err_not_number"):
            out.append("sayiya harf cevrilmis iletiyle reddedilmedi")
        if not api.tree()["docs"][0]["dirty"]:
            out.append("agacta dirty yok")
        # 9.25 — agac degisen TABLOYU da gosterir; dokunulmayan tablo isaretsiz.
        marks = {d["id"]: d["dirty"] for d in api.tree()["docs"][0]["datasets"]}
        if marks != {"$": False, "users": True}:
            out.append(f"agacta tablo isareti yanlis: {marks}")

        api.set_transpose(doc_id, "users", None, True)
        kv = api.table(doc_id, "$")["table"]
        row = [x[0]["d"] for x in kv["rows"]].index("users")
        r = api.edit_cell(doc_id, "$", None, row, 0, "people")
        ids = [d.id for d in api._docs[doc_id]["datasets"]]
        if not r.get("ok") or "people" not in ids or "users" in ids:
            out.append("veri kumesi adi degismedi")
        # 9.25 — anahtar hucresi YENI adla isaretlenir (eski adla aranip
        # dusuyordu) ve tablosu agacta isaretlenir.
        if [row, 0] not in r.get("table", {}).get("edited", []):
            out.append(f"anahtar hucresi isaretlenmedi: {r.get('table', {}).get('edited')}")
        if not next(d["dirty"] for d in api.tree()["docs"][0]["datasets"] if d["id"] == "$"):
            out.append("anahtari degisen tablo agacta isaretlenmedi")
        if api._key(doc_id, "people", None) not in api._transposed \
                or api._key(doc_id, "users", None) in api._transposed:
            out.append("gorunum durumu yeni kimlige tasinmadi")
        u = api.undo_edit(doc_id)
        if u.get("renamed") != {"people": "users"} \
                or api._key(doc_id, "users", None) not in api._transposed:
            out.append(f"geri alma kimligi/gorunumu geri tasimadi: {u.get('renamed')}")
        api.redo_edit(doc_id)
        api.undo_edit(doc_id)
        api.undo_edit(doc_id)
        st = api.edit_state(doc_id)["edit"]
        if st["dirty"] or st["can_undo"] or not st["can_redo"]:
            out.append(f"hepsi geri alininca durum yanlis: {st}")
        if api.save_doc(doc_id).get("ok") is not True or p.read_bytes() != raw:
            out.append("degisiklik yokken kayit dosyaya dokundu")
        bak = p.with_name("belge.json.bak")
        if bak.exists():
            out.append("degisiklik yokken .bak yazildi")

        api.redo_edit(doc_id)                                 # age 30 -> 99
        s = api.save_doc(doc_id)
        want = raw.replace(b'"age": 30', b'"age": 99')
        if not s.get("ok") or p.read_bytes() != want or bak.read_bytes() != raw:
            out.append("ilk kayit yanlis (yalnizca belirtec + .bak)")
        if api.edit_state(doc_id)["edit"]["dirty"]:
            out.append("kayittan sonra hala kirli")
        api.edit_cell(doc_id, "users", None, 1, age, "7")
        api.save_doc(doc_id)
        if bak.read_bytes() != raw:
            out.append(".bak ikinci kayitta degisti")
        api.edit_cell(doc_id, "users", None, 2, age, "8")
        p.write_bytes(p.read_bytes().replace(b'"title": "x"', b'"title": "y"'))
        s = api.save_doc(doc_id)
        if s.get("ok") or s.get("reason") != JW.ERR_CHANGED \
                or s.get("error") != I18N.t("edit.save_changed_on_disk"):
            out.append(f"diskte degismis dosyaya yazildi ya da neden yanlis: {s.get('reason')}")
        other = p.read_bytes()
        if not api.save_doc(doc_id, force=True).get("ok") or b'"age": 8' not in p.read_bytes():
            out.append("zorla kayit yazmadi")
        # 10.8 — `.bak` bu oturumda ZATEN yazildi: obur programin surumu yine de
        # korunmali (`.conflict.bak`) ve oturumun ozgun hali ezilmemeli. Ilk
        # yazimda bu durumda obur surum yedeksiz eziliyordu.
        conflict = p.with_name("belge.json.conflict.bak")
        if not conflict.exists() or conflict.read_bytes() != other or bak.read_bytes() != raw:
            out.append("zorla yazimda obur programin surumu korunmadi ya da ozgun yedek ezildi")
    if out:
        for o in out:
            print(f"  ! duzenleme koprusu: {o}")
        return len(out)
    print("  duzenleme koprusu: deger + cevrilmis red · tablo adi gorunumu tasiyor, geri al "
          "geri tasiyor · kirli durum ve agac · kayit yalnizca belirtec + ilk .bak · "
          "diskte degisen dosya sorulur, zorla yazilir")
    return 0


def check_json_save() -> int:
    """Diske yazma (Faz 10.3) — gecici klasorde, sentetik belgeyle.

    Belge klasorune dokunulmaz. Sinanan: atomik yazim artik birakmaz · `.bak`
    diskteki hali tutar ve ikinci kayitta istenmezse degismez (KB-4) ·
    diskte degismis belgeye yazilmaz, `force` ile yazilir ve baska programin
    surumu yedeklenir (KB-3) · BOM korunur · red nedenleri.
    """
    import tempfile
    out = []
    raw = '{\r\n  "a": 1,\r\n  "b": "\\u00e7ay",\r\n  "c": [true, 1.50]\r\n}\r\n'.encode()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "belge.json"
        p.write_bytes(raw)
        root = json.loads(raw)
        root["a"] = 2
        data = JW.render(raw, root)
        if data != raw.replace(b'"a": 1', b'"a": 2'):
            out.append(f"yalnizca degisen belirtec yazilmadi: {data!r}")
        JW.save(p, raw, data, backup=True)
        bak = p.with_name("belge.json.bak")
        if p.read_bytes() != data or bak.read_bytes() != raw:
            out.append("ilk kayit ya da .bak yanlis")
        root["a"] = 3
        data2 = JW.render(data, root)
        JW.save(p, data, data2, backup=False)
        if bak.read_bytes() != raw:
            out.append(".bak ikinci kayitta degisti")
        other = data2.replace(b"3", b"9")
        p.write_bytes(other)                       # baska bir program yazdi
        try:
            JW.save(p, data2, data, backup=False)
            out.append("diskte degismis belgeye yazildi")
        except JW.WriteError as e:
            if e.reason != JW.ERR_CHANGED or p.read_bytes() != other:
                out.append("cakisma nedeni ya da dosya yanlis")
        JW.save(p, data2, data, backup=True, force=True)
        if p.read_bytes() != data or bak.read_bytes() != other:
            out.append("zorla yazim ya da baska programin yedegi yanlis")
        # Catisma yedegi: `.bak` istenmiyorsa obur surum `.conflict.bak`a gider
        # ve `.bak`a dokunulmaz; catisma yoksa hic yazilmaz.
        conflict = p.with_name("belge.json.conflict.bak")
        JW.save(p, data, data2, backup=False, conflict_backup=True)
        if conflict.exists():
            out.append("catisma yokken catisma yedegi yazildi")
        p.write_bytes(other)
        JW.save(p, data2, data, backup=False, force=True, conflict_backup=True)
        if not conflict.exists() or conflict.read_bytes() != other or bak.read_bytes() != other:
            out.append("catisma yedegi yanlis ya da .bak'a dokunuldu")
        left = [f.name for f in Path(tmp).iterdir() if f.name.endswith(".tmp")]
        if left:
            out.append(f"gecici dosya kaldi: {left}")

    bom = b"\xef\xbb\xbf" + b'{"x": 1}'
    if JW.render(bom, {"x": 2}) != b"\xef\xbb\xbf" + b'{"x": 2}':
        out.append("BOM korunmadi")
    if JW.render(b'{"x": NaN, "y": 1}', {"x": float("nan"), "y": 2}) != b'{"x": NaN, "y": 2}':
        out.append("NaN iceren belge yazilamadi")
    if JW.render(b'{"k": 1}', {"K": 1}) != b'{"K": 1}':
        out.append("anahtar yeniden adlandirmasi yazilmadi")
    if JW.render(b"[1, true]", [True, 1]) != b"[true, 1]":
        out.append("tur degisimi (1 <-> true) yazilmadi")
    for label, src, new, why in [
        ("kopya anahtar", b'{"a": 1, "a": 2}', {"a": 2}, JW.ERR_DUPLICATE),
        ("sekil", b'{"a": 1}', {"a": 1, "b": 2}, JW.ERR_STRUCTURE),
        ("dizi boyu", b"[1, 2]", [1], JW.ERR_STRUCTURE),
        ("fazladan metin", b'{"a": 1} x', {"a": 1}, JW.ERR_SYNTAX),
        ("kodlama", b'{"a": "\xff"}', {"a": 1}, JW.ERR_ENCODING),
    ]:
        try:
            JW.render(src, new)
            out.append(f"{label}: reddedilmedi")
        except JW.WriteError as e:
            if e.reason != why:
                out.append(f"{label}: neden {e.reason} (beklenen {why})")
    if out:
        for o in out:
            print(f"  ! diske yazma: {o}")
        return len(out)
    print("  diske yazma: yalnizca degisen belirtec · atomik, artik yok · .bak ilk hal (KB-4) · "
          "diskte degismise yazilmaz, zorla yazimda baska surum yedeklenir (KB-3) · BOM · 5 red nedeni")
    return 0


def check_edit_core() -> int:
    """Cekirdegin kurallari (Faz 10.2) — sentetik, belgeden bagimsiz."""
    out = []

    def expect(label: str, fn, want) -> None:
        try:
            got = fn()
        except EC.EditError as e:
            got = f"!{e.reason}"
        if not (EC.same(got, want) if not isinstance(want, str) or not want.startswith("!")
                else got == want):
            out.append(f"{label}: {got!r} != {want!r}")

    P = EC.parse_input
    # KB-2: dolu hucrede tur korunur, bos hucrede JSON gibi yorumlanir.
    for label, fn, want in [
        ("sayi", lambda: P("42", 7), 42), ("ondalik", lambda: P(" 1.5 ", 7), 1.5),
        ("us", lambda: P("1e3", 7.0), 1000.0), ("sayiya harf", lambda: P("12a", 7), "!not_number"),
        ("nan", lambda: P("nan", 7), "!not_number"), ("inf", lambda: P("1e999", 7), "!not_number"),
        ("arti isaret", lambda: P("+1", 7), "!not_number"), ("bas sifir", lambda: P("01", 7), "!not_number"),
        ("mantiksal", lambda: P("False", True), False), ("mantiksala sayi", lambda: P("1", True), "!not_bool"),
        ("metne sayi", lambda: P("12", "a"), "12"), ("metin bosluk", lambda: P(" a ", "b"), " a "),
        ("bosa sayi", lambda: P("12", None), 12), ("bosa true", lambda: P("true", None), True),
        ("bosa null", lambda: P("null", None), None), ("bosa metin", lambda: P("abc", None), "abc"),
    ]:
        expect(label, fn, want)

    if EC.same(True, 1) or EC.same(1, 1.0) or not EC.same(2, 2):
        out.append("same ture duyarli degil")

    root = {"a": {"x": 1, "y": True}, "b": [{"k": "v"}], "c": None}
    h = EC.History()
    expect("bos ad", lambda: EC.rename_op(root, ["a"], "  "), "!empty_key")
    expect("var olan ad", lambda: EC.rename_op(root, ["a"], "b"), "!key_exists")
    expect("dizi ogesi", lambda: EC.rename_op(root, ["b", 0], "z"), "!index_key")
    EC.apply(root, h, EC.rename_op(root, ["a"], "A"))
    EC.apply(root, h, EC.set_value_op(root, ["A", "y"], 1))      # true -> 1 degisikliktir
    if list(root) != ["A", "b", "c"]:
        out.append(f"yeniden adlandirma sirayi bozdu: {list(root)}")
    # `same` ile DEGIL: sinanan islevin kendisiyle olcmek, o bozulunca bu
    # satiri da kor ederdi (duz `==` ile `True == 1` "yazildi" gorunur).
    if type(root["A"]["y"]) is not int:
        out.append("true -> 1 yazilmadi")
    if EC.apply(root, h, EC.set_value_op(root, ["A", "x"], 1)):
        out.append("degismeyen duzenleme yigina girdi")
    EC.mark_saved(h)
    EC.undo(root, h)
    if not EC.dirty(h):
        out.append("kayittan sonra geri alinca kirli degil")
    EC.apply(root, h, EC.set_value_op(root, ["c"], 5))
    if not EC.dirty(h):
        out.append("geri al + yeni islem ayni boyda ama kirli degil")
    while EC.undo(root, h):
        pass
    if json.dumps(root) != json.dumps({"a": {"x": 1, "y": True}, "b": [{"k": "v"}], "c": None}):
        out.append(f"geri alinca ozgun degil: {json.dumps(root)}")

    if out:
        for o in out:
            print(f"  ! duzenleme kurallari: {o}")
        return len(out)
    print("  duzenleme kurallari: tur korunur, bos hucre JSON gibi · JSON sayi dilbilgisi · "
          "esitlik ture duyarli · ad kurallari · sira korunur · kayit isareti kimlikle")
    return 0


def dump_datasets(root, datasets: list[D.Dataset]) -> None:
    """Belgenin veri kumesi dokumu — `--datasets` bayragiyla.

    Yeni bir ornek belge eklendiginde `samples/ANALIZ.md`'ye yazilacak beklenen
    degerler buradan okunur: veri kumesi kimligi, tur, satir x sutun, sutunlarin
    grup ve doluluk bilgisi. Rutin kosuda basilmaz — 81 veri kumeli belgede
    ciktiyi okunmaz hale getirir.
    """
    print(f"  --- {len(datasets)} veri kumesi ---")
    for i, ds in enumerate(datasets, 1):
        line = f"  {i}. {ds.id} · {ds.kind_label} · {ds.row_count}x{ds.col_count}"
        if ds.variants:
            disc = ds.variants[0].discriminator or "?"
            line += f" · varyant[{disc}]: " + ", ".join(
                f"{v.row_count}x{v.col_count}" for v in ds.variants)
        print(line)
        try:
            t = F.build_table(root, ds)
        except Exception:
            continue
        for c in t["columns"]:
            fill = f"{c.get('present', 0)}/{c.get('total', 0)}"
            flags = " SEYREK" if c.get("sparse") else ""
            kind = "" if c["kind"] == F.C_SCALAR else f"/{c['kind']}"
            print(f"       {c['label']} · {c['dtype']}{kind} · {c['group']} · {fill}{flags}")


def check_text(name: str, root, datasets: list[D.Dataset]) -> int:
    """Dort metin ciktisini uretir; hata veya bos cikti basarisizliktir."""
    fail = 0
    sizes: list[str] = []

    # 11.2 — ic ice NESNE `anahtar=deger` olarak yazilir; uygulamanin urettigi
    # "Anahtar/Deger" sutun adlari metne girmez (hucre kopyalama da bu kurali izler).
    probe = {"rows": [{"id": 1, "dim": {"w": 4, "h": 5}}, {"id": 2, "dim": {"w": 6}}]}
    pt = F.build_table(probe, D.discover(probe)[0])
    pk = [c["key"] for c in pt["columns"]].index("dim")
    got = [T.cell_text(r[pk]) for r in pt["rows"]]
    if got != ["w=4, h=5", "w=6"]:
        print(f"  ! ic ice nesne metni: {got}")
        fail += 1

    t0 = time.perf_counter()
    try:
        rep = T.document_markdown(name, root, datasets)
        if not rep.strip():
            print("  ! report: bos cikti")
            fail += 1
        sizes.append(f"rapor {len(rep):,} krk")
    except Exception as exc:
        print(f"  ! report: {type(exc).__name__}: {exc}")
        fail += 1

    try:
        out = T.outline(name, root)
        if not out.strip():
            print("  ! outline: bos cikti")
            fail += 1
        sizes.append(f"anahat {len(out):,} krk")
    except Exception as exc:
        print(f"  ! outline: {type(exc).__name__}: {exc}")
        fail += 1

    if datasets:
        ds = max(datasets, key=lambda d: d.row_count * d.col_count)
        try:
            table = F.build_table(root, ds)
            md = T.table_markdown(table)
            csv_out = T.table_csv(table)
            # Basliklar + her satir icin bir satir olmali.
            want = len(table["rows"]) + 1
            got = len([r for r in csv_out.strip().split("\n") if r])
            if got < want:
                print(f"  ! csv: {got} satir, beklenen >= {want}")
                fail += 1
            if not md.startswith("|"):
                print("  ! table: Markdown tablo basligi yok")
                fail += 1

            # HTML (K-18): tek dosya, gomulu CSS, DIS ISTEK YOK. Metin
            # secilebilir olmali — yani gercek <td>'ler, gomulu SVG degil.
            html = T.table_html(table, title=ds.id, source=name)
            if html.count("<td") < len(table["rows"]):
                print(f"  ! html: {html.count('<td')} hucre, "
                      f"beklenen >= {len(table['rows'])}")
                fail += 1
            # Aranan sey HUCRE METNI degil, dosyanin KENDI disariya acilmasi:
            # veri icinde URL gecmesi normaldir (kacisli metin, baglanti degil).
            for leak in ("<script", "<link", "<iframe", "src=", "@import"):
                if leak in html:
                    print(f"  ! html: dis kaynak yukleyen etiket var — {leak}")
                    fail += 1
            if "&lt;" not in _esc_probe(T, table, name):
                print("  ! html: kacis (escape) uygulanmiyor")
                fail += 1

            # Acik satir: ekranda acilan satir HTML'de de acik gelmeli
            # (`9.11`). Ic ice hucresi olan bir satir varsa `<details>` yazilir
            # ve YALNIZCA acik olan `open` alir.
            nested = [i for i, r in enumerate(table["rows"])
                      if any(c and c.get("sub") for c in r)]
            if nested:
                closed = T.table_html(table, title=ds.id, source=name)
                opened = T.table_html(table, title=ds.id, source=name,
                                      expanded={nested[0]})
                if "<details>" not in closed or "<details open>" in closed:
                    print("  ! html: acik satir yokken `open` durumu yanlis")
                    fail += 1
                if opened.count("<details open>") != 1:
                    print(f"  ! html: bir satir acikken {opened.count('<details open>')} "
                          f"`<details open>` var, beklenen 1")
                    fail += 1
                # Ic tablo GERCEK olmali: duzlestirilmis metin degil.
                if "<table class=\"sub\">" not in opened:
                    print("  ! html: ic ice hucre gercek bir ic tablo degil")
                    fail += 1

                # CIZIM de acik satiri gostermeli (`9.11.3`): ayrinti blogu
                # sahneyi buyutur ve ic tablonun basliklari sahneye girer.
                view = {"order": [c["key"] for c in table["columns"]],
                        "hidden": [], "widths": {}, "groups": False}
                sc_closed = ITB.table_scene(table, view, None, None)
                sc_open = ITB.table_scene(table, view, None, None,
                                          expanded={nested[0]})
                if sc_open.h <= sc_closed.h:
                    print(f"  ! cizim: acik satir sahneyi buyutmuyor "
                          f"({sc_open.h} <= {sc_closed.h})")
                    fail += 1
                sub_labels = {c["label"] for c in
                              next(c["sub"] for c in table["rows"][nested[0]]
                                   if c and c.get("sub"))["columns"]}
                drawn = {it["s"] for it in sc_open.items if it["t"] == "text"}
                if not (sub_labels & drawn):
                    print("  ! cizim: ic tablonun basliklari sahnede yok")
                    fail += 1

            sizes.append(f"tablo {len(md):,} krk · csv {len(csv_out):,} krk "
                         f"· html {len(html):,} krk")
        except Exception as exc:
            print(f"  ! table/csv/html ({ds.id}): {type(exc).__name__}: {exc}")
            fail += 1

    print(f"  metin: {' · '.join(sizes)} ({time.perf_counter() - t0:.3f}s)")
    return fail


def _esc_probe(T, table: dict, name: str) -> str:
    """HTML kacisini sinamak icin tabloya `<b>` iceren bir satir ekler.

    Kacis calismazsa hucre metni HTML olarak yorumlanir; bu, paylasilan bir
    dosyada script calistirmaya kadar gider.
    """
    probe = {"columns": table["columns"],
             "rows": [[{"k": F.C_SCALAR, "d": "<b>x</b>"}] * len(table["columns"])],
             "kind_label": table.get("kind_label", "")}
    return T.table_html(probe, title=name)


def check_schema(root, datasets: list[D.Dataset]) -> int:
    """Sema ciktisinda hucre degeri bulunmadigini dogrular.

    Alan ADLARI gonderilir, DEGERLER gonderilmez. Test: her tablodan birkac
    skaler hucre degeri toplanip sema metninde aranir; bulunursa sizinti vardir.
    """
    fail = 0
    payload = SCHEMA.document_schema("belge", root, datasets)
    text = SCHEMA.schema_markdown(payload)

    # Ad sayilan her sey haric tutulur: sutun etiketleri ve veri kumesi yolunun
    # parcalari. Anahtar-Deger tablolarinda `Anahtar` sutununun DEGERLERI aslinda
    # JSON alan adlaridir (`restrictivenessRank` gibi) — bunlar sizinti degildir.
    names: set[str] = set()
    for ds in datasets:
        names.update(c["label"] for c in F.build_table(root, ds)["columns"])
        for part in ds.id.replace("[", ".").replace("]", "").split("."):
            if part:
                names.add(part)

    # Belirtec bazli eslesme: `temperature`, `temperature_pressure` ADININ
    # icinde alt dize olarak gecer; bu sizinti degildir. Sema metni kelimelere
    # ayrilip TAM eslesme aranir.
    tokens = set(re.split(r"[^\w-]+", text))

    leaked: list[str] = []
    checked = 0
    for ds in datasets:
        t = F.build_table(root, ds)
        for row in t["rows"][:20]:
            for cell in row:
                if not cell or cell.get("k") != F.C_SCALAR:
                    continue
                val = (cell.get("d") or "").strip()
                # Kisa/sayisal degerler tesadufen eslesebilir; ayirt edici
                # uzunluktaki metin degerleri sinanir.
                if len(val) < 8 or val in names:
                    continue
                checked += 1
                hit = (val in text) if " " in val else (val in tokens)
                if hit:
                    leaked.append(val[:40])
    if leaked:
        print(f"  ! sema sizintisi: {len(leaked)} deger sema metninde bulundu — {leaked[:3]}")
        fail += 1

    # 9.26 — uygulamanin urettigi sutunlar semada isaretli ve metinde bildirilir.
    # Beklenti TURDEN gelir, sutun anahtarindan degil: gercek bir alan `_key`
    # adini tasiyabilir. Bildirimsiz model "Anahtar/Deger"i alan adi saniyordu.
    want_made = {D.KEYVALUE: "all", D.KEYLIST: "all", D.KEYED: "first", D.PIVOT: "first",
                 D.RECORDS: "none"}
    note = SCHEMA.I18N.t("schema.synthetic", names="\0").split("\0")[0]
    bad_made = []
    for ds, entry in zip(datasets, payload["datasets"]):
        flags = [c["synthetic"] for c in entry["columns"]]
        rule = want_made.get(ds.kind)
        expect = {"all": [True] * len(flags), "none": [False] * len(flags),
                  "first": [True] + [False] * (len(flags) - 1)}.get(rule, flags)
        if flags and flags != expect:
            bad_made.append(f"{ds.id} ({ds.kind}): {flags}")
    if any(c["synthetic"] for e in payload["datasets"] for c in e["columns"]) != (note in text):
        bad_made.append("uretilmis sutun bildirimi metinde yok ya da gereksiz")
    if bad_made:
        print(f"  ! sema uretilmis sutun: {bad_made[:3]}")
        fail += 1

    fail += check_prompt_history(payload)

    print(f"  sema: {len(text):,} krk · {checked} deger sinandi · sizinti yok"
          if not leaked else f"  sema: {len(text):,} krk")
    return fail


# 9.7.1 — public depoya cikacak icerik (`K-25`). 9.8'de `make_public.py` bu
# listeyi ICE AKTARIR; ikinci bir liste yazilmaz, iki liste zamanla sapar.
# Henuz olmayan dosyalar (README, LICENSE…) sessizce atlanir — olusturulduklari
# an denetime girerler.
#
# ⚠ 9.8.1: liste yalnizca YAYIMLANACAK degil, public agacin CALISMASI icin
# gereken dosyalari da tasimali. `assets/icon.ico` (`build.spec` okuyor) ve
# `tools/make_icon.py` (`check_logo` ice aktariyor) eksikti — izin listesi yasak
# listesinin tersine EKSIK yonde yanilir ve bu ancak agacin kendisinde gorunur.
PUBLIC_SCOPE = (
    "src/**/*", "examples/**/*", "assets/icon.ico", "licenses/*",
    "tools/check.py", "tools/devserver.py", "tools/make_examples.py", "tools/make_icon.py",
    "tools/make_notices.py",
    # 9.14.5: `devserver.py` sunuyor, `check_web` kapsamini okuyor.
    "tools/layout_matrix.html", "tools/layout_matrix.js",
    # 9.9.1: `build.spec` ice aktariyor, `check_version_info` sinaniyor.
    "tools/version_info.py",
    "run.py", "build.spec", "requirements.txt", ".gitignore", ".gitattributes",
    "README.md", "README.tr.md", "docs/ARCHITECTURE.md", "LICENSE", "THIRD-PARTY-NOTICES.md",
    "SECURITY.md", "CHANGELOG.md",
    # 9.10.2: README'lerin gosterdigi ekran goruntuleri — yalnizca ornek belgeler
    # (gizlilik denetimi resmi okuyamaz; kural elle uygulandi).
    "docs/screenshots/*.jpg",
)
# Metin olarak taranan uzantilar; `""` uzantisiz dosyalar icin (LICENSE, .gitignore).
PRIVACY_TEXT = {".py", ".js", ".html", ".css", ".json", ".md", ".txt", ".spec", ""}

# Ic surec belgeleri: public depoda YOKLAR, bu yuzden public icerik onlari anmaz.
# Tek kaynak — `SECURITY.md` denetimi de buradan desen kurar. Buyuk/kucuk harf
# duyarli: public mimari notu `docs/ARCHITECTURE.md` ic belgeyle karismaz.
INTERNAL_DOCS = (
    "PROJECT.md", "CLAUDE.md", "architecture.md", "ui-guide.md", "theming.md",
    "output-pipeline.md", "verification.md", "project-memory-bank.md",
)
# Tireli adlar uzantisiz da yakalanir; tek kelimelik adlar (`verification`,
# `theming`) duz metinde kelime olarak gecer, onlarda uzanti sart. `#` ile baslayan
# baslik capasi gonderme degil: 9.8.4'te "Output pipeline" basliginin `#output-pipeline`
# capasi ic belge sanildi.
INTERNAL_DOC_RE = re.compile(r"(?<![\w#-])(?:" + "|".join(
    re.escape(n.removesuffix(".md")) + (r"(?:\.md)?" if "-" in n else r"\.md")
    for n in INTERNAL_DOCS) + r")(?![\w-])")


def scope_files(root: Path, scope: tuple[str, ...] = PUBLIC_SCOPE) -> set[str]:
    """`root` altinda kapsama uyan dosyalar, goreli POSIX yol. Yalnizca okur.

    Hem bu depoda hem uretilen public agacta ayni sekilde calisir — `make_public.py`
    eski dosyayi bununla bulur, `check_public_tree` fazla dosyayi bununla.
    """
    found: set[str] = set()
    for pattern in scope:
        for p in root.glob(pattern):
            rel = p.relative_to(root)
            if p.is_file() and "__pycache__" not in rel.parts:
                found.add(rel.as_posix())
    return found


def in_scope(rel: str, scope: tuple[str, ...] = PUBLIC_SCOPE) -> bool:
    """Goreli POSIX yol kapsama uyuyor mu — diske bakmadan.

    `scope_files` diskteki dosyayi bulur; bu ise git'in bildirdigi SILINMIS bir
    dosyanin da kapsamda olup olmadigini soyler (kirli agac tespiti).
    """
    from pathlib import PurePosixPath

    p = PurePosixPath(rel)
    return "__pycache__" not in p.parts and any(p.full_match(s) for s in scope)


def public_targets() -> list[Path]:
    """Public kapsamdaki metin dosyalari (henuz olmayanlar sessizce yok)."""
    return sorted(ROOT / r for r in scope_files(ROOT) if Path(r).suffix in PRIVACY_TEXT)


# `.gitignore`un bu kapinin anladigi alt kumesi: `ad/` (klasor), `*.uzanti` ya da
# `ad` (her duzeyde), `!ad` (geri alma), son eslesen kazanir. Kok capasi (`/ad`),
# ara egik cizgi ve `**` ANLASILMAZ — sessizce yanlis yorumlamak yerine kapi
# kirmizi yanar; boylece `.gitignore`a yeni bir bicim girince kural ile kapi sapmaz.
def ignore_rules(text: str) -> tuple[list[tuple[bool, str, bool]], list[str]]:
    """(geri_alma, desen, yalnizca_klasor) listesi ve anlasilmayan satirlar."""
    rules: list[tuple[bool, str, bool]] = []
    unsupported: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        pat = line[1:] if neg else line
        dir_only = pat.endswith("/")
        pat = pat.rstrip("/")
        if not pat or "/" in pat or "**" in pat:
            unsupported.append(line)
            continue
        rules.append((neg, pat, dir_only))
    return rules, unsupported


def is_ignored(rel: str, rules: list[tuple[bool, str, bool]]) -> bool:
    """Goreli POSIX yol `.gitignore` alt kumesine gore yok sayiliyor mu."""
    import fnmatch

    parts = rel.split("/")
    hit = False
    for neg, pat, dir_only in rules:
        pool = parts[:-1] if dir_only else parts
        if any(fnmatch.fnmatchcase(p, pat) for p in pool):
            hit = not neg
    return hit


def tree_files(root: Path, rules: list[tuple[bool, str, bool]]) -> set[str]:
    """`root` altindaki, `.git` ve yok sayilanlar disindaki dosyalar. Yalnizca okur.

    Yok sayilan klasore INILMEZ: public agacta kullanicinin `.venv`i binlerce dosya.
    """
    import os

    out: set[str] = set()
    for cur, dirs, files in os.walk(root):
        base = Path(cur).relative_to(root).as_posix()
        prefix = "" if base == "." else base + "/"
        dirs[:] = [d for d in dirs
                   if d != ".git" and not is_ignored(prefix + d + "/_", rules)]
        out.update(prefix + f for f in files if not is_ignored(prefix + f, rules))
    return out


def privacy_targets() -> list[Path]:
    """Gizlilik denetiminin taradigi dosyalar: kok belgeler + public kapsam."""
    return sorted({*(p for p in ROOT.glob("*.md") if p.is_file()), *public_targets()})


def check_public_refs() -> int:
    """Public kapsamdaki hicbir dosya ic surec belgesini anmiyor mu.

    9.8.1 acilis olcumu: 13 yer (kaynakta yedi, araclarda alti). Public depoda
    bu belgeler olmadigi icin gonderme okuyucuyu var olmayan dosyaya yollar.
    `K-NN` / `Faz N` kimlikleri bu denetimin konusu DEGIL: cevresindeki cumle
    kurali zaten anlatiyor. Yalnizca belge ADI aranir.
    """
    own = ROOT / "tools" / "check.py"
    # Demetin kendi tanimi bu dosyada; gonderme degil tanim, taramadan cikar.
    defn = re.compile(r"^INTERNAL_DOCS = \(.*?^\)\n", re.M | re.S)
    hits: list[str] = []
    targets = public_targets()
    for p in targets:
        text = p.read_text(encoding="utf-8", errors="replace")
        if p == own:
            text = defn.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        for n, line in enumerate(text.splitlines(), 1):
            if m := INTERNAL_DOC_RE.search(line):
                hits.append(f"{p.relative_to(ROOT).as_posix()}:{n} {m.group(0)}")
    if hits:
        print(f"  ! public icerik ic belgeye gonderme yapiyor ({len(hits)}): {', '.join(hits[:6])}")
        return 1
    print(f"  public gonderme: {len(targets)} dosya · ic belge adi yok")
    return 0


def check_architecture_doc() -> int:
    """`docs/ARCHITECTURE.md`: public mimari notu kodla ve kurallarla ayni kaliyor mu (9.8.4).

      - ic surece gonderme yok (faz, karar kimligi, ic belge adi) — `SECURITY.md` ile ayni desen
      - Ingilizce: Turkce harf yok (`K-29`)
      - ters tirnakli her `ad.py` / `ad.js` gercekten var
      - HER Python modulu ve HER arayuz dosyasi anilmis: modul eklenince not eskimesin
      - goreli baglantilar var olan dosyaya gidiyor
    """
    doc_path = ROOT / "docs" / "ARCHITECTURE.md"
    if not doc_path.is_file():
        print("  ! docs/ARCHITECTURE.md yok")
        return 1
    doc = doc_path.read_text(encoding="utf-8")
    fail = 0

    internal = sorted(set(re.findall(r"\bFaz\b|\bA?K-\d+\b|\[D-\d+\]|\b9\.\d+|ANALIZ|samples/", doc))
                      | {m.group(0) for m in INTERNAL_DOC_RE.finditer(doc)})
    if internal:
        print(f"  ! ARCHITECTURE.md ic surece gonderme yapiyor: {', '.join(internal)}")
        fail += 1
    if turkish := sorted(set(re.findall(r"[çğıöşüÇĞİÖŞÜ]", doc))):
        print(f"  ! ARCHITECTURE.md Ingilizce degil — Turkce harf: {''.join(turkish)}")
        fail += 1

    pkg = ROOT / "src" / "jsonimager"
    existing = {p.name for p in (*pkg.glob("*.py"), *(pkg / "web" / "js").glob("*.js"),
                                 *(ROOT / "tools").glob("*.py"))}
    named = set(re.findall(r"`(?:[\w./]*/)?([\w-]+\.(?:py|js))`", doc))
    if ghosts := sorted(named - existing):
        print(f"  ! ARCHITECTURE.md var olmayan dosya aniyor: {', '.join(ghosts)}")
        fail += 1
    required = {p.name for p in pkg.glob("*.py") if p.name != "__init__.py"}
    required |= {p.name for p in (pkg / "web" / "js").glob("*.js")}
    if missing := sorted(required - named):
        print(f"  ! ARCHITECTURE.md modulu anmiyor: {', '.join(missing)}")
        fail += 1

    links = re.findall(r"\]\((?!https?:|#)([^)#]+)(?:#[^)]*)?\)", doc)
    if broken := sorted({ln for ln in links if not (doc_path.parent / ln).resolve().is_file()}):
        print(f"  ! ARCHITECTURE.md kirik baglanti: {', '.join(broken)}")
        fail += 1

    if not fail:
        print(f"  mimari notu: {len(required)} modul/dosya anildi · {len(links)} baglanti gecerli"
              " · ic gonderme ve Turkce yok")
    return fail


def check_public_tree() -> int:
    """Public agacta izin listesi disinda dosya kalmadi mi (`K-25`).

    Iki kip, isaret ic belgelerin varligi:
      - public agac: diskteki her dosya (`.git` ve `.gitignore`un yok saydiklari
        haric) `PUBLIC_SCOPE`a uymali. Elle eklenen ya da eski bir surumden kalan
        dosya burada yakalanir.
      - ozel depo: fazla dosya burada tasarim geregi; bunun yerine ureticinin
        (`make_public.py`) saf parcalari sinanir. Uretici public agaca GIRMEZ.

    Gercek agac ici kosu (`make_public.py` sonunda agacin kendi `check.py`si) burada
    tekrarlanmaz: tam dogrulama ~75 s, ic ice kosu her rutin dogrulamayi ikiye katlardi.
    """
    fail = 0
    gi = ROOT / ".gitignore"
    rules, unsupported = ignore_rules(gi.read_text(encoding="utf-8")) if gi.is_file() else ([], [])
    if unsupported:
        print(f"  ! .gitignore: kapinin anlamadigi desen — {', '.join(unsupported)}")
        fail += 1

    if any((ROOT / n).is_file() for n in INTERNAL_DOCS):
        return fail + _probe_make_public(rules)

    files = tree_files(ROOT, rules)
    extra = sorted(r for r in files if not in_scope(r))
    if extra:
        print(f"  ! public agacta izin listesi disinda dosya ({len(extra)}): {', '.join(extra[:6])}")
        return fail + 1
    if not fail:
        print(f"  public agac: {len(files)} dosya · hepsi izin listesinde")
    return fail


def _probe_make_public(rules: list[tuple[bool, str, bool]]) -> int:
    """`make_public.py`nin saf parcalari: yorum, kapsam, secim, hedef korumasi, esitleme."""
    import tempfile

    if not (ROOT / "tools" / "make_public.py").is_file():
        print("  ! tools/make_public.py yok")
        return 1
    import make_public as MP

    fail = 0

    def bad(msg: str) -> None:
        nonlocal fail
        print(f"  ! make_public: {msg}")
        fail += 1

    # 1) `.gitignore` yorumu — bu deponun GERCEK dosyasiyla; public agaca o kopyalaniyor.
    expect = {".venv/Lib/x.py": True, "src/jsonimager/__pycache__/a.pyc": True,
              "build.spec": False, "foo.spec": True, "samples/x.json": True,
              "dist/JSON Imager.exe": True, "LICENSE": False, "src/jsonimager/web/index.html": False}
    if wrong := [k for k, v in expect.items() if is_ignored(k, rules) != v]:
        bad(f".gitignore yanlis yorumlaniyor — {wrong}")
    if ignore_rules("/kok\na/b\n**/x\nnot/\n")[1] != ["/kok", "a/b", "**/x"]:
        bad("anlasilmayan desen sessizce kabul edildi")

    # 2) Kapsam: uretici ve ic belgeler disarida; calisma icin gereken dosyalar icerde.
    if outside := [n for n in ("tools/make_public.py", *INTERNAL_DOCS, "samples/a.json",
                               "assets/icon-variants.png") if in_scope(n)]:
        bad(f"kapsamda olmamasi gereken — {outside}")
    if missing := [n for n in ("assets/icon.ico", "tools/make_icon.py", "src/jsonimager/web/js/a.js",
                               ".gitattributes", "LICENSE") if not in_scope(n)]:
        bad(f"kapsamda olmasi gereken — {missing}")

    # 3) Secim: izlenmeyen dosya yalnizca `--allow-dirty` ile gelir; degisen ya da
    #    izlenmeyen kapsam dosyasi kirli sayilir, kapsam disi olan sayilmaz.
    tracked = ["src/a.py", INTERNAL_DOCS[0], "tools/make_public.py"]
    untracked = ["LICENSE", "notes.txt"]
    got = MP.select_files(tracked, untracked, ["src/a.py", INTERNAL_DOCS[0]], allow_dirty=False)
    if got != (["src/a.py"], ["LICENSE", "src/a.py"]):
        bad(f"secim yanlis — {got}")
    if MP.select_files(tracked, untracked, [], allow_dirty=True)[0] != ["LICENSE", "src/a.py"]:
        bad("--allow-dirty izlenmeyen kapsam dosyasini almiyor")

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        prev = t / "prev"
        for rel, body in {"repo/src/a.py": "yeni", "repo/.gitignore": ".venv/\n",
                          "prev/src/a.py": "eski", "prev/src/old.py": "x",
                          "prev/tools/check.py": "x", "prev/notes.txt": "x",
                          "prev/.git/HEAD": "x", "prev/.venv/x.py": "x",
                          "foreign/belge.txt": "x", "gitonly/.git/HEAD": "x"}.items():
            (t / rel).parent.mkdir(parents=True, exist_ok=True)
            (t / rel).write_text(body, encoding="utf-8")

        # 4) Hedef korumasi: depo icinde, depoyu iceren ve yabanci dolu klasor reddedilir.
        cases = {repo: True, repo / "out": True, t: True, t / "foreign": True,
                 t / "empty": False, prev: False, t / "gitonly": False}
        if wrong := [p.name for p, refuse in cases.items()
                     if (MP.refuse_target(repo, p) is not None) != refuse]:
            bad(f"hedef korumasi yanlis — {wrong}")

        # 5) Esitleme: eski kapsam dosyasi raporlanir, yalnizca `--prune` ile silinir;
        #    kapsam disi dosyaya, `.git`e ve yok sayilan klasore hic dokunulmaz.
        files = ["src/a.py", ".gitignore"]
        rep = MP.sync(files, repo, prev, prune=False)
        if (rep["updated"], rep["new"], rep["stale"], rep["outside"]) != (
                ["src/a.py"], [".gitignore"], ["src/old.py", "tools/check.py"], ["notes.txt"]):
            bad(f"esitleme raporu yanlis — {rep}")
        if not (prev / "src" / "old.py").is_file():
            bad("--prune olmadan dosya silindi")
        rep = MP.sync(files, repo, prev, prune=True)
        if (prev / "src" / "old.py").exists() or (prev / "tools").exists():
            bad("--prune eski dosyayi ya da bosalan klasoru silmedi")
        if not all((prev / r).is_file() for r in ("notes.txt", ".git/HEAD", ".venv/x.py")):
            bad("--prune kapsam disina, .git'e ya da yok sayilan klasore dokundu")
        if rep["same"] != 2 or (prev / "src" / "a.py").read_text(encoding="utf-8") != "yeni":
            bad("ikinci esitleme ayni dosyayi yeniden yazdi ya da icerik eski")

        # 6) Public kip: agacta izin disi dosya yakalanir, yok sayilan klasor sayilmaz.
        extra = sorted(r for r in tree_files(prev, ignore_rules(".venv/\n")[0]) if not in_scope(r))
        if extra != ["notes.txt"]:
            bad(f"public agac taramasi yanlis — {extra}")

    if not fail:
        print("  make_public: gitignore yorumu · kapsam · secim · hedef korumasi"
              " · esitleme ve --prune · izin disi dosya")
    return fail


def check_security() -> int:
    """Tehdit modelinin (`SECURITY.md`) denetimsiz kalan sinirlari ve belgenin kendisi.

    9.7.3 acilis olcumu: dort sinir belgelerde yaziliydi ama hicbir denetime bagli
    degildi — CSP, `innerHTML` yoklugu, ag kodunun iki modulde kalmasi, SVG kacisi.
    Bir sinir denetlenmezse ilk "kucuk" degisiklikte sessizce delinir.

    Belge de denetlenir: her satiri bir denetim adi tasimali, o ad bu dosyada
    gercekten tanimli olmali ve belge ic surece gonderme yapmamali — public'e
    cikiyor, faz numarasi ve karar kimligi orada anlamsiz.
    """
    import xml.etree.ElementTree as ET

    fail = 0
    pkg = ROOT / "src" / "jsonimager"

    # 1) Ag ve surec: yalnizca iki modul aga cikar, yalnizca biri surec baslatir.
    # `urllib.parse` ayristirmadir, aga cikmaz — desende yok.
    net = re.compile(r"^\s*(?:import|from)\s+(urllib\.request|urllib\.error|http\.client"
                     r"|socket|ssl|requests|httpx|aiohttp|websockets?)\b", re.M)
    spawn = re.compile(r"^\s*(?:import|from)\s+subprocess\b", re.M)
    net_modules = {"providers.py", "remote_images.py"}
    for p in sorted(pkg.rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        hits = sorted({m.group(1) for m in net.finditer(text)})
        if hits and p.name not in net_modules:
            print(f"  ! ag kodu izinli iki modulun disinda: {p.name} — {', '.join(hits)}")
            fail += 1
        if spawn.search(text) and p.name != "providers.py":
            print(f"  ! surec baslatan kod beklenmeyen modulde: {p.name}")
            fail += 1
        if "shell=True" in text:
            print(f"  ! kabuk uzerinden surec: {p.name}")
            fail += 1

    # 2) CSP: sayfa kendi basina aga cikamaz, satir ici betik calismaz.
    html = (WEB / "index.html").read_text(encoding="utf-8")
    m = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    if m is None:
        print("  ! index.html'de CSP yok")
        fail += 1
    else:
        csp = {parts[0]: parts[1:] for parts in
               (d.split() for d in m.group(1).split(";")) if parts}
        wrong = []
        if csp.get("default-src") != ["'none'"]:
            wrong.append("default-src 'none' degil")
        if csp.get("script-src") != ["'self'"]:
            wrong.append("script-src yalnizca 'self' degil")
        if "connect-src" in csp:
            wrong.append("connect-src tanimli (sayfa aga cikabilir)")
        for name, values in csp.items():
            loose = [v for v in values if v in {"'unsafe-inline'", "'unsafe-eval'", "*"}
                     or v.startswith("http")]
            if loose:
                wrong.append(f"{name}: {' '.join(loose)}")
        if wrong:
            print(f"  ! CSP gevsemis: {' · '.join(wrong)}")
            fail += 1

    # 3) Belge metni ekrana ISARETLEME olarak girmez. Yorumlarda `innerHTML` kelimesi
    # geciyor ("innerHTML yok"); desen yalnizca KULLANIMI arar (nokta, cagri).
    sink = re.compile(r"\.(?:innerHTML|outerHTML)\b|insertAdjacentHTML\s*\(|document\.write\s*\("
                      r"|\beval\s*\(|\bnew\s+Function\s*\(")
    for p in sorted((WEB / "js").glob("*.js")):
        hits = sorted(set(sink.findall(p.read_text(encoding="utf-8"))))
        if hits:
            print(f"  ! {p.name}: metni isaretleme olarak ekleyen cagri — {', '.join(hits)}")
            fail += 1
    markup = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    handlers = sorted(set(re.findall(r"<[^>]*?\s(on[a-z]+)\s*=", markup)))
    if handlers:
        print(f"  ! index.html'de satir ici olay ozniteligi: {', '.join(handlers)}")
        fail += 1

    # 4) SVG: belgeden gelen metin, ipucu ve adres kacislanir; ciktida yeni oge dogmaz.
    hostile = '</text><script>alert(1)</script><text>'
    sc = VEC.Scene(100, 40)
    sc.text(0, 10, hostile)
    sc.rect(0, 0, 10, 10, hover='"><script>x</script>')
    sc.image(0, 0, 10, 10, 'data:image/png;base64,AAAA"><script>y</script>', hover=hostile)
    try:
        tree = ET.fromstring(VEC.to_svg(sc))
        tags = {el.tag.rsplit("}", 1)[-1] for el in tree.iter()}
        texts = [el.text or "" for el in tree.iter() if el.tag.rsplit("}", 1)[-1] == "text"]
        if "script" in tags or hostile not in texts:
            print("  ! svg: belge metni kacislanmadan yaziliyor (yeni oge dogdu)")
            fail += 1
    except ET.ParseError as exc:
        print(f"  ! svg: kacislama cikti XML'ini bozuyor — {exc}")
        fail += 1

    # 5) SECURITY.md: her sinir satiri gercek bir denetime bagli, ic gonderme yok.
    sec = ROOT / "SECURITY.md"
    rows: list[str] = []
    if not sec.is_file():
        print("  ! SECURITY.md yok")
        fail += 1
    else:
        doc = sec.read_text(encoding="utf-8")
        own = (ROOT / "tools" / "check.py").read_text(encoding="utf-8")
        named = set(re.findall(r"`(_?check_\w+)`", doc))
        ghosts = sorted(n for n in named if not re.search(rf"^def {n}\(", own, re.M))
        if ghosts:
            print(f"  ! SECURITY.md var olmayan denetime gonderme yapiyor: {', '.join(ghosts)}")
            fail += 1
        rows = [line for line in doc.splitlines()
                if line.startswith("|") and not re.fullmatch(r"\|[\s|:-]+", line)][1:]
        unchecked = [r.split("|")[1].strip() for r in rows if not re.search(r"`_?check_\w+`", r)]
        if unchecked:
            print(f"  ! SECURITY.md'de denetime bagli olmayan sinir: {', '.join(unchecked)}")
            fail += 1
        internal = sorted(set(re.findall(
            r"\bFaz\b|\bA?K-\d+\b|\b9\.\d+|ANALIZ|samples/", doc))
            | {m.group(0) for m in INTERNAL_DOC_RE.finditer(doc)})
        if internal:
            print(f"  ! SECURITY.md ic surece gonderme yapiyor: {', '.join(internal)}")
            fail += 1

    if not fail:
        print(f"  guvenlik: ag kodu 2 modulde · CSP siki · isaretleme ekleyen cagri yok · svg kacisli"
              f" · SECURITY.md {len(rows)} sinir, hepsi denetime bagli")
    return fail


def check_doc_privacy() -> int:
    """Izlenen belgelere ve public'e cikacak KODA ozel ad sizmadigini dogrular (`K-09`).

    `samples/` git ile izlenmez; oradaki belgelerin adlari ve alan adlari izlenen
    hicbir dosyaya kopyalanmamalidir — izlenen dosyalar yalnizca yapisal bilgi
    tasir, ad yerine ROL yazar.

    Iki ad kaynagi:
      - `ANALIZ.md` icinde ters tirnak icinde gecen tanimlayicilar (alan adlari)
      - `samples/*.json` dosya adlari — uzantisiyla, cunku kok ad genel bir kelime
        olabilir (`base64`)

    ⚠ `9.7.1`e kadar yalnizca kok `.md` dosyalari taraniyordu. Kod hic
    gorulmedigi icin yedi sizinti yorumlarda duruyordu: iki dosya adi, bir veri
    kumesi yolu, alan adlari ve bir `<sutun> = <deger>` cifti — ucu dosya adi
    oldugu icin eski ad kaynagi onlari kapsami genis olsa da yakalayamazdi.
    """
    analysis = SAMPLES / "ANALIZ.md"

    # Bu terimler her projede gecer; ozel ad sayilmaz. `meta`, `config`, `stats`
    # gibi kelimeler hem veri kumesi adi hem kod terimi olabiliyor (`Scene.meta`) —
    # kod bagalminda kacinilmaz olduklari icin haric tutuluyorlar.
    generic = {"enum", "type", "list", "dict", "true", "false", "float", "null",
               "int", "str", "bool", "json", "data", "name", "value", "text",
               "index", "key", "keys", "count", "items", "path", "size",
               "meta", "config", "stats", "info", "label", "title", "notes",
               # 9.7.1 — KOD da taraninca olculen yanlis alarmlar: genel kod
               # kelimeleri (`exc.reason` urllib niteligi, `scope`/`activation`
               # kategori ipucu listesi) ve `ANALIZ.md`nin andigi kendi sabitimiz.
               "values", "default", "scope", "reason", "activation",
               "min_visible_cols",
               # 9.8.3.1 — `importlib.metadata` dagitim niteligi (`dist.requires`).
               "requires",
               # `K-29` — public belgeler INGILIZCE; alan adlarinin cogu Ingilizce
               # kelime oldugu icin duz metinde cakisma artacak. Olculen: `SECURITY.md`
               # "same rule". README ve mimari notu yazildikca olcup buraya eklenir.
               "rule"}

    fields: set[str] = set()
    if analysis.is_file():
        fields = {a for a in re.findall(r"`([A-Za-z_][A-Za-z0-9_]{3,})`",
                                        analysis.read_text(encoding="utf-8"))
                  if a.lower() not in generic}
    files = {p.name for p in SAMPLES.glob("*.json")}
    names = fields | files
    if not names:
        return 0     # bos alternasyon her yerde eslesirdi

    fail = 0
    # Tek tek sayilmaz, desenle toplanir: belge ya da modul eklendikce yeni dosya
    # sessizce denetim disinda kalirdi (kok belgeler Faz 9'da ikiden sekize cikti).
    docs = privacy_targets()

    # ⚠ Ad basina bir arama DEGIL, tek bir birlesik desen: belge sayisi 2'den
    # 8'e cikinca ad×belge carpimi 344 tam gecise ulasmisti (97 ms → 4 ms).
    # Sinir `\b`den daha SIKI: tire ve alt cizgi de bitisiklik sayilir. Yoksa
    # `default-src` (CSP yonergesi) icindeki `default`, ayni adi tasiyan bir
    # alan yuzunden sizinti sanilir. Gercek bir sizinti adi cıplak ya da
    # `<sutun> = <deger>` biciminde yazar; daha uzun bir tanimlayicinin
    # PARCASI olarak degil.
    pat = re.compile(r"(?<![\w-])(?:"
                     + "|".join(re.escape(a) for a in sorted(names))
                     + r")(?![\w-])")
    for p in docs:
        leaked = sorted(set(pat.findall(p.read_text(encoding="utf-8", errors="ignore"))))
        if leaked:
            print(f"  ! {p.relative_to(ROOT).as_posix()}: ozel ad sizmis — {', '.join(leaked[:8])}")
            fail += 1
    if not fail:
        print(f"  gizlilik: {len(fields)} alan + {len(files)} dosya adi sinandi · "
              f"{len(docs)} dosyada yok (belgeler + public kapsam)")
    return fail


def check_prompt_history(payload: dict) -> int:
    """Sohbet gecmisinin isteme dogru islendigini dogrular (Faz 6.5).

    Serit bir sohbet penceresidir ama `claude -p` her cagrida sifirdan baslar:
    sureklilik yalnizca gecmisin isteme yazilmasiyla saglanir. Uc kural:
    gecmissiz istem gecmis bolumu ACMAZ, tasinan tur sayisi sinirlidir ve
    uzun yanitlar kirpilir.
    """
    fail = 0
    plain = SCHEMA.build_prompt(payload, "soru")
    if "daha önce konuşulanlar" in plain:
        print("  ! bos gecmiste istem gecmis bolumu aciyor")
        fail += 1

    turns = [(f"eski soru {i}", f"eski yanit {i}") for i in range(SCHEMA.HISTORY_TURNS + 2)]
    withh = SCHEMA.build_prompt(payload, "yeni soru", turns)
    carried = sum(1 for i in range(len(turns)) if f"eski soru {i}" in withh)
    if carried != SCHEMA.HISTORY_TURNS:
        print(f"  ! gecmis siniri tutmadi: {carried} tur tasindi, "
              f"beklenen {SCHEMA.HISTORY_TURNS}")
        fail += 1
    if "yeni soru" not in withh:
        print("  ! yeni soru isteme girmemis")
        fail += 1

    long_answer = "x" * (SCHEMA.HISTORY_ANSWER_CHARS + 500)
    clipped = SCHEMA.build_prompt(payload, "soru", [("q", long_answer)])
    if long_answer in clipped or "[…]" not in clipped:
        print("  ! uzun yanit gecmiste kirpilmamis")
        fail += 1
    return fail


def check_wrap(root, datasets: list[D.Dataset]) -> int:
    """Sarilan sutunun cizimde de sarildigini dogrular (Faz 7.3, `AK-10`).

    Ekranda `td.cell-wrap` metni alt satirlara yayar; sahne modeli de ayni
    sutunlari sarmali, yoksa PNG/PDF ekrandan farkli cikar. Olcut: sarilan
    sutun GORUNURKEN sahne, gizliyken uretilenden daha YUKSEK olmali.
    """
    fail = 0
    for ds in datasets:
        try:
            table = F.build_table(root, ds)
        except Exception:
            continue

        # `wrap` isareti "bir satira sigmayabilir" demek; sutun genisligi 420 px
        # oldugu icin bazi metinler yine tek satira siğar. Yukseklik artisi
        # yalnizca GERCEKTEN cok satira bolunen sutunlarda beklenir.
        multi = []
        for c in table["columns"]:
            if not c.get("wrap"):
                continue
            i = table["columns"].index(c)
            w = ITB.auto_width(c, table["rows"], i) - ITB.CELL_PAD * 2
            longest = max((r[i].get("d") or "") for r in table["rows"]
                          if i < len(r) and r[i]) if table["rows"] else ""
            if len(ITB._wrap_lines(longest, TH.metrics().font, w)) > 1:
                multi.append(c)

        if not multi or not table["rows"]:
            continue

        keys = [c["key"] for c in table["columns"]]
        shown = {"order": keys, "hidden": [], "widths": {}, "groups": False}
        collapsed = {"order": keys, "hidden": [c["key"] for c in multi],
                     "widths": {}, "groups": False}

        h_shown = ITB.table_scene(table, shown, None, None).h
        h_collapsed = ITB.table_scene(table, collapsed, None, None).h
        if h_shown <= h_collapsed:
            print(f"  ! {ds.id}: sarilan sutun cizimde satiri buyutmuyor "
                  f"({h_shown} <= {h_collapsed})")
            fail += 1

    # Satir sayisi sinirli olmali: tek hucre sahneyi on binlerce piksel yapmasin.
    if len(ITB._wrap_lines("kelime " * 400, TH.metrics().font, 200)) > ITB.WRAP_MAX_LINES:
        print("  ! sarma satir siniri (WRAP_MAX_LINES) uygulanmiyor")
        fail += 1
    return fail


def check_chart_roles(root, datasets: list[D.Dataset]) -> int:
    """Grafik sutun rollerini ve onerileri dogrular (Faz 7.4).

    Eski arayuz tum skaler sutunlari kategori olarak sunuyordu; serbest metin
    de listeye giriyor ve anlamsiz grafikler cikiyordu. Uc kural:
    kirilim listesine METIN/UZUN METIN girmez, kardinalite sinirlari tutar,
    ve oneriler ureten kod belgeye ozel varsayim yapmaz.
    """
    fail = 0
    for ds in datasets:
        try:
            table = F.build_table(root, ds)
        except Exception:
            continue
        if not table["rows"]:
            continue

        roles = CD.chart_roles(table)
        by_key = {c["key"]: c for c in table["columns"]}

        for c in roles["breakdown"]:
            col = by_key[c["key"]]
            if col.get("wrap") or col["kind"] != F.C_SCALAR:
                print(f"  ! {ds.id}: uzun/skaler olmayan sutun kirilimda — {c['label']}")
                fail += 1
            if not CD.BREAKDOWN_MIN <= c["uniq"] <= CD.BREAKDOWN_MAX:
                print(f"  ! {ds.id}: kirilim kardinalitesi disarida — "
                      f"{c['label']} ({c['uniq']})")
                fail += 1

        for c in roles["measure"]:
            if not by_key[c["key"]].get("numeric"):
                print(f"  ! {ds.id}: sayisal olmayan sutun olcude — {c['label']}")
                fail += 1

        # Uygun sutun varsa arac kendi sorusunu kurabilmeli. Oneriler MODA GORE
        # ayri listelerdedir; arayuz secili modunkini gosterir.
        cards = CD.chart_suggestions(table)
        if (roles["breakdown"] or roles["measure"]) and not cards["distribution"]:
            print(f"  ! {ds.id}: uygun sutun var ama dagilim onerisi uretilmedi")
            fail += 1
        if roles["breakdown"] and roles["measure"] and not cards["compare"]:
            print(f"  ! {ds.id}: kirilim+olcu var ama karsilastirma onerisi yok")
            fail += 1

        for mode, group in cards.items():
            for s in group:
                if s["mode"] != mode:
                    print(f"  ! {ds.id}: '{mode}' listesinde '{s['mode']}' karti")
                    fail += 1
                if not s["cat"] and not s["numeric"]:
                    print(f"  ! {ds.id}: bos oneri karti")
                    fail += 1
                if mode == "compare" and not (s["cat"] and s["numeric"]):
                    print(f"  ! {ds.id}: karsilastirma karti eksik sutun tasiyor")
                    fail += 1

        # Kullaniciya sunulan olcumler: `count` disarida (Dagilim modunun isi),
        # hepsi `AGGS` icinde tanimli olmali ve `_aggregate` calistirabilmeli.
        if "count" in CD.COMPARE_AGGS:
            print("  ! COMPARE_AGGS icinde 'count' var — Dagilim modunun kopyasi")
            fail += 1
        if roles["breakdown"] and roles["measure"]:
            ck, mk = roles["breakdown"][0]["key"], roles["measure"][0]["key"]
            for agg in CD.COMPARE_AGGS:
                if agg not in CD.AGGS:
                    print(f"  ! olcum AGGS icinde tanimli degil: {agg}")
                    fail += 1
                    continue
                try:
                    CD._aggregate(table, ck, mk, agg, None)
                except Exception as exc:
                    print(f"  ! {ds.id}: '{agg}' olcumu calismadi — {exc}")
                    fail += 1

        # Tek sayisal sutun: kucuk tabloda her kayit bir cubuk, buyukte kova.
        if roles["measure"]:
            key = roles["measure"][0]["key"]
            data, st, unit = CD.numeric_distribution(table, key, None)
            expected = (CD.UNIT_ROWS if st["rows"] <= CD.ROW_BAR_LIMIT
                        else CD.UNIT_BINS)
            if unit != expected:
                print(f"  ! {ds.id}: {st['rows']} satirda '{unit}' modu, "
                      f"beklenen '{expected}'")
                fail += 1
            if unit == CD.UNIT_BINS and len(data) > CD.HIST_BINS:
                print(f"  ! {ds.id}: histogram {len(data)} kova, "
                      f"sinir {CD.HIST_BINS}")
                fail += 1
    return fail


def check_images(name: str, root, datasets: list[D.Dataset]) -> int:
    """Uc gorsel ciktiyi uretir ve makul boyutta oldugunu dogrular."""
    import io
    import warnings

    from PIL import Image

    fail = 0
    notes: list[str] = []
    t0 = time.perf_counter()

    def shape(png: bytes) -> tuple[int, int]:
        # ⚠ Olculen gorsel BIZIM urettigimiz: bomba uyarisi burada anlamsiz.
        # Genis bir tablo 104 MP'ye cikabiliyor ve uyari her rutin kosunun
        # basina dusuyordu — sessiz kip artik sessiz degildi (`T-3`). Boyut
        # sinirini asagidaki kapilar zaten olcuyor.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(png))
        return im.width, im.height

    # Agac: sahne + dort bicim (PNG/SVG/PDF/.drawio) uretilebilmeli.
    try:
        sc, tnodes, tedges = ITR.tree_scene(name, root)
        dx = VEC.to_drawio(tnodes, tedges, name)
        if dx.count('vertex="1"') != len(tnodes) or dx.count('edge="1"') != len(tedges):
            print("  ! drawio: dugum/kenar sayisi tutmuyor")
            fail += 1
        if not VEC.to_pdf(sc).startswith(b"%PDF-"):
            print("  ! agac pdf: gecersiz")
            fail += 1
        notes.append(f"drawio {len(tnodes)}d/{len(tedges)}k")
    except Exception as exc:
        print(f"  ! agac vektor: {type(exc).__name__}: {exc}")
        fail += 1

    try:
        w, h = shape(ITR.render_tree(name, root))
        if h > 40000 or w > 20000:
            print(f"  ! agac gorseli asiri buyuk: {w}x{h}")
            fail += 1
        notes.append(f"agac {w}x{h}")
    except Exception as exc:
        print(f"  ! agac: {type(exc).__name__}: {exc}")
        fail += 1

    if datasets:
        ds = max(datasets, key=lambda d: d.row_count * d.col_count)
        try:
            table = F.build_table(root, ds)
            w, h = shape(ITB.render_table(table, title=ds.label))
            if h > 40000 or w > 20000:
                print(f"  ! tablo gorseli asiri buyuk: {w}x{h}")
                fail += 1
            notes.append(f"tablo {w}x{h}")
            # Tablo da sahneden uretiliyor: SVG ve PDF calismali.
            tsc = ITB.table_scene(table, title=ds.label)
            if "<svg" not in VEC.to_svg(tsc) or not VEC.to_pdf(tsc).startswith(b"%PDF-"):
                print(f"  ! tablo vektor ({ds.id}): gecersiz")
                fail += 1
        except Exception as exc:
            print(f"  ! tablo gorseli ({ds.id}): {type(exc).__name__}: {exc}")
            fail += 1

        # Grafik icin kategorik + sayisal sutun ciftini kendisi bulur.
        drawn = 0
        for d_ in datasets:
            t = F.build_table(root, d_)
            num = next((c["key"] for c in t["columns"] if c.get("numeric")), None)
            cat = next((c["key"] for c in t["columns"]
                        if not c.get("numeric") and c["kind"] == F.C_SCALAR), None)
            if not (num and cat):
                continue
            # "Adet" olcumu sayisal sutun GEREKTIRMEZ; kategori dagilimi sayilir.
            try:
                cnt, st = CD._aggregate(t, cat, None, "count", None)
                if st["rows"] != len(t["rows"]) or sum(v for _, v in cnt) != st["total"]:
                    print(f"  ! adet olcumu ({d_.id}): satir/toplam tutmuyor")
                    fail += 1
            except Exception as exc:
                print(f"  ! adet olcumu ({d_.id}): {type(exc).__name__}: {exc}")
                fail += 1

            try:
                for chart in ("bar", "pie", "line"):
                    shape(ICH.render_chart(t, cat, num, chart))
                    # Ayni sahne SVG ve PDF'e de basilabilmeli (K-12).
                    sc = ICH.chart_scene(t, cat, num, chart)
                    svg = VEC.to_svg(sc)
                    pdf = VEC.to_pdf(sc, "kontrol")
                    if "<svg" not in svg or 'data-tip=' not in svg:
                        print(f"  ! svg ({d_.id}/{chart}): etkilesimli oge yok")
                        fail += 1
                    if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-12:]:
                        print(f"  ! pdf ({d_.id}/{chart}): gecersiz yapi")
                        fail += 1
                drawn += 1
            except Exception as exc:
                print(f"  ! grafik ({d_.id}): {type(exc).__name__}: {exc}")
                fail += 1
            if drawn >= 3:
                break
        notes.append(f"{drawn} veri kumesinde 3'er grafik")

    print(f"  gorsel: {' · '.join(notes)} ({time.perf_counter() - t0:.2f}s)")
    return fail


def check_claude(path: Path) -> int:
    """`claude -p` yolunu uctan uca dener — Api.claude_ask uzerinden.

    Yalnizca `--claude` bayragiyla calisir: gercek bir Claude cagrisi yapar ve
    token harcar, bu yuzden rutin dogrulamanin parcasi degildir.
    """
    from jsonimager.app import Api          # noqa: PLC0415 — yalnizca bu testte

    print(f"\n=== Claude uctan uca ({path.name}) ===")
    api = Api()
    err = api._load_one(path)
    if err:
        print(f"  ! belge yuklenemedi: {err}")
        return 1

    st = api.agent_status()
    if not st.get("available"):
        print(f"  ! {st.get('error')}")
        return 1
    print(f"  claude bulundu: {st['path']}")

    t0 = time.perf_counter()
    res = api.agent_ask(str(path),
                         "Tek cümlede: bu şemadaki en büyük veri kümesi hangisi?")
    dt = time.perf_counter() - t0

    if not res.get("ok"):
        print(f"  ! {res.get('error', '')[:300]}")
        return 1

    answer = (res.get("answer") or "").strip()
    print(f"  gonderilen {res['sent_chars']:,} krk · {dt:.1f}s · yanit {len(answer)} krk")
    print(f"  yanit: {answer[:200]}")
    if not answer:
        print("  ! bos yanit")
        return 1
    return 0


# --- Arayuz denetimleri (Faz 8.5) ------------------------------------------
#
# Bu uc kontrol belgeye degil KAYNAGA bakar; samples/ bos olsa da calisirlar.

WEB = ROOT / "src" / "jsonimager" / "web"

# Ayni olcu iki calisma zamaninda ayri ayri yaziliyor: tarayicidaki JS Python
# sabitini okuyamaz (ES modulu yok, `file://` var — bkz. K-21). Tek kaynak
# yerine ZORUNLU ESLESME kuruldu; sapma buradan yakalanir.
# (js_adi, python_modulu, python_adi)
CONST_PAIRS = [
    ("MIN_W", "img_table", "MIN_W"),
    ("MAX_W", "img_table", "MAX_W"),
    # `CHAR_W` artik boyuttan turuyor (`theme.metrics`), yani sabit degil.
    # Eslesen sey TURETIMIN girdileri: iki taraf ayni tamsayi aritmetigini
    # uygulamak zorunda (`boyut * CHAR_W_BASE // SIZE_BASE`).
    ("CHAR_W_BASE", "theme", "CHAR_W_BASE"),
    ("SIZE_BASE", "theme", "SIZE_BASE"),
    ("BADGE_CHAR_W", "theme", "BADGE_CHAR_W_BASE"),
    ("PAD_X", "img_table", "PAD_X"),
    ("TEXT_COL_W", "flatten", "TEXT_COL_W"),
    ("TEXT_MAX_LINES", "flatten", "TEXT_MAX_LINES"),
    # 9.15 — tablodaki adres onizlemesi dosya onizlemesiyle AYNI kenarda istenir;
    # ayrisirsa ayni sutunda iki ayri boyutta gorsel durur.
    ("TABLE_THUMB_PX", "images", "THUMB_PX"),
]

# JS sabiti <-> CSS olcusu. (js_adi, css_secici, css_ozellik)
CSS_PAIRS = [
    ("COMPOSER_MAX_H", "#cdock-q", "max-height"),
    ("DOCK_MIN_W", ".cdock", "width"),
    # 9.14.4 `fitLayout` esikleri bunlardan hesaplanir.
    ("SIDE_W", "#side", "width"),
    ("RAIL_W", ":root", "--rail-w"),
]

PY_MODULES = {"img_table": ITB, "flatten": F, "theme": TH, "images": F.IM}

# Boyut ayarina TASINMIS ciziciler: bunlar `draw`in taban punto sabitlerini
# (`FONT_SIZE`, `TITLE_SIZE`, `SMALL_SIZE`, `TITLE_H`) ICE AKTARMAMALI,
# olculeri `theme.metrics()`ten okumali. Goc `9.4.5.2`de bitti ve sabitler
# `draw`dan silindi — liste artik tam: adlardan biri geri gelirse hem burada
# hem ice aktarmada yakalanir.
SIZED_MODULES = ("img_table", "img_tree", "img_chart")
LEGACY_SIZES = ("FONT_SIZE", "TITLE_SIZE", "SMALL_SIZE", "TITLE_H")

CSS_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# Adi kaynakta DUZ DIZGE olarak gecmeyen siniflar — birlestirilerek kuruluyor.
# `g-3` icin JS'te yalnizca `'gcell g-' + ORDER_GROUPS.indexOf(g)` vardir.
# Yeni bir dinamik sinif eklenirse buraya da yazilmali, yoksa olu sanilir.
CSS_DYNAMIC = re.compile(r"^g-\d+$")


@functools.cache
def _css_rules(css: str) -> list[tuple[str, str]]:
    """(secici, govde) ciftleri. Yorumlar ONCE atilir: aciklama blogu seciciyle
    ayni yakalamaya giriyor ve `#cdock-q` gibi bir ad `/* ... */\n#cdock-q`
    olarak okunup hicbir seye esitlenemiyordu.

    Onbellekli: tek koşuda 13 kez cagriliyor (tema, yazi tipi, olcu ve olu
    sinif denetimleri) ve her cagri 69 KB'lik dosyayi bastan ayristiriyordu.
    """
    return CSS_BLOCK.findall(CSS_COMMENT.sub("", css))


def _js_sources() -> dict[Path, str]:
    """web/*.js ve web/js/*.js — bolunmeden once de sonra da ayni denetim."""
    files = sorted(WEB.glob("*.js")) + sorted((WEB / "js").glob("*.js"))
    return {p: p.read_text(encoding="utf-8") for p in files}


def _js_decls(text: str) -> list[str]:
    """Ust duzey `function` / `const` / `let` adlari (girintili olanlar ic kapsam)."""
    names: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^(?:async\s+)?function\s+(\w+)", line)
        if m:
            names.append(m.group(1))
            continue
        m = re.match(r"^(?:const|let)\s+(\w+)", line)
        if m:
            names.append(m.group(1))
            names += re.findall(r",\s*(\w+)\s*=", line)   # `const A = 1, B = 2;`
    return names


def _js_numbers(blob: str) -> dict[str, int]:
    """Ust duzey sayisal sabitler: ad -> deger."""
    out: dict[str, int] = {}
    for line in blob.splitlines():
        if not re.match(r"^(?:const|let)\s", line):
            continue
        for name, val in re.findall(r"(\w+)\s*=\s*(\d+)", line):
            out.setdefault(name, int(val))
    return out


def _css_px(css: str, selector: str, prop: str) -> int | None:
    """Bir seciciye yazilmis piksel olcusu. `width` ararken `min-width`e
    takilmamak icin ozellik adinin soluna bakilir."""
    pat = re.compile(rf"(?<![-\w]){re.escape(prop)}\s*:\s*(\d+)px")
    for sel, body in _css_rules(css):
        if selector in (s.strip() for s in sel.split(",")):
            m = pat.search(body)
            if m:
                return int(m.group(1))
    return None


def _overlay_bounds(css: str, html: str) -> list[str]:
    """Kaplamanin dogrudan cocugu olan her panel yukseklikce SINIRLI mi.

    `.overlay` sabit konumlu ve cocugunu ortaliyor; cocuk kaplamadan uzunsa
    tasma IKI UCTAN kesilir ve kaplama kaydirilsa da ust kisma ulasilamaz.
    9.14.1 olcumu: sinirsiz `.tpanel.dlg` 1366x700'de Ayarlar'in basligini ve
    `Kapat`ini ekran disina itiyordu. Sinir: `max-height` ya da `height` icinde
    `100%` (kaplamanin ic kutusu). Sinirli bir `.dlg` panelinde govde kaymali,
    yoksa sinir icerigi kirpar.

    Kurallar dosya sirasiyla birlestirilir; bilesik secici (`.tpanel.dlg`) basit
    seciciden sonra yazildigi icin sira burada ozgulluge denk dusuyor.
    """
    out = []
    rules = _css_rules(css)
    kids = set(re.findall(r'class="overlay"[^>]*>\s*<div class="([^"]+)"', html))
    for combo in sorted(kids):
        classes = set(combo.split())
        decl: dict[str, str] = {}
        for sel, body in rules:
            parts = [s.strip() for s in sel.split(",")]
            if any(re.fullmatch(r"(?:\.[\w-]+)+", s) and set(s[1:].split(".")) <= classes
                   for s in parts):
                decl.update((k, v.strip()) for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body))
        if "100%" not in decl.get("max-height", "") and "100%" not in decl.get("height", ""):
            out.append(f".{'.'.join(sorted(classes))} yukseklikce sinirsiz")
    if any("dlg" in k.split() for k in kids):
        body = " ".join(b for s, b in rules if s.strip() == ".dlg-body")
        if not re.search(r"overflow(?:-y)?\s*:\s*(auto|scroll)", body):
            out.append(".dlg-body kaymiyor")
    return out


# En kucuk pencere (9.14.3). `min_size` mantiksal piksel ve CERCEVE DAHIL
# (pywebview WinForms `MinimumSize`); icerik bu kadar daha kucuk kalir.
WINDOW_FRAME = (16, 39)
# Hedef kucuk ekran: %150 olcekli 1366x768'in calisma alani (gorev cubugu 48).
TARGET_WORK_AREA = (910, 464)


def _window_min(app_src: str, css: str, js_nums: dict[str, int], blob: str) -> list[str]:
    """`app.py`deki en kucuk pencere iki uctan sinirli mi.

    Ust: hedef ekranin calisma alanina sigmali — 9.14.3 oncesi 960x580 o
    ekrana hic sigmiyordu, pencere gorev cubugunun altina tasiyordu.
    Alt: icerik alani en genis sabit pencereyi (Ayarlar + dar kaplama
    boslugu) ve Agent seridi kapaliyken kenar cubugu + `MAIN_MIN_W`yi tasimali.
    Olculer CSS/JS'ten okunur; biri buyurse bu kapi kirmizi yanar.
    """
    m = re.search(r"^WINDOW_MIN_W, WINDOW_MIN_H = (\d+), (\d+)$", app_src, re.M)
    if not m:
        return ["app.py'de WINDOW_MIN_W, WINDOW_MIN_H yok"]
    if "min_size=(WINDOW_MIN_W, WINDOW_MIN_H)" not in app_src:
        return ["create_window en kucuk boyutu sabitlerden okumuyor"]
    w, h = int(m.group(1)), int(m.group(2))
    out = []
    if w > TARGET_WORK_AREA[0] or h > TARGET_WORK_AREA[1]:
        out.append(f"{w}x{h} hedef ekrana sigmiyor ({TARGET_WORK_AREA[0]}x{TARGET_WORK_AREA[1]})")
    inner = w - WINDOW_FRAME[0]
    dlg = re.search(r"\.tpanel\.dlg\.settings-dlg\s*\{[^}]*width:\s*min\((\d+)px", css)
    pad = re.search(r"@media \(max-height: (\d+)px\) \{ \.overlay \{ padding: (\d+)px", css)
    side = _css_px(css, "#side", "width")
    if not (dlg and pad and side and "MAIN_MIN_W" in js_nums):
        return out + ["olcu okunamadi (Ayarlar genisligi, kaplama boslugu, #side, MAIN_MIN_W)"]
    if h - WINDOW_FRAME[1] > int(pad.group(1)):
        out.append(f"en kucuk yukseklikte dar kaplama boslugu gecerli degil (> {pad.group(1)} px)")
    need = int(dlg.group(1)) + 2 * int(pad.group(2))
    if inner < need:
        out.append(f"icerik {inner} px < Ayarlar {need} px")
    if inner < side + js_nums["MAIN_MIN_W"]:
        out.append(f"icerik {inner} px < kenar cubugu + ana alan {side + js_nums['MAIN_MIN_W']} px")
    # 9.14.4.2: soru kutusu seridin bir payiyla sinirli. Pay en kucuk
    # yukseklikte `COMPOSER_MAX_H`in ALTINDA kalmali (yoksa sinir hic devreye
    # girmez, kutu 220'ye buyuyup sohbeti ~48 px'e indirir) ve yarimi gecmemeli.
    share = re.search(r"^const COMPOSER_MAX_SHARE = ([\d.]+);", blob, re.M)
    if not share:
        out.append("COMPOSER_MAX_SHARE JS'te yok")
    else:
        s, inner_h = float(share.group(1)), h - WINDOW_FRAME[1]
        if not (0 < s <= 0.5) or inner_h * s >= js_nums["COMPOSER_MAX_H"]:
            out.append(f"soru kutusu payi {s}: en kucuk yukseklikte {inner_h * s:.0f} px "
                       f"(sinir {js_nums['COMPOSER_MAX_H']}, pay en fazla 0.5)")
    return out


def _matrix_cover(app_src: str, html: str) -> list[str]:
    """Yerlesim matrisi (9.14.5, `tools/layout_matrix.js`) guncel mi.

    Matris tarayicida kosar, bu kapi onu CALISTIRAMAZ; kapsamini denetler:
    en kucuk pencerenin icerik boyutu SIZES'ta, index.html'deki her kaplama
    OVERLAYS'te olmali. Yeni bir pencere eklenip matrise yazilmazsa ya da en
    kucuk boyut degisip matris eski boyutu olcmeye devam ederse kirmizi.
    """
    path = ROOT / "tools" / "layout_matrix.js"
    if not path.is_file():
        return ["tools/layout_matrix.js yok"]
    src = path.read_text(encoding="utf-8")
    out = []
    m = re.search(r"^WINDOW_MIN_W, WINDOW_MIN_H = (\d+), (\d+)$", app_src, re.M)
    if m:
        w, h = int(m.group(1)) - WINDOW_FRAME[0], int(m.group(2)) - WINDOW_FRAME[1]
        sizes = {(int(a), int(b)) for a, b in re.findall(r"^\s*\[(\d+), (\d+), '", src, re.M)}
        if (w, h) not in sizes:
            out.append(f"en kucuk icerik {w}x{h} SIZES'ta yok")
    block = re.search(r"^const OVERLAYS = \{(.*?)^\};", src, re.M | re.S)
    keys = set(re.findall(r"^  '([\w-]+-overlay)':", block.group(1), re.M)) if block else set()
    for name in sorted(set(re.findall(r'id="([\w-]+-overlay)"', html)) - keys):
        out.append(f"{name} OVERLAYS'te yok")
    for name in sorted(keys - set(re.findall(r'id="([\w-]+-overlay)"', html))):
        out.append(f"{name} index.html'de yok")
    return out


def _tab_pairs(html: str) -> list[str]:
    """`role="tab"` ↔ `role="tabpanel"` esleri ve baslangic gorunurlugu."""
    def attrs(tag: str) -> dict[str, str]:
        return dict(re.findall(r'([\w-]+)="([^"]*)"', tag)) | (
            {"hidden": ""} if re.search(r"\shidden[\s>]", tag) else {})

    tags = re.findall(r"<(?:button|section|div|nav)\b[^>]*>", html)
    tabs = [attrs(t) for t in tags if 'role="tab"' in t]
    panels = {a.get("id"): a for a in (attrs(t) for t in tags if 'role="tabpanel"' in t)}
    out = []
    for tab in tabs:
        tid, pid = tab.get("id", "?"), tab.get("aria-controls")
        panel = panels.get(pid)
        if panel is None:
            out.append(f"{tid} → olmayan panel {pid}")
            continue
        if panel.get("aria-labelledby") != tid:
            out.append(f"{pid} sekmesine donmuyor")
        selected = tab.get("aria-selected") == "true"
        if selected == ("hidden" in panel):
            out.append(f"{pid} baslangic gorunurlugu secimle celisiyor")
    if (ghost := set(panels) - {t.get("aria-controls") for t in tabs}):
        out.append(f"sekmesiz panel: {', '.join(sorted(ghost))}")
    return out


def _center_scroll_traps(css: str) -> list[str]:
    """Kaydirilabilir bir flex kapsayicida duz `justify-content: center`.

    Ortalanmis bir flex ogesi kapsayicidan genis oldugunda tasmanin YARISI
    kaydirma baslangicinin soluna duser ve oraya ulasilamaz: `scrollLeft`
    negatif olamaz. Yakinlastirilmis cizimde solda kalan sutunlar kalici olarak
    gorunmez kalir (`#svg-wrap`, olculdu: %400'de 49 px). Cozum `safe center` —
    icerik tasar tasmaz hizalama `start`a duser.

    Denetim ucunu de arar: kaydirma · flex · korumasiz `center`. Kaydirilamayan
    kapsayicinin (`.overlay`) tuzagi AYRIDIR — orada cocugun sinirli olmasi
    gerekir, bkz. `_overlay_bounds` (9.14.1).
    """
    out = []
    for sel, body in _css_rules(css):
        if not re.search(r"overflow(?:-x)?\s*:\s*(auto|scroll)", body):
            continue
        if not re.search(r"display\s*:\s*(inline-)?flex", body):
            continue
        if re.search(r"justify-content\s*:\s*center", body):
            out.append(sel.strip().replace("\n", " "))
    return out


def _hidden_leaks(css: str, html: str) -> list[str]:
    """`hidden` niteligi tasiyan ama `display` verilmis ogeler.

    `display` yazilan bir seciciye `[hidden] { display: none }` esligi
    yazilmazsa tarayicinin varsayilan gizlemesi EZILIR ve oge her zaman
    gorunur (`.tpanel-sub` tuzagi).
    """
    styled: set[str] = set()             # display verilmis basit seciciler
    guards: list[set[str]] = []          # [hidden] kurallarinin bilesenleri

    for sel, body in _css_rules(css):
        if not re.search(r"(?<![-\w])display\s*:", body):
            continue
        for part in (s.strip() for s in sel.split(",")):
            if part.endswith("[hidden]"):
                # Bilesik secici de gecerli bir koruma: `.sub-note.agg-note
                # [hidden]` ustteki `.sub-note`u ozgullukle yener. Bu yuzden
                # koruma tek bir ad degil, BILESEN KUMESI olarak tutulur.
                head = part[: -len("[hidden]")]
                if " " in head or not re.fullmatch(r"(?:[#.][\w-]+)+", head):
                    continue                     # torun secici — degerlendirilmez
                if re.search(r"display\s*:\s*none", body):
                    guards.append(set(re.findall(r"[#.][\w-]+", head)))
            elif re.fullmatch(r"[#.][\w-]+", part):
                styled.add(part)

    leaks = []
    for tag, before, after in re.findall(r"<(\w+)([^>]*?)\shidden([^>]*)>", html):
        attrs = before + after
        ids = re.findall(r'id="([^"]+)"', attrs)
        classes = [c for g in re.findall(r'class="([^"]+)"', attrs) for c in g.split()]
        keys = {f"#{i}" for i in ids} | {f".{c}" for c in classes}
        if any(g <= keys for g in guards):
            continue                             # oge korunuyor
        risky = sorted(keys & styled)
        if risky:
            leaks.append(f"<{tag} {ids[0] if ids else classes[0]}> → {', '.join(risky)}")
    return leaks


def check_web() -> int:
    """Arayuz kaynagi: olu kod, olcu sapmasi, [hidden] kacagi."""
    fail = 0
    sources = _js_sources()
    if not sources:
        print("  ! web/ altinda JS bulunamadi")
        return 1

    blob = "\n".join(sources.values())
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")

    # 1. Olu kod — tanimlanip hicbir yerde kullanilmayan ad.
    #    ⚠ Bazi JS islevlerini PYTHON cagirir (`evaluate_js("askQuit()")`,
    #    10.5.3): JS'te tek geciyorlar ama olu degiller. Python kaynaginda dize
    #    icinde `ad(` bicimiyle gecen adlar kullanilmis sayilir.
    py_calls = set(re.findall(
        r"[\"'](\w+)\(", "\n".join(p.read_text(encoding="utf-8")
                                   for p in sorted((ROOT / "src").rglob("*.py")))))
    dead = []
    for path, text in sources.items():
        for name in _js_decls(text):
            if len(re.findall(rf"\b{re.escape(name)}\b", blob)) <= 1 and name not in py_calls:
                dead.append(f"{path.name}:{name}")
    if dead:
        print(f"  ! kullanilmayan ad: {' · '.join(sorted(dead))}")
        fail += len(dead)

    # 1b. Hicbir yerde kullanilmayan CSS sinifi. Arama havuzuna PYTHON da
    # girer: `vsvg` gibi bazi siniflar vector.py'de uretilen SVG'ye yazilir,
    # yalnizca HTML+JS'e bakan bir tarama onlari olu sanirdi.
    used = html + blob + "\n".join(
        p.read_text(encoding="utf-8") for p in sorted((ROOT / "src").rglob("*.py")))
    unused = sorted({
        cls for sel, _ in _css_rules(css)
        for cls in re.findall(r"\.([\w-]+)", sel)
        if not CSS_DYNAMIC.match(cls)
        and not re.search(rf"[\"'\s.]{re.escape(cls)}[\"'\s.:\[]", used)
    })
    if unused:
        print(f"  ! kullanilmayan CSS sinifi: {' · '.join(unused)}")
        fail += len(unused)

    # 1c. AYNI ADIN iki dosyada tanimlanmasi (Faz 9.5.2.2).
    #
    # ⚠ JS dosyalari klasik `<script>` ile yukleniyor ve TEK kuresel kapsami
    # paylasiyor. Ayni ad iki kez tanimlanirsa ikinci
    # dosya `SyntaxError` ile BASTAN SONA calismaz ve uygulama yalnizca
    # tarayici konsolunda konusur — Python denetimi yesil yanar, ekran boş
    # kalir. Tam boyle oldu: `shell.js`e yazilan `saveKey`, `panel.js`teki
    # `const saveKey` ile carpisti ve kabuk hic kurulmadi.
    owner: dict[str, str] = {}
    clash = []
    for path, text in sources.items():
        for name in _js_decls(text):
            if name in owner and owner[name] != f"{path.name}:{name}":
                clash.append(f"{name} ({owner[name]} · {path.name})")
            else:
                owner[name] = path.name
    if clash:
        print(f"  ! ad iki kez tanimli (ikinci dosya hic calismaz): "
              f"{' · '.join(sorted(set(clash)))}")
        fail += len(set(clash))

    # 2. Olcu sapmasi — JS <-> Python ve JS <-> CSS.
    js_nums = _js_numbers(blob)
    drift = []
    for js_name, mod_name, py_name in CONST_PAIRS:
        py_val = getattr(PY_MODULES[mod_name], py_name)
        if js_name not in js_nums:
            drift.append(f"{js_name} JS'te yok")
        elif js_nums[js_name] != py_val:
            drift.append(f"{js_name}: JS {js_nums[js_name]} != {mod_name}.{py_name} {py_val}")
    for js_name, sel, prop in CSS_PAIRS:
        css_val = _css_px(css, sel, prop)
        if js_name not in js_nums:
            drift.append(f"{js_name} JS'te yok")
        elif css_val is None:
            drift.append(f"{sel} {{{prop}}} CSS'te yok")
        elif css_val != js_nums[js_name]:
            drift.append(f"{js_name}: JS {js_nums[js_name]} != CSS {sel} {prop} {css_val}")
    if drift:
        print(f"  ! olcu sapmasi: {' · '.join(drift)}")
        fail += len(drift)

    # 3. [hidden] kacagi.
    leaks = _hidden_leaks(css, html)
    if leaks:
        print(f"  ! [hidden] kacagi: {' · '.join(leaks)}")
        fail += len(leaks)

    # 4. Kaydirilabilir flex kapsayicida korumasiz `center`.
    traps = _center_scroll_traps(css)
    if traps:
        print(f"  ! kaydirmada ortalama tuzagi (`safe center` gerekli): "
              f"{' · '.join(traps)}")
        fail += len(traps)

    # 5. Her modal HEM Escape zincirinde HEM odak tuzaginda olmali (9.5.5.2).
    #
    # ⚠ Ikisi de SESSIZCE eksik kalir: Escape'e yazilmayan pencere yalnizca
    # fareyle kapanir, odak tuzagina yazilmayan pencerede sekme ARKADAKI
    # arayuze kacar. Konsolda hata cikmaz, ekranda bozuk bir sey gorunmez —
    # yalnizca klavye kullanan biri fark eder ve o da sebebini soyleyemez.
    #    ⚠ UC liste var, ucu de elle tutuluyor: Escape zinciri, odak tuzagi ve
    #    ORTUYE TIKLAMA. Ilk yazimda yalnizca ikisi denetleniyordu; ucuncusunu
    #    unutan bir modal hicbir kapiya takilmazdi — tam da bu denetimin
    #    yakalamak icin yazildigi sessiz eksigin ucuncusu.
    main = next((t for p, t in sources.items() if p.name == "main.js"), "")
    overlays = set(re.findall(r'id="([\w-]+-overlay)"', html))
    esc = re.search(r"e\.key !== 'Escape'.*?\n  \}\);", main, re.S)
    trap = re.search(r"focusTrap\(e, \[(.*?)\]", main, re.S)
    # Ortu baglamasi iki yerde olabiliyor (`shell.js` dongusu ve `main.js`teki
    # `export-overlay` varyanti), o yuzden havuz tum JS.
    click = re.findall(r"\$\('([\w-]+-overlay)'\)\.addEventListener\('click'", blob)
    click += re.findall(r"\['([\w-]+-overlay)', close\w+\]", blob)
    missing = []
    for name in sorted(overlays):
        if not esc or name not in esc.group(0):
            missing.append(f"{name} (Escape)")
        if not trap or name not in trap.group(1):
            missing.append(f"{name} (odak tuzagi)")
        if name not in click:
            missing.append(f"{name} (ortuye tiklama)")
    if missing:
        print(f"  ! modal klavyeye baglanmamis: {' · '.join(missing)}")
        fail += len(missing)

    # 6. Belgeden SINIFLA tek oge secmek: `document.querySelector('.x')` ilk
    #    eslesen ogeyi dondurur. Sinif bugun tek ogedeyse dogru calisir; ayni
    #    sinifi tasiyan yeni bir oge ONE eklenince sessizce yanlis ogeyi tutar.
    #    Tam boyle oldu: Ayarlar penceresi (`tpanel dlg`) DOM'da Kaydet panelinin
    #    onune girdi, boyutlandirma tutamagi gizli Ayarlar panelini buyuttu ve
    #    ekranda hicbir sey olmadi. Tek oge `id` ile secilir.
    ambiguous = []
    for m in re.finditer(r"document\.querySelector\(\s*['\"]\.([\w-]+)['\"]\s*\)", blob):
        cls = m.group(1)
        n = len(re.findall(rf'class="(?:[^"]*\s)?{re.escape(cls)}(?:\s[^"]*)?"', html))
        if n > 1:
            ambiguous.append(f".{cls} ({n} oge)")
    if ambiguous:
        print(f"  ! belirsiz secici — sinif birden cok ogede, ilki doner: {' · '.join(ambiguous)}")
        fail += len(ambiguous)

    # 7. Kaplamanin cocugu sinirli mi (9.14.1) — kaydirilamayan ortalama tuzagi.
    unbounded = _overlay_bounds(css, html)
    if unbounded:
        print(f"  ! kaplamada sinirsiz panel (iki uctan kirpilir): {' · '.join(unbounded)}")
        fail += len(unbounded)

    # 8. Sekme listeleri (9.14.2): her `role=tab` var olan bir panele gider,
    #    panel sekmeye geri isaret eder, baslangicta yalnizca secili sekmenin
    #    paneli gorunur. Esi kopan sekme tiklaninca hicbir sey gostermez ya da
    #    iki panel ust uste acilir — konsolda hata cikmaz.
    tabs = _tab_pairs(html)
    if tabs:
        print(f"  ! sekme/panel esi bozuk: {' · '.join(tabs)}")
        fail += len(tabs)

    # 9. En kucuk pencere (9.14.3): hedef ekrana sigar, icerigi tasir.
    app_src = (ROOT / "src" / "jsonimager" / "app.py").read_text(encoding="utf-8")
    small = _window_min(app_src, css, js_nums, blob)
    if small:
        print(f"  ! en kucuk pencere: {' · '.join(small)}")
        fail += len(small)

    # 10. Yerlesim matrisi (9.14.5) en kucuk boyutu ve her kaplamayi kapsiyor.
    cover = _matrix_cover(app_src, html)
    if cover:
        print(f"  ! yerlesim matrisi eksik: {' · '.join(cover)}")
        fail += len(cover)

    if not fail:
        print(f"  arayuz: {len(sources)} JS dosyasi · olu kod yok · "
              f"{len(CONST_PAIRS) + len(CSS_PAIRS)} olcu esit · "
              f"[hidden] kacagi yok · kaydirmada ortalama guvenli · "
              f"{len(overlays)} modal klavyeye bagli · belirsiz secici yok · "
              f"kaplama panelleri sinirli · sekme/panel esleri tam · "
              f"en kucuk pencere hedef ekrana sigiyor · matris her kaplamayi kapsiyor")
    return fail


# --- Palet (Faz 9.4) -------------------------------------------------------

# Paletin iki tarafi: CSS'te `:root[data-theme="<ad>"]`, Python'da
# `theme.PALETTES["<ad>"]`. Secici burada tek yerde yazilidir.
THEME_SELECTOR = ':root[data-theme="{}"]'
FONT_SELECTOR = ':root[data-font="{}"]'

CSS_VAR = re.compile(r"--([\w-]+)\s*:\s*([^;]+);")

# Ciziciler: bunlarin hicbirinde sabit renk KALMAMALI, hepsi paletten okur.
# `theme.py` doğal olarak disarida (paletin kendisi orada); `tools/make_icon.py`
# de disarida ve bu KASITLI — gorev cubugu simgesi uygulamanin temasini
# izleyemez, `.ico` kendi zeminini tasimak zorunda.
DRAW_MODULES = ("draw.py", "img_table.py", "img_tree.py", "img_chart.py",
                "vector.py", "export_text.py")

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _css_vars(css: str, selector: str) -> dict[str, str]:
    """Bir seciciye yazilmis ozel ozellikler. Secici VIRGULLE ayrilmis bir
    listede de gecebilir (`:root, :root[data-theme="dark"]`), bu yuzden
    bilesenlere bakilir — `_css_px` ile ayni kalip."""
    out: dict[str, str] = {}
    for sel, body in _css_rules(css):
        if selector in (s.strip() for s in sel.split(",")):
            for name, value in CSS_VAR.findall(body):
                out[name] = value.strip()
    return out


def _css_prop(css: str, selector: str, prop: str) -> str | None:
    """Bir seciciye yazilmis duz ozelligin degeri (`_css_vars`in `--` olmayan
    karsiligi). Ozellik adinin soluna bakilir ki `color-scheme` ararken
    `-color-scheme` gibi bir ad eslesmesin."""
    pat = re.compile(rf"(?<![-\w]){re.escape(prop)}\s*:\s*([^;]+);")
    for sel, body in _css_rules(css):
        if selector in (s.strip() for s in sel.split(",")):
            if m := pat.search(body):
                return m.group(1).strip()
    return None


def check_theme() -> int:
    """Paletin uc kurali.

    1. **Iki temanin anahtar kumesi ayni olmali.** Acik blokta eksik kalan bir
       anahtar sessizce koyu degeri miras alir; ekranda yalnizca "bir yeri koyu
       kalmis" diye gorunur ve sebebi hicbir yerde yazmaz.
    2. **Palet degeri LITERAL olmali**, `var()` degil. Bu kural bir kazadan
       dogdu: renkleri belirtece indirirken toplu degistirme paletin KENDI
       tanimini da yakaladi ve `--danger: var(--danger)` gibi kendine gonderme
       yapan, tarayicinin sessizce dusurdugu bildirimler olustu. Ayrica
       `theme.py` ile karsilastirma ancak literal degerde anlamli.
    3. **`theme.PALETTES` CSS'in ALT KUMESI olmali ve degerler esit.** Cizim
       (PNG/SVG/PDF) ekranla birebir olmak zorunda; Pillow CSS okuyamadigi icin
       ayni ad iki yerde yazilir — `CONST_PAIRS`teki gerekcenin aynisi. Ters yon
       serbesttir: golge, imlec ve yalnizca ekranda gorunen tonlar CSS'te kalir.
    """
    css = (WEB / "style.css").read_text(encoding="utf-8")
    fail = 0

    blocks: dict[str, dict[str, str]] = {}
    for name in TH.THEMES:
        blocks[name] = _css_vars(css, THEME_SELECTOR.format(name))
        if not blocks[name]:
            print(f"  ! CSS'te {THEME_SELECTOR.format(name)} blogu yok")
            fail += 1
    if fail:
        return fail

    first, *rest = TH.THEMES
    for name in rest:
        if missing := sorted(set(blocks[first]) - set(blocks[name])):
            print(f"  ! {name} paletinde eksik: {' · '.join(missing)}")
            fail += len(missing)
        if extra := sorted(set(blocks[name]) - set(blocks[first])):
            print(f"  ! {first} paletinde eksik: {' · '.join(extra)}")
            fail += len(extra)

    for name, css_vars in blocks.items():
        for key, value in sorted(css_vars.items()):
            if "var(" in value:
                print(f"  ! {name} paletinde literal olmayan deger: --{key}: {value}")
                fail += 1

    # `color-scheme` bir belirtec DEGIL ama temaya baglidir: tarayicinin kendi
    # cizdigi parcalari (kaydirma cubugu, `<select>` listesi) o boyar. Acik
    # blokta yazilmazsa koyu deger miras kalir ve beyaz sayfada koyu bir
    # kaydirma cubugu durur — belirtec eksikligiyle ayni sinsilikte.
    for name in TH.THEMES:
        declared = _css_prop(css, THEME_SELECTOR.format(name), "color-scheme")
        if declared != name:
            print(f"  ! {name} bloğunda color-scheme: {declared or 'yok'}")
            fail += 1

    for name, colors in TH.PALETTES.items():
        css_vars = blocks.get(name, {})
        for key, value in sorted(colors.items()):
            css_val = css_vars.get(key)
            if css_val is None:
                print(f"  ! theme.py {name}.{key} CSS'te yok (--{key})")
                fail += 1
            elif css_val.lower() != value.lower():
                print(f"  ! {name} --{key}: CSS {css_val} != theme.py {value}")
                fail += 1

    # Seri renkleri CSS'te YOK (grafik yalnizca cizimde renkleniyor), ama iki
    # temada ayni uzunlukta olmali: kisa kalan liste sessizce basa sarar ve iki
    # seri ayni rengi alir.
    lengths = {name: len(cols) for name, cols in TH.SERIES.items()}
    if len(set(lengths.values())) > 1:
        print(f"  ! seri renk sayilari farkli: {lengths}")
        fail += 1

    fail += _check_fonts(css)
    fail += _check_sizes()
    fail += _check_screen_metrics(css)
    fail += _check_no_literal_colors()
    fail += _check_theme_flows()

    if not fail:
        print(f"  palet: {len(TH.THEMES)} tema · {len(blocks[first])} belirtec · "
              f"{len(TH.PALETTES[first])} tanesi theme.py ile esit · "
              f"{lengths[first]} seri rengi · {len(DRAW_MODULES)} cizici temiz · "
              f"{len(TH.FONTS)} yazi tipi ailesi")
    return fail


def _check_fonts(css: str) -> int:
    """Yazi tipi ailesi CSS'te ve `theme.FONTS`ta AYNI mi?

    Ayni yigin iki yerde yazili: `style.css` ekrana uyguluyor, `theme.py` ise
    SVG ciktisina yaziyor (`vector.to_svg` → `font-family`). Ayrisirlarsa ekran
    bir aileyle, disa aktarilan SVG baskasiyla cizilir — paletteki sapmanin
    yazi tipi karsiligi.

    Aile eksikligi de yakalanir: `theme.FONTS`a uye eklenip CSS blogu
    yazilmazsa secicide gorunen aile ekranda hicbir sey yapmaz (`--font`
    tanimsiz kalir) ama CIZIM degisir.
    """
    fail = 0
    for name, fam in TH.FONTS.items():
        # ⚠ `_css_vars` anahtari `--` ONEKSIZ dondurur (`--font` → `font`).
        stack = _css_vars(css, FONT_SELECTOR.format(name)).get("font")
        if stack is None:
            print(f"  ! {FONT_SELECTOR.format(name)} blogu yok ya da --font tanimsiz")
            fail += 1
        elif " ".join(stack.split()) != " ".join(fam.css.split()):
            print(f"  ! {name} yigini: CSS {stack!r} != theme.py {fam.css!r}")
            fail += 1

    # ⚠ `--mono` belirteci ile `data-font="mono"` yigini AYNI kalmali. Ikisi
    # ayri sorulari yanitliyor (biri kullanicinin sectigi aile ve `theme.py`
    # ile esit, oteki "tema ne olursa olsun esaralikli" metin) ama ayni yazi
    # tipini gostermek zorundalar; ayrisirlarsa kod blogu ile mono temasi
    # farkli yazi tipiyle cizilir ve kimse fark etmez.
    token = _css_vars(css, ":root").get("mono")
    mono = TH.FONTS.get("mono")
    if token is None:
        print("  ! `--mono` belirteci :root'ta tanimsiz")
        fail += 1
    elif mono and " ".join(token.split()) != " ".join(mono.css.split()):
        print(f"  ! `--mono` belirteci yiginla ayrismis: {token!r} != {mono.css!r}")
        fail += 1

    # Ters yon: CSS'te olup `theme.FONTS`ta olmayan aile, secicide hic
    # gorunmeyen olu bir bloktur.
    for m in re.finditer(r':root\[data-font="([\w-]+)"\]', css):
        if m.group(1) not in TH.FONTS:
            print(f"  ! CSS'te theme.FONTS'ta olmayan aile: {m.group(1)}")
            fail += 1

    fail += _check_font_files()
    return fail


def _check_sizes() -> int:
    """Boyut ayarina tasinmis ciziciler taban sabitleri kullaniyor mu?

    Goc bitene kadar `draw` hem yeni yolu (`theme.metrics`) hem eski sabitleri
    tasiyor. Tasinmis bir modul yanlislikla eskisini ice aktarirsa boyut ayari
    orada SESSIZCE calismaz — tablo buyur, agac buyumez.

    ⚠ Taban boyutta turetilen olculerin bugunku sayilarla ayni cikmasi da
    burada dogrulanir: formul degisirse varsayilan gorunum kayar ve bunu hicbir
    belge denetimi gostermez.
    """
    fail = 0
    for name in SIZED_MODULES:
        src = (ROOT / "src" / "jsonimager" / f"{name}.py").read_text(encoding="utf-8")
        used = [c for c in LEGACY_SIZES if re.search(rf"\b{c}\b", src)]
        if used:
            print(f"  ! {name}.py hala taban punto sabiti kullaniyor: "
                  f"{' · '.join(used)}")
            fail += len(used)

    before = TH.get_size()
    try:
        TH.set_size(TH.SIZE_BASE)
        m = TH.metrics()
        base = {"font": 12, "title": 16, "small": 10, "title_h": 46, "row_h": 26,
                "head_h": 30, "group_h": 22, "wrap_line_h": 16, "char_w": 7,
                "badge_char_w": 5}
        for key, want in base.items():
            if getattr(m, key) != want:
                print(f"  ! taban boyutta {key}: {getattr(m, key)} != {want}")
                fail += 1
    finally:
        TH.set_size(before)

    fail += _check_size_flows()
    return fail


# Akis sondalari icin sentetik belge: kirilim (`kind`) + olcu (`n`), yani hem
# agac hem tablo hem grafik kurulabiliyor. `NOTE_PROBE` ile ayni gerekce —
# ornek belgeye guvenilmez, `samples/` bos olabilir.
SIZE_PROBE = {"rows": [{"kind": "a", "n": 3}, {"kind": "b", "n": 5},
                       {"kind": "a", "n": 2}]}


def _probe_scenes() -> dict:
    """Sentetik belgeden dort sahne — gecerli tema VE gecerli punto ile.

    Iki akis sondasi da bunu kullanir: biri cizilen renkleri, oteki cizilen
    yazi olculerini paletle/olculerle karsilastirir. Once ikisi de yalnizca
    `tree_scene` kuruyordu; oysa en cok renk ve olcu tasiyan cizici TABLO ve
    tam da o, sondalarin disinda kalmisti.
    """
    ds = D.discover(SIZE_PROBE)[0]
    table = F.build_table(SIZE_PROBE, ds)
    keys = [c["key"] for c in table["columns"]]
    view = {"order": keys, "hidden": [], "widths": {}, "groups": False}
    return {
        "agac": ITR.tree_scene("probe", SIZE_PROBE)[0],
        "tablo": ITB.table_scene(table, view, None, None),
        "sutun": ICH.chart_scene(table, keys[0], keys[1], "bar"),
        "pasta": ICH.chart_scene(table, keys[0], keys[1], "pie"),
    }


def _check_size_flows() -> int:
    """Punto degisince AGAC ve GRAFIK de degisiyor mu?

    Yukaridaki liste yalnizca "eski sabit ice aktarilmiyor" der; sabiti silip
    yerine baska bir sayi yazmak ya da olcuyu modul duzeyinde saklamak yine
    sessizce gecerdi — temanin `_check_theme_flows`la kapatilan aciginin
    aynisi. Sonda sahneyi en kucuk ve en buyuk puntoda kurar ve iki sey arar:
    cizilen her yazi gecerli olculerden BIRI olmali, ve agac gercekten
    buyumeli.

    ⚠ Grafik tuvali SABITTIR (bkz. `img_chart` basi), bu yuzden orada boyut
    degil yalnizca yazi olculeri sinanir — sahne yuksekligi beklenerek degismez.
    """
    before = TH.get_size()
    fail, tree_h = 0, {}
    try:
        for size in (TH.FONT_SIZES[0], TH.FONT_SIZES[-1]):
            TH.set_size(size)
            m = TH.metrics()
            allowed = {m.font, m.title, m.small}
            scenes = _probe_scenes()
            tree_h[size] = scenes["agac"].h

            for label, sc in scenes.items():
                stray = {it["size"] for it in sc.items
                         if it["t"] == "text" and it["size"] not in allowed}
                if stray:
                    print(f"  ! {label}: {size} puntoda olcu disi yazi "
                          f"{sorted(stray)} (beklenen {sorted(allowed)})")
                    fail += 1
    finally:
        TH.set_size(before)

    lo, hi = TH.FONT_SIZES[0], TH.FONT_SIZES[-1]
    if tree_h.get(hi, 0) <= tree_h.get(lo, 0):
        print(f"  ! agac puntoyla buyumuyor: {lo} → {tree_h.get(lo)} px, "
              f"{hi} → {tree_h.get(hi)} px")
        fail += 1
    return fail


# Ekranin kopruden aldigi turetilmis olculer: CSS degiskeni → `Metrics` alani.
# `state.js --> METRIC_VARS` ile ayni olmak zorunda.
METRIC_VARS = {"--small-size": "small", "--group-h": "group_h",
               "--cell-pad-y": "cell_pad_y"}

# Puntoyu izlemek ZORUNDA olan tablo kurallari. Bunlar kabuk degil TABLO:
# cizim taraflari `theme.metrics()`ten turuyor, dolayisiyla ekran da turemeli.
SIZED_CSS_RULES = (("thead th", "font-size"), (".group-row th", "font-size"),
                   (".group-row th", "height"), (".th-badge", "font-size"))


def _check_screen_metrics(css: str) -> int:
    """Ekran, puntodan tureyen olculeri KOPRUDEN mi aliyor?

    `9.4.5.3`e kadar tablonun baslik satiri, grup seridi ve tip rozeti CSS'te
    sabit punto tasiyordu; cizim tarafi ise `theme.metrics()`ten turuyordu.
    Sonuc: kullanici 12 disinda bir punto sectigi anda "cikti ekranla birebir"
    degismezi bozuluyordu — ve grup seridi TABAN boyutta bile ayrisikti
    (ekran 23, cizim 22).

    ⚠ Cozum CSS'e `calc(var(--font-size) * …)` yazmak DEGIL: formul iki
    calisma zamaninda iki kez tutulurdu. Degerler kopruden gelir; bu denetim
    de kanali ucundan ucuna kilitler — sozlesme (`Metrics` alani), yazan
    (`state.METRIC_VARS`) ve okuyan (CSS kurali).
    """
    fail = 0
    js = "\n".join(_js_sources().values())

    for var, field in METRIC_VARS.items():
        if field not in TH.Metrics._fields:
            print(f"  ! {var}: `theme.Metrics` icinde {field} alani yok")
            fail += 1
        if f"'{var}'" not in js:
            print(f"  ! {var}: `state.js --> METRIC_VARS` icinde yazili degil")
            fail += 1

    allowed = set(METRIC_VARS) | {"--font-size"}
    for selector, prop in SIZED_CSS_RULES:
        value = _css_prop(css, selector, prop)
        if value is None:
            print(f"  ! {selector} icinde {prop} bildirimi yok")
            fail += 1
        elif not (m := re.fullmatch(r"var\((--[\w-]+)\)", value.strip())):
            print(f"  ! {selector} {{ {prop}: {value} }} sabit — puntoyu izlemiyor")
            fail += 1
        elif m.group(1) not in allowed:
            print(f"  ! {selector} {{ {prop} }} bilinmeyen degiskeni okuyor: {m.group(1)}")
            fail += 1
    return fail


def _check_font_files() -> int:
    """Her ailenin TTF'i GERCEKTEN yukleniyor mu?

    `draw._font` hicbir aday bulamazsa `ImageFont.load_default()`e duser ve
    **istisna firlatmaz**: cizim uretilir, yalnizca cirkinlesir. Yazim hatali
    bir dosya adi (`gerogia.ttf`) ya da yalnizca kalin varyanti eksik bir aile
    boylece sessizce gecerdi — ekranda Georgia, PNG'de gomulu yedek.

    ⚠ Olcut `path`in DIZGE olmasi, dolu olmasi degil. Pillow'un varsayilani da
    bir `FreeTypeFont` dondurur ve onun `path`i gomulu bir `BytesIO`dur —
    "path var mi" diye bakan ilk yazim bu yuzden hicbir seyi yakalamadi ve
    yazim hatasi sinamasinda ortaya cikti.

    Denetim Windows'a bagli: aday listelerinin sonunda DejaVu var, yani baska
    bir ortamda da gecer; hicbiri yoksa zaten gercek bir sorun vardir.
    """
    before = TH.get_font()
    fail = 0
    try:
        for name in TH.FONTS:
            TH.set_font(name)
            for bold in (False, True):
                if not isinstance(getattr(DRAW._font(12, bold), "path", None), str):
                    kind = "kalin" if bold else "duz"
                    print(f"  ! {name} ({kind}): hicbir TTF bulunamadi, "
                          "cizim Pillow'un gomulu yedegine dusuyor")
                    fail += 1
    finally:
        TH.set_font(before)
    return fail


def _check_theme_flows() -> int:
    """Tema degisince CIZIM de degisiyor mu?

    Statik tarama "sabit renk kalmadi" der ama "renk gercekten paletten geldi"
    diyemez: bir cizici sabit rengi silip yanlis anahtari okuyabilir ya da
    modul duzeyinde bir kopya tutabilir — o zaman tema degisir, cizim degismez.
    Bu sonda sahneyi IKI temada da kurar ve **her ogenin rengini** paletle
    karsilastirir.

    Sonda sentetik bir belgeden calisir (`_probe_scenes`), boylece `samples/`
    bos olsa da dort cizicinin dordu de sinanir — once yalnizca agac
    kuruluyordu ve en cok renk tasiyan tablo denetimin disindaydi.
    """
    before = TH.get_theme()
    fail = 0
    try:
        for name in TH.THEMES:
            TH.set_theme(name)
            allowed = set(TH.PALETTES[name].values()) | set(TH.SERIES[name])

            for label, sc in _probe_scenes().items():
                if sc.bg != TH.PALETTES[name]["bg"]:
                    print(f"  ! {name}/{label}: sahne zemini {sc.bg}, "
                          f"palet {TH.PALETTES[name]['bg']}")
                    fail += 1

                stray = {c for it in sc.items for key in ("fill", "stroke")
                         if (c := it.get(key)) and c not in allowed}
                if stray:
                    print(f"  ! {name}/{label}: palet disi renk cizildi: "
                          f"{' · '.join(sorted(stray))}")
                    fail += 1
    finally:
        TH.set_theme(before)
    return fail


def _docstring_ids(tree) -> set[int]:
    """Docstring olan dize dugumlerinin kimlikleri.

    Docstring bir govdenin ILK ifadesidir ve duz bir dizeden ancak boyle ayirt
    edilir. Iki denetim de bunu kullaniyor: yorumlar ve docstring'ler Turkce
    kalabilir (`check_py_strings`) ve icinde renk ADI gecebilir (asagisi).
    """
    import ast

    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", []) if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) else []
        if body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant) and \
                isinstance(body[0].value.value, str):
            out.add(id(body[0].value))
    return out


def _check_no_literal_colors() -> int:
    """Cizicilerde sabit renk kaldi mi?

    Palet ile ekran arasindaki eslesmeyi denetlemek YETMEZ: paletin disinda
    kalmis tek bir `#1e222a`, acik temada koyu bir leke olarak durur ve
    `check_theme`in oteki kurallari onu hic gormez — cunku o deger zaten
    paletin parcasi degildir.

    Arama `ast` ile DIZE SABITLERINDE yapilir; yorumlar agacta hic yok,
    docstring'ler ise elenir. Boylece "once `#c792ea` yaziyordu" gibi bir
    aciklama denetimi kirmizi yakmaz.
    """
    import ast

    fail = 0
    for name in DRAW_MODULES:
        src = ROOT / "src" / "jsonimager" / name
        tree = ast.parse(src.read_text(encoding="utf-8"))
        skip = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in skip:
                continue
            if found := HEX_COLOR.findall(node.value):
                print(f"  ! {name}:{node.lineno} — sabit renk: {' · '.join(found)}")
                fail += 1
    return fail


# --- Ice aktarma zinciri (Faz 8.6) -----------------------------------------

# Bu moduller ice aktarilirken Pillow YUKLENMEMELIDIR. Sebep tek tek yazili:
#   chart_data — `Api.chart_columns()` her veri kumesi acilisinda cagriliyor
#   flatten    — tabloyu kuran yol; gorsel yalnizca `attach_images` ile girer
#   app        — acilis yolu; PNG istenmeden Pillow'un bedeli odenmemeli
# Kural sessizce bozulabilir: birinin ic aktardigi bir modul tepeye `from PIL
# import ...` yazarsa zincir geri gelir ve kimse fark etmez.
PILLOW_FREE = ("chart_data", "flatten", "discover", "export_text", "app", "edit_map",
               "edit_core", "json_write")


def check_import_chain() -> int:
    """Pillow'suz kalmasi gereken modulleri AYRI SURECTE ice aktarip dogrular.

    Ayri surec sart: bu betik zaten `img_table` ve `draw` ice aktardigi icin
    Pillow bellekte duruyor, ayni surecte olcum hep "yuklu" derdi.
    """
    code = (
        "import sys; "
        f"import jsonimager.{{m}} as _m; "
        "print('PIL.Image' in sys.modules)"
    )
    bad = []
    for mod in PILLOW_FREE:
        out = subprocess.run(
            [sys.executable, "-c", code.format(m=mod)],
            capture_output=True, text=True, cwd=str(ROOT / "src"),
        )
        if out.returncode != 0:
            bad.append(f"{mod}: ice aktarilamadi — {out.stderr.strip().splitlines()[-1:]}")
        elif out.stdout.strip() == "True":
            bad.append(f"{mod}: Pillow yukleniyor")

    if bad:
        for b in bad:
            print(f"  ! {b}")
        return 1
    print(f"  ice aktarma: {len(PILLOW_FREE)} modul Pillow'suz")
    return 0


# --- Dil sozlugu (Faz 9.2) -------------------------------------------------

def check_i18n() -> int:
    """Anahtar/etiket ayrimi ve iki dilin esligi.

    Uc sessiz bozulma yolu var ve ucu de burada kapatiliyor:
      1. Bir dile anahtar eklenip digerine eklenmemesi — eksik dilde ekranda
         `group.id` gorunur.
      2. Yer tutucularin ayrisması (`{rows}` bir dilde var, digerinde yok) —
         `t()` cagrisi `KeyError` ile duser.
      3. Grup/tur ANAHTARLARININ etikete geri donmesi — koprude dize
         esitligiyle karsilastirildiklari icin ceviri eslesmeyi koparir.
    """
    from jsonimager import columns as COL
    from jsonimager import discover as D
    from jsonimager import i18n as I18N

    fail = 0
    keysets = {lang: set(I18N.STRINGS[lang]) for lang in I18N.LANGS}
    base = keysets[I18N.DEFAULT_LANG]

    for lang, keys in keysets.items():
        missing = sorted(base - keys)
        extra = sorted(keys - base)
        if missing:
            print(f"  ! i18n[{lang}]: eksik anahtar — {', '.join(missing[:6])}")
            fail += 1
        if extra:
            print(f"  ! i18n[{lang}]: fazla anahtar — {', '.join(extra[:6])}")
            fail += 1

    # Yer tutucular iki dilde de ayni olmali.
    for key in sorted(base):
        holders = {lang: set(re.findall(r"\{(\w+)\}", I18N.STRINGS[lang].get(key, "")))
                   for lang in I18N.LANGS}
        if len({frozenset(h) for h in holders.values()}) != 1:
            print(f"  ! i18n: '{key}' yer tutuculari ayrisiyor — {holders}")
            fail += 1

    # Anahtarlar ASCII olmali: koprude dize olarak tasiniyorlar.
    for name, keys in (("group", COL.GROUP_ORDER),
                       ("kind", [D.RECORDS, D.KEYVALUE, D.KEYLIST, D.KEYED, D.PIVOT])):
        for k in keys:
            if not k.isascii() or not k.islower():
                print(f"  ! {name} anahtari ASCII/kucuk harf degil: {k!r}")
                fail += 1
            if f"{name}.{k}" not in base:
                print(f"  ! {name}.{k} icin etiket yok")
                fail += 1

    # `ORDER_GROUPS` (JS) ile `GROUP_ORDER` (Python) BIREBIR ayni sirada olmali:
    # JS `indexOf` ile hem dizilim hem renk indeksi uretiyor.
    js = (WEB / "js" / "state.js").read_text(encoding="utf-8")
    m = re.search(r"const ORDER_GROUPS = \[([^\]]+)\]", js)
    if not m:
        print("  ! state.js icinde ORDER_GROUPS bulunamadi")
        fail += 1
    else:
        js_groups = re.findall(r"'([^']+)'", m.group(1))
        if js_groups != list(COL.GROUP_ORDER):
            print(f"  ! grup sirasi ayrisiyor — JS {js_groups} / PY {COL.GROUP_ORDER}")
            fail += 1

    # Cagri yerlerindeki anahtarlar GERCEKTEN sozlukte mi? `check_i18n`in ust
    # kismi iki dilin ESITLIGINI denetler; hicbir dilde olmayan bir anahtar
    # (yazim hatasi) ikisinden de eksik oldugu icin oradan gecer ve `t()`
    # anahtarin KENDISINI dondurur — ekranda `chart.no_dta` gorunur.
    #
    # ⚠ Yalnizca TAM anahtar taranir: tirnaktan sonra `,` ya da `)` gelmeli.
    # `t('group.' + g)` gibi ONEK birlestiren cagrilar disarida kalir — onlarin
    # uyeleri asagidaki aile denetimlerinden geciyor.
    used = 0
    sources = [(p, r"\bt\(\s*\"([a-z][\w.]*)\"\s*[,)]")
               for p in (ROOT / "src" / "jsonimager").rglob("*.py")]
    sources += [(p, r"\bt\(\s*'([a-z][\w.]*)'\s*[,)]")
                for p in (WEB / "js").glob("*.js")]
    for path, pattern in sources:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(pattern, text):
            used += 1
            if m.group(1) not in base:
                line = text[:m.start()].count("\n") + 1
                print(f"  ! {path.name}:{line} — sozlukte olmayan anahtar: "
                      f"{m.group(1)!r}")
                fail += 1

    # F-dizeyle kurulan anahtar AILELERI (`f\"agg.{k}.label\"`) yukaridaki
    # taramaya gorunmez; uye listesi uzerinden ayrica denetlenir.
    from jsonimager import api_agent as AG
    from jsonimager import chart_data as CD
    from jsonimager import schema as SC

    for name, members, parts in (("agg", CD.AGGS, ("label", "note")),
                                 # Model anahtarlari artik SAGLAYICIDAN geliyor;
                                 # ailede hepsinin birlesimi aranir, yoksa yeni
                                 # bir saglayicinin modeli etiketsiz kalirdi.
                                 ("model", _provider_models(), ("label", "note")),
                                 ("effort", AG.AGENT_EFFORT_KEYS, ("label", "note")),
                                 # Saglayici adlari: `agent_keys` ve ileride
                                 # saglayici secicisi bunlari cagri aninda
                                 # cozuyor, yani etiketsiz bir saglayici
                                 # ekranda anahtarinin kendisini gosterirdi.
                                 ("provider", _provider_keys(), ("label",)),
                                 ("action", SC.ACTIONS, ("label", "q")),
                                 # Dil, tema ve yazi tipi ailelerinde alt parca
                                 # YOK: anahtarin kendisi etikettir
                                 # (`theme.system`, `lang.auto`).
                                 ("lang", I18N.CHOICES, ()),
                                 ("theme", TH.CHOICES, ()),
                                 ("font", tuple(TH.FONTS), ()),
                                 ("density", TH.DENSITIES, ()),
                                 ("export_theme", TH.EXPORT_THEMES, ())):
        for k in members:
            keys = [f"{name}.{k}.{part}" for part in parts] or [f"{name}.{k}"]
            for key in keys:
                if key not in base:
                    print(f"  ! {key} icin metin yok")
                    fail += 1

    fail += _check_dataset_notes()

    if not fail:
        print(f"  dil: {len(I18N.LANGS)} dil · {len(base)} anahtar · "
              f"{len(COL.GROUP_ORDER)} grup anahtari eslesti · "
              f"{used} cagri yeri sozlukte")
    return fail


def _provider_models() -> set[str]:
    """Butun saglayicilarin sundugu model anahtarlarinin birlesimi."""
    from jsonimager import providers as PR

    return {k for p in PR.PROVIDERS.values() for k in p.models()}


def _provider_keys() -> set[str]:
    """Kayitli saglayici anahtarlari."""
    from jsonimager import providers as PR

    return set(PR.PROVIDERS)


# Kesif notlarini ve kok adini tetikleyen SENTETIK belge (Faz 9.2.7).
# ⚠ `examples/` ve `samples/` altindaki belgelerin HICBIRI bu yollari
# tetiklemiyor — olculdu. Yani gercek belgelerle kosan denetim, notlarin
# dile baglanmasini hic sinamiyordu ve gerileme sessiz kalirdi.
NOTE_PROBE = {
    "name": "x", "version": "1", "env": "dev", "debug": True, "level": 3,
    "rows": [{"id": 1, "v": 2}, {"id": 2, "v": 3}, {"id": 3, "v": 4}],
    "meta": {"a": 1},
    "pv": {
        "c1": {f"r{i}": i for i in range(1, 9)},
        "c2": {f"r{i}": i for i in range(1, 6)},
        "note": "x",
    },
}
NOTE_KEYS = {"ds.note_promoted", "ds.note_inline",
             "ds.note_skipped", "ds.note_missing"}


def _check_dataset_notes() -> int:
    """`Dataset.notes` ve kok adi GERCEKTEN dile bagli mi?

    Kesif belge acilirken bir kez calisir; notlar orada metne cevrilseydi
    dil degisince eski dilde kalirlardi. Denetim metnin iki dilde
    FARKLI oldugunu dogrular — sabit bir dize iki dilde de ayni cikardi.
    """
    from jsonimager import discover as D
    from jsonimager import i18n as I18N

    before = I18N.get_lang()
    fail = 0
    try:
        datasets = D.discover(NOTE_PROBE)
        seen = {k for ds in datasets for k, _ in ds.notes}
        if missing := NOTE_KEYS - seen:
            # Sonda tetikleyemiyorsa denetim bos donuyor demektir.
            print(f"  ! not sondasi eksik kaldi: {', '.join(sorted(missing))}")
            fail += 1

        texts = {}
        for lang in I18N.LANGS:
            I18N.set_lang(lang)
            texts[lang] = [t for ds in datasets for t in ds.note_texts]
            texts[lang] += [ds.label_text for ds in datasets if not ds.path]

        tr, en = texts["tr"], texts["en"]
        for a, b in zip(tr, en):
            if a == b:
                print(f"  ! kesif metni dile baglanmamis: {a!r}")
                fail += 1
    finally:
        I18N.set_lang(before)
    return fail


# --- Arayuz metinleri (Faz 9.2.2) ------------------------------------------

TR_CHARS = "çğıöşüÇĞİÖŞÜ"

# ⚠ `TR_CHARS`in KOR NOKTASI: ASCII harfli Turkce (`Kaydedildi`, `Gruplar`,
# `Bilinmeyen hata`) taramadan kaciyor. Olctum, uc olcut denendi:
#
#   • kelime listesi        → bitmez, her yeni kelimede buyur
#   • "cumle gibi duran dize" → JS'te 99 yanlis alarm (bicim parcalari,
#     sinif adlari); Python'da bicim ureten uc modul haric tutulunca 0
#   • "kullaniciya YAZAN cagrinin ilk argumani"  → JS'te 1 isabet, 0 yanlis
#
# Bu yuzden iki taraf iki ayri olcut kullanir. Sinir acik: JS kurali yalnizca
# ILK argumani gorur (`setStatus(x || 'metin')` gibi bir yedek degeri
# gormez), Python kurali ise boslugu olmayan tek kelimeyi gormez.
UI_SINK_LIT = re.compile(
    r"(?:\b(?:setStatus|setInfo|setFoot)\(\s*|\.(?:textContent|placeholder)\s*=\s*)"
    r"('(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\")")
LETTERISH = re.compile(rf"[A-Za-z{TR_CHARS}]")

# Bicim ureten moduller: PDF/SVG/HTML/CSS parcalari cumleye benziyor ama
# kullaniciya METIN olarak gitmiyor. Uygulama adi da cevrilmez.
PY_MARKUP = ("vector.py", "export_text.py", "theme.py")
APP_NAME = "JSON Imager"
# Ceviri isaretinin aranacagi nitelikler. `title` listede DEGIL: agac ve tablo
# hucrelerinde VERI gosteriyor (tam yol, kirpilmis metnin tamami), arayuz metni
# degil.
I18N_ATTRS = ("data-tip", "aria-label", "placeholder")

HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
HTML_TAG = re.compile(r"<[^>]+>")
# Kapanis etiketi olmayan ogeler — derinlik sayacini bozmamalari icin atlanir.
HTML_VOID = {"input", "meta", "link", "br", "hr", "img", "source", "!DOCTYPE"}


# Bir `/`yi BOLME degil duzenli ifade basi yapan onceki karakterler ve
# anahtar sozcukler. `)` ve `]` listede yok: `(a) / 2`, `x[0] / 2` bolmedir.
_JS_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")
_JS_REGEX_WORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete",
                   "void", "throw", "case", "do", "else", "yield", "await"}


def _js_regex_end(text: str, i: int) -> int:
    """`text[i] == '/'` bir duzenli ifade sabitini aciyorsa bayraklar dahil
    bitis konumunu, acmiyorsa -1 dondurur.

    Karakter sinifi (`[...]`) icindeki `/` ifadeyi kapatmaz, `\\` sonraki
    karakteri kacirir; satir sonuna kadar kapanmayan `/` ifade degildir.
    """
    j, n, in_class = i + 1, len(text), False
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "\n":
            return -1
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "/":
            j += 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1                         # bayraklar: g, i, m, s, u, y, d
            return j
        j += 1
    return -1


def _js_regex_can_start(text: str, prev: int) -> bool:
    """`prev` son anlamli (bosluk/yorum olmayan) karakterin konumu; -1 = girdi basi."""
    if prev < 0 or text[prev] in _JS_REGEX_PREV:
        return True
    k = prev
    while k >= 0 and (text[k].isalnum() or text[k] in "_$"):
        k -= 1
    word = text[k + 1:prev + 1]
    # `a.return / 2` bir ozellik erisimi: anahtar sozcuk sayilmaz.
    return word in _JS_REGEX_WORDS and (k < 0 or text[k] != ".")


def _strip_js_comments(text: str) -> str:
    """JS yorumlarini bosluga cevirir; dize sabitlerine DOKUNMAZ, duzenli
    ifade sabitlerinin ICINI bosluga cevirir.

    Duz `re.sub` yetmez: `'http://x'` icindeki `//` yorum sanilir, yorumun
    icindeki tirnak da dize sanilir. Bu yuzden kucuk bir durum makinesi —
    ceviri denetimi yorumlari es gecmek zorunda, Turkce yorum serbest.

    Duzenli ifade de ayri bir durum: `/^@"([^"]*)"/` icindeki tirnak dize basi
    sayilirsa eslesme dosyanin geri kalaninda kayar ve sonraki yorumlar sahte
    "cevrilmemis dize" olarak cikar (Faz 11.2'de `new RegExp` ile dolasilmisti).
    Ifade kopyalanmaz, BOSALTILIR: kopyalansaydi sonraki adimin dize araması
    icindeki `"…"` ciftini yine dize sanardi. Uzunluk korunur, satirlar kaymaz.
    """
    out, i, n, prev = [], 0, len(text), -1
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch in "'\"`":                       # dize: oldugu gibi kopyala
            quote, j = ch, i + 1
            while j < n and text[j] != quote:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            prev = min(j, n - 1)
            i = j + 1
        elif (ch == "/" and nxt not in "/*" and _js_regex_can_start(text, prev)
              and (j := _js_regex_end(text, i)) > 0):
            body = text[i:j]
            close = body.rindex("/")
            out.append("/" + " " * (close - 1) + body[close:])
            prev = j - 1
            i = j
        elif ch == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            # Satir sonlari KORUNUR (satir numaralari kaysin istemiyoruz),
            # geri kalan her karakter bosluga cevrilir.
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
        else:
            out.append(ch)
            if not ch.isspace():
                prev = i
            i += 1
    return "".join(out)


JS_LITERAL = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`")


def _js_turkish_literals(src: str) -> list[str]:
    """Yorumlari ayiklanmis JS kaynaginda Turkce harf tasiyan dize sabitleri."""
    return [lit for lit in JS_LITERAL.findall(_strip_js_comments(src))
            if any(ch in TR_CHARS for ch in lit)]


# Tarayici sondasi: her satir bir tuzak, yalnizca SON satirdaki dize gercek.
# ⚠ Ifadelerdeki tirnaklarin sayisi TEK olmali: cift olursa yanlis ayristirma
# kendi kendini dengeliyor ve sonda kusuru gormuyor (ilk taslakta oldu).
# Ikinci satirda sinif icindeki `/` ifadeyi erken kapatirsa `"` acikta kalir;
# `typeof` ardindaki `/` ifade basidir. Yorumdaki tirnak ve ters tirnak dize
# sanilmamali. Son satirda gercek dize IKI BOLMENIN arasinda: bolme ifade
# sanilirsa dize ifadenin icinde kalir, bosaltilir ve kaybolur.
_JS_SCANNER_PROBE = (
    "const A = /^@(?:\"([^\"]*)\"|x)$/.exec(s);\n"
    "const B = s.split(/[/\"]/g), C = typeof /`/;\n"
    "const half = (total) / 2, url = 'http://x/y';\n"
    "// yorum: \"tırnak\" ve `ters tırnak` serbest\n"
    "/* çok satırlı \"yorum\" */\n"
    "const msg = n / 2 + 'Kaydı aç' + m / 3;\n"
)


def _probe_js_scanner() -> int:
    """`_strip_js_comments` duzenli ifadeyi, bolmeyi ve yorumu ayirt ediyor mu?"""
    got = _js_turkish_literals(_JS_SCANNER_PROBE)
    if got == ["'Kaydı aç'"]:
        return 0
    print(f"  ! JS tarayici sondasi: beklenen yalnizca 'Kaydı aç', gelen {got}")
    return 1


def check_ui_strings() -> int:
    """`index.html`'de ISARETLENMEMIS Turkce metin kaldi mi?

    Gocun bittigini olcen ve gerilemeyi onleyen denetim: yeni bir dugme
    eklenip `data-i18n` yazilmazsa Ingilizce arayuzde Turkce kalir ve bunu
    kimse fark etmez.

    HTML'deki Turkce metin SILINMEZ, yer tutucu olarak durur — sozluk hic
    gelmezse arayuz bos degil Turkce gorunur. Denetim metnin varligina degil,
    **isaretin yokluguna** bakar.
    """
    html = HTML_COMMENT.sub("", (WEB / "index.html").read_text(encoding="utf-8"))
    fail = 0

    # 1) Etiketler arasindaki METIN. Turkce tasiyan her metin parcasi, kendisi
    #    ya da bir ATASI tarafindan isaretlenmis olmali.
    #
    #    ⚠ Ata kontrolu sart: `data-i18n-rich` tasiyan bir `<p>`nin icinde
    #    `<b>` var ve o `<b>`nin metni ayri bir parca olarak goruluyor. Isaretli
    #    oge TUM icerigini degistirdigi icin altindaki her sey kapsanmis sayilir.
    pos, depth, covered = 0, 0, None
    for m in HTML_TAG.finditer(html):
        text = html[pos:m.start()].strip()
        if text and covered is None and any(ch in TR_CHARS for ch in text):
            print(f"  ! index.html: isaretsiz metin — {' '.join(text.split())[:60]!r}")
            fail += 1
        pos = m.end()

        tag = m.group(0)
        name = re.match(r"</?([\w-]+)", tag)
        if not name or name.group(1) in HTML_VOID:
            continue
        if tag.startswith("</"):
            if covered == depth:
                covered = None
            depth -= 1
        else:
            depth += 1
            if covered is None and ("data-i18n=" in tag or "data-i18n-rich=" in tag):
                covered = depth

    # 2) Nitelikler. Turkce tasiyan her nitelik `data-i18n-attr` icinde anilmali.
    for tag in HTML_TAG.findall(html):
        marks = re.search(r'data-i18n-attr="([^"]*)"', tag)
        listed = {p.split(":")[0] for p in marks.group(1).split("|")} if marks else set()
        for attr in I18N_ATTRS:
            val = re.search(rf'(?<![-\w]){attr}="([^"]*)"', tag)
            if val and any(ch in TR_CHARS for ch in val.group(1)) and attr not in listed:
                print(f"  ! index.html: isaretsiz {attr}= — {val.group(1)[:50]!r}")
                fail += 1

    # 3) Isaretlenen her anahtarin sozlukte KARSILIGI olmali.
    from jsonimager import i18n as I18N

    keys = set(re.findall(r'data-i18n(?:-rich)?="([^"]+)"', html))
    keys |= {p.split(":", 1)[1] for g in re.findall(r'data-i18n-attr="([^"]*)"', html)
             for p in g.split("|") if ":" in p}
    unknown = sorted(k for k in keys if k not in I18N.STRINGS[I18N.DEFAULT_LANG])
    if unknown:
        print(f"  ! index.html: sozlukte olmayan anahtar — {', '.join(unknown[:6])}")
        fail += 1

    # 4) JS dizelerinde cevrilmemis Turkce. Yorumlar HARIC — onlar Turkce
    #    kalabilir (tanimlayicilar Ingilizce, yorumlar Turkce). Bu yuzden once yorumlar
    #    ayiklanir, sonra dize sabitleri aranir.
    fail += _probe_js_scanner()
    for src in sorted((WEB / "js").glob("*.js")):
        for lit in _js_turkish_literals(src.read_text(encoding="utf-8")):
            print(f"  ! {src.name}: cevrilmemis dize — {lit[:60]}")
            fail += 1

    # 4b) ASCII harfli Turkce icin ikinci ag: kullaniciya METIN YAZAN bir
    #     cagrinin ilk argumani dize SABITI ise, o metin `t()`ten gelmiyor
    #     demektir. Olcut TR_CHARS'a bakmaz, dizenin NEREYE gittigine bakar —
    #     `'Kaydedildi: '` boyle yakalandi (bkz. UI_SINK_LIT).
    for src in sorted((WEB / "js").glob("*.js")):
        code = _strip_js_comments(src.read_text(encoding="utf-8"))
        for m in UI_SINK_LIT.finditer(code):
            if LETTERISH.search(m.group(1)[1:-1]):
                line = code[:m.start()].count("\n") + 1
                print(f"  ! {src.name}:{line} — ekrana yazilan dize sabiti: "
                      f"{m.group(1)[:46]}")
                fail += 1

    # 5) Global `t()` cevirici islevini GOLGELEYEN yerel degisken.
    #
    #    ⚠ Tek harflik ad tehlikeli: `const t = document.createElement('b')`
    #    ayni kapsamda `t('anahtar')` cagrisini bozar ve `const` yuzunden hata
    #    "cannot access 't' before initialization" olur — sebebi belli olmayan
    #    bir cokme. Faz 9.2.2'de iki kez yasandi.
    for src in sorted((WEB / "js").glob("*.js")):
        text = src.read_text(encoding="utf-8")
        if src.name == "state.js":
            continue                     # `t` burada TANIMLANIR
        # Hem bildirim (`const t = …`) hem dongu degiskeni (`for (const t of …`).
        for m in re.finditer(r"(?:const|let|var)\s+t\s*(?:=|of\b|in\b)", text):
            line = text[:m.start()].count("\n") + 1
            print(f"  ! {src.name}:{line} — yerel `t` global cevirici islevini golgeliyor")
            fail += 1

    if not fail:
        js_count = len(list((WEB / "js").glob("*.js")))
        print(f"  arayuz metni: index.html'de {len(keys)} anahtar · {js_count} JS "
              "dosyasinda cevrilmemis dize yok · `t` golgelenmiyor")
    return fail


# Ayar aciklamasinin ust siniri (9.17). Aciklama kartin tum genisliginde, adin
# ALTINDA durur; en dar pencerede bir satir ~95 karakter aliyor, yani sinir
# "en cok iki satir" demek. Uzun gerekce ayarlar penceresine degil belgeye aittir.
SET_DESC_MAX = 120
# Aciklama tasiyan ayarlar (9.18, kullanici karari). Liste bir IZIN listesidir:
# herkesin bildigi ayar (dil, tema, yazi tipi…) ad + denetimden ibarettir ve
# aciklama yalnizca kullanicinin BASKA YERDEN BILEMEYECEGI bir sonucu soyleyen
# ayarda durur. Yeni bir aciklama eklemek bu listeyi degistirmeyi gerektirir —
# "her ayara bir cumle" aliskanligi sessizce geri donmesin diye.
SET_DESC_KEYS = {
    "ui.images_url_note",       # ayar aga cikis aciyor; karsi taraf IP'yi gorur (`K-10`)
    "ui.set_desc_keys",         # anahtarin nerede durdugu ve neyin gonderildigi
    "ui.set_desc_custom",       # ne gonderilir, hangi adres kabul edilir (`K-34`)
    "ui.set_desc_restore",      # 9.28 — acikken yollar diske yazilir (gizlilik)
}
_SET_ROW = re.compile(r'<label class="set-row">(.*?)</label>', re.S)
_SET_DESC_KEY = re.compile(r'class="set-desc" data-i18n="([\w.]+)"')


def check_settings_rows() -> int:
    """Ayar satiri kalibi: ad + denetim ayni hizada, aciklama SEYREK (9.17 · 9.18).

    Dort sey olculur: (1) her `set-row` adini ve secicisini tasiyor;
    (2) aciklama yalnizca `SET_DESC_KEYS`teki ayarlarda var — fazlasi da eksigi
    de kirmizi; (3) aciklamalar ve saglayici notlari iki dilde `SET_DESC_MAX`
    karakteri asmiyor; (4) satir bir IZGARA, aciklama italik ve girintisiz.
    Sonuncusu bicim sozlesmesi: esnek kutuya donulurse secici, aciklama
    uzadikca adin hizasindan duser.
    """
    from jsonimager import i18n as I18N
    from jsonimager import providers as P
    html = HTML_COMMENT.sub("", (WEB / "index.html").read_text(encoding="utf-8"))
    fail = 0
    rows = _SET_ROW.findall(html)
    if not rows:
        print("  ! ayar satiri: index.html'de `set-row` bulunamadi")
        return 1
    for body in rows:
        name = re.search(r'class="lbl-txt" data-i18n="([\w.]+)"', body)
        missing = [part for part, found in (
            ("ad", name), ("denetim", re.search(r"<(?:select|input) id=", body)))
            if not found]
        if missing:
            where = name.group(1) if name else body.strip()[:40]
            print(f"  ! ayar satiri `{where}`: eksik parca — {', '.join(missing)}")
            fail += 1

    keys = set(_SET_DESC_KEY.findall(html))
    if keys != SET_DESC_KEYS:
        extra, gone = sorted(keys - SET_DESC_KEYS), sorted(SET_DESC_KEYS - keys)
        print("  ! ayar aciklamasi izin listesinden sapti"
              + (f" — listede olmayan: {', '.join(extra)}" if extra else "")
              + (f" — sayfada olmayan: {', '.join(gone)}" if gone else ""))
        fail += 1
    # Saglayici notlari ayni blogun aciklamasina eklenir; ayni olcuye tabidir.
    notes = sorted({p.note for p in P.PROVIDERS.values() if p.note})
    for lang in I18N.LANGS:
        for key in sorted(keys) + notes:
            size = len(I18N.STRINGS[lang].get(key, ""))
            if not 0 < size <= SET_DESC_MAX:
                print(f"  ! ayar aciklamasi {lang}:{key} — {size} karakter "
                      f"(1..{SET_DESC_MAX} olmali)")
                fail += 1
    # Arayuz ayni notu tasiyan saglayicilari METNE gore tek satirda toplar;
    # bir dilde ayni, otekinde farkli iki not ekranda ayri duzen verirdi.
    shape = {lang: sorted(sorted(p.key for p in P.PROVIDERS.values()
                                 if p.note and I18N.STRINGS[lang].get(p.note) == text)
                          for text in {I18N.STRINGS[lang].get(n) for n in notes})
             for lang in I18N.LANGS}
    if len({repr(v) for v in shape.values()}) > 1:
        print(f"  ! saglayici notlari dillerde farkli gruplaniyor: {shape}")
        fail += 1

    rules = _css_rules((WEB / "style.css").read_text(encoding="utf-8"))
    for selector, want in ((".set-row", "display: grid"),
                           (".set-row > .set-text", "display: contents"),
                           (".set-desc", "font-style: italic"),
                           # Bloklarin icinde kopruden kurulan aciklamalar.
                           (".set-pane .dlg-sub", "font-style: italic")):
        # Ayni secici birden cok kuralda gecer (ortak dolgu + kendi yerlesimi).
        if not any(want in body for sel, body in rules
                   if selector in (s.strip() for s in sel.split(","))):
            print(f"  ! ayar satiri: `{selector}` kurali `{want}` tasimiyor")
            fail += 1
    # Aciklama adla ayni sol hatta baslar: girinti iki ayri hat olusturuyordu.
    indented = [sel.strip() for sel, body in rules
                if ".set-desc" in sel and re.search(r"(padding|margin)(-left)?\s*:", body)]
    if indented:
        print(f"  ! ayar aciklamasi girintili: {' · '.join(indented)}")
        fail += 1

    if not fail:
        print(f"  ayar satirlari: {len(rows)} satir · aciklama yalnizca {len(keys)} ayarda "
              f"+ {len(notes)} saglayici notu × {len(I18N.LANGS)} dil, "
              f"en cok {SET_DESC_MAX} karakter")
    return fail


# Kesfin kaybettigi veri (9.22). Ikisi de SENTETIK ve rol adlariyla yazildi:
# gercek belge kullanicinin ozel dosyasiydi, alan adlari buraya tasinmaz.
COVERAGE_PROBES = {
    # Kokte ust veri + anahtarlari TESADUFEN ortusen iki kucuk nesne + iki
    # kayit dizisi. Eskiden kok pivot sayiliyor, iki dizi hic taranmiyordu.
    "karisik kok": {
        "name": "x", "version": "1", "origin": "y",
        "labels": {"a": "A", "b": "B", "c": "C"},
        "counts": {"total": 3, "a": 1, "b": 1, "c": 1},
        "items": [{"group": "g", "title": f"t{i}", "state": "a"} for i in range(6)],
        "index": [{"id": f"k{i}", "kind": "f", "tags": ["p", "q"]} for i in range(4)],
    },
    # Gercek bir harita (alt nesneler cogunlukta) + yaninda kayit dizisi:
    # harita tablosu korunur, dizi de kendi tablosunu alir.
    "harita + dizi": {
        "tr": {"k1": "a", "k2": "b", "k3": "c", "k4": "d"},
        "en": {"k1": "a", "k2": "b", "k3": "c", "k4": "d"},
        "rows": [{"id": 1, "v": 2}, {"id": 2, "v": 3}],
    },
    # Anahtar-liste dugumu (%80 skaler liste) + kayit dizisi.
    "anahtar-liste + dizi": {
        "a": [1, 2], "b": [3], "c": [4, 5], "d": [6],
        "rows": [{"id": 1}, {"id": 2}],
    },
}
COVERAGE_WANT = {
    "karisik kok": {"$": D.KEYVALUE, "items": D.RECORDS, "index": D.RECORDS},
    "harita + dizi": {"$": D.PIVOT, "rows": D.RECORDS},
    "anahtar-liste + dizi": {"$": D.KEYLIST, "rows": D.RECORDS},
}


def _lost_records(root) -> list[str]:
    """Hicbir tabloda GORUNMEYEN kayit dizileri.

    Dizi gorunur sayilir: kendisi bir veri kumesiyse, ya da onu hucre olarak
    gosteren bir veri kumesinin altindaysa — kayit tablosu ve Anahtar-Deger
    tablosu tum alt dugumlerini hucrede gosterir; harita (anahtarli/pivot)
    yalnizca UYE alt nesnelerini; anahtar-liste yalnizca skaler listelerini.
    """
    datasets = D.discover(root)

    def visible(path: list) -> bool:
        for ds in datasets:
            n = len(ds.path)
            if list(path[:n]) != list(ds.path):
                continue
            if len(path) == n or ds.kind in (D.RECORDS, D.KEYVALUE):
                return True
            node = D.resolve(root, ds.path)
            if ds.kind in (D.KEYED, D.PIVOT) and isinstance(node.get(path[n]), dict):
                return True
        return False

    lost: list[str] = []

    def walk(node, path):
        if D.is_records(node):
            if not visible(path):
                lost.append(D.path_id(path))
            return
        items = node.items() if isinstance(node, dict) else (
            enumerate(node) if isinstance(node, list) else ())
        for k, v in items:
            walk(v, path + [k])

    walk(root, [])
    return lost


def check_discover_coverage() -> int:
    """Kesif belgedeki hicbir kayit dizisini kaybetmiyor mu (9.22)?

    Iki olcu: sentetik sondalar beklenen veri kumelerini BIREBIR veriyor; ve
    elimizdeki her belgede (ornekler + `samples/`) gorunmeyen kayit dizisi yok.
    Ikincisi genel kural: harita ya da anahtar-liste tablosu yalnizca kendi
    uyelerini gosterir, geri kalan kaplar taranmazsa veri sessizce kaybolur.
    """
    out = []
    for name, root in COVERAGE_PROBES.items():
        got = {ds.id: ds.kind for ds in D.discover(root)}
        want = COVERAGE_WANT[name]
        if any(got.get(k) != v for k, v in want.items()):
            out.append(f"sonda '{name}': beklenen {want}, cikan {got}")
        if (lost := _lost_records(root)):
            out.append(f"sonda '{name}': gorunmeyen kayit dizisi — {lost}")
    # Tabloya girmeyen ama kendi tablosunu alan alan "dahil edilmedi" denmemeli.
    mixed = next(ds for ds in D.discover(COVERAGE_PROBES["harita + dizi"]) if ds.id == "$")
    notes = dict(mixed.notes)
    if "rows" in notes.get("ds.note_skipped", {}).get("list", "") or \
            "rows" not in notes.get("ds.note_promoted", {}).get("list", ""):
        out.append(f"harita notu kendi tablosu olan diziyi 'dahil edilmedi' sayiyor — {mixed.notes}")

    files = sorted(EXAMPLES.glob("*.json")) + sorted(SAMPLES.glob("*.json"))
    for path in files:
        try:
            root = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (lost := _lost_records(root)):
            # Ad degil SAYI basilir: `samples/` ozel, dosya adi da bir addir.
            out.append(f"bir belgede {len(lost)} kayit dizisi hicbir tabloda gorunmuyor")
    for msg in out:
        print(f"  ! kesif kapsami: {msg}")
    if not out:
        print(f"  kesif kapsami: {len(COVERAGE_PROBES)} sonda birebir · {len(files)} belgede "
              "gorunmeyen kayit dizisi yok")
    return len(out)


# Ozel saglayicinin adres kurali (9.21, `K-34`): girdi -> beklenen uc nokta.
CUSTOM_OK = {
    "https://servis.example/v1": "https://servis.example/v1/chat/completions",
    "https://servis.example/v1/": "https://servis.example/v1/chat/completions",
    "  https://servis.example/v1  ": "https://servis.example/v1/chat/completions",
    "https://servis.example/v1/chat/completions": "https://servis.example/v1/chat/completions",
    "https://servis.example": "https://servis.example/chat/completions",
    "https://servis.example:8443/api/v1": "https://servis.example:8443/api/v1/chat/completions",
    "http://localhost:11434/v1": "http://localhost:11434/v1/chat/completions",
    "http://127.0.0.1:1234/v1": "http://127.0.0.1:1234/v1/chat/completions",
    "http://[::1]:8080/v1": "http://[::1]:8080/v1/chat/completions",
}
# Reddedilenler: girdi -> hata anahtari. Her satir kuralin bir maddesidir.
CUSTOM_BAD = {
    "http://servis.example/v1": "err.custom_http",           # sifresiz, baska makine
    "http://192.168.1.10:11434/v1": "err.custom_http",       # yerel AG bu bilgisayar degil
    "http://localhost.ornek.example/v1": "err.custom_http",  # ad TAM eslesmeli
    "http://2130706433/v1": "err.custom_http",               # sayiyla yazilmis adres
    "ftp://servis.example/v1": "err.custom_bad",
    "file:///C:/x": "err.custom_bad",
    "servis.example/v1": "err.custom_bad",                   # sema yok
    "https:///v1": "err.custom_bad",                         # sunucu adi yok
    "https://kullanici:parola@servis.example/v1": "err.custom_bad",
    "https://@servis.example/v1": "err.custom_bad",
    "https://servis.example\\@baska.example/v1": "err.custom_bad",
    "https://servis.example/v1?key=abc": "err.custom_bad",   # anahtar adrese yazilmaz
    "https://servis.example/v1#x": "err.custom_bad",
    "https://servis.example/v1 x": "err.custom_bad",
    "https://servis.example:port/v1": "err.custom_bad",
    "https://" + "a" * 400 + ".example/v1": "err.custom_bad",
    "": "err.custom_unset",
    "   ": "err.custom_unset",
}


def _custom_redirect_probe(P) -> list[str]:
    """Gercek acici ile olcum, yalnizca GERI DONGU uzerinde (disari cikmaz).

    Iki yerel sunucu: A yonlendirir, B yanit verir. Dogrudan B'ye giden soru
    yanit almali; A'ya giden soru hata vermeli ve B'ye HIC ulasmamali —
    yonlendirme semayi ve anahtari dogrulanmamis bir adrese tasirdi.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    hits: list[tuple[str, str | None]] = []

    class Answer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            hits.append((self.path, self.headers.get("Authorization")))
            body = json.dumps({"choices": [{"message": {"content": "merhaba"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # ⚠ `urllib` 302'yi izlerken POST'u GET'e cevirir ve `Authorization`
            # basligini YENI adrese tasir: govde gitmez ama anahtar gider.
            # Izlenen bir yonlendirme buraya duser ve sayilir.
            hits.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    class Redirect(BaseHTTPRequestHandler):
        target = ""

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            # 302: `urllib`in POST'ta bile IZLEDIGI kod (307/308'i zaten izlemez).
            self.send_response(302)
            self.send_header("Location", self.target)
            self.send_header("Content-Length", "0")
            self.end_headers()

    out = []
    prov = P.PROVIDERS[P.CUSTOM]
    real_read = P.KEYS.read
    servers = [ThreadingHTTPServer(("127.0.0.1", 0), h) for h in (Answer, Redirect)]
    try:
        for srv in servers:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        b, a = (f"http://127.0.0.1:{s.server_address[1]}/v1" for s in servers)
        Redirect.target = b + "/chat/completions"

        # Anahtarsiz: yanit gelir ve `Authorization` basligi HIC gitmez.
        P.KEYS.read = lambda name: None
        prov.configure(b)
        if prov.ask("soru", "yerel-model", "medium") != "merhaba":
            out.append("yerel sunucudan yanit alinamadi")
        if hits != [("/v1/chat/completions", None)]:
            out.append(f"anahtarsiz istek beklenen gibi gitmedi — {hits}")

        # Anahtarli: baslikta gider.
        P.KEYS.read = lambda name: "sk-yerel"
        prov.ask("soru", "yerel-model", "medium")
        if hits[-1][1] != "Bearer sk-yerel":
            out.append("anahtar baslikta gitmedi")

        # Yonlendirme: hata, ve hedefe ULASILMAZ.
        before = len(hits)
        prov.configure(a)
        try:
            prov.ask("soru", "yerel-model", "medium")
            out.append("yonlendirme izlendi (hata bekleniyordu)")
        except P.ProviderError:
            pass
        if len(hits) != before:
            out.append(f"yonlendirilen istek hedefe ulasti — anahtar tasindi: {hits[-1][1]!r}")
    except Exception as exc:
        out.append(f"geri dongu olcumu yapilamadi — {type(exc).__name__}: {exc}")
    finally:
        P.KEYS.read = real_read
        prov.configure("")
        for srv in servers:
            srv.shutdown()
            srv.server_close()
    return out


def check_custom_provider() -> int:
    """Ozel saglayici (9.21, `K-34`): uygulamanin kullanicinin YAZDIGI adrese ciktigi tek yol.

    Sinir uc yerde olculur:
      kural   — `custom_endpoint` saf; izinli ve reddedilen adreslerin tablosu
                (`CUSTOM_OK` / `CUSTOM_BAD`). http yalnizca bu bilgisayara.
      acici   — gercek istekle, yalnizca geri dongude: anahtar istege bagli ve
                baslikta; yonlendirme izlenmiyor
      kopru   — gecersiz adres yazilmiyor; elle bozulmus ayar KULLANIMDA yine
                reddediliyor; modelsiz saglayici soru sormuyor
    """
    import tempfile
    from jsonimager import i18n as I18N
    from jsonimager import providers as P
    from jsonimager import settings as S
    from jsonimager.app import Api

    out = []
    for raw, want in CUSTOM_OK.items():
        got = P.custom_endpoint(raw)
        if got != (want, ""):
            out.append(f"izinli adres reddedildi ya da yanlis kuruldu — {raw!r} → {got}")
    for raw, want in {**CUSTOM_BAD, None: "err.custom_unset", 5: "err.custom_unset"}.items():
        got = P.custom_endpoint(raw)
        if got != ("", want):
            out.append(f"gecersiz adres kabul edildi ya da sebep yanlis — {str(raw)[:50]!r} → {got}")
    for lang in I18N.LANGS:
        for key in sorted(set(CUSTOM_BAD.values()) | {"err.no_models"}):
            if key not in I18N.STRINGS[lang]:
                out.append(f"{lang}: {key} sozlukte yok")

    prov = P.PROVIDERS[P.CUSTOM]
    if not isinstance(prov, P._HttpProvider) or not prov.key_optional or prov.models():
        out.append("ozel saglayici ortak HTTP govdesini kullanmiyor ya da fabrika listesi var")
    try:
        req = P.urllib.request.Request("https://a.example/v1", data=b"{}", method="POST")
        followed = P._NoRedirect().redirect_request(req, None, 307, "", {}, "https://x.example")
    except Exception:
        followed = "hata"       # izlemeyi deneyen taban uygulama boyle duser
    if followed is not None:
        out.append("yonlendirme kapisi istegi geri veriyor")
    # Kapi ORTAK govdededir: sabit uclu saglayicilar da ayni aciciyi kullanir.
    # Geri dongu olcumu ozel saglayici uzerinden yapiliyor; otekilerin ayri bir
    # yol acmadigi kaynaktan okunur.
    src = (ROOT / "src" / "jsonimager" / "providers.py").read_text(encoding="utf-8")
    if re.search(r"\burlopen\(", src) or len(re.findall(r"def _open\(", src)) != 1:
        out.append("providers.py yonlendirme kapisini atlayan ikinci bir acici iceriyor")
    out += _custom_redirect_probe(P)

    # --- kopru ---------------------------------------------------------------
    opened: list[str] = []
    real = (S.path, P.urllib.request.build_opener, P.urllib.request.urlopen)

    def no_network(*args, **kwargs):
        opened.append("acici")
        raise AssertionError("ag cagrisi beklenmiyordu")

    with tempfile.TemporaryDirectory() as tmp:
        S.path = lambda: Path(tmp) / S.FILE_NAME
        P.urllib.request.build_opener = P.urllib.request.urlopen = no_network
        try:
            doc = Path(tmp) / "belge.json"
            doc.write_text(json.dumps({"rows": [{"id": 1}, {"id": 2}]}), encoding="utf-8")
            api = Api()
            api.open_path(str(doc))

            res = api.agent_endpoint_set("http://baska.example/v1")
            if res.get("ok") or res.get("error") != I18N.t("err.custom_http"):
                out.append("kopru: gecersiz adres icin cevrilmis red donmedi")
            if api._settings["agent"]["custom_url"]:
                out.append("kopru: gecersiz adres ayara yazildi")

            res = api.agent_endpoint_set("  https://servis.example/v1/ ")
            if (not res.get("ok") or res.get("url") != "https://servis.example/v1/"
                    or res.get("endpoint") != "https://servis.example/v1/chat/completions"):
                out.append(f"kopru: gecerli adres yazilamadi — {res}")
            if Api()._settings["agent"]["custom_url"] != "https://servis.example/v1/":
                out.append("kopru: adres diske yazilmadi")

            api._settings["agent"]["provider"] = P.CUSTOM
            st = api.agent_status()
            if st.get("available") or st.get("error") != I18N.t(
                    "err.no_models", provider=I18N.t("provider.custom.label")):
                out.append("kopru: modelsiz saglayici kullanilabilir gorunuyor")
            if api.agent_ask(str(doc), "soru").get("ok"):
                out.append("kopru: modelsiz saglayiciya soru gitti")

            api.agent_model_add(P.CUSTOM, "yerel-model:1")
            st = api.agent_status()
            if not st.get("available") or st.get("model") != "yerel-model:1":
                out.append(f"kopru: model eklenince saglayici acilmadi — {st.get('error')}")

            # Ayar dosyasi elle bozulmus: yazarken yapilan dogrulama onu kapsamaz.
            api._settings["agent"]["custom_url"] = "http://baska.example/v1"
            if api.agent_status().get("available"):
                out.append("kopru: elle bozulmus adres kullanimda reddedilmedi")
            ask = api.agent_ask(str(doc), "soru", "yerel-model:1")
            if ask.get("ok") or ask.get("error") != I18N.t("err.custom_http") or opened:
                out.append(f"kopru: elle bozulmus adrese istek denendi — {opened}")

            if not api.agent_endpoint_set("").get("ok") or api._settings["agent"]["custom_url"]:
                out.append("kopru: bos adres silmiyor")
            if not any(p["key"] == P.CUSTOM for p in api.agent_keys()["providers"]):
                out.append("kopru: ozel saglayicinin anahtar satiri yok")
        finally:
            S.path, P.urllib.request.build_opener, P.urllib.request.urlopen = real
            prov.configure("")

    for msg in out:
        print(f"  ! ozel saglayici: {msg}")
    if not out:
        print(f"  ozel saglayici: {len(CUSTOM_OK)} izinli · {len(CUSTOM_BAD)} reddedilen adres · "
              "http yalnizca bu bilgisayara · anahtar istege bagli ve baslikta · "
              "yonlendirme izlenmiyor (geri dongude olculdu) · bozuk ayar kullanimda da red")
    return len(out)


# Renk ureten kopru metotlari (9.19.3). Her biri govdesini `_out_theme()` icinde
# calistiran ince bir sarmalayicidir; asil is alt cizgili esindedir.
THEMED_OUTPUTS = {
    "api_export.py": ("export_text", "export_image", "scene_svg", "save_drawio", "save_vector"),
    "api_chart.py": ("chart_svg",),
}
# Cizim yiginina giden cagrilar. Public bir kopru metodunda DOGRUDAN gorunurse
# o metot temayi atlamis demektir.
_DRAW_CALL = re.compile(r"\b(?:ITB|ITR|ICH)\.\w+\(|\bVEC\.to_\w+\(|\bT\.table_html\(")


def _prefs_source() -> list[str]:
    """9.19'un kaynakta olculen yarisi: sarmalayicilar, CSS ve arayuz kapisi."""
    import ast
    out = []
    pkg = ROOT / "src" / "jsonimager"
    for name, wanted in THEMED_OUTPUTS.items():
        src = (pkg / name).read_text(encoding="utf-8")
        funcs = {n.name: ast.get_source_segment(src, n) or ""
                 for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}
        for fn in wanted:
            if "with self._out_theme():" not in funcs.get(fn, ""):
                out.append(f"{name}: `{fn}` ciktinin temasini kurmuyor")
        # Listede olmayan ama cizen public metot: yeni bir cikti yolu temasiz acilmis.
        for fn, body in funcs.items():
            if not fn.startswith("_") and _DRAW_CALL.search(body):
                out.append(f"{name}: public `{fn}` cizimi dogrudan cagiriyor (sarmalayici degil)")

    css = (WEB / "style.css").read_text(encoding="utf-8")
    pad = _css_prop(css, "tbody td", "padding") or ""
    if not pad.strip().startswith("var(--cell-pad-y)"):
        out.append(f"`tbody td` dolgusu yogunlugu izlemiyor: {pad!r}")
    if not re.search(r':root\[data-agent="off"\]\s+#btn-claude\s*\{\s*display:\s*none', css):
        out.append("Agent kapaliyken dugmesini gizleyen CSS kurali yok")
    agent_js = (WEB / "js" / "agent.js").read_text(encoding="utf-8")
    if not re.search(r"if \(open && !agentOn\) return;", agent_js):
        out.append("`setDock` kapali Agent'i aciyor (kapi yok)")
    return out


def check_search_output() -> int:
    """Transpozede alan aramasi ciktiya da yansir (9.29) — gecici klasorde.

    Arama mantigi JS'tedir (Node yok, tarayicida sinanir); burada yalnizca
    koprunun yarisi olculur: gorunumdeki `searchHidden` her ciktinin ortak
    yolundan (`_table_for_output`) gizlenir, kullanicinin `hidden`ina
    karismaz, bozuk deger yok sayilir.
    """
    import tempfile
    from jsonimager.app import Api
    out: list[str] = []
    src = {"rows": [{"id": "AQ1", "kind": "x"}, {"id": "BQ2", "kind": "y"},
                    {"id": "CQ3", "kind": "x"}]}
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "belge.json"
        p.write_text(json.dumps(src), encoding="utf-8")
        api = Api()
        api._load_one(p)
        d = str(p)
        api.set_transpose(d, "rows", None, True)
        view = api.table(d, "rows")["view"]
        rec = [c["key"] for c in api.table(d, "rows")["table"]["columns"]][1:]
        api.set_view(d, "rows", None, {**view, "searchHidden": [rec[1]]}, True)
        csv_text = api.export_text("csv", d, "rows", None, None, None).get("text", "")
        if "BQ2" in csv_text or "AQ1" not in csv_text or "CQ3" not in csv_text:
            out.append("aramanin gizledigi kayit metin ciktisinda duruyor")
        stored = api._views[api._key(d, "rows", None) + "|T"]
        if stored.get("hidden") != view.get("hidden"):
            out.append("arama kullanicinin gizli sutun listesine yazildi")
        api.set_view(d, "rows", None, {**view, "searchHidden": "bozuk"}, True)
        if "BQ2" not in api.export_text("csv", d, "rows", None, None, None).get("text", ""):
            out.append("bozuk `searchHidden` ciktiyi etkiledi")
    if out:
        for o in out:
            print(f"  ! arama ciktisi: {o}")
        return len(out)
    print("  arama ciktisi: transpozede suzulen kayit ciktida yok · kullanicinin gizlileri "
          "ayri · bozuk deger yok sayiliyor")
    return 0


def check_agent_values() -> int:
    """Agent'a veri gonderimi (9.27, `K-14` istisnasi) — sinir davranisla olculur.

    Sahte saglayici istemi yakalar; aga cikilmaz, gercek ayar dosyasina dokunulmaz.
      - kapali (varsayilan) ve bozuk deger (`"evet"`): baglam gelse de TEK deger
        gitmez; baslik ayarin GERCEK adini anar (model kullaniciyi oraya yollar)
      - acik: yalnizca SECILI tablo; satir sirasi arayuzun `rows`u; en fazla
        `VALUE_ROWS` satir ve kesilince not; gizli sutun gitmez; gorsel gitmez
      - gecersiz baglam (baska tablo kimligi, sayi olmayan satir) degersiz duser
      - karakter siniri uzun metinde de tutar
      - `agent_status().values` ayari izler (seritteki isaret)
    """
    import base64
    import io as _io
    import tempfile
    from PIL import Image
    from jsonimager import api_agent as AA
    from jsonimager import i18n as I18N
    from jsonimager import providers as P
    from jsonimager import settings as S
    from jsonimager.app import Api

    class _Catch(P.Provider):
        key = "probe927"
        needs_key = False
        prompts: list[str] = []

        def models(self) -> list[str]:
            return ["m"]

        def available(self) -> tuple[bool, str]:
            return True, ""

        def ask(self, prompt: str, model: str, effort: str) -> str:
            self.prompts.append(prompt)
            return "yanit"

    buf = _io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
    png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    n = AA.VALUE_ROWS + 20
    src = {"items": [{"id": i, "name": f"deger-{i:03d}-XQ", "pic": png} for i in range(n)],
           "other": [{"code": f"BASKA-{i}-ZK", "k": i} for i in range(3)],
           # Isaret BASTA: hucre `export_text.MAX_CELL`te kirpiliyor.
           "notes": [{"id": i, "body": f"N{i:03d} " + "uzun " * 70} for i in range(n)]}
    out: list[str] = []
    real = (S.path, S.session_path)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        S.path = lambda: base / S.FILE_NAME
        S.session_path = lambda: base / S.SESSION_NAME
        P.PROVIDERS[_Catch.key] = _Catch()
        try:
            doc = base / "belge.json"
            doc.write_text(json.dumps(src), encoding="utf-8")
            api = Api()
            api._load_one(doc)
            api._settings["agent"]["provider"] = _Catch.key
            d = str(doc)

            def ask(ctx, values=None):
                if values is not None:
                    api._settings["agent"]["send_values"] = values
                _Catch.prompts.clear()
                r = api.agent_ask(d, "soru", None, None, ctx)
                return _Catch.prompts[0] if r.get("ok") and _Catch.prompts else ""

            whole = {"ds": "items", "variant": None, "rows": None}
            for label, val in (("varsayilan", None), ("bozuk deger", "evet")):
                if val is None:
                    api._settings["agent"].pop("send_values", None)
                p = ask(whole, val)
                if not p or "XQ" in p or "ZK" in p or I18N.t("ui.agent_values") not in p:
                    out.append(f"{label}: deger gitti ya da baslik ayari anmiyor")
            if api.agent_status().get("values") is not False:
                out.append("durum: kapaliyken `values` acik")

            p = ask(whole, True)
            rows = re.findall(r"deger-(\d{3})-XQ", p)
            if rows != [f"{i:03d}" for i in range(AA.VALUE_ROWS)]:
                out.append(f"acik: satir siniri ya da sirasi yanlis ({len(rows)} satir)")
            if I18N.t("prompt.values_cut", sent=AA.VALUE_ROWS, total=n) not in p:
                out.append("acik: kesilen tabloda not yok")
            if "ZK" in p:
                out.append("acik: secili olmayan tablonun degeri gitti")
            if "base64" in p or "iVBOR" in p or I18N.t("agent.image_cell") not in p:
                out.append("acik: gorsel verisi gitti ya da yer tutucu yok")
            if not p.startswith(I18N.t("prompt.header_values")):
                out.append("acik: baslik degerli istem basligi degil")
            if api.agent_status().get("values") is not True:
                out.append("durum: acikken `values` kapali")

            p = ask({"ds": "items", "variant": None, "rows": [5, 3]})
            if re.findall(r"deger-(\d{3})-XQ", p) != ["005", "003"]:
                out.append("acik: arayuzun satir sirasi izlenmedi")

            for label, ctx in (("baska tablo", {"ds": "yok", "rows": None}),
                               ("sayi olmayan satir", {"ds": "items", "rows": ["1"]}),
                               ("baglam yok", None)):
                p = ask(ctx)
                if not p or "XQ" in p:
                    out.append(f"gecersiz baglam ({label}): deger gitti")

            view = api.table(d, "items")["view"]
            api.set_view(d, "items", None, {**view, "hidden": ["name"]})
            if "XQ" in ask(whole):
                out.append("acik: gizli sutunun degeri gitti")

            # Uzun metin sutunu kendiliginden gizlenir; sinir ACIK sutunda olculur.
            nv = api.table(d, "notes")["view"]
            api.set_view(d, "notes", None,
                         {**nv, "hidden": [], "autoHidden": [], "longHidden": []})
            p = ask({"ds": "notes", "variant": None, "rows": None})
            block = p.split("\n---\n")[2] if p.count("\n---\n") >= 3 else p
            sent = re.findall(r"N(\d{3})", p)
            if len(block) > AA.VALUE_CHARS + 500 or not 0 < len(sent) < AA.VALUE_ROWS:
                out.append(f"karakter siniri tutmadi ({len(block)} krk, {len(sent)} satir)")
        finally:
            S.path, S.session_path = real
            P.PROVIDERS.pop(_Catch.key, None)
    if out:
        for o in out:
            print(f"  ! Agent veri gonderimi: {o}")
        return len(out)
    print(f"  Agent veri gonderimi: kapali/bozuk deger hic gondermiyor · acikken yalnizca secili "
          f"tablo, ekran sirasi, {AA.VALUE_ROWS} satir / {AA.VALUE_CHARS:,} krk · gizli sutun "
          "ve gorsel yok · gecersiz baglam degersiz")
    return 0


def check_prefs() -> int:
    """Bes tercih (9.19): yogunluk · uzun metin · cikti temasi · Agent · son oturum.

    Ortak sozlesme: ayar `settings.DEFAULTS`ta durur, `_apply_prefs` /
    `_after_change` ile surece uygulanir ve EKRAN ile CIKTI ayni yaniti alir.
    Her birimin kendi siniri var ve hepsi davranisla olculur:
      yogunluk    — `normal` eski formulle ayni; uc deger sirali; cizim de izliyor
      uzun metin  — kapaliyken hicbir sutun sarilmaz ama `long` (icerik) degismez;
                    "uzun metin" diye gizlenen sutun geri acilir
      cikti temasi — sabitleme blok ve IS PARCACIGI ile sinirli; uygulamanin
                    temasi degismez
      Agent       — kapaliyken kopru soruyu reddeder, saglayiciya HIC dokunmaz
      son oturum  — kapaliyken diske yol yazilmaz; acilista bir kez geri yuklenir;
                    kapatilinca dosya silinir
    Gercek ayar ve oturum dosyasina dokunmaz (gecici klasor).
    """
    import tempfile
    import threading
    from jsonimager import api_docs as AD
    from jsonimager import i18n as I18N
    from jsonimager import providers as P
    from jsonimager import settings as S
    from jsonimager.app import Api

    out = _prefs_source()
    state = (TH.get_theme(), TH.get_density(), TH.get_size())

    # --- 9.19.1 yogunluk ---------------------------------------------------
    probe = {"rows": [{"id": i, "v": i * 2} for i in range(5)]}
    ds = D.discover(probe)[0]
    for size in (TH.FONT_SIZES[0], TH.FONT_SIZES[-1]):
        TH.set_size(size)
        got, heights = {}, {}
        for name in TH.DENSITIES:
            TH.set_density(name)
            got[name] = TH.metrics()
            heights[name] = ITB.table_scene(F.build_table(probe, ds), None, None,
                                            title="t", subtitle="s").h
            if got[name].cell_pad_y != TH.CELL_PAD_Y[name]:
                out.append(f"yogunluk {name}: dolgu olcuye yansimiyor")
        if got["normal"].row_h != size * 2 + 2:
            out.append(f"`normal` yogunluk eski satir yuksekligini vermiyor ({size} px)")
        if not got["compact"].row_h < got["normal"].row_h < got["comfortable"].row_h:
            out.append(f"yogunluk sirali degil ({size} px)")
        if got["compact"].row_h < size + 4:
            out.append(f"siki satir metni sigdirmiyor ({size} px: {got['compact'].row_h})")
        if not heights["compact"] < heights["normal"] < heights["comfortable"]:
            out.append(f"cizim yogunlugu izlemiyor ({size} px: {heights})")
    if TH.set_density("yok") != TH.DENSITY_DEFAULT:
        out.append("taninmayan yogunluk varsayilana dusmuyor")
    TH.set_density(state[1])
    TH.set_size(state[2])

    # --- 9.19.2 uzun metin (saf yarisi) -------------------------------------
    wide = {"rows": [{"id": i, "kind": "a" if i % 2 else "b", "n": i, "m": i * 3,
                      "flag": bool(i % 2), "code": f"k{i}", "at": f"2026-01-0{i + 1}",
                      "text": "kelime " * 40} for i in range(6)]}
    wds = D.discover(wide)[0]
    on, off = F.build_table(wide, wds), F.build_table(wide, wds, wrap=False)
    if [c["key"] for c in on["columns"] if c.get("wrap")] != ["text"]:
        out.append("uzun metin: sarma acikken uzun sutun isaretlenmedi")
    if any(c.get("wrap") for c in off["columns"]):
        out.append("uzun metin: sarma kapaliyken sarilan sutun var")
    if [c.get("long") for c in on["columns"]] != [c.get("long") for c in off["columns"]]:
        out.append("uzun metin: `long` (icerik) cizim tercihine gore degisiyor")
    roles = [[c["key"] for c in CD.chart_roles(t)["excluded"]] for t in (on, off)]
    if roles[0] != roles[1]:
        out.append(f"uzun metin: grafik adaylari tercihe gore degisiyor — {roles}")

    # --- 9.19.3 cikti temasi (saf yarisi) -----------------------------------
    TH.set_theme("dark")
    with TH.using("light"):
        seen: list[str] = []
        th = threading.Thread(target=lambda: seen.append(TH.get_theme()))
        th.start()
        th.join()
        if TH.get_theme() != "light" or TH.active().bg != TH.PALETTES["light"]["bg"]:
            out.append("cikti temasi: blok icinde palet degismiyor")
        if seen != ["dark"]:
            out.append(f"cikti temasi: sabitleme baska is parcacigina sizdi — {seen}")
        with TH.using(TH.EXPORT_APP):
            if TH.get_theme() != "light":
                out.append("cikti temasi: ic ice `app` dis blogu bozdu")
    with TH.using("bozuk"):
        if TH.get_theme() != "dark":
            out.append("cikti temasi: taninmayan ad uygulamanin temasini bozdu")
    if TH.get_theme() != "dark":
        out.append("cikti temasi: bloktan sonra uygulamanin temasi geri gelmedi")

    # --- kopru (gecici ayar + gecici oturum) --------------------------------
    class _Count(P.Provider):
        """Aga cikmayan saglayici: her dokunusu sayar."""

        key = "probe919"
        needs_key = False
        calls: list[str] = []

        def models(self) -> list[str]:
            return ["m"]

        def available(self) -> tuple[bool, str]:
            self.calls.append("available")
            return True, ""

        def ask(self, prompt: str, model: str, effort: str) -> str:
            self.calls.append("ask")
            return "yanit"

    real = (S.path, S.session_path)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        S.path = lambda: base / S.FILE_NAME
        S.session_path = lambda: base / S.SESSION_NAME
        P.PROVIDERS[_Count.key] = _Count()
        try:
            docs = []
            for name in ("bir.json", "iki.json"):
                p = base / name
                p.write_text(json.dumps(wide), encoding="utf-8")
                docs.append(str(p))
            session = base / S.SESSION_NAME

            api = Api()
            # 9.19.5 — kapaliyken (varsayilan) diske yol YAZILMAZ.
            api.open_path(docs[0])
            if session.exists():
                out.append("son oturum: ayar kapaliyken yollar diske yazildi")
            ds_id = api._docs[docs[0]]["datasets"][0].id

            # 9.19.2 — "uzun metin" diye gizlenen sutun sarma kapaninca geri gelir.
            view = api.table(docs[0], ds_id)["view"]
            if "text" not in view["longHidden"]:
                out.append("uzun metin: sonda sutun varsayilan olarak gizlenmedi (sonda bozuk)")
            api.settings_set({"table": {"wrap": False}})
            res = api.table(docs[0], ds_id)
            if "text" in res["view"]["hidden"] or res["view"]["longHidden"]:
                out.append("uzun metin: sarma kapaninca gizli sutun geri acilmadi")
            if any(c.get("wrap") for c in res["table"]["columns"]):
                out.append("uzun metin: ayar kopruden tabloya ulasmiyor")
            api.settings_set({"table": {"wrap": True}})

            # 9.19.3 — cikti sabitlenen temada, uygulama kendi temasinda kalir.
            api.settings_set({"theme": "dark", "export": {"theme": "light"}})
            svg = api.scene_svg("table", docs[0], ds_id).get("svg", "")
            light, dark = TH.PALETTES["light"]["bg"], TH.PALETTES["dark"]["bg"]
            if light not in svg or dark in svg:
                out.append("cikti temasi: sahne sabitlenen temada cizilmedi")
            if TH.get_theme() != "dark" or api._shell()["theme"] != "dark":
                out.append("cikti temasi: cikti uygulamanin temasini degistirdi")
            api.settings_set({"export": {"theme": "app"}})
            if dark not in api.scene_svg("table", docs[0], ds_id).get("svg", ""):
                out.append("cikti temasi: `app` uygulamanin temasini izlemiyor")

            # 9.19.4 — kapali Agent: kopru reddeder, saglayiciya dokunulmaz.
            api._settings["agent"]["provider"] = _Count.key
            api.settings_set({"agent": {"enabled": False}})
            st = api.agent_status()
            ask = api.agent_ask(docs[0], "soru")
            if st.get("available") or st.get("enabled") is not False or not st.get("error"):
                out.append(f"Agent: kapaliyken durum acik gorunuyor — {st.get('available')}")
            if ask.get("ok") or ask.get("error") != I18N.t("err.agent_off"):
                out.append("Agent: kapaliyken soru reddedilmedi")
            if _Count.calls:
                out.append(f"Agent: kapaliyken saglayiciya dokunuldu — {_Count.calls}")
            if api._shell()["agent"] is not False:
                out.append("Agent: kabuk sunumu kapaliligi tasimiyor")
            api.settings_set({"agent": {"enabled": True}})
            api.agent_status()
            if not api.agent_ask(docs[0], "soru").get("ok") or "ask" not in _Count.calls:
                out.append("Agent: yeniden acilinca soru gitmiyor")

            # 9.19.5 — acilinca o anki oturum yazilir, her degisiklikte guncellenir.
            api.settings_set({"documents": {"restore": True}})
            if S.load_session()["docs"] != [docs[0]]:
                out.append("son oturum: ayar acilinca acik belge yazilmadi")
            api.open_path(docs[1])
            api.close_doc(docs[0])
            if S.load_session()["docs"] != [docs[1]]:
                out.append(f"son oturum: ac/kapa izlenmiyor — {S.load_session()['docs']}")

            # Yeni surec: belge geri gelir, ornek belge AYRICA acilmaz.
            fresh = Api()
            fresh.startup()
            if list(fresh._docs) != [docs[1]]:
                out.append(f"son oturum: acilista geri yuklenmedi — {len(fresh._docs)} belge")
            # Ayni surecte ikinci `startup` (sayfa yenileme) geri YUKLEMEZ.
            fresh.close_doc(docs[1])
            S.save_session([docs[1]], [])
            fresh.startup()
            if docs[1] in fresh._docs:
                out.append("son oturum: sayfa yenilemesi kapatilan belgeyi geri getirdi")

            # Olmayan yol ve ag yolu atlanir, acilis dusmez.
            S.save_session([str(base / "yok.json"), "\\\\sunucu\\pay\\x.json", docs[0]], [])
            other = Api()
            other.startup()
            if list(other._docs) != [docs[0]]:
                out.append("son oturum: olmayan/ag yolu atlanmadi")
            if not AD._is_unc("\\\\sunucu\\pay\\x.json") or AD._is_unc(docs[0]):
                out.append("son oturum: ag yolu ayrimi yanlis")

            # Bozuk dosya bos oturumdur; dize olmayan oge alinmaz.
            session.write_text("{bozuk", encoding="utf-8")
            if S.load_session() != {"docs": [], "folders": []}:
                out.append("son oturum: bozuk dosya bos oturum vermedi")
            session.write_text(json.dumps({"docs": [1, None, "a"], "folders": "x"}),
                               encoding="utf-8")
            if S.load_session() != {"docs": ["a"], "folders": []}:
                out.append("son oturum: dize olmayan ogeler suzulmedi")

            # Kapatilinca yollar diskte KALMAZ — sifirlamada da.
            other.settings_set({"documents": {"restore": False}})
            if session.exists():
                out.append("son oturum: ayar kapaninca dosya silinmedi")
            other.settings_set({"documents": {"restore": True}})
            other.settings_reset()
            if session.exists():
                out.append("son oturum: sifirlama dosyayi birakti")
        finally:
            S.path, S.session_path = real
            P.PROVIDERS.pop(_Count.key, None)
            TH.set_theme(state[0])
            TH.set_density(state[1])
            TH.set_size(state[2])

    for msg in out:
        print(f"  ! tercihler: {msg}")
    if not out:
        print(f"  tercihler: {len(TH.DENSITIES)} yogunluk cizimle birlikte · uzun metin "
              "ayari tabloya ve gizli sutuna · cikti temasi is parcacigina ozel, "
              f"{sum(map(len, THEMED_OUTPUTS.values()))} cikti yolu sarili · kapali Agent "
              "saglayiciya dokunmuyor · son oturum yalnizca acikken diskte")
    return len(out)


# i18n gocu TAMAMLANMIS moduller. Liste her alt birimde buyur ve "bitti"nin
# tanimi budur: modul buraya girdikten sonra icine Turkce dize yazilamaz.
PY_I18N_DONE = {
    "api_agent.py", "api_chart.py", "api_docs.py", "api_export.py",
    "api_settings.py", "api_table.py", "app.py", "chart_data.py", "columns.py",
    "discover.py", "draw.py", "export_text.py", "flatten.py", "images.py",
    "img_chart.py", "img_table.py", "img_tree.py", "keys.py", "paths.py",
    "providers.py", "schema.py", "settings.py", "theme.py", "vector.py",
}

# VERI sozlukleri — icerikleri ekran metni degil, belgedeki alan adlariyla
# eslesen ANAHTAR KELIMELERDIR. Turkce olmalari zorunlu: Turkce adli alanlari
# (`tür`, `aşama`) taniyan sinyal budur. Cevirmek siniflandirmayi bozardi.
PY_I18N_DATA = {
    "columns.py": {"_CAT_WORDS", "_ID_EXACT", "_ID_SUFFIX"},
}


def check_py_strings() -> int:
    """Tasinmis Python modullerinde cevrilmemis Turkce dize kaldi mi?

    ⚠ Docstring'ler ve yorumlar HARIC — onlar Turkce kalabilir (global dil
    kurali). Ayrim `ast` ile yapilir: docstring bir govdenin ILK ifadesidir,
    duz metinle ayirt edilemezdi.

    Denetim yalnizca `PY_I18N_DONE` listesindekilere bakar; goc surerken
    denetimin surekli kirmizi kalmasi, gercek bir gerilemeyi gorunmez yapardi.
    """
    import ast

    fail = 0
    for src in sorted((ROOT / "src" / "jsonimager").glob("*.py")):
        if src.name not in PY_I18N_DONE:
            continue
        tree = ast.parse(src.read_text(encoding="utf-8"))
        skip = _docstring_ids(tree)

        # VERI sozlukleri: adi listede olan atamanin ALTINDAKI her dize atlanir.
        data_names = PY_I18N_DATA.get(src.name, set())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id in data_names
                       for t in node.targets):
                continue
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    skip.add(id(sub))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in skip:
                continue
            if any(ch in TR_CHARS for ch in node.value):
                text = " ".join(node.value.split())[:52]
                print(f"  ! {src.name}:{node.lineno} — cevrilmemis dize: {text!r}")
                fail += 1
                continue

            # ASCII harfli Turkce icin ikinci ag: bosluklu ve en az uc harfli
            # bir dize CUMLEDIR ve kullaniciya gidiyor olabilir. Bicim ureten
            # modullerde bu olcut ise yaramaz (PDF/SVG/CSS parcalari cumleye
            # benziyor: olculdu, 83 yanlis alarm), onlar haric tutulur.
            if (src.name not in PY_MARKUP and node.value != APP_NAME
                    and " " in node.value.strip()
                    and len(LETTERISH.findall(node.value)) >= 3):
                text = " ".join(node.value.split())[:52]
                print(f"  ! {src.name}:{node.lineno} — sozluge girmemis cumle: {text!r}")
                fail += 1

    if not fail:
        total = len(list((ROOT / "src" / "jsonimager").glob("*.py")))
        print(f"  python metni: {len(PY_I18N_DONE)}/{total} modul tasindi · "
              "docstring disinda cevrilmemis dize yok")
    return fail


# --- Ayar dosyasi (Faz 9.1) ------------------------------------------------

def check_settings() -> int:
    """Ayar yukleme/kaydetme sozlesmesi.

    GECICI klasorde calisir: kullanicinin gercek `%APPDATA%` ayarlarina
    dokunulmaz. Denetlenen dort davranis da sessizce bozulabilecek turden —
    hicbiri istisna firlatmadigi icin fark edilmezler.
    """
    import tempfile

    from jsonimager import settings as S

    fail = 0
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "settings.json"

        # 1) Dosya yokken varsayilan doner ve DISKE YAZMAZ — kullanici hicbir
        #    sey degistirmediyse ortada dosya da olmamali.
        if S.load(target) != S.defaults():
            print("  ! ayarlar: dosya yokken varsayilan donmedi")
            fail += 1
        if target.exists():
            print("  ! ayarlar: salt okuma diske dosya yazdi")
            fail += 1

        # 2) Gidis-donus: kaydedilen deger aynen geri okunmali.
        data = S.defaults()
        data["theme"] = "light"
        data["font"]["size"] = 15
        S.save(data, target)
        again = S.load(target)
        if again["theme"] != "light" or again["font"]["size"] != 15:
            print("  ! ayarlar: gidis-donus degeri korumadi")
            fail += 1

        # 3) Tipi tutmayan deger varsayilana duser, BILINMEYEN anahtar korunur.
        target.write_text(json.dumps({
            "version": 1,
            "theme": 42,                       # str olmali
            "font": {"size": "buyuk"},         # sayi olmali
            "images": {"allow_url": "evet"},   # bool olmali
            "gelecek_anahtar": {"a": 1},       # bilinmiyor: korunmali
        }), encoding="utf-8")
        mixed = S.load(target)
        if mixed["theme"] != S.DEFAULTS["theme"]:
            print("  ! ayarlar: tipi tutmayan deger varsayilana dusmedi")
            fail += 1
        if mixed["font"]["size"] != S.DEFAULTS["font"]["size"]:
            print("  ! ayarlar: ic sozlukte tip denetimi calismadi")
            fail += 1
        if mixed["images"]["allow_url"] is not False:
            print("  ! ayarlar: bool alanina metin yazilabildi")
            fail += 1
        if "gelecek_anahtar" not in mixed:
            print("  ! ayarlar: bilinmeyen anahtar silindi")
            fail += 1

        # 4) Bozuk dosya: karantinaya alinir, varsayilanla devam edilir ve
        #    ISTISNA FIRLATILMAZ — kullanici belgesini acamaz hale gelmemeli.
        target.write_text("{ bu gecerli json degil", encoding="utf-8")
        try:
            broken = S.load(target)
        except Exception as exc:
            print(f"  ! ayarlar: bozuk dosya istisna firlatti — {exc}")
            return fail + 1
        if broken != S.defaults():
            print("  ! ayarlar: bozuk dosyadan sonra varsayilana donulmedi")
            fail += 1
        if not (Path(tmp) / S.BACKUP_NAME).is_file():
            print("  ! ayarlar: bozuk dosya karantinaya alinmadi")
            fail += 1

    if not fail:
        print(f"  ayarlar: {len(S.DEFAULTS)} anahtar · gidis-donus, tip, "
              "bilinmeyen anahtar ve bozuk dosya sinandi")
    return fail


# --- Anahtar deposu (Faz 9.5.2) --------------------------------------------

def check_keys() -> int:
    """API anahtari deposunun sozlesmesi.

    ⚠ En onemli kontrol ucuncusu: **anahtar diskte duz metin gecmemeli**.
    Sifrelemenin sessizce devre disi kalmasi (DPAPI cagrisinin basarisiz olup
    yutulmasi, base64'un sifreleme sanilmasi) hicbir yerde hata uretmez —
    dosyaya bakmadan fark edilmez. Digerleri de ayni turden: hepsi sessizce
    bozulabilecek davranislar.

    GECICI klasorde calisir; kullanicinin gercek anahtarlarina dokunulmaz.
    """
    import tempfile

    from jsonimager import keys as K

    if not K.available():
        print("  anahtar deposu: DPAPI yok, atlandi")
        return 0

    fail = 0
    secret = "sk-test-0123456789-ABCDEF"
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / K.FILE_NAME

        # 1) Dosya yokken bos liste doner ve DISKE YAZMAZ.
        if K.names(target) != [] or K.read("gemini", target) is not None:
            print("  ! anahtarlar: dosya yokken bos donmedi")
            fail += 1
        if target.exists():
            print("  ! anahtarlar: salt okuma diske dosya yazdi")
            fail += 1

        # 2) Gidis-donus: kaydedilen anahtar aynen geri okunmali.
        K.store("gemini", secret, target)
        if K.read("gemini", target) != secret:
            print("  ! anahtarlar: gidis-donus degeri korumadi")
            fail += 1
        if K.names(target) != ["gemini"] or not K.has("gemini", target):
            print("  ! anahtarlar: kayitli ad listede gorunmedi")
            fail += 1

        # 3) DISKTE DUZ METIN YOK. Hem ham bayt hem base64 cozulmus icerik
        #    aranir: ikincisi olmadan "base64'ledim" sifreleme sanilabilirdi.
        blob = target.read_bytes()
        decoded = b""
        try:
            stored = json.loads(blob.decode("utf-8"))["gemini"]
            decoded = base64.b64decode(stored, validate=True)
        except Exception as exc:
            print(f"  ! anahtarlar: kap okunamadi — {exc}")
            fail += 1
        needle = secret.encode("utf-8")
        if needle in blob or needle in decoded:
            print("  ! anahtarlar: anahtar diskte DUZ METIN duruyor")
            fail += 1

        # 4) Bos deger reddedilir ve diski DEGISTIRMEZ.
        before = target.read_bytes()
        try:
            K.store("groq", "   ", target)
            print("  ! anahtarlar: bos deger kabul edildi")
            fail += 1
        except K.KeyStoreError:
            pass
        if target.read_bytes() != before:
            print("  ! anahtarlar: reddedilen kayit diske dokundu")
            fail += 1

        # 5) Gecersiz ad bir CAGIRAN hatasidir: cevrilmis mesaj degil, ValueError.
        try:
            K.store("Gemini API!", secret, target)
            print("  ! anahtarlar: gecersiz ad kabul edildi")
            fail += 1
        except ValueError:
            pass

        # 6) Cozulemeyen girdi: `read` None doner, liste adi YINE gosterir ve
        #    istisna cikmaz. Silmek, yanlis hesapla acilmis bir oturumda
        #    kurtarilabilir kaydi yok ederdi.
        target.write_text(json.dumps({
            "gemini": "bu-gecerli-bir-blob-degil",
        }), encoding="utf-8")
        try:
            if K.read("gemini", target) is not None:
                print("  ! anahtarlar: bozuk blob cozulmus gibi donduruldu")
                fail += 1
        except Exception as exc:
            print(f"  ! anahtarlar: bozuk blob istisna firlatti — {exc}")
            fail += 1
        if K.names(target) != ["gemini"]:
            print("  ! anahtarlar: cozulemeyen kayit sessizce silindi")
            fail += 1

        # 7) Son anahtar silinince dosya da KALKAR: geride bos bir kap birakmak
        #    kullaniciya hala bir sey saklandigini dusundururdu.
        K.clear("gemini", target)
        if target.exists():
            print("  ! anahtarlar: bosalan kap diskte kaldi")
            fail += 1

        # 8) Bozuk kap: karantinaya alinir, ISTISNA FIRLATILMAZ.
        target.write_text("{ bu gecerli json degil", encoding="utf-8")
        try:
            broken = K.names(target)
        except Exception as exc:
            print(f"  ! anahtarlar: bozuk dosya istisna firlatti — {exc}")
            return fail + 1
        if broken != []:
            print("  ! anahtarlar: bozuk dosyadan sonra bos liste donmedi")
            fail += 1
        if not (Path(tmp) / K.BACKUP_NAME).is_file():
            print("  ! anahtarlar: bozuk dosya karantinaya alinmadi")
            fail += 1

    if not fail:
        print("  anahtar deposu: DPAPI gidis-donusu, duz metin yoklugu, "
              "bozuk blob ve bozuk kap sinandi")
    return fail


def check_key_bridge() -> int:
    """Anahtar kopru metotlari — SENTETIK bir saglayiciyla (Faz 9.5.2.2).

    ⚠ Sonda, `9.5.3` gercek saglayicilari getirdikten SONRA da duruyor ve
    sebebi degisti: yazma/silme yolu artik gercek bir saglayiciyla sinanabilir
    ama o zaman denetim kullanicinin GERCEK anahtarina bagimli olurdu —
    Gemini anahtari kayitli bir makinede gecer, kayitsizda baska davranirdi.
    Sentetik saglayici denetimi makineden bagimsiz tutuyor.

    ⚠ Kap GECICI klasore alinir (`keys.path` yamanir): denetim kullanicinin
    gercek anahtarlarina dokunmamali.
    """
    import tempfile

    from jsonimager import api_agent as AG      # noqa: F401 — yama hedefi degil
    from jsonimager import keys as K
    from jsonimager import providers as P
    from jsonimager.app import Api

    if not K.available():
        print("  anahtar koprusu: DPAPI yok, atlandi")
        return 0

    class _Probe(P.Provider):
        key = "probe"
        needs_key = True

        def models(self) -> list[str]:
            return ["probe-model"]

        def available(self) -> tuple[bool, str]:
            return True, ""

        def ask(self, prompt: str, model: str, effort: str) -> str:
            return ""

    fail = 0
    secret = "sk-bridge-9876543210-ZYXW"
    real_path = K.path
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / K.FILE_NAME
        K.path = lambda: target
        P.PROVIDERS["probe"] = _Probe()
        try:
            api = Api()

            def row():
                return next((p for p in api.agent_keys()["providers"]
                             if p["key"] == "probe"), None)

            # 1) Anahtar isteyen saglayici listede, anahtar istemeyen DEGIL.
            listed = {p["key"] for p in api.agent_keys()["providers"]}
            if "probe" not in listed:
                print("  ! anahtar koprusu: anahtar isteyen saglayici listede yok")
                fail += 1
            if P.CLI in listed:
                print("  ! anahtar koprusu: anahtar istemeyen saglayici listelendi")
                fail += 1
            if (row() or {}).get("saved") is not False:
                print("  ! anahtar koprusu: kayitsiz saglayici 'kayitli' gorundu")
                fail += 1

            # 2) Yazma: kaydedilir ve durum degisir.
            res = api.agent_key_set("probe", secret)
            if not res.get("ok") or (row() or {}).get("saved") is not True:
                print(f"  ! anahtar koprusu: yazma calismadi — {res.get('error')}")
                fail += 1
            if K.read("probe", target) != secret:
                print("  ! anahtar koprusu: kaydedilen deger geri okunamadi")
                fail += 1

            # 3) ⚠ ASIL KAPI: anahtarin kendisi HICBIR donuste gecmemeli.
            #    Donusler JS'e gidiyor; bir gun `settings_get`teki dosya yolu
            #    gibi "belki lazim olur" diye eklenirse burada kirmizi yanar.
            for name, out in (("agent_key_set", res),
                              ("agent_keys", api.agent_keys())):
                if secret in json.dumps(out, ensure_ascii=False):
                    print(f"  ! anahtar koprusu: {name} anahtari GERI DONDURDU")
                    fail += 1

            # 4) Anahtar istemeyen saglayiciya yazilamaz. ⚠ `providers.get()`
            #    kullanilsaydi taninmayan ad varsayilana duser ve anahtar
            #    sessizce `cli`nin altina yazilirdi.
            for bad in (P.CLI, "hicboyle_yok"):
                out = api.agent_key_set(bad, secret)
                if out.get("ok"):
                    print(f"  ! anahtar koprusu: '{bad}' icin yazma reddedilmedi")
                    fail += 1
            if K.names(target) != ["probe"]:
                print(f"  ! anahtar koprusu: reddedilen yazim kaba girdi — "
                      f"{K.names(target)}")
                fail += 1

            # 5) Bos deger reddedilir ama KAYITLI anahtari dusurmez.
            if api.agent_key_set("probe", "  ").get("ok"):
                print("  ! anahtar koprusu: bos deger kabul edildi")
                fail += 1
            if (row() or {}).get("saved") is not True:
                print("  ! anahtar koprusu: bos deger kayitli anahtari dusurdu")
                fail += 1

            # 6) Silme.
            if not api.agent_key_clear("probe").get("ok"):
                print("  ! anahtar koprusu: silme calismadi")
                fail += 1
            if (row() or {}).get("saved") is not False:
                print("  ! anahtar koprusu: silinen anahtar hala kayitli gorunuyor")
                fail += 1
        finally:
            P.PROVIDERS.pop("probe", None)
            K.path = real_path

    if not fail:
        print("  anahtar koprusu: sentetik saglayici · yazma, red, silme · "
              "anahtar donuslerde gecmiyor")
    return fail


# --- Model listesi deposu (Faz 9.5.5) --------------------------------------

def check_model_store(path: Path) -> int:
    """Kullanicinin duzenledigi model listesi — `AK-13`in cozumu.

    ⚠ Denetim GECICI bir ayar dosyasiyla calisir; kullanicinin gercek
    tercihlerine dokunmamali (`check_key_bridge` ile ayni koruma).

    Belge gerekiyor cunku asil kapi `agent_ask`in dogrulamasi: onun listesi
    menuyu besleyen listeyle ayni olmak zorunda ve bu ancak gercek bir cagri
    yolunda gorunur.
    """
    import tempfile

    from jsonimager import api_agent as AG
    from jsonimager import providers as P
    from jsonimager import settings as S
    from jsonimager.app import Api

    class _Probe(P.Provider):
        """Aga cikmayan saglayici: `ask` sabit doner."""

        key = "probe"
        needs_key = False

        def models(self) -> list[str]:
            return ["probe-a", "probe-b"]

        def available(self) -> tuple[bool, str]:
            return True, ""

        def ask(self, prompt: str, model: str, effort: str) -> str:
            return f"yanit:{model}"

    fail = 0
    added = "vendor/new-model-9.9:preview"
    real_path = S.path
    with tempfile.TemporaryDirectory() as tmp:
        S.path = lambda: Path(tmp) / S.FILE_NAME
        P.PROVIDERS["probe"] = _Probe()
        try:
            api = Api()
            api._settings["agent"]["provider"] = "probe"

            def row():
                return next((p for p in api.agent_models()["providers"]
                             if p["key"] == "probe"), {})

            def ids():
                return [m["key"] for m in row().get("models", [])]

            # 1) Baslangic: fabrika listesi, sapma yok, hicbiri ozel degil.
            if ids() != ["probe-a", "probe-b"] or row().get("edited") is not False:
                print(f"  ! model deposu: fabrika listesi yanlis — {row()}")
                fail += 1
            if any(m["custom"] for m in row().get("models", [])):
                print("  ! model deposu: fabrika modeli 'ozel' isaretlendi")
                fail += 1

            # 2) Gecersiz kimlik reddedilir ve liste DEGISMEZ. Bosluk ozellikle
            #    sinanir: kopyala-yapistirdan gelen bir bosluk kimligi ekranda
            #    dogru gosterip istegi 400 ile dusururdu.
            for bad in ("", "   ", "iki kelime", "yeni\tmodel", "a" * 200,
                        "türkçe-model"):
                if api.agent_model_add("probe", bad).get("ok"):
                    print(f"  ! model deposu: gecersiz kimlik kabul edildi — {bad!r}")
                    fail += 1
            if ids() != ["probe-a", "probe-b"]:
                print(f"  ! model deposu: reddedilen kimlik listeye girdi — {ids()}")
                fail += 1

            # 2b) KENAR boslugu kirpilir, ICERIDEKI reddedilir. Kimlik cogunlukla
            #     bir belgeden kopyalanip yapistiriliyor ve sondaki satir sonu
            #     kullanicinin yazdigi bir sey degil.
            api.agent_model_add("probe", "  kenar-boslugu \n")
            if "kenar-boslugu" not in ids():
                print(f"  ! model deposu: kenar boslugu kirpilmadi — {ids()}")
                fail += 1
            api.agent_model_remove("probe", "kenar-boslugu")

            # 3) Ekleme: sona eklenir ve OZEL isaretlenir (cevrilmis etiketi yok).
            res = api.agent_model_add("probe", added)
            if not res.get("ok") or ids() != ["probe-a", "probe-b", added]:
                print(f"  ! model deposu: ekleme calismadi — {res.get('error')}")
                fail += 1
            new = next((m for m in row()["models"] if m["key"] == added), {})
            # ⚠ Ozel modelin ETIKETI KIMLIGIN KENDISI olmali. `i18n.t` eksik
            #    anahtarda anahtarin kendisine dusuyor; ayrim acikca
            #    yapilmasaydi menude `model.<kimlik>.label` gorunurdu.
            if not new.get("custom") or new.get("label") != added or new.get("note"):
                print(f"  ! model deposu: ozel modelin gorunumu yanlis — {new}")
                fail += 1
            if row().get("edited") is not True:
                print("  ! model deposu: sapma isaretlenmedi")
                fail += 1

            # 4) Kalicilik: yeni bir surec ayni listeyi gormeli.
            fresh = Api()
            if [m["key"] for m in next(p for p in fresh.agent_models()["providers"]
                                       if p["key"] == "probe")["models"]] != ids():
                print("  ! model deposu: liste diske yazilmadi")
                fail += 1

            # 5) Yinelenen ekleme reddedilir.
            if api.agent_model_add("probe", added).get("ok"):
                print("  ! model deposu: ayni kimlik iki kez eklendi")
                fail += 1

            # 6) ⚠ ASIL KAPI: eklenen model HEM menude HEM cagri yolunda
            #    gecerli olmali. Iki liste ayrisirsa menude gorunen model
            #    "bilinmeyen model" hatasi verir ve iki yol da tek basina
            #    dogru gorunur — bunu baska hicbir kapi yakalamaz.
            if [m["key"] for m in api.agent_status().get("models", [])] != ids():
                print("  ! model deposu: `agent_status` baska bir liste veriyor")
                fail += 1
            if (err := api._load_one(path)):
                print(f"  ! model deposu: belge yuklenemedi — {err}")
                fail += 1
            else:
                out = api.agent_ask(str(path), "soru", model=added)
                if not out.get("ok") or out.get("model") != added:
                    print(f"  ! model deposu: `agent_ask` ozel modeli reddetti — "
                          f"{out.get('error')}")
                    fail += 1

            # 7) Son model cikarilamaz: bos liste "fabrika listesi" demek, yani
            #    sonuncuyu silmek listeyi silmek degil SIFIRLAMAK olurdu.
            api.agent_model_remove("probe", "probe-a")
            api.agent_model_remove("probe", "probe-b")
            if ids() != [added]:
                print(f"  ! model deposu: yerlesik model cikarilamadi — {ids()}")
                fail += 1
            if api.agent_model_remove("probe", added).get("ok"):
                print("  ! model deposu: son model cikarildi")
                fail += 1

            # 8) Sifirlama girdiyi SILER; fabrika listesi geri gelir.
            if not api.agent_models_reset("probe").get("ok"):
                print("  ! model deposu: sifirlama calismadi")
                fail += 1
            if ids() != ["probe-a", "probe-b"] or row().get("edited") is not False:
                print(f"  ! model deposu: sifirlama fabrikaya donmedi — {row()}")
                fail += 1

            # 9) ⚠ Bozuk ayar SUZULUR. `settings._merge` bu agacta tip denetimi
            #    yapmiyor (taban `{}`, her anahtar "bilinmeyen" ve korunuyor);
            #    dogrulama okuyan tarafta olmasaydi bozuk bir dosya arayuzu
            #    cizilemez hale getirirdi.
            api._settings["agent"]["models"] = {
                "probe": ["gecerli-1", "iki kelime", "gecerli-1", 42, ""],
                "hicboyle_saglayici_yok": ["x"],
                "cli": "liste degil",
            }
            if api._model_map() != {"probe": ["gecerli-1"]}:
                print(f"  ! model deposu: bozuk ayar suzulmedi — {api._model_map()}")
                fail += 1

            api._settings["agent"]["models"] = ["liste", "olmamali"]
            if api._model_map() != {}:
                print("  ! model deposu: sozluk olmayan deger suzulmedi")
                fail += 1

            # 10) Taninmayan saglayiciya yazilamaz. ⚠ `providers.get()`
            #     kullanilsaydi taninmayan ad varsayilana duser ve liste
            #     sessizce `cli`nin altina yazilirdi (`_key_provider` ile ayni).
            api._settings["agent"]["models"] = {}
            if api.agent_model_add("hicboyle_yok", "x").get("ok"):
                print("  ! model deposu: taninmayan saglayiciya yazildi")
                fail += 1
        finally:
            P.PROVIDERS.pop("probe", None)
            S.path = real_path

    if not fail:
        print(f"  model deposu: fabrika/ozel ayrimi · kalicilik · bozuk ayar "
              f"suzuluyor · menu ile cagri ayni listeden (en fazla "
              f"{AG.MODEL_LIST_MAX})")
    return fail


# --- HTTP saglayicilari (Faz 9.5.3) ----------------------------------------

def check_providers() -> int:
    """HTTP saglayicilarinin istek/yanit sozlesmesi — AGA CIKMADAN.

    `build_request` bilerek saf tutuldu (anahtar arguman olarak geliyor), yani
    istegin sekli gercek bir cagri yapilmadan sinanabiliyor. Buradaki kapilarin
    hicbiri calisma aninda kendini gostermez: yanlis kurulmus bir istek
    saglayicidan gelen anlasilmaz bir 400 olarak gorunur.
    """
    import tempfile

    from jsonimager import keys as K
    from jsonimager import providers as P

    fail = 0
    key = "sk-provider-check-13579"
    prompt = "SEMA-SONDASI-abc"
    https = [p for p in P.PROVIDERS.values() if isinstance(p, P._HttpProvider)]
    if not https:
        print("  ! saglayici: HTTP saglayicisi kayitli degil")
        return 1

    # Ozel saglayicinin ucu ayardan gelir (9.21); ortak sozlesme (anahtar
    # baslikta, govde, yanit ve hata cozumu) onun icin de olculsun diye gecerli
    # bir adresle kurulur. Fabrika listesi bos oldugu icin model sondadir.
    # Adres kurali ayri denetimde: `check_custom_provider`.
    P.PROVIDERS[P.CUSTOM].configure("https://ozel.example/v1")
    for prov in https:
        model = (prov.models() or ["sonda-model"])[0]
        url, headers, body = prov.build_request(prompt, model, "medium", key)

        # 1) ⚠ ASIL KAPI: anahtar URL'ye GIRMEMELI. Gemini'nin kendi ucu
        #    `?key=` kabul ediyor ve o yol sorgu dizesini vekil gunluklerine,
        #    hata izlerine ve tarayici gecmisine dusururdu.
        if key in url:
            print(f"  ! saglayici[{prov.key}]: anahtar URL'de")
            fail += 1
        if not url.startswith("https://"):
            print(f"  ! saglayici[{prov.key}]: uc nokta https degil — {url}")
            fail += 1
        if headers.get("Authorization") != f"Bearer {key}":
            print(f"  ! saglayici[{prov.key}]: anahtar Authorization basliginda degil")
            fail += 1

        # 2) Govde: gecerli JSON, dogru model ve istem GERCEKTEN tasiniyor.
        try:
            sent = json.loads(body)
        except Exception as exc:
            print(f"  ! saglayici[{prov.key}]: govde JSON degil — {exc}")
            fail += 1
            continue
        if sent.get("model") != model:
            print(f"  ! saglayici[{prov.key}]: model govdeye yazilmadi")
            fail += 1
        if prompt not in json.dumps(sent, ensure_ascii=False):
            print(f"  ! saglayici[{prov.key}]: istem govdede yok")
            fail += 1
        if key in body.decode("utf-8"):
            print(f"  ! saglayici[{prov.key}]: anahtar GOVDEDE de duruyor")
            fail += 1

        # 3) Yanit cozumu ve BOS yanit. Bos icerik HTTP 200 ile geliyor;
        #    sessizce bos donmek kullaniciya bos bir baloncuk gosterirdi.
        good = json.dumps({"choices": [{"message": {"content": " merhaba "}}]})
        if prov.parse_response(200, good.encode("utf-8")) != "merhaba":
            print(f"  ! saglayici[{prov.key}]: yanit metni cozulemedi")
            fail += 1
        for name, bad in (("bos icerik", '{"choices":[{"message":{"content":""}}]}'),
                          ("choices yok", "{}"),
                          ("JSON degil", "<html>")):
            try:
                prov.parse_response(200, bad.encode("utf-8"))
                print(f"  ! saglayici[{prov.key}]: '{name}' hata uretmedi")
                fail += 1
            except P.ProviderError:
                pass

        # 4) Hata cevirisi: kullanicinin gercekten gorecegi iki durum AYRI
        #    mesaj vermeli, yoksa "HTTP 429" ne yapacagini soylemiyor.
        # ⚠ Sondalanacak durumlar TABLODAN turer (`P.STATUS_ERRORS`); elle
        #    tutulan bir demet, koda yeni bir durum eklendiginde sessizce
        #    eskirdi. 500 tabloda yok ve olmamali — genel yolu temsil ediyor.
        codes = sorted(P.STATUS_ERRORS) + [500]
        blob = json.dumps({"error": {"message": "x" * 900}}).encode("utf-8")
        msgs = {s: prov.parse_error(s, blob) for s in codes}
        # 401 ile 403 ayni mesaji paylasiyor (ikisi de "anahtar reddedildi"),
        # o yuzden beklenen sayi durum sayisi degil ANAHTAR sayisidir.
        want = len(set(P.STATUS_ERRORS.values())) + 1
        if len(set(msgs.values())) != want:
            print(f"  ! saglayici[{prov.key}]: {codes} icin {want} ayri mesaj "
                  f"bekleniyordu, {len(set(msgs.values()))} cikti")
            fail += 1

        # 5) ⚠ HICBIR govde sekli HAVADA ASILI bir mesaj birakmamali. Gercek
        #     bir cagrida `Saglayici 404 dondurdu: ` ciktı: govde OpenAI hata
        #     seklinde degildi, okuyucu bos dizeye dusuyordu ve geriye iki
        #     nokta ile biten bir cumle kaliyordu. Sondalar o gun gercekten
        #     gelen govdeleri temsil ediyor.
        for name, raw, want in (
                ("bos govde", b"", ""),
                ("JSON degil", b"<html>503 Service Unavailable</html>", "Service"),
                ("baska sekil", b'{"message":"nope"}', "nope"),
                ("dizi", b"[1,2,3]", "1")):
            out = prov.parse_error(500, raw).strip()
            if out.endswith(":"):
                print(f"  ! saglayici[{prov.key}]: '{name}' iki nokta ile bitti")
                fail += 1
            if want and want not in out:
                print(f"  ! saglayici[{prov.key}]: '{name}' govdeyi tasimadi — {out}")
                fail += 1
        if len(msgs[500]) > P.ERROR_DETAIL_CHARS + 200:
            print(f"  ! saglayici[{prov.key}]: hata govdesi kirpilmadi "
                  f"({len(msgs[500])} karakter)")
            fail += 1

        # 6) ⚠ `groq/compound` aileleri listede OLMAMALI: gomulu web arama
        #    araclari var ve sema bir arama sorgusuna girebilirdi (`K-22`).
        if any("compound" in m for m in prov.models()):
            print(f"  ! saglayici[{prov.key}]: gomulu arama araci olan model listede")
            fail += 1

        # 7) ⚠ `uses_effort` BILDIRIM degil OLCUM olmali (`AK-16`). Bayragi
        #    sabit bir degerle karsilastirmak, bayragin yalan soylemesini
        #    yakalamazdi: burada iki AYRI caba duzeyiyle kurulan govdeler
        #    karsilastiriliyor. Govde degismiyorsa caba gitmiyor demektir ve
        #    secici gosterilmemeli — hicbir sey yapmayan bir denetim,
        #    olmayan bir denetimden kotudur.
        lo = prov.build_request(prompt, model, "low", key)[2]
        hi = prov.build_request(prompt, model, "max", key)[2]
        if (lo != hi) != prov.uses_effort:
            sends = "gonderiyor" if lo != hi else "gondermiyor"
            print(f"  ! saglayici[{prov.key}]: cabayi {sends} ama "
                  f"uses_effort={prov.uses_effort}")
            fail += 1

        # 8) ⚠ Uc nokta OpenAI UYUMLU olmali (`9.5.4`). `_HttpProvider`in
        #    yanit ve hata cozumu `choices[0].message.content` bekliyor; ayni
        #    sinifi bir saglayicinin NATIVE ucuna baglamak (Anthropic'te
        #    `/v1/messages`) gecerli bir istek gonderip anlasilmaz bir yanit
        #    alirdi.
        #
        #    ⚠ `endswith` DEGIL `in`: uyumlu bir ucun sorgu dizesi olabiliyor
        #    (Azure'da `…/chat/completions?api-version=…`) ve son ek kontrolu
        #    orada sozlesme bozulmadigi halde kirmizi yanardi — kapi, korudugu
        #    seyi degil bugunku uc URL'nin tesadufi ortak sonunu koruyordu.
        if "/chat/completions" not in url:
            print(f"  ! saglayici[{prov.key}]: uc OpenAI uyumlu degil — {url}")
            fail += 1
    P.PROVIDERS[P.CUSTOM].configure("")

    # 9) Saglayiciya ozel uyarinin i18n anahtari sozlukte mi? Anahtar bir
    #    SINIF NITELIGI (`Provider.note`), yani `t("...")` cagrisi degil ve
    #    `check_i18n`in literal taramasi onu gormez; yazim hatasi ekranda
    #    `provider.gemini.data_note` diye gorunurdu.
    from jsonimager import i18n as I18N

    base = I18N.STRINGS[I18N.DEFAULT_LANG]
    for prov in P.PROVIDERS.values():
        if prov.note and prov.note not in base:
            print(f"  ! saglayici[{prov.key}]: uyari anahtari sozlukte yok — "
                  f"{prov.note}")
            fail += 1

    # 9b) Baglanti hatalari CEVRILMIS cumleye duser (9.23). Ornekler temiz
    #     makinede (Windows Sandbox) GERCEKTEN gorulen iki ham metin: sertifika
    #     dogrulanamadi ve ag yokken adres cozulemedi. Taninmayan sebep ham
    #     ayrintisini KORUMALI.
    import socket
    import ssl
    for reason, want in (
            (ssl.SSLCertVerificationError(1, "unable to get local issuer certificate"),
             I18N.t("err.tls_verify")),
            (socket.gaierror(11001, "getaddrinfo failed"), I18N.t("err.net_offline")),
            (ConnectionRefusedError(10061, "refused"), I18N.t("err.net_refused")),
            (TimeoutError("timed out"), I18N.t("err.timeout", seconds=P.TIMEOUT))):
        if P.net_error(reason) != want:
            print(f"  ! saglayici: {type(reason).__name__} cevrilmedi — {P.net_error(reason)}")
            fail += 1
    odd = P.net_error(OSError("baska-bir-ayrinti"))
    if "baska-bir-ayrinti" not in odd:
        print(f"  ! saglayici: taninmayan baglanti hatasi ayrintisini kaybetti — {odd}")
        fail += 1
    if "_ssl.c" in I18N.t("err.tls_verify") or "Errno" in I18N.t("err.net_offline"):
        print("  ! saglayici: cevrilmis baglanti iletisi ham metin tasiyor")
        fail += 1

    # 10) ⚠ Varsayilan saglayici ANAHTAR ISTEMEYEN ve listenin BASINDAKI
    #     olmali (`K-13`). Kayit sirasi ekrandaki secicinin sirasidir; ucretli
    #     bir saglayici basa gecerse yeni kullanici hicbir sey yapilandirmadan
    #     soru soramaz ve bunu ancak ekranda fark ederiz.
    if P.PROVIDERS[P.DEFAULT].needs_key:
        print(f"  ! saglayici: varsayilan ({P.DEFAULT}) anahtar istiyor")
        fail += 1
    if next(iter(P.PROVIDERS)) != P.DEFAULT:
        print(f"  ! saglayici: listenin basi varsayilan degil — "
              f"{next(iter(P.PROVIDERS))}")
        fail += 1

    # 11) ⚠ CLI tarafinda AYNI olcum (`AK-16`). Ustteki kapi yalnizca HTTP
    #     saglayicilarini geziyor; caba bugun SADECE burada gerceklesiyor ve
    #     olculmezse `uses_effort = True` bir iddia olarak kalirdi. Alt surec
    #     CALISTIRILMAZ: `subprocess.run` yakalanip argv okunur.
    cli = P.PROVIDERS[P.CLI]
    captured: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    real_which, real_run = P.shutil.which, P.subprocess.run
    P.shutil.which = lambda name: "claude"
    P.subprocess.run = lambda argv, **kw: (captured.append(argv), _Proc())[1]
    try:
        cli.ask(prompt, cli.models()[0], "max")
    except Exception as exc:
        print(f"  ! saglayici[{cli.key}]: caba olcumu yapilamadi — {exc}")
        fail += 1
    finally:
        P.shutil.which, P.subprocess.run = real_which, real_run

    argv = captured[0] if captured else []
    if ("max" in argv) != cli.uses_effort:
        sends = "gonderiyor" if "max" in argv else "gondermiyor"
        print(f"  ! saglayici[{cli.key}]: cabayi argv'ye {sends} ama "
              f"uses_effort={cli.uses_effort}")
        fail += 1

    # 12) `available()` anahtara bakiyor mu? Gecici kapla sinanir.
    if K.available():
        real_path = K.path
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / K.FILE_NAME
            K.path = lambda: target
            try:
                prov = https[0]
                if prov.available()[0]:
                    print(f"  ! saglayici[{prov.key}]: anahtarsiz 'kullanilabilir' dedi")
                    fail += 1
                K.store(prov.key, key, target)
                if not prov.available()[0]:
                    print(f"  ! saglayici[{prov.key}]: anahtar varken kullanilamaz dedi")
                    fail += 1
            finally:
                K.path = real_path

    if not fail:
        models = sum(len(p.models()) for p in https)
        effort = sum(p.uses_effort for p in P.PROVIDERS.values())
        print(f"  saglayicilar: {len(https)} HTTP · {models} model · anahtar "
              f"yalnizca baslikta · yanit/hata cevirisi sinandi · cabayi "
              f"{effort} saglayici gonderiyor (olculdu)")
    return fail


# --- Api kopru sozlesmesi (Faz 8.6) ----------------------------------------

def check_api() -> int:
    """`Api` mixin bilesimi arayuzun bekledigi yuzeyi veriyor mu?

    Iki ayri tuzagi birden kapatir:

    1. **pywebview ozyineleme tuzagi.** `js_api` nesnesinin alt cizgisiz her
       niteligi gezilir ve nesne ise ICINE inilir; public bir VERI alani
       WinForms/COM nesnelerinde kaybolup "maximum recursion depth" uretir.
       Bu yuzden public olan her sey CAGIRILABILIR olmali.
    2. **Eksik mixin.** Arayuz `api.<ad>()` diye cagirir; mixin bilesime
       yazilmayi unutulursa hata yalnizca o dugmeye basilinca cikar ve
       "hicbir sey olmuyor" diye gorunur. Beklenen ad listesi JS KAYNAGINDAN
       cikarilir — elle tutulan ikinci bir liste zamanla saparcdi.
    """
    from jsonimager.app import Api

    api = Api()
    fail = 0

    data_fields = sorted(n for n in dir(api)
                         if not n.startswith("_") and not callable(getattr(api, n)))
    if data_fields:
        print(f"  ! Api'de public VERI alani var (pywebview ozyinelemeye girer): "
              f"{', '.join(data_fields)}")
        fail += 1

    called: set[str] = set()
    for src in (WEB / "js").glob("*.js"):
        called |= set(re.findall(r"\bapi\.(\w+)\s*\(", src.read_text(encoding="utf-8")))

    missing = sorted(n for n in called if not callable(getattr(api, n, None)))
    if missing:
        print(f"  ! Arayuzun cagirdigi metot Api'de yok: {', '.join(missing)}")
        fail += 1

    if not fail:
        print(f"  kopru: {len(called)} metot · public veri alani yok")
    return fail


def check_api_smoke(path: Path) -> int:
    """Kopru metotlarini gercek bir belgeyle uctan uca calistirir.

    Mixin'ler ortak duruma (`self._docs`, `self._views`) dokunuyor; bolme
    sirasinda biri kopsa ice aktarma yine calisir, hata ancak metot cagrilinca
    cikar. Bu yuzden denetim ice aktarmayla yetinmez.
    """
    from jsonimager.app import Api

    api = Api()
    if (err := api._load_one(path)):
        print(f"  ! belge yuklenemedi: {err}")
        return 1

    doc_id = str(path)
    ds = api._docs[doc_id]["datasets"]
    if not ds:
        print("  kopru akisi: veri kumesi yok, atlandi")
        return 0
    ds_id = ds[0].id

    steps = [
        ("tree", lambda: api.tree()),
        ("table", lambda: api.table(doc_id, ds_id)),
        ("chart_columns", lambda: api.chart_columns(doc_id, ds_id)),
        ("export_text/report", lambda: api.export_text("report", doc_id)),
        ("export_text/csv", lambda: api.export_text("csv", doc_id, ds_id)),
        # ⚠ Acik satirli cagri da sinanir: bugune kadar yalnizca KAPALI hali
        # geciyordu ve `expanded` yolu kopruden hic gecmiyordu (`9.11`).
        ("export_text/html+acik",
         lambda: api.export_text("html", doc_id, ds_id, None, None, [0])),
        ("scene_svg/tree", lambda: api.scene_svg("tree", doc_id)),
        ("scene_svg/table", lambda: api.scene_svg("table", doc_id, ds_id)),
        ("export_image/table", lambda: api.export_image("table", doc_id, ds_id)),
        ("claude_payload", lambda: api.agent_payload(doc_id)),
        # Yalnizca OKUYAN anahtar cagrisi; yazanlar `check_key_bridge` icinde
        # gecici bir kapla sinaniyor (ayni gerekce: `settings_set`).
        ("agent_keys", lambda: api.agent_keys()),
        # Yalnizca OKUYAN ayar cagrilari: `settings_set`/`settings_reset`
        # kullanicinin gercek dosyasini ezerdi, onlar `check_settings` icinde
        # gecici klasorde sinaniyor.
        ("settings_get", lambda: api.settings_get()),
        ("strings", lambda: api.strings()),
        ("app_info", lambda: api.app_info()),
        ("set_transpose", lambda: api.set_transpose(doc_id, ds_id, None, True)),
        ("reset_view", lambda: api.reset_view(doc_id, ds_id)),
        ("close_doc", lambda: api.close_doc(doc_id)),
    ]

    fail = 0
    for name, run in steps:
        try:
            res = run()
        except Exception as exc:
            print(f"  ! {name}: {type(exc).__name__}: {exc}")
            fail += 1
            continue
        if not res.get("ok"):
            print(f"  ! {name}: {res.get('error')}")
            fail += 1

    if not fail:
        print(f"  kopru akisi: {len(steps)} metot calisti")
    return fail


# --- Galeri sozlesmesi (Faz 9.6.1) -----------------------------------------

def _check_grouping() -> int:
    """Gruplama ve kart basligi KAYNAKTAN turuyor mu (`9.6.3`)?

    Sentetik bir belge klasoru kuruluyor: iki alt klasor, bir de belgenin
    yanindaki dosya, ustune gomulu bir gorsel. Gercek orneklerde bugun tek
    klasor var, yani ayrimin bozuldugu gorunmezdi.
    """
    import shutil
    import tempfile

    from PIL import Image

    from jsonimager import images as IM

    tmp = Path(tempfile.mkdtemp(prefix="jsonimager-group-"))
    try:
        for rel in ("yaninda.png", "assets/bir.png", "baska/iki.png"):
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (4, 4), "red").save(target)

        buf = io.BytesIO()
        Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
        embedded = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        root = {"a": "yaninda.png", "b": "assets/bir.png",
                "c": "baska/iki.png", "d": embedded}
        listed = IM.catalog(root, IM.Sources(tmp))
        items = {it["json_path"]: it for it in listed}

        fail = 0
        if len(items) != 4:
            print(f"  ! gruplama sondasi: 4 gorsel bekleniyordu, {len(items)} geldi")
            return 1

        expect = {"a": ("", "yaninda.png"), "b": ("assets", "bir.png"),
                  "c": ("baska", "iki.png"), "d": (None, None)}
        for key, (group, name) in expect.items():
            got = items[key]
            if got["group"] != group or got["name"] != name:
                print(f"  ! {key}: grup/ad ({got['group']!r}, {got['name']!r}) "
                      f"beklenen ({group!r}, {name!r})")
                fail += 1

        # ⚠ Grup MUTLAK yol olmamali: ekranda baslik olarak yaziliyor ve her
        # satirda tam yolu tekrarlamak hem uzun hem gereksiz (`full` var).
        absolute = [i["json_path"] for i in items.values()
                    if i["group"] and Path(i["group"]).is_absolute()]
        if absolute:
            print(f"  ! grup mutlak yol tasiyor: {', '.join(absolute)}")
            fail += 1

        # Ayrimin kendisi: uc dosya UC ayri gruba dusmeli, gomulu hicbirine.
        groups = {i["group"] for i in items.values()}
        if groups != {"", "assets", "baska", None}:
            print(f"  ! kaynaklar ayrisamadi: {sorted(map(str, groups))}")
            fail += 1

        # Grup SIRASI: gomulu -> belge klasoru -> klasorler alfabetik. Belgede
        # gomulu gorsel EN SONDA duruyor, yani gecen sira belge sirasi degil.
        order = list(dict.fromkeys(i["group"] for i in listed))
        if order != [None, "", "assets", "baska"]:
            print(f"  ! grup sirasi: {order}")
            fail += 1

        if not fail:
            print("  galeri gruplama: 3 klasor + gomulu ayrisiyor · "
                  "ad dosyadan, grup goreli")
        return fail
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _check_url_policy() -> int:
    """Gorsel adresleri: yalniz izinle, yalniz galeri/kaydetme — AGA CIKMADAN (`9.6.5.2`).

    Ag cagrisinin tek noktasi `remote_images._urlopen`; burada sahte bir yanitla
    degistiriliyor ve her cagri kaydediliyor. Asil iki kapi yokluk iddiasi:
    izin yokken istek GITMEZ; izin varken bile liste ve tablo KURULUMU istek
    GONDERMEZ — tablo adres hucresini yalnizca isaretler, onizlemeyi arayuz
    cizimden sonra galeri yolundan ister (`K-32`).
    """
    import email.message
    import shutil
    import socket
    import tempfile
    import urllib.request

    from PIL import Image

    from jsonimager import images as IM
    from jsonimager import remote_images as RM
    from jsonimager.app import Api

    fail = 0

    # 1) Taninma — saf. http de taninir (dosya sanilmasin), acilmaz.
    probes = {
        "https://img.example.com/a/tom.png?w=2": ("url", "image/png"),
        "HTTPS://IMG.EXAMPLE.COM/B.JPG": ("url", "image/jpeg"),
        "http://img.example.com/c.gif": ("url", "image/gif"),
        "https://img.example.com/page": None,
    }
    for raw, want in probes.items():
        d = IM.detect(raw)
        got = (d["source"], d["mime"]) if d else None
        if got != want:
            print(f"  ! detect({raw!r}) = {got}, beklenen {want}")
            fail += 1

    # 2) Adres kurali — saf.
    rules = {"https://img.example.com/a.png": True, "http://img.example.com/a.png": False,
             "https://localhost/a.png": False, "https://127.0.0.1/a.png": False,
             "https://192.168.1.20/a.png": False, "https://[::1]/a.png": False,
             "https://169.254.1.1/a.png": False, "https://user:pw@img.example.com/a.png": False}
    for url, want in rules.items():
        if RM.allowed(url) != want:
            print(f"  ! allowed({url!r}) = {not want}")
            fail += 1

    # Yonlendirme ayni kapidan gecer.
    handler = RM._redirect_handler()
    req = urllib.request.Request("https://img.example.com/a.png")
    if handler.redirect_request(req, None, 302, "Found", {}, "http://img.example.com/a.png") is not None:
        print("  ! https'ten http'ye yonlendirmeye izin verildi")
        fail += 1
    if handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.com/a.png") is None:
        print("  ! https'ten https'e yonlendirme reddedildi")
        fail += 1

    # Baglanti: aileler harmanlanir ve dusen IPv6'nin bedeli oturumda BIR KEZ odenir.
    # Olculen olay: IPv6 calismayan agda sirali deneme 2 × 8 s bekletiyordu. Sahte
    # soketle, aga cikmadan (belgeleme adresleri: 2001:db8::/32, 192.0.2.0/24).
    v6a = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
    v6b = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::2", 443, 0, 0))
    v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
    if [i[4][0] for i in RM._ordered([v6a, v6b, v4], False)] != ["2001:db8::1", "192.0.2.1", "2001:db8::2"]:
        print("  ! adres aileleri harmanlanmiyor")
        fail += 1

    tried: list[str] = []

    class FakeSocket:
        def __init__(self, family, *args):
            self.family = family

        def settimeout(self, value):
            pass

        def connect(self, addr):
            tried.append(addr[0])
            if self.family == socket.AF_INET6:
                raise TimeoutError("sahte IPv6 bekleyisi")

        def close(self):
            pass

    RM.clear_cache()
    try:
        sock = RM._connect_any([v6a, v6b, v4], 8, FakeSocket)
        first = list(tried)
        tried.clear()
        RM._connect_any([v6a, v6b, v4], 8, FakeSocket)
        if sock.family != socket.AF_INET or first != ["2001:db8::1", "192.0.2.1"] or tried != ["192.0.2.1"]:
            print(f"  ! baglanti sirasi: ilk {first} · sonraki {tried}")
            fail += 1
    finally:
        RM.clear_cache()
    # 9.7.2 — cozulmus adres denetimi. Olculen acik: adres kuralindan gecen bir ad
    # loopback'e cozuluyor ve baglanti ona gidiyordu. Sahte cozumleme ve sahte
    # baglayiciyla, aga cikmadan; "genel" orneklerde paket gitmez.
    public_cases = {"8.8.8.8": True, "2606:4700::1": True, "127.0.0.1": False,
                    "10.0.0.5": False, "100.64.0.1": False, "169.254.1.1": False,
                    "::ffff:127.0.0.1": False, "fe80::1%12": False, "224.0.0.1": False}
    for raw, want in public_cases.items():
        if RM.public_ip(raw) != want:
            print(f"  ! public_ip({raw!r}) = {not want}")
            fail += 1
    if RM.allowed("https://[::ffff:7f00:1]/a.png"):
        print("  ! adreste IPv4'e eslenmis loopback kabul edildi")
        fail += 1

    def infos_of(*ips: str) -> list:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 443, 0, 0)) if ":" in ip
                else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]

    kept = [i[4][0] for i in RM._public_infos(infos_of("10.0.0.5", "8.8.8.8", "::1", "2606:4700::1"))]
    if kept != ["8.8.8.8", "2606:4700::1"]:
        print(f"  ! cozulmus adres suzgeci: {kept}")
        fail += 1

    dialed: list[str] = []
    real_gai, real_connect = socket.getaddrinfo, RM._connect_any
    socket.getaddrinfo = lambda host, *a, **k: infos_of("127.0.0.1", "::1") \
        if host == "rebind.example" else infos_of("10.1.2.3")
    RM._connect_any = lambda infos, timeout, *a: dialed.extend(i[4][0] for i in infos) or object()
    try:
        direct = RM._https_connection()("rebind.example", 443)
        try:
            direct._create_connection(("rebind.example", 443), 1, None)
            print("  ! loopback'e cozulen ada baglanma reddedilmedi")
            fail += 1
        except OSError:
            pass
        if dialed:
            print(f"  ! reddedilmesi gereken adrese baglanti denendi: {dialed}")
            fail += 1

        # Vekil: baglanti hedefe degil vekile, vekil de ozel bir IP'de — kabul edilmeli.
        proxied = RM._https_connection()("proxy.corp", 3128)
        proxied.set_tunnel("img.example.com", 443)
        try:
            proxied._create_connection(("proxy.corp", 3128), 1, None)
        except OSError:
            print("  ! ozel IP'deki vekil sunucuya baglanti reddedildi (kurumsal agda gorsel gelmezdi)")
            fail += 1
        if dialed != ["10.1.2.3"]:
            print(f"  ! vekil baglantisi: {dialed}")
            fail += 1
    finally:
        socket.getaddrinfo, RM._connect_any = real_gai, real_connect

    buf = io.BytesIO()
    Image.new("RGB", (6, 3), "blue").save(buf, format="PNG")
    payload = buf.getvalue()
    calls: list[str] = []
    special: dict[str, tuple[str, bytes, int | None]] = {}

    class FakeResponse:
        def __init__(self, ctype: str, body: bytes, length: int | None):
            self.headers = email.message.Message()
            self.headers["Content-Type"] = ctype
            if length is not None:
                self.headers["Content-Length"] = str(length)
            self._body = body

        def read(self, n: int = -1) -> bytes:
            return self._body if n < 0 else self._body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> bool:
            return False

    def fake_urlopen(request):
        calls.append(request.full_url)
        return FakeResponse(*special.get(request.full_url, ("image/png", payload, None)))

    real_open, real_ttl, real_timeout = RM._urlopen, RM.FAIL_TTL_S, RM.TIMEOUT_S
    tmp = Path(tempfile.mkdtemp(prefix="jsonimager-url-"))
    RM._urlopen = fake_urlopen
    RM.clear_cache()
    try:
        # 3) Sinirlar ve onbellek.
        html = "https://img.example.com/html.png"
        special[html] = ("text/html", b"<html>", None)
        special["https://img.example.com/huge.png"] = ("image/png", b"x", RM.MAX_BYTES + 1)
        special["https://img.example.com/fat.png"] = ("image/png", b"x" * (RM.MAX_BYTES + 1), None)
        for url in (html, "https://img.example.com/huge.png", "https://img.example.com/fat.png"):
            if RM.fetch(url) is not None:
                print(f"  ! sinir asan yanit kabul edildi: {url}")
                fail += 1

        calls.clear()
        good = "https://img.example.com/good.png"
        RM.fetch(good)
        RM.fetch(good)
        RM.fetch(html)                     # az once dustu: TTL icinde yeniden istenmez
        if calls != [good]:
            print(f"  ! onbellek: basarili bir kez, basarisiz TTL icinde hic istenmeli: {calls}")
            fail += 1
        RM.FAIL_TTL_S = 0
        calls.clear()
        RM.fetch(html)
        if calls != [html]:
            print("  ! TTL dolunca basarisiz adres yeniden denenmedi")
            fail += 1
        RM.FAIL_TTL_S = real_ttl

        # 4) Api uzerinden politika.
        doc_path = tmp / "doc.json"
        doc_path.write_text(json.dumps({"items": [
            {"img": "https://img.example.com/photos/tom.png"},
            {"img": "http://img.example.com/plain.png"},
            {"img": "https://192.168.1.20/router.png"},
        ]}), encoding="utf-8")
        api = Api()
        # ⚠ Ayar yalnizca BELLEKTE degistiriliyor; kullanicinin dosyasina yazilmaz.
        api._settings = {**api._settings, "images": {**api._settings.get("images", {}),
                                                     "allow_url": False}}
        if (err := api._load_one(doc_path)):
            print(f"  ! adres sondasi: belge yuklenemedi: {err}")
            return fail + 1
        doc_id = str(doc_path)
        ds_id = api._docs[doc_id]["datasets"][0].id
        target = "https://img.example.com/photos/tom.png"

        RM.clear_cache()
        calls.clear()
        gal = api.gallery(doc_id)
        off = api.table(doc_id, ds_id)
        api.gallery_thumbs(doc_id, ["items[0].img"], 64)
        api.save_images(doc_id, ["items[0].img"])
        if calls:
            print(f"  ! ayar kapaliyken istek gitti: {calls}")
            fail += 1
        if any(c.get("k") == "image" or "remote" in c or "jp" in c
               for row in off["table"]["rows"] for c in row if c):
            print("  ! ayar kapaliyken tablo adres hucresini gorsel saydi")
            fail += 1
        if gal.get("url_refs") != 1 or gal.get("items"):
            print(f"  ! kapali ayarda galeri: url_refs {gal.get('url_refs')} · {len(gal.get('items', []))} oge")
            fail += 1

        api._settings["images"]["allow_url"] = True
        calls.clear()
        gal = api.gallery(doc_id)
        tbl = api.table(doc_id, ds_id)
        if calls:
            print(f"  ! ayar acikken liste ya da tablo istek gonderdi: {calls}")
            fail += 1
        items = gal.get("items", [])
        item = items[0] if items else {}
        if ([i["json_path"] for i in items] != ["items[0].img"] or gal.get("url_refs") != 0
                or item.get("group") != "img.example.com" or item.get("name") != "tom.png"
                or item.get("embedded") or item.get("full") != target or item.get("bytes")):
            print(f"  ! acik ayarda katalog: {items}")
            fail += 1
        # `K-32` (9.15) — ayar acikken tablo adres hucresini UZAK GORSEL diye
        # isaretler ama KURULURKEN istek gondermez ve onizleme tasimaz (yukarida
        # `calls` bos). Yalnizca adres kuralini gecen hucre isaretlenir; http ve
        # yerel ag adresi duz metin kalir. `jp` galerinin JSON yoluyla AYNI
        # dizge olmali: arayuz onizlemeyi o yolla `gallery_thumbs`tan ister.
        cells = [row[0] for row in tbl["table"]["rows"]]
        marks = [(c.get("k"), c.get("remote"), c.get("jp"), "thumb" in c) for c in cells]
        if marks != [("image", True, "items[0].img", False),
                     ("scalar", None, None, False), ("scalar", None, None, False)]:
            print(f"  ! tablo adres hucreleri: {marks}")
            fail += 1
        if cells[0].get("x") != "image" or cells[0].get("src") != target:
            print("  ! uzak gorsel hucresi duzenlenemez isaretli degil ya da adresi tasimiyor")
            fail += 1

        th = api.gallery_thumbs(doc_id, ["items[0].img"], 64).get("thumbs", [])
        if calls != [target] or not th or th[0].get("bytes") != len(payload) or th[0].get("source_width") != 6:
            print(f"  ! onizleme: istekler {calls} · yanit {th[:1]}")
            fail += 1

        out = tmp / "out"
        out.mkdir()
        doc = api._docs[doc_id]
        written, _ = api._write_images(doc, api._pick_images(doc, ["items[0].img"]), out)
        if calls != [target] or [p.name for p in written] != ["tom.png"] \
                or (out / "tom.png").read_bytes() != payload:
            print(f"  ! kaydetme: istekler {calls} · yazilan {[p.name for p in written]}")
            fail += 1

        # 5) Zaman asimi TUM isi kapsar. Ad cozumlemesi `urllib`in zaman asiminin
        # disinda kaliyor (olculdu: 12,1 s); asilan istek beklenmemeli.
        def slow_urlopen(request):
            time.sleep(1.0)
            return FakeResponse("image/png", payload, None)

        RM._urlopen, RM.TIMEOUT_S = slow_urlopen, 0.2
        started = time.perf_counter()
        late = RM.fetch("https://img.example.com/slow.png")
        waited = time.perf_counter() - started
        if late is not None or waited > 0.8:
            print(f"  ! zaman asimi tutulmadi: {waited:.2f} s bekledi, sonuc {late is not None}")
            fail += 1
    finally:
        RM._urlopen, RM.FAIL_TTL_S, RM.TIMEOUT_S = real_open, real_ttl, real_timeout
        RM.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if not fail:
        print("  galeri adresleri: aga cikmadan · https ve yerel ag kurali · yonlendirme ayni kapidan"
              " · sinirlar · kapaliyken istek yok · acikken liste ve tablo kurulumu istek yok"
              " · tablo hucresi galeriyle ayni yolu tasiyor · kaydetme onbellekten"
              " · zaman asimi tum isi kapsiyor · cozulmus ozel adres red · vekil gecer")
    return fail


def _check_absolute_policy() -> int:
    """Mutlak yol yalnizca belge basina izinle, UNC hic (`9.6.5.1`).

    Asil kapi okumadan ONCE: izin yokken dosya sistemine hic dokunulmamali.
    `Path.is_file`, `Path.resolve` ve `Path.read_bytes` gecici olarak sarilip
    disaridaki dosyanin ya da UNC sunucusunun adina uzanan her cagri
    kaydediliyor — sayim, galeri ya da tablo kurulumu onlari yoklarsa kapi
    kirmizi yanar.
    """
    import pathlib
    import shutil
    import tempfile

    from PIL import Image

    from jsonimager import images as IM
    from jsonimager import settings as S
    from jsonimager.app import Api

    fail = 0

    # 1) Saf siniflandirma.
    kinds = {r"C:\a\b.png": IM.PATH_ABSOLUTE, r"\a\b.png": IM.PATH_ABSOLUTE,
             "/a/b.png": IM.PATH_ABSOLUTE, r"\\srv\s\b.png": IM.PATH_UNC,
             "//srv/s/b.png": IM.PATH_UNC, r"\\?\C:\b.png": IM.PATH_UNC,
             "assets/b.png": IM.PATH_RELATIVE, "C:b.png": IM.PATH_RELATIVE}
    for raw, want in kinds.items():
        if IM.path_kind(raw) != want:
            print(f"  ! path_kind({raw!r}) = {IM.path_kind(raw)}, beklenen {want}")
            fail += 1

    if "allow_absolute" in S.DEFAULTS["images"]:
        print("  ! settings.images.allow_absolute geri geldi (karar: yalniz belge basina izin)")
        fail += 1
    # ⚠ Alan eski ayar dosyalarinda KALIYOR (`_merge` bilinmeyeni korur); onu okuyan
    # bir satir kalici bir "her zaman izin ver" yolunu sessizce geri getirirdi.
    # Kelime siniri sart: `gallery_allow_absolute` kopru metodunun ADI, ayar degil —
    # ilk yazimda duz alt dize aramasi bu yuzden dort dosyada yanlis alarm verdi.
    setting_name = re.compile(r"\ballow_absolute\b")
    readers = [p.name for p in (ROOT / "src" / "jsonimager").rglob("*")
               if p.suffix in {".py", ".js", ".html"} and p.name != "settings.py"
               and setting_name.search(p.read_text(encoding="utf-8"))]
    if readers:
        print(f"  ! allow_absolute okunuyor: {', '.join(readers)}")
        fail += 1

    tmp = Path(tempfile.mkdtemp(prefix="jsonimager-abs-"))
    real = {n: getattr(pathlib.Path, n) for n in ("is_file", "resolve", "read_bytes")}
    touched: list[str] = []

    def spy(name: str):
        def wrapper(self, *args, **kwargs):
            if "secret-probe" in str(self) or "probe-host" in str(self):
                touched.append(f"{name} {self}")
            return real[name](self, *args, **kwargs)
        return wrapper

    def watching(on: bool) -> None:
        for n, fn in real.items():
            setattr(pathlib.Path, n, spy(n) if on else fn)

    try:
        doc_dir, outside = tmp / "doc", tmp / "outside"
        doc_dir.mkdir()
        outside.mkdir()
        secret = outside / "secret-probe.png"
        Image.new("RGB", (4, 4), "green").save(secret)
        Image.new("RGB", (4, 4), "red").save(doc_dir / "near.png")
        doc_path = doc_dir / "doc.json"
        doc_path.write_text(json.dumps({"items": [
            {"img": str(secret)},
            {"img": "near.png"},
            {"img": "\\\\probe-host.invalid\\share\\x.png"},
            {"img": "../outside/secret-probe.png"},
        ]}), encoding="utf-8")

        api = Api()
        if (err := api._load_one(doc_path)):
            print(f"  ! mutlak yol sondasi: belge yuklenemedi: {err}")
            return fail + 1
        doc_id = str(doc_path)
        ds_id = api._docs[doc_id]["datasets"][0].id

        # 2) Izinsiz: sayilir ama DOKUNULMAZ.
        watching(True)
        try:
            gal = api.gallery(doc_id)
            tbl = api.table(doc_id, ds_id)
        finally:
            watching(False)
        if touched:
            print(f"  ! izinden once dosya sistemine dokunuldu: {touched[:3]}")
            fail += 1
        if gal.get("absolute_refs") != 1 or [i["json_path"] for i in gal["items"]] != ["items[1].img"]:
            print(f"  ! izinsiz galeri: refs {gal.get('absolute_refs')} · "
                  f"{[i['json_path'] for i in gal.get('items', [])]}")
            fail += 1
        if tbl["table"].get("images_blocked") != 1 or any("thumb" in c for c in tbl["table"]["rows"][0] if c):
            print("  ! izinsiz tablo: izin bekleyen sayilmadi ya da onizleme uretildi")
            fail += 1

        # 3) Izinle: okunur; UNC ve goreli kacis yine hic.
        api.gallery_allow_absolute(doc_id)
        touched.clear()
        watching(True)
        try:
            gal = api.gallery(doc_id)
            tbl = api.table(doc_id, ds_id)
        finally:
            watching(False)
        paths = [i["json_path"] for i in gal["items"]]
        if paths != ["items[1].img", "items[0].img"] or gal.get("absolute_refs") != 0:
            print(f"  ! izinli galeri (sira: belge klasoru, sonra mutlak): {paths}")
            fail += 1
        if any("probe-host" in t for t in touched):
            print("  ! UNC yolu izinle yoklandi")
            fail += 1
        leaked = [t for t in touched if "secret-probe" in t and ".." in t]
        if leaked:
            print(f"  ! goreli kacis diske indi: {leaked[:2]}")
            fail += 1
        absolute = next((i for i in gal["items"] if i["json_path"] == "items[0].img"), None)
        if absolute and absolute["full"] != str(secret.resolve()):
            print(f"  ! mutlak gorselin tam yolu: {absolute['full']}")
            fail += 1
        if tbl["table"].get("images_blocked") != 0 or not any("thumb" in c for c in tbl["table"]["rows"][0] if c):
            print("  ! izinli tabloda mutlak gorsel onizlenmedi")
            fail += 1

        # 4) Izin belgeyle biter.
        api.close_doc(doc_id)
        api._load_one(doc_path)
        if api.gallery(doc_id).get("absolute_refs") != 1:
            print("  ! belge kapaninca izin dusmedi")
            fail += 1
    finally:
        watching(False)
        shutil.rmtree(tmp, ignore_errors=True)

    if not fail:
        print("  galeri mutlak yol: izinsiz dokunulmuyor · izinle okunuyor · UNC ve kacis hic"
              " · izin belgeyle bitiyor · tablo izne uyuyor")
    return fail


def _check_image_export() -> int:
    """Secilenleri kaydetme: ad kaynaktan, cakisma sayi alir, USTUNE YAZMA YOK.

    Diyalog burada acilamaz; yazma cekirdegi (`_pick_images` + `_write_images`)
    gecici bir klasore dogrudan cagriliyor, kopru metodunun kendisi yalnizca
    pencere yokken verdigi hatayla sinaniyor (`9.6.4`).
    """
    import shutil
    import tempfile

    from PIL import Image

    from jsonimager import i18n as I18N
    from jsonimager import images as IM
    from jsonimager.app import Api

    fail = 0

    # 1) Ad turetimi — saf.
    png = {"source": "data", "mime": "image/png"}
    cases = [
        ({"source": "file", "path": "assets\\p-1.png", "mime": "image/png"}, "a", "p-1.png"),
        (png, "products[0].image", "products-0-image.png"),
        ({"source": "data", "mime": "image/jpeg"}, "x", "x.jpg"),
        (png, "$", "image.png"),
        (png, "con", "_con.png"),          # Windows'ta ayrilmis ad
    ]
    for desc, json_path, want in cases:
        got = IM.export_name(desc, json_path)
        if got != want:
            print(f"  ! export_name({json_path!r}): {got!r}, beklenen {want!r}")
            fail += 1

    # 2) Cakisma — harfe duyarsiz, hedefte duranlar dahil.
    got = IM.unique_names(["a.png", "A.png", "b.png"], {"B.PNG"})
    if got != ["a.png", "A-2.png", "b-2.png"]:
        print(f"  ! unique_names: {got}")
        fail += 1

    # 3) Yazma cekirdegi — gercek dosyalarla.
    tmp = Path(tempfile.mkdtemp(prefix="jsonimager-save-"))
    try:
        src, out = tmp / "doc", tmp / "out"
        (src / "assets").mkdir(parents=True)
        out.mkdir()
        Image.new("RGB", (4, 4), "red").save(src / "assets" / "logo.png")
        original = (src / "assets" / "logo.png").read_bytes()

        buf = io.BytesIO()
        Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
        payload = buf.getvalue()
        doc_path = src / "doc.json"
        doc_path.write_text(json.dumps({
            "a": "assets/logo.png",
            "b": "data:image/png;base64," + base64.b64encode(payload).decode(),
        }), encoding="utf-8")

        # Hedefte harf farkiyla AYNI ADLI bir dosya zaten var: dokunulmamali.
        sentinel = b"existing user file"
        (out / "LOGO.png").write_bytes(sentinel)

        api = Api()
        if (err := api._load_one(doc_path)):
            print(f"  ! kaydetme sondasi: belge yuklenemedi: {err}")
            return fail + 1
        doc = api._docs[str(doc_path)]

        picked = api._pick_images(doc, ["b", "a", "yok", "b"])
        if [p for p, _ in picked] != ["b", "a"]:
            print(f"  ! _pick_images istek sirasini korumadi: {[p for p, _ in picked]}")
            fail += 1

        written, skipped = api._write_images(doc, picked, out)
        names = sorted(p.name for p in written)
        if names != ["b.png", "logo-2.png"] or skipped:
            print(f"  ! yazilan adlar {names} · okunamayan {skipped}")
            fail += 1
        if (out / "LOGO.png").read_bytes() != sentinel:
            print("  ! hedefteki mevcut dosyanin USTUNE YAZILDI")
            fail += 1
        # Ozgun bayt: kaynak dosyanin kendisi ve cozulmus base64. Onizleme
        # yazilsaydi yeniden kodlanmis bir PNG gelirdi ve esitlik bozulurdu.
        if written and (out / "logo-2.png").read_bytes() != original:
            print("  ! dosya kaynagi ozgun baytlarla yazilmadi")
            fail += 1
        if written and (out / "b.png").read_bytes() != payload:
            print("  ! gomulu gorsel cozulmus baytlarla yazilmadi")
            fail += 1

        ghost = [("g", {"source": "file", "path": "assets/yok.png", "mime": "image/png"})]
        if api._write_images(doc, ghost, out) != ([], 1):
            print("  ! okunamayan gorsel sayilmadi")
            fail += 1

        # 4) Kopru: pencere yokken anlasilir hata, bos secimde ayri hata.
        desktop = I18N.t("err.desktop_only")
        for paths in (["a"], ["a", "b"]):
            res = api.save_images(str(doc_path), paths)
            if res.get("ok") or res.get("error") != desktop:
                print(f"  ! save_images ({len(paths)} gorsel) pencere yokken: {res}")
                fail += 1
        res = api.save_images(str(doc_path), ["yok"])
        if res.get("error") != I18N.t("err.no_selection"):
            print(f"  ! save_images bos secimde: {res}")
            fail += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not fail:
        print("  galeri kaydetme: ad kaynaktan · cakisma harfe duyarsiz · ustune yazma yok"
              " · baytlar ozgun · pencere yokken hata")
    return fail


def _check_view_modes() -> int:
    """Gorunum kipi UC yerde birden tanimli; ucu de ayni kumeyi soylemeli.

    Ekrandaki dugme (`index.html`), olcu haritasi (`panel.js`) ve varsayilan
    (`settings.DEFAULTS`). Biri otekinden saparsa kusur sessizdir: dugme
    `GALLERY_VIEWS[undefined]` uretir, kutu `NaN` olur ve onizleme HIC gelmez —
    ekranda yalnizca bos kartlar gorunur, konsolda hata yoktur.
    """
    from jsonimager import i18n as I18N
    from jsonimager import images as IM
    from jsonimager import settings as S

    js = (WEB / "js" / "panel.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")

    block = re.search(r"const GALLERY_VIEWS = \{([^}]*)\}", js)
    if block is None:
        print("  ! panel.js icinde GALLERY_VIEWS yok")
        return 1

    js_modes = dict(re.findall(r"(\w+):\s*(\d+)", block.group(1)))
    html_modes = set(re.findall(r'data-view="(\w+)"', html))
    default = S.DEFAULTS["images"]["view"]

    fail = 0
    if set(js_modes) != html_modes:
        only_js = sorted(set(js_modes) - html_modes)
        only_html = sorted(html_modes - set(js_modes))
        print(f"  ! kip listesi sapti — yalnizca JS'te: {only_js or '-'} · "
              f"yalnizca HTML'de: {only_html or '-'}")
        fail += 1
    if default not in js_modes:
        print(f"  ! varsayilan kip listede yok: {default}")
        fail += 1

    # Uretim kutusu gosterim kenarinin iki kati isteniyor; tavani asan bir kip
    # sessizce kirpilir ve o kipin onizlemesi bulanik kalir.
    for name, px in js_modes.items():
        if int(px) * 2 > IM.MAX_PREVIEW_PX:
            print(f"  ! `{name}` kipi uretim tavanini asiyor: {int(px) * 2} px")
            fail += 1

    missing = [f"ui.view_{m}" for m in js_modes
               if any(f"ui.view_{m}" not in I18N.STRINGS[lang] for lang in I18N.STRINGS)]
    if missing:
        print(f"  ! kip etiketi eksik: {', '.join(missing)}")
        fail += 1

    if not fail:
        print(f"  galeri kipleri: {len(js_modes)} kip · HTML/JS/varsayilan ayni · "
              f"etiketler {len(I18N.STRINGS)} dilde")
    return fail

def check_gallery(docs: list[Path]) -> int:
    """Liste ONIZLEME TASIMAZ, onizleme PARCA PARCA istenir.

    Iki gerileme birden hedefleniyor: (1) listeye yeniden `uri` konmasi —
    yuz gorselli belgede yanit onlarca megabayta cikardi ve kart ekrana
    girmeden uretilirdi; (2) uretim boyutunun gosterim boyutuna yapismasi —
    124 px'lik kart icin 900 px'lik PNG uretmek eski davranisti.
    """
    from jsonimager import images as IM
    from jsonimager.app import Api

    fail = (_check_view_modes() + _check_grouping() + _check_image_export()
            + _check_absolute_policy() + _check_url_policy())

    api = Api()
    doc_id = None
    for p in docs:
        if api._load_one(p):
            continue
        res = api.gallery(str(p))
        if res.get("ok") and res["items"]:
            doc_id = str(p)
            break

    if doc_id is None:
        print("  galeri: gorsel tasiyan belge yok, kip disindaki kapilar atlandi")
        return fail

    items = api.gallery(doc_id)["items"]

    leaked = [it["json_path"] for it in items if "uri" in it]
    if leaked:
        print(f"  ! galeri listesi onizleme tasiyor: {', '.join(leaked[:3])}")
        fail += 1

    paths = [it["json_path"] for it in items]
    want = paths[:2]
    res = api.gallery_thumbs(doc_id, want, 64)
    if not res.get("ok"):
        print(f"  ! gallery_thumbs: {res.get('error')}")
        return fail + 1

    got = [th["json_path"] for th in res["thumbs"]]
    if set(got) - set(want):
        print(f"  ! istenmeyen yol dondu: {', '.join(set(got) - set(want))}")
        fail += 1

    for th in res["thumbs"]:
        if th["width"] > 64 or th["height"] > 64:
            print(f"  ! onizleme istenen kutuyu asti: "
                  f"{th['width']}x{th['height']} > 64 ({th['json_path']})")
            fail += 1

    # Kutu istegi ne kadar buyuk olursa olsun uretim tavani asilmaz.
    big = api.gallery_thumbs(doc_id, want[:1], 9000)
    for th in big.get("thumbs", []):
        if max(th["width"], th["height"]) > IM.MAX_PREVIEW_PX:
            print(f"  ! uretim tavani asildi: {th['width']}x{th['height']}")
            fail += 1

    # ⚠ Kutu KATALOGU degistirmemeli: listedeki olcu gorselin ASIL olcusudur,
    # gosterim boyutu degil. Ikisi bir kez birbirine karismisti.
    after = api.gallery(doc_id)["items"]
    if [(i["width"], i["height"]) for i in after] != [(i["width"], i["height"])
                                                     for i in items]:
        print("  ! katalog olculeri onizleme istegiyle degisti")
        fail += 1

    # Kapsam disi yol hata degil: yaniti kucultur.
    ghost = api.gallery_thumbs(doc_id, ["$.yok[99]"], 64)
    if not ghost.get("ok") or ghost["thumbs"]:
        print("  ! kapsam disi yol sessizce atlanmadi")
        fail += 1

    empty = api.gallery_thumbs(doc_id, [], 64)
    if not empty.get("ok") or empty["thumbs"]:
        print("  ! bos istek bos yanit vermedi")
        fail += 1

    # `MAX_PIXELS` ustundeki gorselin GOVDESI cozulmez: bayrak listede olmali ve
    # onizleme istegi bos donmeli. Bayrak dusesse arayuz kartlari gozlemeye
    # baslar ve 100+ megapikselluk bir PNG'yi cozmeye kalkar.
    if any("oversize" not in it for it in items):
        print("  ! katalogda `oversize` bayragi eksik")
        fail += 1
    huge = [it["json_path"] for it in items if it.get("oversize")]
    if huge and api.gallery_thumbs(doc_id, huge[:1], 64).get("thumbs"):
        print(f"  ! olcu tavani asan gorsele onizleme uretildi: {huge[0]}")
        fail += 1

    if not fail:
        print(f"  galeri: {Path(doc_id).name} · {len(items)} gorsel "
              f"({len(huge)} olcu tavani ustunde) · liste onizlemesiz · "
              f"{len(res['thumbs'])} onizleme parca parca uretildi")
    return fail


# --- Hakkinda penceresi (Faz 9.3.4) ----------------------------------------

def check_about() -> int:
    """Ucuncu taraf atiflari kurulu paketlerle ayni mi?

    Liste elle tutuluyor (`api_settings.THIRD_PARTY`) cunku PyInstaller
    dist-info'yu her paket icin gomuyor — calisma aninda okumak dondurulmus
    exe'de listeyi sessizce bosaltirdi. Elle liste bayatlar; bu denetim onu
    yakalar. Bir bagimlilik yukseltilince BURASI kirmizi yanar ve atif
    guncellenir.

    Tanilama metni ayrica **yol tasimamali**: `app_info()` ciktisinda yol
    gorunuse benzeyen bir deger olmadigini da dogrularuz.
    """
    from importlib.metadata import PackageNotFoundError, version

    from jsonimager.api_settings import THIRD_PARTY

    fail = 0
    for name, declared, _lic in THIRD_PARTY:
        try:
            actual = version(name)
        except PackageNotFoundError:
            print(f"  ! atif listesinde kurulu olmayan paket: {name}")
            fail += 1
            continue
        if actual != declared:
            print(f"  ! {name} atfi bayat: listede {declared}, kurulu {actual}")
            fail += 1

    # `app_info()` yol sizdirmamali — tanilama metni bundan uretiliyor.
    from jsonimager.app import Api

    info = Api().app_info()
    flat = " ".join(str(v) for k, v in info.items() if k != "third_party")
    if re.search(r"[A-Za-z]:\\|/home/|/Users/", flat):
        print(f"  ! app_info() dosya yolu tasiyor: {flat[:80]}")
        fail += 1

    if not fail:
        print(f"  hakkinda: {len(THIRD_PARTY)} atif kurulu surumle ayni · "
              "app_info yol tasimiyor")
    return fail


# --- Paket icerigi (Faz 9.8.3.1) -------------------------------------------

# `requirements.txt`te olup exe'ye GIRMEYEN dagitimlar: paketleme araci.
BUILD_TOOLS = ("pyinstaller",)
# Exe'de BULUNMAMASI gereken ust duzey paketler. 2026-09-14 derlemesinde hepsi
# vardi: pywebview/pythonnet kancalari PyInstaller'i, `cffi` derleme yolu
# setuptools'u cekiyordu. PyInstaller modulleri GPL-2.0 ve onyukleyici istisnasi
# disinda. `build.spec` bu demeti okuyamaz; kapi oradaki `excludes`i metinden arar.
BUILD_ONLY = ("PyInstaller", "setuptools", "pkg_resources", "_distutils_hack",
              "packaging", "altgraph", "pefile", "ordlookup", "win32ctypes")


def _dist_key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_closure() -> dict[str, str]:
    """Exe'ye giren dagitimlar (normal ad → surum): `requirements.txt` kapanisi.

    Windows isaretleri degerlendirilir (`pywebview` macOS'ta pyobjc ister, burada
    istemez); `extra` bagimliliklari alinmaz. `BUILD_TOOLS` kokte dusurulur. Yalnizca okur.
    """
    from importlib.metadata import distribution
    from packaging.requirements import Requirement

    env = {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "extra": ""}
    roots = [Requirement(line.split("#")[0]).name
             for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
             if line.split("#")[0].strip()]
    out: dict[str, str] = {}
    todo = [r for r in roots if _dist_key(r) not in BUILD_TOOLS]
    while todo:
        name = todo.pop()
        key = _dist_key(name)
        if key in out:
            continue
        dist = distribution(name)
        out[key] = dist.version
        for spec in dist.requires or []:
            req = Requirement(spec)
            if req.marker is None or req.marker.evaluate(env):
                todo.append(req.name)
    return dict(sorted(out.items()))


def _toc_entries(path: Path) -> list[tuple[str, str, str]]:
    """PyInstaller `.toc` dokumunun (ad, yol, tur) uclulerini duzlestirir."""
    import ast

    def flat(x):
        if isinstance(x, (list, tuple)):
            if len(x) == 3 and all(isinstance(i, str) for i in x):
                yield x
            else:
                for i in x:
                    yield from flat(i)
    return list(flat(ast.literal_eval(path.read_text(encoding="utf-8"))))


def check_bundle() -> int:
    """Exe'de derleme araci yok ve paketlenen her ucuncu taraf paketi kapanista mi.

    ⚠ `.venv` taramasi Grep araciyla YAPILMAZ: `.gitignore` yuzunden sessizce
    atlaniyor ve "ice aktaran yok" sonucu arama bozuklugu olabilir (9.8.3 olcumu).

    Iki katman:
      (a) `build.spec` metni: kanca suzgeci var ve her `BUILD_ONLY` adi `excludes`te.
          Derlemeden bagimsiz, her kosuda.
      (b) Son derlemenin dokumu (`build/build/PYZ-00.toc`, `PKG-00.toc`): yalnizca
          `build.spec`ten YENIYSE olculur. Derleme kullanicida; eski dokum duzeltmeden
          onceki icerigi gosterir ve kapiyi yanlis kirmizi yakardi. Yoksa ya da bayatsa
          bildirilir, basarisizlik sayilmaz.
    """
    fail = 0
    spec = (ROOT / "build.spec").read_text(encoding="utf-8")
    m = re.search(r"excludes=\[(.*?)\]", spec, re.S)
    excluded = set(re.findall(r'"([\w.]+)"', m.group(1))) if m else set()
    if missing := [n for n in BUILD_ONLY if n not in excluded]:
        print(f"  ! build.spec derleme aracini dislamiyor: {', '.join(missing)}")
        fail += 1
    if not re.search(r"collect_all\(pkg, filter_submodules=", spec) or '"_pyinstaller"' not in spec:
        print("  ! build.spec paketlerin kendi PyInstaller kancalarini suzmuyor")
        fail += 1

    closure = runtime_closure()
    build = ROOT / "build" / "build"
    pyz, pkg = build / "PYZ-00.toc", build / "PKG-00.toc"
    if not (pyz.is_file() and pkg.is_file()):
        note = "derleme dokumu yok, icerik olculmedi"
    elif min(pyz.stat().st_mtime, pkg.stat().st_mtime) < (ROOT / "build.spec").stat().st_mtime:
        note = "derleme dokumu build.spec'ten eski, icerik olculmedi (yeniden derle)"
    else:
        tops, bad, stray = bundle_findings(pyz, pkg, closure)
        if bad:
            print(f"  ! exe'de derleme araci paketlenmis: {', '.join(bad)}")
            fail += 1
        if stray:
            print(f"  ! exe'de kapanis disi dagitim (atif belgesinde olmayacak): {', '.join(stray)}")
            fail += 1
        note = f"son derlemede {len(tops)} ust duzey ad · derleme araci yok"

    if not fail:
        print(f"  paket icerigi: kapanis {len(closure)} dagitim · build.spec {len(BUILD_ONLY)}"
              f" derleme aracini disliyor · {note}")
    return fail


# `K-30` — proje lisansi.
LICENSE_HEAD = ("MIT License", "Copyright (c) 2026 Barış Karakaya")

EXE_PATH = ROOT / "dist" / "JSON Imager.exe"


def _exe_strings(info) -> dict[str, str]:
    """Okunan kunyenin metin alanlari (`VSVersionInfo` -> ad: deger)."""
    out: dict[str, str] = {}
    for block in info.kids:
        if getattr(block, "name", "") != "StringFileInfo":
            continue
        for table in block.kids:
            out.update({s.name: s.val for s in table.kids})
    return out


def check_tls_probe() -> int:
    """Iki HTTPS yolu Windows'un dogrulayicisini kullaniyor mu (9.9.2 · 9.24, `K-35`).

    `9.9.2`de iki yol da Python'un varsayilan baglamindaydi ve bu kapi ondan
    ayrilmayi yasakliyordu — "o gun gelirse olcum de birlikte degisir" diye.
    O gun geldi: Windows Sandbox'ta varsayilan baglam 11 kok gordu ve iki yol da
    `CERTIFICATE_VERIFY_FAILED` ile dustu. Simdi olculen:
      - tek kaynak `providers.tls_context()`: `truststore` baglami, ana bilgisayar
        adi denetimi ACIK, `CERT_REQUIRED`
      - iki yol da (`providers`, `remote_images`) o baglami kullaniyor
      - baska hicbir sertifika kaynagi ya da dogrulamayi kapatan bir ayar yok
      - tanilamadaki kok sayisi (bilgi amacli) koprude
    Aga cikilmaz.
    """
    import ast
    import ssl
    import urllib.request
    from jsonimager import providers as PV
    from jsonimager import remote_images as RI
    from jsonimager.app import Api
    out = []
    ctx = PV.tls_context()
    if type(ctx).__module__.split(".")[0] != "truststore":
        out.append(f"tls_context truststore baglami degil — {type(ctx)}")
    if not ctx.check_hostname or ctx.verify_mode != ssl.CERT_REQUIRED:
        out.append("tls_context dogrulamayi gevsetiyor")
    if PV.tls_context() is not ctx:
        out.append("tls_context her cagrida yeni baglam kuruyor")

    # Yol 1 — gorseller: kurulan isleyici ayni baglami tasiyor mu.
    if getattr(RI._https_handler(), "_context", None) is not ctx:
        out.append("remote_images ortak TLS baglamini kullanmiyor")
    # Yol 2 — saglayicilar: acici kurulurken verilen HTTPS isleyicisi yakalanir.
    seen: list = []
    real = urllib.request.build_opener
    urllib.request.build_opener = lambda *h: (seen.extend(h), real(*h))[1]
    try:
        try:
            PV._HttpProvider()._open(urllib.request.Request("https://tls.invalid/", method="POST"))
        except Exception:
            pass          # ad cozulemez; yalnizca kurulan isleyici olculuyor
    finally:
        urllib.request.build_opener = real
    if not any(getattr(h, "_context", None) is ctx for h in seen):
        out.append("saglayicilar ortak TLS baglamini kullanmiyor")

    # Kaynak: baska sertifika kaynagi ya da kapatilmis dogrulama yok. `truststore`
    # ve `SSLContext(` YALNIZCA `tls_context` icinde gecebilir.
    own = re.compile(r"certifi|truststore|cafile\s*=|capath\s*=|SSLContext\(|load_verify_locations"
                     r"|_create_unverified_context|CERT_NONE|check_hostname\s*=\s*False")
    for name in ("providers.py", "remote_images.py"):
        src = (ROOT / "src" / "jsonimager" / name).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == "tls_context":
                src = src.replace(ast.get_source_segment(src, node), "")
        code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        hits = sorted(set(own.findall(code)))
        if hits:
            out.append(f"{name} ortak TLS baglaminin disinda: {', '.join(hits)}")

    n = PV.tls_roots()
    info = Api().app_info()
    if info.get("tls_roots") != n or isinstance(info.get("tls_roots"), bool):
        out.append("app_info tls_roots tasimiyor ya da olcumle ayni degil")
    if out:
        for o in out:
            print(f"  ! TLS olcumu: {o}")
        return len(out)
    print(f"  TLS olcumu: iki HTTPS yolu Windows dogrulayicisinda (truststore) · ad denetimi ve "
          f"CERT_REQUIRED acik · baska sertifika kaynagi yok · depoda {n} kok (bilgi)")
    return 0


def check_version_info() -> int:
    """Exe'nin surum kunyesi `__version__`dan mi (Faz 9.9.1).

    Uc katman:
      (a) `tools/version_info.py`nin saf kurallari: dort parcali sayisal surum,
          surumun TEK kaynaktan okunmasi, telif satirinin `LICENSE` ile ayni olmasi.
      (b) `build.spec` kunyeyi oradan aliyor ve kendisi surum yazmiyor — elle
          yazilan bir numara ilk surum yukseltmesinde unutulurdu.
      (c) Son derleme: exe kaynaktan YENIYSE kunyesi geri okunur ve
          karsilastirilir, boyutu bildirilir. Derleme kullanicida; exe yoksa ya
          da bayatsa bildirilir, basarisizlik sayilmaz (`check_bundle` kalibi).
    """
    import jsonimager
    import version_info as VI
    out = []
    for text, want in [("0.1.0", (0, 1, 0, 0)), ("1.0.0", (1, 0, 0, 0)), ("1.2", (1, 2, 0, 0)),
                       ("1.0.0rc1", (1, 0, 0, 0)), ("2.10.3.4.5", (2, 10, 3, 4)), ("x", (0, 0, 0, 0))]:
        if VI.file_version(text) != want:
            out.append(f"file_version({text!r}) = {VI.file_version(text)}, beklenen {want}")
    version = jsonimager.__version__
    if VI.read_version() != version:
        out.append(f"kunye surumu {VI.read_version()!r}, paket {version!r}")
    fields = VI.strings()
    if fields["FileVersion"] != version or fields["ProductVersion"] != version:
        out.append("kunye metni surumu tasimiyor")
    if fields["LegalCopyright"] != LICENSE_HEAD[1]:
        out.append("kunyenin telif satiri LICENSE ile ayni degil")

    # Kunye nesnesi gercekten kurulabiliyor mu: `build()` hata verirse bu ancak
    # kullanicinin derlemesinde gorunurdu. PyInstaller yoksa (public agac) atlanir.
    try:
        built = VI.build()
    except ImportError:
        built = None
    if built is not None:
        ms, ls = built.ffi.fileVersionMS, built.ffi.fileVersionLS
        if (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF) != VI.file_version(version) \
                or _exe_strings(built) != fields:
            out.append("kurulan kunye nesnesi kaynakla ayni degil")

    spec = (ROOT / "build.spec").read_text(encoding="utf-8")
    if "version=version_info.build()" not in spec:
        out.append("build.spec kunyeyi version_info'dan almiyor")
    code = "\n".join(line.split("#", 1)[0] for line in spec.splitlines())
    if re.search(r"filevers|StringStruct|\b\d+\.\d+\.\d+\b", code):
        out.append("build.spec'te elle yazilmis surum var")

    sources = [ROOT / "build.spec", ROOT / "src" / "jsonimager" / "__init__.py",
               ROOT / "tools" / "version_info.py", ROOT / "LICENSE"]
    if not EXE_PATH.is_file():
        note = "exe yok, kunye olculmedi"
    elif EXE_PATH.stat().st_mtime < max(p.stat().st_mtime for p in sources):
        note = "exe kaynaktan eski, kunye olculmedi (yeniden derle)"
    else:
        try:
            from PyInstaller.utils.win32.versioninfo import read_version_info_from_executable
            info = read_version_info_from_executable(str(EXE_PATH))
        except Exception as exc:   # PyInstaller yok ya da exe'de kunye yok
            info = None
            out.append(f"exe'nin kunyesi okunamadi: {type(exc).__name__}")
        if info is not None:
            ms, ls = info.ffi.fileVersionMS, info.ffi.fileVersionLS
            numbers = (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
            got = _exe_strings(info)
            if numbers != VI.file_version(version) or got.get("FileVersion") != version:
                out.append(f"exe'nin surumu {got.get('FileVersion')!r} {numbers}, kaynak {version!r}")
            if got.get("ProductName") != VI.PRODUCT or got.get("LegalCopyright") != LICENSE_HEAD[1]:
                out.append("exe'nin urun adi ya da telif satiri yanlis")
        note = f"exe {version} · {EXE_PATH.stat().st_size / 1_048_576:.1f} MB"

    if out:
        for o in out:
            print(f"  ! surum kunyesi: {o}")
        return len(out)
    print(f"  surum kunyesi: tek kaynak __version__ ({version}) · build.spec'te elle surum yok · {note}")
    return 0


README_PAIR = ("README.md", "README.tr.md")
SCREENSHOT_DIR = "docs/screenshots"
_MD_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def _md_outline(text: str) -> tuple[list[int], list[str]]:
    """(baslik duzeyleri, goreli baglantilar) — kod bloklarinin disinda."""
    levels: list[int] = []
    links: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if m := re.match(r"(#{1,6}) \S", line):
            levels.append(len(m.group(1)))
        for target in _MD_LINK.findall(line):
            if not re.match(r"[a-z][a-z0-9+.-]*:|#", target, re.I):
                links.append(target.split("#", 1)[0])
    return levels, links


def check_readme(root: Path = ROOT) -> int:
    """Iki README (9.10.1, `K-29`) — public deponun kapisi.

      - ikisi de var ve AYNI baslik yapisini tasir (duzey dizisi): biri degisince
        oteki ayni turda guncellenmezse kirmizi
      - her goreli baglanti ve gorsel public agacta VAR (`PUBLIC_SCOPE`): depoda
        olup public'e cikmayan bir dosyaya baglanti GitHub'da kirik gorunurdu
      - ikisi birbirine baglanir (dil secimi) ve ayni gorsel ADLARINI kullanir
        (Ingilizce takim alt klasorde ayni adla gelir)
      - `docs/screenshots` altindaki her gorsel en az bir README'de kullanilir:
        kullanilmayan gorsel gozden gecmeden yayimlanirdi
    """
    out: list[str] = []
    public = scope_files(root)
    seen_images: dict[str, set[str]] = {}
    outlines: dict[str, list[int]] = {}
    used: set[str] = set()
    for name in README_PAIR:
        path = root / name
        if not path.is_file():
            out.append(f"{name} yok")
            continue
        levels, links = _md_outline(path.read_text(encoding="utf-8"))
        outlines[name] = levels
        if levels[:1] != [1] or levels.count(1) != 1:
            out.append(f"{name}: tek bir 1. duzey baslikla baslamiyor")
        for link in links:
            rel = (Path(name).parent / link).as_posix()
            used.add(rel)
            if rel not in public:
                out.append(f"{name}: baglanti public agacta yok — {link}")
        seen_images[name] = {Path(l).name for l in links if l.startswith(SCREENSHOT_DIR + "/")}
        other = next(n for n in README_PAIR if n != name)
        if other not in links:
            out.append(f"{name}: {other} baglantisi (dil secimi) yok")
    if len(outlines) == 2 and len(set(map(tuple, outlines.values()))) != 1:
        a, b = (outlines[n] for n in README_PAIR)
        out.append(f"baslik yapisi farkli: {len(a)} / {len(b)} baslik")
    if len(seen_images) == 2 and len({frozenset(s) for s in seen_images.values()}) != 1:
        out.append(f"gorsel adlari farkli: {sorted(set.symmetric_difference(*seen_images.values()))}")
    orphans = sorted(f for f in public if f.startswith(SCREENSHOT_DIR + "/") and f not in used)
    if orphans:
        out.append(f"README'de kullanilmayan gorsel yayimlanacak: {orphans}")
    if out:
        for o in out:
            print(f"  ! README: {o}")
        return len(out)
    n = len(outlines[README_PAIR[0]])
    print(f"  README: iki dil · {n} baslik ayni yapida · {len(used)} goreli baglanti public "
          f"agacta · {len(seen_images[README_PAIR[0]])} gorsel, hepsi kullaniliyor")
    return 0


def check_notices() -> int:
    """`LICENSE` ve `THIRD-PARTY-NOTICES.md` exe'nin icerigiyle tutarli mi (9.8.3.2).

      - `LICENSE` MIT ve telif satiri karardaki gibi
      - atif belgesi `make_notices.build_notices()`un BUGUNKU ciktisiyla ayni: bir
        bagimlilik yukseltilince ya da `licenses/` degisince kirmizi
      - kapanistaki her dagitimin ve paket olmayan her bilesenin bolumu var
      - Hakkinda listesi (`THIRD_PARTY`) kapanisin alt kumesi — ikinci bir atif
        listesi dogmasin
      - `licenses/webview2-sdk.txt` surumu paketlenen DLL'in dosya surumuyle ayni:
        pywebview SDK'yi yukseltirse eski lisans metni sessizce kalmasin
    """
    fail = 0
    lic = ROOT / "LICENSE"
    head = lic.read_text(encoding="utf-8").splitlines()[:3] if lic.is_file() else []
    if [h for h in head if h] != list(LICENSE_HEAD):
        print(f"  ! LICENSE MIT ya da telif satiri karardan farkli: {head[:3]}")
        fail += 1

    if not (ROOT / "tools" / "make_notices.py").is_file():
        print("  ! tools/make_notices.py yok")
        return fail + 1
    import make_notices as MN

    out = ROOT / "THIRD-PARTY-NOTICES.md"
    expected = MN.build_notices()
    if not out.is_file() or out.read_text(encoding="utf-8") != expected:
        print("  ! THIRD-PARTY-NOTICES.md bayat — "
              r"`.\.venv\Scripts\python.exe tools\make_notices.py` ile yenile")
        fail += 1

    # Basliklar kod bloklarinin DISINDAN okunur: lisans metinleri de `## ` satiri
    # tasiyor (pythonnet `AUTHORS.md`) ve metnin icindeki bir satir eksik bolumu
    # varmis gibi gosterirdi.
    outside = re.sub(r"^(`{3,})text\n.*?^\1$", "", expected, flags=re.M | re.S)
    titles = set(re.findall(r"^## (.+)$", outside, re.M)) - {"Contents"}
    from importlib.metadata import distribution
    closure = runtime_closure()
    names = {distribution(k).metadata["Name"] for k in closure}
    if missing := sorted(names - titles):
        print(f"  ! atif belgesinde bolumu olmayan dagitim: {', '.join(missing)}")
        fail += 1
    if missing := [t for t, *_ in MN.VENDORED if t not in titles]:
        print(f"  ! atif belgesinde bolumu olmayan bilesen: {', '.join(missing)}")
        fail += 1

    from jsonimager.api_settings import THIRD_PARTY
    if extra := [n for n, v, _ in THIRD_PARTY if closure.get(_dist_key(n)) != v]:
        print(f"  ! Hakkinda atfi kapanista yok ya da surumu farkli: {', '.join(extra)}")
        fail += 1

    import webview
    import pefile

    dll = Path(webview.__file__).parent / "lib" / "Microsoft.Web.WebView2.Core.dll"
    pe = pefile.PE(str(dll), fast_load=True)
    pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    fixed = pe.VS_FIXEDFILEINFO[0]
    dll_version = (f"{fixed.FileVersionMS >> 16}.{fixed.FileVersionMS & 0xFFFF}"
                   f".{fixed.FileVersionLS >> 16}.{fixed.FileVersionLS & 0xFFFF}")
    vendored = MN.vendored(MN.LICENSES / "webview2-sdk.txt")[0].get("Version")
    if vendored != dll_version:
        print(f"  ! WebView2 lisans metni {vendored} icin, paketlenen DLL {dll_version}")
        fail += 1
    # CPython bildirimi surume sabit indirildi; Python yamasi degisince yeniden alinir.
    cp = MN.vendored(MN.LICENSES / "cpython-incorporated.txt")[0].get("Version")
    if cp != sys.version.split()[0]:
        print(f"  ! CPython bildirimi {cp} icin, calisma zamani {sys.version.split()[0]}")
        fail += 1

    if not fail:
        print(f"  lisans: MIT · atif belgesi guncel · {len(titles)} bilesen"
              f" ({len(closure)} dagitim + {len(titles) - len(closure)} diger)"
              f" · WebView2 {dll_version} metniyle eslesiyor")
    return fail


def bundle_findings(pyz: Path, pkg: Path, closure: dict[str, str]
                    ) -> tuple[set[str], list[str], list[str]]:
    """(ust duzey adlar, paketlenmis derleme araclari, kapanis disi dagitimlar). Yalnizca okur.

    Standart kutuphane ve kendi paketimiz hicbir dagitima eslenmez, sayilmaz.
    """
    from importlib.metadata import packages_distributions

    dists = packages_distributions()
    tops = {name.split(".")[0] for name, _p, _k in _toc_entries(pyz)}
    tops |= {re.split(r"[\\/]", name)[0] for name, _p, kind in _toc_entries(pkg)
             if kind in {"BINARY", "EXTENSION", "DATA"}}
    bad = sorted(t for t in tops if t in BUILD_ONLY)
    stray = sorted({d for t in tops if t not in BUILD_ONLY for d in dists.get(t, [])
                    if _dist_key(d) not in closure})
    return tops, bad, stray


# --- Logo (Faz 9.3.1) ------------------------------------------------------

def check_logo() -> int:
    """Depodaki logo, `make_icon.py`nin BUGUN uretecegi seyle ayni mi?

    Logo elle duzenlenebilir bir dosya gibi duruyor ama uretilmis bir cikti;
    biri `logo.svg`yi elle rotuslarsa `.ico` ile arayuz logosu **sessizce**
    ayrisir — biri yeni sekli, oteki eskisini gosterir. Denetim betigi
    calistirmadan yalnizca ciktisini karsilastirir.

    `.ico` ayrica VAR OLMALI: `build.spec` onu `EXE(icon=)` ile istiyor ve
    eksikse paketleme kullanicinin elinde patlar — burada yakalamak ucuz.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import make_icon

    fail = 0
    svg = WEB / "logo.svg"
    if not svg.is_file():
        print("  ! web/logo.svg yok — `tools/make_icon.py` calistirilmali")
        return 1
    if svg.read_text(encoding="utf-8") != make_icon.build_svg():
        print("  ! web/logo.svg uretecin ciktisindan farkli — elle mi duzenlendi?")
        print(r"    `.\.venv\Scripts\python.exe tools\make_icon.py` ile yenile")
        fail += 1

    # Sozcuk isareti (`K-33`) `index.html`de SATIR ICIDIR: rengini temadan
    # almasi icin. Bu, uretecin ciktisinin ikinci bir kopyasi demek — tam da
    # `<img>` kuralinin onlemek istedigi sey. Kopya burada kilitlenir: satir
    # ureticinin BUGUNKU ciktisiyla ayni olmali, renk ise CSS'te belirtecten.
    html = (WEB / "index.html").read_text(encoding="utf-8")
    if make_icon.wordmark_markup() not in html:
        print("  ! index.html'deki sozcuk isareti uretecin ciktisindan farkli")
        print("    `tools/make_icon.py` ciktisindaki satir `#btn-app` icine yazilmali")
        fail += 1
    css = (WEB / "style.css").read_text(encoding="utf-8")
    for cls, token in ((".wm-j", "--json"), (".wm-img", "--export")):
        if not re.search(rf"{re.escape(cls)}\s*\{{\s*stroke:\s*var\({token}\)", css):
            print(f"  ! sozcuk isareti rengi belirtecten gelmiyor: {cls} -> {token}")
            fail += 1
    # Simge kendi koyu zeminini tasir ve temayla degismez; renkleri koyu temanin
    # belirtecleriyle AYNI olmali ki sozcuk isaretiyle yan yana ayri tonlarda
    # durmasin. Dosyadaki ILK tanim koyu temadir (`:root`).
    def first(token: str) -> str:
        m = re.search(rf"--{token}:\s*(#[0-9a-fA-F]{{6}})", css)
        return m.group(1).lower() if m else ""
    if make_icon.AMBER.lower() != first("json") or make_icon.ACCENT.lower() != first("export"):
        print(f"  ! simge renkleri koyu temanin belirtecleriyle ayni degil: "
              f"--json {first('json')} · --export {first('export')}")
        fail += 1

    ico = ROOT / "assets" / "icon.ico"
    if not ico.is_file():
        print("  ! assets/icon.ico yok — build.spec `EXE(icon=)` ile istiyor")
        return fail + 1

    # Butun boyutlar gomulu mu? Eksik boyut sessizce olceklenir ve gorev
    # cubugunda bulanik cikar — bakan kimse "eksik" demez, "cirkin" der.
    from PIL import Image

    # ⚠ Her kare uretecin BUGUN cizecegiyle ayni mi? SVG karsilastirmasinin
    # ikili karsiligi. Yalnizca "dosya var mi" demek yetmez: `.ico` bayat
    # kalabilir, ya da `SIMPLE_MAX_PX` esigi degisip 16 px sessizce tam cizime
    # donebilir (Faz 9.3.1'de tam cizim o boyutta lekeye donusuyordu).
    #
    # Once "sade surum tam surumden farkli mi" diye bakiliyordu; o denetim
    # esik degisikligini GORMUYORDU, cunku fonksiyonlarin uretebildigine
    # bakiyordu, dosyanin icindekine degil.
    #
    # Dosya BIR KEZ acilir: `.ico` butun kareleri tek cozumlemede veriyor,
    # boyut basina yeniden acmak ayni dosyayi dort kez ayristirmakti.
    with Image.open(ico) as im:
        have = {n for n, _ in im.ico.sizes()}
        if missing := set(make_icon.ICO_SIZES) - have:
            print(f"  ! icon.ico'da eksik boyut: {sorted(missing)}")
            fail += 1

        for n in sorted(set(make_icon.ICO_SIZES) & have):
            frame = im.ico.getimage((n, n)).convert("RGBA")
            if frame.tobytes() != make_icon.build_png(n).convert("RGBA").tobytes():
                print(f"  ! icon.ico {n} px karesi uretecin ciktisindan farkli")
                print(r"    `.\.venv\Scripts\python.exe tools\make_icon.py` ile yenile")
                fail += 1

    if not fail:
        small = [n for n in make_icon.ICO_SIZES if n <= make_icon.SIMPLE_MAX_PX]
        print(f"  logo: svg uretecle ayni · icon.ico {ico.stat().st_size // 1024} KB · "
              f"{len(have)} boyut, {len(small)} tanesi sadelesmis")
    return fail


def check_window_fit() -> int:
    """Acilis boyutu ekrana sigar mi (9.14.5, `app._fit_screen`).

    Pencere acilmaz: `_fit_screen` sahte bir formla cagrilir, ekran gercek
    ekrandir. Hicbir ekrandan buyuk olamayacak bir form kisilip buyutulmeli,
    her ekrana sigan bir form hic degismemeli. Olay kaydi da denetlenir —
    islev dogru olup `before_show`a baglanmazsa hicbir sey olmaz.
    """
    from webview.platforms import winforms  # noqa: F401 — .NET derlemelerini yukler
    from System.Windows.Forms import Cursor, FormWindowState, Screen
    from jsonimager import app as APP

    class Form:
        def __init__(self, w: int, h: int) -> None:
            self.Width, self.Height, self.WindowState = w, h, None

        @property
        def Size(self):  # noqa: N802 — .NET ozellik adi
            return (self.Width, self.Height)

        @Size.setter
        def Size(self, s) -> None:  # noqa: N802
            self.Width, self.Height = s.Width, s.Height

    class Win:
        def __init__(self, form: Form) -> None:
            self.native = form

    area = Screen.FromPoint(Cursor.Position).WorkingArea
    out = []
    big, small = Form(100_000, 100_000), Form(100, 100)
    APP._fit_screen(Win(big))
    APP._fit_screen(Win(small))
    if (big.Width, big.Height) != (area.Width, area.Height):
        out.append(f"buyuk form {big.Width}x{big.Height}, calisma alani {area.Width}x{area.Height}")
    if big.WindowState != FormWindowState.Maximized:
        out.append("buyuk form buyutulmedi")
    if (small.Width, small.Height, small.WindowState) != (100, 100, None):
        out.append("ekrana sigan form degisti")
    src = (ROOT / "src" / "jsonimager" / "app.py").read_text(encoding="utf-8")
    if "window.events.before_show += _fit_screen" not in src:
        out.append("_fit_screen before_show'a bagli degil")
    if out:
        print(f"  ! acilis boyutu: {' · '.join(out)}")
        return len(out)
    print(f"  acilis boyutu: ekrandan buyuk pencere {area.Width}x{area.Height}'e kisilip "
          f"buyutuluyor · sigan dokunulmuyor · before_show'a bagli")
    return 0


def main() -> int:
    # `-q` RUTIN kosunun kipidir: belge bloklari basilmaz, yalnizca bolum
    # sonuclari ve varsa hatalar gorunur. Tam cikti 125 satir, sessiz kip ~12 —
    # her kosuda `grep` ile suzmek hem tur harciyor hem etiket adi degisince
    # sessizce yanlis suzuyordu. `--datasets` dokum ister, sessiz kiple birlikte
    # kullanilmaz.
    quiet = ("-q" in sys.argv or "--quiet" in sys.argv) and "--datasets" not in sys.argv

    # ⚠ Hicbir denetim kullanicinin GERCEK oturum dosyasina dokunmamali (9.19.5).
    # Bircok denetim `Api()`yi gercek ayarlarla kuruyor ve belge acip kapatiyor;
    # kullanici geri yuklemeyi actiysa bu kosu, uygulamanin bir sonraki acilista
    # geri yukleyecegi listeyi gecici dosya yollariyla ezerdi.
    import tempfile
    from jsonimager import settings as S
    session_dir = tempfile.TemporaryDirectory()
    S.session_path = lambda: Path(session_dir.name) / S.SESSION_NAME

    # Arayuz denetimi belgeye bagli degil: samples/ bos olsa da calisir, bu
    # yuzden erken donuslerin ONUNDE durur.
    print("=== arayuz ===")
    fail = check_web()
    fail += check_theme()
    fail += check_import_chain()
    fail += check_settings()
    fail += check_keys()
    fail += check_key_bridge()
    fail += check_providers()
    fail += check_i18n()
    fail += check_ui_strings()
    fail += check_settings_rows()
    fail += check_prefs()
    fail += check_agent_values()
    fail += check_search_output()
    fail += check_custom_provider()
    fail += check_discover_coverage()
    fail += check_py_strings()
    fail += check_logo()
    fail += check_about()
    fail += check_bundle()
    fail += check_version_info()
    fail += check_tls_probe()
    fail += check_notices()
    fail += check_readme()
    fail += check_api()
    fail += check_window_fit()
    fail += check_edit_core()
    fail += check_json_save()
    fail += check_edit_bridge()
    fail += check_edit_messages()
    fail += check_exit_flow()
    fail += check_rename_dataset()
    fail += check_rename_column()
    fail += check_doc_write()

    # `examples/` IZLENIR ve depoyla birlikte gelir: klonlayan biri dogrulamayi
    # gercek belgelerle kosabilsin. `samples/` izlenmez ve ozeldir; varsa o da
    # taranir ama yoklugu basarisizlik degildir.
    docs = sorted(EXAMPLES.glob("*.json")) + sorted(SAMPLES.glob("*.json"))
    if not docs:
        print(f"\nDogrulanacak belge yok: {EXAMPLES} bos ya da yok.")
        print("`tools/make_examples.py` ornekleri yeniden uretir.")
        return 1 if fail else 0

    for p in docs:
        head = f"\n=== {p.name}  ({p.stat().st_size / 1024:,.0f} KB) ==="
        if not quiet:
            print(head)
            fail += check_document(p)
            continue

        # SESSIZ KIP: belge blogu yakalanir ve YALNIZCA o belge basarisizsa
        # basilir. Boylece rutin kosu on satira iner ama hata durumunda tam
        # baglam korunur — kirpilmis bir hata mesaji tesissiz kalirdi.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bad = check_document(p)
        if bad:
            print(head)
            print(buf.getvalue(), end="")
        fail += bad

    if quiet:
        print(f"\n  {len(docs)} belge dogrulandi")

    # Belge basina degil, depo basina: izlenen belgelere ozel ad sizmis mi.
    print("\n=== depo ===")
    fail += check_doc_privacy()
    fail += check_security()
    fail += check_public_refs()
    fail += check_architecture_doc()
    fail += check_public_tree()
    # Kopru akisi tek belgeyle yeter: amac mixin bilesimini sinamak, belgeleri
    # degil — onlari `check_document` zaten tek tek geziyor.
    fail += check_api_smoke(docs[0])
    fail += check_model_store(docs[0])
    # Galeri gorsel TASIYAN bir belge ister; listeyi kendisi geziyor.
    fail += check_gallery(docs)

    # Gercek Claude cagrisi yalnizca acikca istendiginde.
    if "--claude" in sys.argv:
        fail += check_claude(docs[0])

    print("\n" + "=" * 60)
    print(f"{len(docs)} belge · " + ("TUM KONTROLLER GECTI" if fail == 0
                                     else f"{fail} KONTROL BASARISIZ"))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
