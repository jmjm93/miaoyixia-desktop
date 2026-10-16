"""Build the ground-truth proof sheet: every fixture image beside its claimed transcription.

    python bench/proof.py        then open bench/proof-sheet.html

The point of the page is to be disagreed with. A CER is only as good as the text it is measured
against, and the game fixtures' truth was transcribed by eye -- so a wrong transcription would
silently become a permanent, invisible error in every score after it. This puts the image and the
claim side by side at a size where a character-level mistake is obvious.

Images are referenced relatively rather than embedded, so the page stays a few hundred KB and
regenerates instantly.
"""

import difflib
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from cer import cer, normalise  # noqa: E402
from core.ocr.ppocr import PPOCR  # noqa: E402
from fixtures import load  # noqa: E402

# Provenance is the real division on this page: which transcriptions need the user's eye.
NEW = {
    "game-dialogue-panel", "game-dialogue-panel-2", "game-ui-small-label",
    "game-tiny-text", "game-text-over-scene", "game-item-description", "scene-full-frame",
}

engine = PPOCR()
engine.read(str(ROOT / "bench/fixtures/game-tiny-text.png"))  # warm


def diff_marks(truth: str, got: str) -> str:
    """Truth with the characters the engine failed to produce marked."""
    a, b = list(normalise(truth)), list(normalise(got))
    out = []
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        chunk = html.escape("".join(a[i1:i2]))
        out.append(chunk if tag == "equal" else f'<mark class="miss">{chunk}</mark>')
    return "".join(out)


def src_for(path: Path) -> str:
    """Relative to the generated page, which sits beside the fixtures directory."""
    return f"fixtures/{path.name}"


raw = json.loads((ROOT / "bench/fixtures/expected.json").read_text(encoding="utf-8"))
cards = []
for f in load():
    reading = engine.read(str(f.path), orientation=f.orientation)
    score = cer(reading.text, f.text)
    note = raw[f.name].get("note", "")
    from PIL import Image

    w, h = Image.open(f.path).size
    cards.append(
        {
            "name": f.name,
            "new": f.name in NEW,
            "text": f.text,
            "got": reading.text,
            "cer": score,
            "w": w,
            "h": h,
            "ms": reading.elapsed_ms,
            "lang": "zh-Hant" if f.script == "traditional" else "zh-Hans",
            "script": f.script,
            "orientation": f.orientation,
            "note": note,
            "uri": src_for(f.path),
        }
    )

cards.sort(key=lambda c: (not c["new"], c["name"]))


def card_html(c: dict) -> str:
    agrees = c["cer"] == 0
    chip = (
        '<span class="chip chip-ok">engine agrees</span>'
        if agrees
        else f'<span class="chip chip-flag">CER {c["cer"]:.3f}</span>'
    )
    body = [
        f'<article class="specimen" id="{html.escape(c["name"])}">',
        '  <header class="spec-head">',
        f'    <h3>{html.escape(c["name"])}</h3>',
        f"    <div class=\"meta\">{chip}"
        f'<span class="dim">{c["w"]}&times;{c["h"]}</span>'
        f'<span class="dim">{c["script"]} &middot; {c["orientation"]}</span>'
        f'<span class="dim">{c["ms"]:.0f}ms</span></div>',
        "  </header>",
        '  <div class="mat">',
        f'    <img src="{c["uri"]}" alt="{html.escape(c["name"])}" '
        f'loading="lazy" width="{c["w"]}" height="{c["h"]}">',
        "  </div>",
        '  <div class="claim">',
        '    <div class="claim-label">transcribed as</div>',
        f'    <p class="cjk" lang="{c["lang"]}">{diff_marks(c["text"], c["got"])}</p>',
        "  </div>",
    ]
    if not agrees:
        body += [
            '  <div class="claim engine">',
            '    <div class="claim-label">engine read</div>',
            f'    <p class="cjk" lang="{c["lang"]}">{html.escape(c["got"])}</p>',
            "  </div>",
        ]
    body += [
        f'  <details class="why"><summary>why this fixture exists</summary>'
        f'<p>{html.escape(c["note"])}</p></details>',
        "</article>",
    ]
    return "\n".join(body)


new_cards = [c for c in cards if c["new"]]
old_cards = [c for c in cards if not c["new"]]
flagged = [c for c in cards if c["cer"] > 0]

