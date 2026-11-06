#!/usr/bin/env python3
"""Infection Lab: map how you discovered artists in your Spotify extended streaming history.

Every artist's first play is an "infection". Its source is the artist you were
playing right before it (within --window hours), so the result is a discovery tree.

    python infection_lab.py --data path/to/Spotify_Extended_History
    python infection_lab.py --demo          # synthetic data, safe to share
"""
import argparse
import glob
import json
import os
import random
import webbrowser
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

ARTIST, TRACK = "master_metadata_album_artist_name", "master_metadata_track_name"
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
WEEK = 7 * 86400


# ---------------------------------------------------------------- data
def prepare(df: pd.DataFrame, min_ms: int) -> pd.DataFrame:
    """Keep real listens and convert Spotify's end-of-play `ts` into a start time."""
    df = df[(df["ms_played"] >= min_ms) & df[ARTIST].notna()].copy()
    end = pd.to_datetime(df["ts"], utc=True)
    df["start"] = end - pd.to_timedelta(df["ms_played"], unit="ms")
    return df.sort_values("start").reset_index(drop=True)


def load_history(folder: str, min_ms: int) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(folder, "Streaming_History_Audio_*.json")))
    if not files:
        raise SystemExit(f"No Streaming_History_Audio_*.json files found in '{folder}'. Use --data.")
    return prepare(pd.concat([pd.read_json(f) for f in files], ignore_index=True), min_ms)


def demo_history(min_ms: int, seed: int = 7, n_artists: int = 260) -> pd.DataFrame:
    """Synthetic listening sessions: mostly favourites, occasionally a new artist."""
    rng = random.Random(seed)
    a = "Neon Velvet Static Hollow Lunar Paper Glass Ember Tidal Quiet Golden Faded Wild Silver Night Coral Iron Soft Pale".split()
    b = "Harbor Choir Machine Garden Echo Signal Parade Orchard Tide Engine Season Animals Letters Hours Radio Gate".split()
    pool = sorted({f"{rng.choice(a)} {rng.choice(b)}" for _ in range(n_artists * 3)})
    rng.shuffle(pool)
    pool, known, rows = iter(pool[:n_artists]), [], []
    clock = pd.Timestamp("2023-03-01", tz="UTC")
    for _ in range(700):
        clock += pd.Timedelta(hours=rng.uniform(4, 40))
        for _ in range(rng.randint(4, 16)):
            artist = next(pool, None) if (not known or rng.random() < 0.07) else None
            if artist:
                known.append(artist)
            else:
                artist = rng.choice(known[-30:] if rng.random() < 0.6 else known)
            ms = rng.randint(20_000, 240_000)
            clock += pd.Timedelta(milliseconds=ms)
            rows.append({"ts": clock.isoformat(), "ms_played": ms, ARTIST: artist,
                         TRACK: f"{rng.choice(b)} {rng.choice(a)}"})
    return prepare(pd.DataFrame(rows), min_ms)


# ---------------------------------------------------------------- graph
def build(df: pd.DataFrame, window_h: float):
    """One parent per artist: whoever played immediately before their first play."""
    names, tracks = df[ARTIST].to_numpy(), df[TRACK].fillna("").to_numpy()
    secs = ((df["start"] - EPOCH) / pd.Timedelta(seconds=1)).to_numpy()
    plays = df.groupby(ARTIST, sort=False).indices  # artist -> sorted row positions
    window, G, info = window_h * 3600, nx.DiGraph(), {}

    for artist, pos in plays.items():
        i = pos[0]
        has_src = i > 0 and secs[i] - secs[i - 1] <= window
        G.add_node(artist)
        if has_src:
            G.add_edge(names[i - 1], artist)
        info[artist] = {
            "first": df["start"].iloc[i].strftime("%Y-%m-%d"),
            "src": names[i - 1] if has_src else None,
            "track": tracks[i - 1] if has_src else "",
            # the artist's own plays in the 7 days after discovery (not a global activity count)
            "wk": int(np.searchsorted(secs[pos], secs[i] + WEEK, side="right")),
            "plays": len(pos),
        }

    nodes = [{"id": a, **info[a], "kids": G.out_degree(a), "reach": len(nx.descendants(G, a))} for a in G]
    roots = sorted((n for n in G if G.in_degree(n) == 0), key=lambda n: -len(nx.descendants(G, n)))
    return {
        "nodes": nodes, "edges": [list(e) for e in G.edges], "roots": roots,
        "stats": {"plays": len(df), "artists": len(nodes), "zeros": len(roots), "window": window_h},
    }


