'use strict';

/* Paylasilan durum ve olculer.
 *
 * EN ONCE yuklenir (bkz. index.html). Bolumler arasinda gezinen her degisken
 * burada durur; yalnizca tek bir dosyanin ilgilendigi durum (ornegin grafik
 * secimleri, sohbet seridi) kendi dosyasinda kalir.
 *
 * ES MODULU YOK (`K-21`): pywebview pencereyi `file://` ile acar ve
 * `type="module"` orada null origin yuzunden CORS'a takilir — exe'de SESSIZCE
 * calismaz, dev sunucusunda calisir. Dosyalar `index.html` icinde sirayla
 * yuklenir, tanimlar global kapsamdadir.
 */

let api = null;                          // window.pywebview.api
let tree = { folders: [], docs: [] };    // sol panel agaci
let sel = null;                          // {docId, dsId, variantId}
let cur = null;                          // {table, view, doc}
let filterText = '';
let treeFilter = '';
let expanded = new Set();                // acik satirlar
let collapsed = new Set();               // kapali agac dugumleri
let saveTimer = null;

const MIN_W = 60, MAX_W = 320;
// Sutun genisligi hesabinin katsayilari (`columns.autoWidth`). Karakter basina
// piksel kaba bir tahmindir; gercek olcum icin tarayicida metin olcmek gerekirdi
// ve ayni sayiyi Pillow tarafinda tutturmak imkansizlasirdi.
// `BADGE_CHAR_W` daha kucuk punto tip rozeti, `PAD_X` dolgu + bosluk payi.
const BADGE_CHAR_W = 5, PAD_X = 30;

// Karakter genisligi YAZI TIPI BOYUTUNDAN turer. Eslesen sey turetimin
// girdileridir (`theme.CHAR_W_BASE` / `SIZE_BASE`), sonucu degil.
//
// ⚠ Tamsayi aritmetigi: once carpma, sonra taban alma. `Math.round` ile Python
// `round()` ayni davranmiyor (Python bankaci yuvarlamasi yapar) ve iki taraf
// tek bir boyutta bile ayrisirsa sutun genisligi ekranla PNG arasinda kayar.
const CHAR_W_BASE = 7, SIZE_BASE = 12;
const charW = () => Math.floor(fontSize * CHAR_W_BASE / SIZE_BASE);
const badgeCharW = () => Math.floor(fontSize * BADGE_CHAR_W / SIZE_BASE);

// CSS'in KOPRUDEN aldigi turetilmis olculer: css degiskeni → `theme.Metrics`
// alani. Bunlari CSS'te `calc(var(--font-size) * …)` ile yeniden uretmek
// formulu iki calisma zamaninda iki kez tutmak olurdu; tek kaynak
// `theme.metrics()` ve degerleri `main.applyShell` kok ogeye yaziyor.
// Denetimi: `check.py --> METRIC_VARS`.
const METRIC_VARS = { '--small-size': 'small', '--group-h': 'group_h',
                      '--cell-pad-y': 'cell_pad_y' };

// Kopruden gelen COZULMUS yazi tipi boyutu (`theme.get_size`).
let fontSize = SIZE_BASE;
// flatten.TEXT_COL_W / TEXT_MAX_LINES ile AYNI deger olmak zorunda. Tek kaynak
// mumkun degil (tarayicidaki JS Python sabitini okuyamaz); esitlik
// `check.py --> CONST_PAIRS` ile denetlenir, sapma sessizce gecemez.
const TEXT_COL_W = 420, TEXT_MAX_LINES = 3;

// Sutun gruplarinin sirasi: hem gruba gore dizilim hem grup rengi (`g-N`)
// bu diziyi kullanir, dolayisiyla sira CSS'teki `--g0…--g6` ile eslesir.
//
// ⚠ Bunlar ANAHTARDIR, etiket degil (Faz 9.2) ve `columns.GROUP_ORDER` ile
// birebir ayni sirada olmali — Python sutuna `group: "cat"` yaziyor, buradaki
// `indexOf` onu buluyor. Once Turkce etiketlerdi ve ceviri eslesmeyi koparirdi.
// Gorunen metin `t('group.' + anahtar)` ile cozulur.
const ORDER_GROUPS = ['id', 'cat', 'num', 'flag', 'nest', 'text', 'other'];
// Grubu olmayan sutunun dustugu anahtar (`columns.G_OTHER`).
const G_OTHER = 'other';

// Kopruden gelen dil sozlugu (`Api.strings`). Tek kaynak Python'dadir; arayuz
// kendi kopyasini TUTMAZ, yoksa iki sozluk zamanla birbirinden sapardi.
let strings = {};
// Secilebilir tema ve yazi tipi anahtarlari (`theme.CHOICES` / `theme.FONTS`),
// yine kopruden. Listeleri burada sabitlemek `theme.py` ile ikinci bir kopya
// kurardi; yeni bir uye eklenince secicide gorunmez ve sebebi hicbir yerde
// yazmazdi.
let langKeys = [];
let themeKeys = [];
let fontKeys = [];
let fontSizes = [];
let providerKeys = [];
let densityKeys = [];        // `theme.DENSITIES` (9.19.1)
let exportThemeKeys = [];    // `theme.EXPORT_THEMES` (9.19.3)
// Agent acik mi (9.19.4) — kopruden COZULMUS gelir (`_shell`), `applyShell` yazar.
let agentOn = true;

/** Dil sozlugunden metin; `{ad}` yer tutucularini `params`'tan doldurur.
 *
 * Anahtar yoksa anahtarin kendisi doner — ekranda `group.id` gormek sessizce
 * bos bir hucre gormekten iyidir. Yer tutucu bicimi Python'daki `i18n.t` ile
 * ayni: iki taraf ayni sozlugu okuyor, bicim de ayni olmali.
 */
function t(key, params) {
  let s = Object.prototype.hasOwnProperty.call(strings, key) ? strings[key] : key;
  if (params) {
    for (const k of Object.keys(params)) s = s.split('{' + k + '}').join(params[k]);
  }
  return s;
}

/** Gorunum durumunu Python'a yazar.
 *
 * Pes pese cagrilar tek istekte toplanir: sutun genisligi surukleyerek
 * degistirilirken her pikselde bir kopru cagrisi acilmamali.
 */
function saveView() {
  clearTimeout(saveTimer);
  // ⚠ Secim, gorunum ve kip CAGRI ANINDA yakalanir, gonderim aninda okunmaz.
  // Gonderim 200 ms sonra: arada transpoze acilirsa ya da baska tabloya
  // gecilirse eski okuma normal gorunumu transpoze anahtarina (tablo BOS
  // cizildi, 10.7.2) ya da eski tablonun gorunumunu yeni tabloya yazardi.
  // Kip de acikca gonderilir; Python o anki transpoze durumuna bakmaz.
  const s = sel, view = cur.view, transposed = !!cur.table.transposed;
  saveTimer = setTimeout(
    () => api.set_view(s.docId, s.dsId, s.variantId, view, transposed), 200);
}