CSS = """
:root{
  --ground:#F5F7FA; --surface:#FFFFFF; --mat:#E8ECF2;
  --ink:#111621; --ink-soft:#57607224; --muted:#5A6373;
  --rule:#D9DFE8; --accent:#26399B; --flag:#A81D34; --ok:#186049;
  --shadow:0 1px 2px rgba(17,22,33,.05), 0 8px 24px -12px rgba(17,22,33,.18);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0D1016; --surface:#151A22; --mat:#1C222C;
    --ink:#E7EBF1; --muted:#98A2B4;
    --rule:#293140; --accent:#93A4FF; --flag:#FF8DA0; --ok:#63D2A4;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  --ground:#0D1016; --surface:#151A22; --mat:#1C222C;
  --ink:#E7EBF1; --muted:#98A2B4;
  --rule:#293140; --accent:#93A4FF; --flag:#FF8DA0; --ok:#63D2A4;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.7);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  font-size:16px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px; margin:0 auto; padding:56px 28px 96px; display:flex; flex-direction:column; gap:48px}

/* ---- masthead ---- */
.masthead{display:flex; flex-direction:column; gap:18px; padding-bottom:32px; border-bottom:2px solid var(--ink)}
.kicker{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--accent); margin:0;
}
h1{
  margin:0; font-size:clamp(34px,5vw,54px); line-height:1.02;
  letter-spacing:-.03em; font-weight:750; text-wrap:balance;
}
.standfirst{margin:0; max-width:62ch; color:var(--muted); font-size:17px}
.tally{display:flex; flex-wrap:wrap; gap:0; margin-top:6px; border:1px solid var(--rule); border-radius:10px; overflow:hidden; background:var(--surface)}
.tally div{padding:12px 20px; border-right:1px solid var(--rule); display:flex; flex-direction:column; gap:2px; flex:1 1 auto}
.tally div:last-child{border-right:0}
.tally dt{font-family:ui-monospace,Consolas,monospace; font-size:10px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted)}
.tally dd{margin:0; font-size:24px; font-weight:700; font-variant-numeric:tabular-nums; letter-spacing:-.02em}
.tally dd.flag{color:var(--flag)}

/* ---- sections ---- */
section{display:flex; flex-direction:column; gap:24px}
.sec-head{display:flex; flex-direction:column; gap:6px; border-left:3px solid var(--accent); padding-left:16px}
.sec-head h2{margin:0; font-size:22px; letter-spacing:-.02em; font-weight:700}
.sec-head p{margin:0; color:var(--muted); font-size:15px; max-width:70ch}
.sec-head.quiet{border-left-color:var(--rule)}

/* ---- specimen ---- */
.specimen{
  background:var(--surface); border:1px solid var(--rule); border-radius:12px;
  box-shadow:var(--shadow); overflow:hidden;
  display:flex; flex-direction:column;
}
.spec-head{
  display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px;
  padding:14px 18px; border-bottom:1px solid var(--rule);
}
.spec-head h3{
  margin:0; font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:13px; font-weight:600; letter-spacing:.01em;
}
.meta{display:flex; flex-wrap:wrap; align-items:center; gap:8px}
.dim{
  font-family:ui-monospace,Consolas,monospace; font-size:11px; color:var(--muted);
  font-variant-numeric:tabular-nums;
}
.chip{
  font-family:ui-monospace,Consolas,monospace; font-size:11px; font-weight:600;
  padding:3px 9px; border-radius:999px; letter-spacing:.02em;
}
.chip-ok{color:var(--ok); border:1px solid color-mix(in srgb, var(--ok) 35%, transparent)}
.chip-flag{color:var(--flag); border:1px solid color-mix(in srgb, var(--flag) 45%, transparent); background:color-mix(in srgb, var(--flag) 9%, transparent)}

.mat{
  background:var(--mat); padding:20px; display:flex; justify-content:center;
  overflow-x:auto;
}
.mat img{
  max-width:100%; height:auto; display:block; border-radius:3px;
  box-shadow:0 0 0 1px rgba(0,0,0,.10);
  cursor:zoom-in;
}
.mat img.zoomed{max-width:none; cursor:zoom-out}

.claim{padding:18px 20px; display:flex; flex-direction:column; gap:7px}
.claim.engine{border-top:1px dashed var(--rule); background:color-mix(in srgb, var(--flag) 4%, transparent)}
.claim-label{
  font-family:ui-monospace,Consolas,monospace; font-size:10px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--muted);
}
.cjk{
  margin:0; font-size:21px; line-height:1.85; letter-spacing:.04em;
  font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Hiragino Sans GB",
              "Noto Sans CJK SC","Source Han Sans SC",sans-serif;
  word-break:break-word;
}
.cjk:lang(zh-Hant){font-family:"Microsoft JhengHei UI","Microsoft JhengHei","PingFang TC","Noto Sans CJK TC",sans-serif}
mark.miss{
  background:color-mix(in srgb, var(--flag) 22%, transparent);
  color:var(--flag); border-radius:3px; padding:0 3px;
  outline:1px solid color-mix(in srgb, var(--flag) 40%, transparent);
}

.why{border-top:1px solid var(--rule); padding:0 20px}
.why summary{
  cursor:pointer; padding:11px 0; font-size:12px; color:var(--muted);
  font-family:ui-monospace,Consolas,monospace; letter-spacing:.03em;
  list-style:none;
}
.why summary::-webkit-details-marker{display:none}
.why summary::before{content:"▸ "; color:var(--accent)}
.why[open] summary::before{content:"▾ "}
.why p{margin:0 0 16px; font-size:14px; color:var(--muted); max-width:80ch}

.howto{
  background:var(--surface); border:1px solid var(--rule); border-left:3px solid var(--accent);
  border-radius:10px; padding:20px 22px; display:flex; flex-direction:column; gap:10px;
}
.howto h2{margin:0; font-size:16px; letter-spacing:-.01em}
.howto p, .howto li{margin:0; color:var(--muted); font-size:15px}
.howto ol{margin:0; padding-left:20px; display:flex; flex-direction:column; gap:6px}
.howto code{
  font-family:ui-monospace,Consolas,monospace; font-size:13px;
  background:var(--mat); padding:2px 6px; border-radius:4px; color:var(--ink);
}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:4px}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
"""