def export_csv(payload: dict, stem: Path) -> list[Path]:
    """Flat tables for Power BI, Excel or anything else that likes rows."""
    nodes = pd.DataFrame(payload["nodes"]).rename(columns={
        "id": "artist", "first": "first_heard", "src": "source_artist", "track": "source_track",
        "kids": "direct_infections", "reach": "total_reach", "wk": "plays_first_7d", "plays": "total_plays"})
    nodes["is_patient_zero"] = nodes["artist"].isin(payload["roots"])
    paths = [stem.with_name(stem.name + "_nodes.csv"), stem.with_name(stem.name + "_edges.csv")]
    nodes.to_csv(paths[0], index=False)
    pd.DataFrame(payload["edges"], columns=["source", "target"]).to_csv(paths[1], index=False)
    return paths


# ---------------------------------------------------------------- page
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Infection Lab: how I found my music</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap">
<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
:root{--bg:#010409;--panel:rgba(13,17,23,.94);--line:#30363d;--text:#e6edf3;--mute:#8b949e;--zero:#00ffad;--node:#1597ff;--edge:rgba(139,148,158,.22);--dim:#3b4a63;--tint:rgba(0,255,173,.06);color-scheme:dark;
  box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:light){:root{--bg:#f6f8fa;--panel:rgba(255,255,255,.95);--line:#d0d7de;--text:#1f2328;--mute:#57606a;--zero:#0a7f5a;--node:#0969da;--edge:rgba(31,35,40,.18);--dim:#aab4c3;--tint:rgba(10,127,90,.07);color-scheme:light}}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--text);font:13px/1.5 'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;overflow:hidden}
#net{position:fixed;inset:0}
.panel{position:fixed;background:var(--panel);border:1px solid var(--line);border-radius:14px;backdrop-filter:blur(10px)}
#side{top:calc(16px + env(safe-area-inset-top,0px));bottom:calc(16px + env(safe-area-inset-bottom,0px));left:16px;width:272px;padding:16px;display:flex;flex-direction:column;gap:12px;z-index:20}
#q{width:100%;padding:11px 14px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font:inherit;outline:none}
#q:focus{border-color:var(--zero)}
h2{margin:4px 0 0;font-size:12px;font-weight:700;color:var(--zero)}
.list{flex:1;overflow:auto;display:grid;gap:6px;align-content:start}
.row{display:flex;justify-content:space-between;gap:8px;width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:none;color:var(--text);font:inherit;text-align:left;cursor:pointer}
.row:hover,.row:focus-visible{border-color:var(--zero);outline:none}
.row small,.note{color:var(--mute)}
.note{margin:0;font-size:11px}
#dossier{top:0;right:0;bottom:0;width:min(400px,100vw);border-radius:0;border-width:0 0 0 1px;z-index:30;overflow:auto;
  padding:calc(24px + env(safe-area-inset-top,0px)) 26px 26px;transform:translateX(100%);transition:transform .35s ease}
#dossier.open{transform:none}
#close{background:none;border:0;color:var(--mute);font:inherit;cursor:pointer;padding:0 0 18px}
#close:hover{color:var(--zero)}
#d-name{margin:0;font-size:30px;line-height:1.1;font-weight:800;letter-spacing:-.03em;overflow-wrap:anywhere}
#d-date{margin:6px 0 22px;color:var(--mute)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:22px}
.stats div{border:1px solid var(--line);border-radius:10px;padding:10px;background:var(--tint)}
.stats b{display:block;font-size:26px;font-weight:800;line-height:1.1}
.stats span{font-size:11px;color:var(--mute)}
.bar{height:6px;border-radius:6px;background:var(--line);margin:6px 0 22px}
.bar i{display:block;height:100%;width:0;border-radius:6px;background:var(--node);transition:width .6s ease}
.block{border-left:3px solid var(--node);padding:4px 0 4px 14px;margin-bottom:22px}
.block p{margin:0}.block .t{color:var(--mute);font-style:italic}
.link{background:none;border:0;padding:0;font:inherit;font-size:16px;font-weight:700;color:var(--text);text-align:left;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.kids{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.kids .row{width:auto;padding:4px 10px;border-radius:999px}
#boot{position:fixed;inset:0;z-index:100;background:var(--bg);display:grid;place-content:center;justify-items:center;gap:28px;padding:24px;transition:opacity .6s}
#boot pre{margin:0;min-height:5.5em;color:var(--zero);font:inherit}
#go{padding:14px 34px;border-radius:999px;border:1px solid var(--zero);background:transparent;color:var(--zero);font:inherit;font-weight:700;cursor:pointer;visibility:hidden}
#go:hover,#go:focus-visible{background:var(--zero);color:var(--bg);outline:none}
@media (max-width:820px){#side{bottom:auto;right:16px;width:auto;max-height:44vh}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<div id="boot"><pre id="log"></pre><button id="go">Open the map</button></div>
<div id="net"></div>
<aside id="side" class="panel">
  <input id="q" type="search" placeholder="Search an artist" aria-label="Search an artist" autocomplete="off">
  <h2 id="list-title">Patient zeros</h2>
  <div id="list" class="list"></div>
  <p class="note" id="note"></p>
</aside>
<section id="dossier" class="panel" aria-live="polite">
  <button id="close">Close</button>
  <h1 id="d-name"></h1>
  <p id="d-date"></p>
  <div class="stats">
    <div><b id="d-kids">0</b><span>direct infections</span></div>
    <div><b id="d-reach">0</b><span>total reach</span></div>
    <div><b id="d-wk">0</b><span>plays, first 7 days</span></div>
  </div>
  <div class="bar"><i id="d-bar"></i></div>
  <div class="block"><p class="note">Infected by</p><p id="d-src"></p><p class="t" id="d-track"></p></div>
  <div id="d-kids-wrap"><p class="note">Went on to infect</p><div class="kids" id="d-kids-list"></div></div>
</section>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const byId = new Map(D.nodes.map(n => [n.id, n]));
const children = new Map();
D.edges.forEach(([u, v]) => { if (!children.has(u)) children.set(u, []); children.get(u).push(v); });
const zeros = new Set(D.roots);
const maxWk = Math.max(1, ...D.nodes.map(n => n.wk));
const labelAt = D.nodes.map(n => n.kids).sort((a, b) => b - a)[Math.min(11, D.nodes.length - 1)] || 1;
// colour the biggest discovery trees; everything else recedes
const palette = ["#00ffad", "#1597ff", "#ff00c1", "#f5a524", "#7c5cff", "#2dd4bf", "#ff5c7a", "#e3b341"];
const treeColor = new Map();
D.roots.slice(0, palette.length).forEach((r, i) => {
  const stack = [r];
  while (stack.length) { const id = stack.pop(); treeColor.set(id, palette[i]); (children.get(id) || []).forEach(k => stack.push(k)); }
});
// artists with no source and no children are not drawn: physics flings them to the rim
const isolated = n => n.kids === 0 && !n.src;
const fmt = iso => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric", timeZone: "UTC"});

const nodes = new vis.DataSet(D.nodes.filter(n => !isolated(n)).map(n => {
  const c = treeColor.get(n.id) || css("--dim");
  return {
    id: n.id, shape: "dot", label: n.kids >= labelAt ? n.id : "",
    size: Math.min(5 + Math.sqrt(n.reach) * 4, 46), borderWidth: zeros.has(n.id) ? 3 : 1,
    color: {background: c, border: zeros.has(n.id) ? css("--text") : c, highlight: {background: css("--text"), border: css("--text")}},
    font: {color: css("--text"), size: 26, strokeWidth: 5, strokeColor: css("--bg")}
  };
}));
const edges = new vis.DataSet(D.edges.map(([from, to]) => ({from, to})));
const network = new vis.Network($("net"), {nodes, edges}, {
  physics: {solver: "forceAtlas2Based", forceAtlas2Based: {gravitationalConstant: -60, springLength: 90}, stabilization: {iterations: 200}},
  edges: {smooth: false, width: 1, arrows: {to: {scaleFactor: .4}}, color: {inherit: "from", opacity: .5}}
});
network.once("stabilized", () => network.setOptions({physics: false}));
network.on("click", p => { if (p.nodes.length) show(p.nodes[0]); });

function row(id, extra) {
  const b = document.createElement("button");
  b.className = "row"; b.append(id);
  if (extra != null) { const s = document.createElement("small"); s.textContent = extra; b.append(s); }
  b.onclick = () => show(id);
  return b;
}
function renderList(ids, title, empty) {
  $("list-title").textContent = title;
  $("list").replaceChildren(...(ids.length ? ids.map(id => row(id, byId.get(id).reach)) : [Object.assign(document.createElement("p"), {className: "note", textContent: empty})]));
}
function show(id) {
  const n = byId.get(id); if (!n) return;
  $("d-name").textContent = id;
  $("d-date").textContent = "First heard " + fmt(n.first);
  $("d-kids").textContent = n.kids; $("d-reach").textContent = n.reach; $("d-wk").textContent = n.wk;
  $("d-bar").style.width = (n.wk / maxWk * 100) + "%";
  const src = $("d-src"); src.replaceChildren();
  if (n.src) { const b = row(n.src); b.className = "link"; src.append(b); }
  else src.textContent = "Nothing in the " + D.stats.window + " hours before. A spontaneous find.";
  $("d-track").textContent = n.src && n.track ? "\u201c" + n.track + "\u201d" : "";
  const kids = children.get(id) || [];
  $("d-kids-wrap").hidden = !kids.length;
  $("d-kids-list").replaceChildren(...kids.slice(0, 14).map(k => row(k)));
  $("dossier").classList.add("open");
  if (nodes.get(id)) { network.selectNodes([id]); network.focus(id, {scale: 1.1, animation: {duration: 600}}); }
}
$("close").onclick = () => { $("dossier").classList.remove("open"); network.unselectAll(); };
$("q").addEventListener("input", e => {
  const v = e.target.value.trim().toLowerCase();
  if (!v) return renderList(D.roots.slice(0, 40), "Patient zeros");
  const hits = D.nodes.filter(n => n.id.toLowerCase().includes(v)).sort((a, b) => b.reach - a.reach).slice(0, 12).map(n => n.id);
  renderList(hits, "Matches", "No artist matches \u201c" + e.target.value + "\u201d.");
});
$("q").addEventListener("keydown", e => { if (e.key === "Enter") { const f = $("list").querySelector(".row"); if (f) f.click(); } });
document.addEventListener("keydown", e => { if (e.key === "Escape") $("close").click(); });
renderList(D.roots.slice(0, 40), "Patient zeros");
$("note").textContent = (D.demo ? "Synthetic demo data. " : "") + "Number = artists downstream. " + D.nodes.filter(isolated).length + " isolated artists not drawn. Top 8 trees coloured.";

const lines = [`> Read ${D.stats.plays.toLocaleString()} plays`, `> Mapped ${D.stats.artists.toLocaleString()} artists`,
  `> Found ${D.stats.zeros.toLocaleString()} patient zeros`, "> Ready"];
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
let li = 0;
(function type() {
  if (li < lines.length) { $("log").textContent += lines[li++] + "\n"; reduce ? type() : setTimeout(type, 450); }
  else { $("go").style.visibility = "visible"; $("go").focus(); }
})();
function start() { const b = $("boot"); b.style.opacity = 0; setTimeout(() => b.remove(), 600); }
$("go").onclick = start;
</script>
</body>
</html>
"""


def write_page(payload: dict, path: Path) -> None:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    path.write_text(PAGE.replace("__DATA__", data), encoding="utf-8")


# ---------------------------------------------------------------- cli
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default=".", help="folder with Streaming_History_Audio_*.json (default: .)")
    p.add_argument("--out", default="infection_lab.html", help="output HTML file")
    p.add_argument("--window", type=float, default=2.0, help="hours before a first play to look for a source")
    p.add_argument("--min-ms", type=int, default=30_000, help="ignore plays shorter than this")
    p.add_argument("--demo", action="store_true", help="use synthetic data instead of your history")
    p.add_argument("--csv", action="store_true", help="also write nodes/edges CSVs (for Power BI)")
    p.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = p.parse_args()

    df = demo_history(args.min_ms) if args.demo else load_history(args.data, args.min_ms)
    payload = build(df, args.window)
    payload["demo"] = args.demo

    out = Path(args.out)
    write_page(payload, out)
    print(f"Wrote {out}  ({payload['stats']['artists']} artists, {len(payload['edges'])} edges)")
    if args.csv:
        for path in export_csv(payload, out.with_suffix("")):
            print(f"Wrote {path}")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