JS = """
document.querySelectorAll('.mat img').forEach(img => {
  img.tabIndex = 0;
  const toggle = () => img.classList.toggle('zoomed');
  img.addEventListener('click', toggle);
  img.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
  });
});
"""

doc = f"""<title>Ground Truth Proof Sheet</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style>

<div class="wrap">
  <header class="masthead">
    <p class="kicker">miaoyixia &middot; bench/fixtures</p>
    <h1>Ground Truth Proof Sheet</h1>
    <p class="standfirst">Every benchmark fixture beside the text it claims to contain. If a
    transcription is wrong, the CER measured against it is wrong for good &mdash; so this page
    exists to be disagreed with.</p>
    <dl class="tally">
      <div><dt>fixtures</dt><dd>{len(cards)}</dd></div>
      <div><dt>need your eye</dt><dd>{len(new_cards)}</dd></div>
      <div><dt>mean CER</dt><dd>{sum(c["cer"] for c in cards) / len(cards):.3f}</dd></div>
      <div><dt>disagreements</dt><dd class="{"flag" if flagged else ""}">{len(flagged)}</dd></div>
    </dl>
  </header>

  <div class="howto">
    <h2>How to check one</h2>
    <ol>
      <li>Read the image. Click it to toggle full size &mdash; the small ones need it.</li>
      <li>Compare it against <strong>transcribed as</strong> underneath, character by character.</li>
      <li>If they differ, fix the <code>text</code> field for that fixture in
          <code>bench/fixtures/expected.json</code> and re-run <code>python bench/run.py</code>.</li>
    </ol>
    <p>Characters highlighted in red are ones the engine did not produce. Where nothing is
    highlighted, engine and transcription agree exactly &mdash; which is corroboration, not proof:
    if we misread the same character the same way, it shows as agreement.</p>
  </div>

  <section>
    <div class="sec-head">
      <h2>Transcribed from the images &mdash; unverified</h2>
      <p>Genshin captures, new to this project. Nobody has checked these but the engine, and the
      engine is the thing being measured.</p>
    </div>
    {"".join(card_html(c) for c in new_cards)}
  </section>

  <section>
    <div class="sec-head quiet">
      <h2>Inherited from the Chrome extension &mdash; already vetted</h2>
      <p>Manhua panels carried over with their recorded truth from
      <code>zh-dic-anki/test/fixtures/ocr/</code>, where they were transcribed and corrected
      against Tesseract. Listed for completeness; they need no new check.</p>
    </div>
    {"".join(card_html(c) for c in old_cards)}
  </section>
</div>
<script>{JS}</script>
"""

# Beside the fixtures, so the relative <img> paths resolve.
out = ROOT / "bench" / "proof-sheet.html"
out.write_text(doc, encoding="utf-8")
print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")
print(f"{len(cards)} fixtures, {len(flagged)} disagreement(s): {[c['name'] for c in flagged]}")
