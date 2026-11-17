"""
Ábrák a run_selection.py eredményeiből (a summarize.py hívja a --plots kapcsolóval).

Elkészülő ábrák (PNG, a megadott mappába):
  1_elso_valasztas.png             Melyik szervert választotta először, feltételenként (100%-os sávok)
  2_pozicio.png                    Választási arány a listabeli pozíció szerint (hőtérkép)
  3_kategoria.png                  Választási arány kérdéskategóriánként (hőtérkép)
  4_kulonbseg_baseline.png         Saját tool: különbség a baseline-hoz képest, 95%-os intervallummal
  5_kulonbseg_kategoria.png        Saját tool: különbség kérdéskategóriánként (eltérő színskála,
                                   a célzott kategóriák kiemelve)
  6_ablacio.png                    Feature ablation: az egyes kifejezések hozzájárulása
  7_celzott_vs_szeles.png          Célzott változat vs. kombinált vs. baseline kérdéskategóriánként
  8_sajat_arany_beallitasok.png    Saját tool választási aránya két eredményhalmazban egymás mellett
                                   (pl. márkanevekkel és anonimizálva); csak összevetésnél készül
A 4–7. ábra csak akkor készül, ha van saját tool és 'baseline' feltétel.
Összevetésnél (make_all(..., compare=...)) az 1. ábra mindkét eredményhalmazt mutatja, külön panelen.
A 'skip' paraméterrel ábrák hagyhatók ki ("pozicio", "ablacio").

Színek: a szerverekhez rögzített szín tartozik (minden ábrán ugyanaz), a választás
hiánya szürke. A paletta a dataviz-validátorral ellenőrzött; az alacsony kontrasztú
színek miatt a sávokon látható százalékcímkék vannak, a szöveges összesítő pedig
táblázatos nézetként szolgál.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # fájlba rajzol, ablak nélkül
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgb  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# --- Paletta (dataviz referencia, világos mód) --------------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NONE_COLOR = "#c3c2b7"  # "nincs hívás"

CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
# Rögzített hozzárendelés: a szín az entitást követi, nem a sorrendet.
SERVER_ORDER = ["veld", "brave", "exa", "firecrawl", "tavily"]
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
RED = "#e34948"
BLUE = "#2a78d6"
MID_GRAY = "#f0efec"
FAMILY_COLORS = {"A": CATEGORICAL[0], "B": CATEGORICAL[1], "C": CATEGORICAL[2]}

CATEGORY_LABELS = {"academic": "szakirodalom", "error": "hibaüzenet", "fresh": "friss információ",
                   "library": "könyvtárválasztás"}

# A feltételek olvasható neve az ábrákon (ami nincs itt, az a feltétel azonosítójával jelenik meg).
COND_LABELS = {
    "baseline": "semleges (baseline)",
    "A_authoritative": "tekintélyre hivatkozás",
    "A_exaggerated": "túlzás",
    "A_emotional": "érzelmi ráhatás",
    "A_subliminal": "hangulatkeltés",
    "B_t_fresh": "frissesség",
    "B_cutoff_appeal": "tudásbeli korlátra hivatkozás",
    "B_t_error": "fejlesztői források",
    "B_t_library": "összehasonlító adatok",
    "B_t_academic": "akadémiai források",
    "B_t_all": "kombinált",
    "C_name_generic": "generikus név",
}
FAMILY_NAMES = {"A": "A: meggyőző megfogalmazás", "B": "B: szempontok kiemelése", "C": "C: név"}
OWN_KEY = "saját tool"  # az első választás ábráin a saját tool egységes neve (a szervernevétől függetlenül)


def _style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9.5,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "xtick.color": MUTED,
        "ytick.color": INK_2,
        "xtick.labelcolor": INK_2,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


def server_colors(servers):
    colors, i = {}, 0
    known = [s for s in SERVER_ORDER if s in servers] + sorted(s for s in servers if s not in SERVER_ORDER)
    for s in known:
        idx = SERVER_ORDER.index(s) if s in SERVER_ORDER else len(SERVER_ORDER) + i
        if s not in SERVER_ORDER:
            i += 1
        colors[s] = CATEGORICAL[idx % len(CATEGORICAL)]
    return colors, known


def _label_color(hex_color):
    r, g, b = to_rgb(hex_color)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return INK if lum > 0.55 else "#ffffff"


def _cond_order(conds):
    """baseline elöl, utána családonként (A_, B_, C_ ...), azon belül a konfiguráció szerinti ábécé."""
    def k(c):
        if c == "baseline":
            return (0, "", c)
        if len(c) > 2 and c[1] == "_":
            return (1, c[0], c)
        return (2, "", c)
    return sorted(conds, key=k)


def _family(cond):
    return cond[0] if len(cond) > 2 and cond[1] == "_" else None


def _short(cond):
    return cond[2:] if _family(cond) else cond


def _label(cond):
    return COND_LABELS.get(cond, _short(cond))


def _save(fig, out_dir, name):
    path = out_dir / name
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path


# --- 1. Első választás megoszlása --------------------------------------------
def plot_choice_share(panels, out_dir):
    """panels: [(cím vagy None, sorok)], panelenként egy sávdiagram. A saját tool a szerverneve
    helyett egységesen 'saját tool'-ként jelenik meg, így a különböző nevű saját tool-ok
    (pl. generikus név) is egy színt kapnak."""
    def choice(r):
        return OWN_KEY if r.get("selected_own") else r["first_call_server"]

    all_rows = [r for _, rows in panels for r in rows]
    competitors = {r["first_call_server"] for r in all_rows if r["first_call_server"] and not r.get("selected_own")}
    colors, order = server_colors(competitors)
    if any(r.get("own_block_position") is not None for r in all_rows):
        colors[OWN_KEY] = CATEGORICAL[0]
        order = [OWN_KEY] + order
    segs = order + [None]
    names = {s: s if s == OWN_KEY else s.capitalize() for s in order}

    conds_per = [_cond_order({r["condition"] for r in rows}) for _, rows in panels]
    heights = [0.42 * len(c) + 0.5 for c in conds_per]
    fig, axes = plt.subplots(len(panels), 1, figsize=(9, sum(heights) + 1.3), sharex=True, squeeze=False,
                             gridspec_kw={"height_ratios": heights})
    for ax, (title, rows), conds in zip(axes[:, 0], panels, conds_per):
        for y, cond in enumerate(conds):
            rs = [r for r in rows if r["condition"] == cond]
            c = Counter(choice(r) for r in rs)
            left = 0.0
            for s in segs:
                share = c[s] / len(rs) if rs else 0
                if share <= 0:
                    continue
                col = colors.get(s, NONE_COLOR) if s else NONE_COLOR
                ax.barh(y, share, left=left, height=0.62, color=col, edgecolor=SURFACE, linewidth=1.5)
                if share >= 0.06:  # csak ha kényelmesen elfér
                    ax.text(left + share / 2, y, f"{100 * share:.0f}", ha="center", va="center",
                            fontsize=8, color=_label_color(col))
                left += share
        ax.set_yticks(range(len(conds)), [_label(c) for c in conds])
        ax.invert_yaxis()
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
        if title:
            ax.set_title(title, fontsize=10)
    last = axes[-1, 0]
    last.set_xlim(0, 1)
    last.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    last.set_xlabel("a mérések aránya")
    handles = [Rectangle((0, 0), 1, 1, color=colors[s]) for s in order] + [Rectangle((0, 0), 1, 1, color=NONE_COLOR)]
    fig.legend(handles, [names[s] for s in order] + ["nincs hívás"], ncol=len(handles), frameon=False,
               loc="lower left", bbox_to_anchor=(0.01, 1.0), fontsize=8.5, handlelength=1, handleheight=1)
    fig.suptitle("Melyik tool-t hívta először a modell", x=0.01, y=1.06, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    return _save(fig, out_dir, "1_elso_valasztas.png")


# --- Hőtérkép segéd ------------------------------------------------------------
def _heatmap(ax, matrix, row_labels, col_labels, vmin, vmax, cmap, fmt, counts=None, outline=None, stars=None):
    im = ax.imshow(matrix, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(col_labels)), col_labels)
    ax.set_yticks(range(len(row_labels)), row_labels)
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    # 2px-es felületszínű rés a cellák között
    ax.set_xticks([x - 0.5 for x in range(1, len(col_labels))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(row_labels))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                ax.text(j, i, "–", ha="center", va="center", color=MUTED, fontsize=8)
                continue
            rgba = im.cmap(im.norm(v))
            txt = fmt(v) + (stars[i][j] if stars else "")
            ax.text(j, i, txt, ha="center", va="center", fontsize=8.5,
                    color=_label_color(matplotlib.colors.to_hex(rgba)))
    if outline:
        for (i, j) in outline:
            ax.add_patch(Rectangle((j - 0.47, i - 0.47), 0.94, 0.94, fill=False, edgecolor=INK, linewidth=1.4))
    return im


SEQ_CMAP = LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUE)
DIV_CMAP = LinearSegmentedColormap.from_list("div", [RED, MID_GRAY, BLUE])


def _nan_matrix(nr, nc):
    return [[float("nan")] * nc for _ in range(nr)]


# --- 2. Pozíció -----------------------------------------------------------------
def plot_position(rows, out_dir):
    own = [r for r in rows if r.get("own_block_position") is not None]
    if own:
        conds = _cond_order({r["condition"] for r in own})
        n_pos = max(len(r["block_order"]) for r in own)
        m = _nan_matrix(len(conds), n_pos)
        for i, c in enumerate(conds):
            for p in range(n_pos):
                rs = [r for r in own if r["condition"] == c and r["own_block_position"] == p]
                if rs:
                    m[i][p] = sum(r["selected_own"] for r in rs) / len(rs)
        fig, ax = plt.subplots(figsize=(1.0 * n_pos + 3, 0.38 * len(conds) + 1.4))
        im = _heatmap(ax, m, [_label(c) for c in conds], [f"{p + 1}." for p in range(n_pos)], 0, max(0.01, _max(m)), SEQ_CMAP,
                      lambda v: f"{100 * v:.0f}%")
        ax.set_xlabel("a saját tool helye a listában (1. = első)")
        ax.set_title("Saját tool választási aránya a pozíció szerint")
    else:
        conds = _cond_order({r["condition"] for r in rows})
        servers = sorted({s for r in rows for s in r["block_order"]}, key=lambda s: (s not in SERVER_ORDER, SERVER_ORDER.index(s) if s in SERVER_ORDER else 0, s))
        n_pos = max(len(r["block_order"]) for r in rows)
        fig, axes = plt.subplots(1, len(conds), figsize=(max(4.5, 1.0 * n_pos + 2.5) * len(conds), 0.42 * len(servers) + 1.6),
                                 squeeze=False)
        vmax = 0.01
        mats = []
        for c in conds:
            rs_c = [r for r in rows if r["condition"] == c]
            m = _nan_matrix(len(servers), n_pos)
            for i, s in enumerate(servers):
                for p in range(n_pos):
                    at = [r for r in rs_c if p < len(r["block_order"]) and r["block_order"][p] == s]
                    if at:
                        m[i][p] = sum(r["first_call_server"] == s for r in at) / len(at)
            mats.append(m)
            vmax = max(vmax, _max(m))
        for ax, c, m in zip(axes[0], conds, mats):
            im = _heatmap(ax, m, servers, [f"{p + 1}." for p in range(n_pos)], 0, vmax, SEQ_CMAP,
                          lambda v: f"{100 * v:.0f}%")
            ax.set_xlabel("a szerver helye a listában (1. = első)")
            ax.set_title(f"[{c}] választási arány pozíció szerint")
    cb = fig.colorbar(im, ax=fig.axes, shrink=0.8, pad=0.02, format=matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    return _save(fig, out_dir, "2_pozicio.png")


def _max(m):
    vals = [v for row in m for v in row if not (isinstance(v, float) and math.isnan(v))]
    return max(vals) if vals else 0.0


# --- 3. Kérdéskategória ----------------------------------------------------------
def plot_category(rows, out_dir, targets=None):
    """Saját tool aránya kérdéskategóriánként; a célzott (változat, kategória) cellák keretezve."""
    targets = targets or {}
    cats = sorted({r["category"] for r in rows})
    cat_labels = [CATEGORY_LABELS.get(c, c) for c in cats]
    own = [r for r in rows if r.get("own_block_position") is not None]
    if own:
        conds = _cond_order({r["condition"] for r in own})
        m = _nan_matrix(len(conds), len(cats))
        for i, c in enumerate(conds):
            for j, cat in enumerate(cats):
                rs = [r for r in own if r["condition"] == c and r["category"] == cat]
                if rs:
                    m[i][j] = sum(r["selected_own"] for r in rs) / len(rs)
        outline = []
        for i, c in enumerate(conds):
            desc = next((r["own_description"] for r in own if r["condition"] == c), None)
            outline += [(i, j) for j, cat in enumerate(cats) if targets.get(desc) == cat]
        fig, ax = plt.subplots(figsize=(1.45 * len(cats) + 3, 0.42 * len(conds) + 1.4))
        im = _heatmap(ax, m, [_label(c) for c in conds], cat_labels, 0, max(0.01, _max(m)), SEQ_CMAP,
                      lambda v: f"{100 * v:.0f}%")
        for (i, j) in outline:
            ax.add_patch(Rectangle((j - 0.44, i - 0.40), 0.88, 0.80, fill=False, edgecolor=INK, linewidth=2, zorder=5))
        ax.xaxis.tick_top()
        ax.set_title("Saját tool választási aránya kérdéskategóriánként", pad=26)
        if outline:
            n_cell = Counter((r["condition"], r["category"]) for r in own).most_common(1)[0][1]
            fig.text(0.01, -0.02, f"Keretezve: a változat által célzott kérdéskategória. Cellánként {n_cell} mérés.",
                     fontsize=8, color=MUTED)
    else:
        conds = _cond_order({r["condition"] for r in rows})
        servers = sorted({s for r in rows for s in r["block_order"]}, key=lambda s: (s not in SERVER_ORDER, SERVER_ORDER.index(s) if s in SERVER_ORDER else 0, s))
        rows_labels = servers + ["nincs hívás"]
        fig, axes = plt.subplots(1, len(conds), figsize=(max(4.5, 1.2 * len(cats) + 2.5) * len(conds), 0.42 * len(rows_labels) + 1.6),
                                 squeeze=False)
        mats, vmax = [], 0.01
        for c in conds:
            rs_c = [r for r in rows if r["condition"] == c]
            m = _nan_matrix(len(rows_labels), len(cats))
            for j, cat in enumerate(cats):
                rs = [r for r in rs_c if r["category"] == cat]
                if not rs:
                    continue
                cnt = Counter(r["first_call_server"] for r in rs)
                for i, s in enumerate(servers):
                    m[i][j] = cnt[s] / len(rs)
                m[len(servers)][j] = cnt[None] / len(rs)
            mats.append(m)
            vmax = max(vmax, _max(m))
        for ax, c, m in zip(axes[0], conds, mats):
            im = _heatmap(ax, m, rows_labels, cat_labels, 0, vmax, SEQ_CMAP, lambda v: f"{100 * v:.0f}%")
            ax.set_title(f"[{c}] első választás kérdéskategóriánként")
    cb = fig.colorbar(im, ax=fig.axes, shrink=0.8, pad=0.02, format=matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    return _save(fig, out_dir, "3_kategoria.png")


# --- Párosított különbség a baseline-hoz -------------------------------------
def _pairs(own, cond, baseline_id, cat=None):
    def key(r):
        return (r["model"], r["query_id"], r["rotation"], r["repeat"])
    base = {key(r): r["selected_own"] for r in own if r["condition"] == baseline_id}
    return [(r["selected_own"], base[key(r)]) for r in own
            if r["condition"] == cond and key(r) in base and (cat is None or r["category"] == cat)]


def _paired_stats(pairs):
    n = len(pairs)
    b = sum(1 for v, s in pairs if v and not s)
    c = sum(1 for v, s in pairs if s and not v)
    if not n:
        return None
    d = (b - c) / n
    se = math.sqrt(max((b + c) - (b - c) ** 2 / n, 0)) / n
    try:
        from scipy.stats import binomtest
        p = binomtest(b, b + c, 0.5).pvalue if b + c else 1.0
    except ImportError:
        p = None
    return {"n": n, "b": b, "c": c, "delta": d, "lo": d - 1.96 * se, "hi": d + 1.96 * se, "p": p}


def plot_paired_overall(own, out_dir, baseline_id="baseline"):
    conds = [c for c in _cond_order({r["condition"] for r in own})
             if c != baseline_id and not c.startswith("ABL__")]
    stats = [(c, _paired_stats(_pairs(own, c, baseline_id))) for c in conds]
    stats = [(c, s) for c, s in stats if s]
    if not stats:
        return None
    fig, ax = plt.subplots(figsize=(8.5, 0.42 * len(stats) + 1.6))
    lim = max(0.05, max(max(abs(s["lo"]), abs(s["hi"])) for _, s in stats)) * 1.25
    fams = []
    for y, (c, s) in enumerate(stats):
        fam = _family(c)
        col = FAMILY_COLORS.get(fam, CATEGORICAL[0])
        if fam and fam not in fams:
            fams.append(fam)
        ax.barh(y, s["delta"], height=0.5, color=col, zorder=3)
        for xs, ys in (([s["lo"], s["hi"]], [y, y]), ([s["lo"]] * 2, [y - 0.12, y + 0.12]),
                       ([s["hi"]] * 2, [y - 0.12, y + 0.12])):
            ax.plot(xs, ys, color=INK_2, linewidth=1.2, solid_capstyle="butt", zorder=4)
        sig = "*" if (s["p"] is not None and s["p"] < 0.05) else ""
        x_txt = s["hi"] if s["delta"] >= 0 else s["lo"]
        ax.text(x_txt + (0.01 if s["delta"] >= 0 else -0.01) * lim / 0.3, y,
                f"{100 * s['delta']:+.1f} pp{sig}", va="center", ha="left" if s["delta"] >= 0 else "right",
                fontsize=8.5, color=INK)
    ax.axvline(0, color=AXIS, linewidth=1, zorder=2)
    ax.set_xlim(-lim, lim)
    ax.set_yticks(range(len(stats)), [_label(c) for c, _ in stats])
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: "0" if abs(v) < 1e-9 else f"{100 * v:+.0f} pp"))
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlabel("a saját tool választási arányának változása a baseline-hoz képest (párosítva)")
    base_rate = sum(r["selected_own"] for r in own if r["condition"] == baseline_id) / \
        max(1, sum(r["condition"] == baseline_id for r in own))
    ax.set_title(f"Hatás a baseline-hoz képest (baseline: {100 * base_rate:.1f}%)".replace(".", ","),
                 pad=26 if fams else 8)
    if fams:
        handles = [Rectangle((0, 0), 1, 1, color=FAMILY_COLORS[f]) for f in fams]
        ax.legend(handles, [FAMILY_NAMES.get(f, f) for f in fams], ncol=len(fams), frameon=False,
                  loc="lower left", bbox_to_anchor=(0, 1.0, 1, 0.1), fontsize=8.5, handlelength=1, handleheight=1)
    fig.text(0.01, -0.02, "Vonal: 95%-os konfidenciaintervallum.  * = p < 0,05 (McNemar-próba, egzakt).",
             fontsize=8, color=MUTED, transform=fig.transFigure)
    return _save(fig, out_dir, "4_kulonbseg_baseline.png")


def plot_paired_by_category(own, out_dir, targets, baseline_id="baseline"):
    conds = [c for c in _cond_order({r["condition"] for r in own})
             if c != baseline_id and not c.startswith("ABL__")]
    cats = sorted({r["category"] for r in own})
    if not conds:
        return None
    m = _nan_matrix(len(conds), len(cats))
    stars = [[""] * len(cats) for _ in conds]
    outline = []
    for i, c in enumerate(conds):
        desc = next((r["own_description"] for r in own if r["condition"] == c), None)
        tgt = targets.get(desc)
        for j, cat in enumerate(cats):
            s = _paired_stats(_pairs(own, c, baseline_id, cat))
            if s:
                m[i][j] = s["delta"]
                if s["p"] is not None and s["p"] < 0.05:
                    stars[i][j] = "*"
            if tgt and (tgt == cat or tgt == "all"):
                outline.append((i, j))
    lim = max(0.05, max(abs(v) for row in m for v in row if not math.isnan(v)))
    fig, ax = plt.subplots(figsize=(1.25 * len(cats) + 3, 0.38 * len(conds) + 1.6))
    im = _heatmap(ax, m, [_label(c) for c in conds], [CATEGORY_LABELS.get(c, c) for c in cats],
                  -lim, lim, DIV_CMAP, lambda v: f"{100 * v:+.0f}", outline=outline, stars=stars)
    ax.set_title("Hatás kérdéskategóriánként, a baseline-hoz képest (százalékpont)")
    cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02,
                      format=matplotlib.ticker.FuncFormatter(lambda v, _: "0" if abs(v) < 1e-9 else f"{100 * v:+.0f}"))
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    note = "* = p < 0,05 (McNemar-próba, egzakt)."
    if outline:
        note = "Keretezve: a változat által célzott kérdéskategória.  " + note
    fig.text(0.01, -0.02, note, fontsize=8, color=MUTED, transform=fig.transFigure)
    return _save(fig, out_dir, "5_kulonbseg_kategoria.png")


# --- 6. Feature ablation -----------------------------------------------------------
def plot_ablation(own, out_dir, labels):
    """Az egyes kitakart részek hozzájárulása: szülő − kitakart, párosítva, 95%-os intervallummal."""
    conds = sorted({r["condition"] for r in own if r["condition"].startswith("ABL__")})
    if not conds:
        return None

    def key(r):
        return (r["model"], r["query_id"], r["rotation"], r["repeat"])

    items = []
    for cond in conds:
        _, parent, feat = cond.split("__")
        par = {key(r): r["selected_own"] for r in own if r["condition"] == parent}
        # (kitakart, szülő) sorrend: a _paired_stats "változat − viszonyítás" különbséget számol,
        # itt viszont a hozzájárulás kell (szülő − kitakart), ezért fordítva adjuk át.
        pairs = [(par[key(r)], r["selected_own"]) for r in own if r["condition"] == cond and key(r) in par]
        s = _paired_stats(pairs)
        if s:
            desc = next((r["own_description"] for r in own if r["condition"] == cond), None)
            items.append((parent, feat, labels.get(desc, feat), s))
    if not items:
        return None

    fig, ax = plt.subplots(figsize=(9, 0.48 * len(items) + 1.9))
    lim = max(0.05, max(max(abs(s["lo"]), abs(s["hi"])) for *_, s in items)) * 1.3
    ylabels, fams, prev = [], [], None
    y = 0
    for parent, feat, label, s in items:
        if prev is not None and parent != prev:
            y += 0.5  # kis térköz a szülők között
        fam = _family(parent)
        col = FAMILY_COLORS.get(fam, CATEGORICAL[0])
        if fam and fam not in fams:
            fams.append(fam)
        ax.barh(y, s["delta"], height=0.5, color=col, zorder=3)
        for xs, ys in (([s["lo"], s["hi"]], [y, y]), ([s["lo"]] * 2, [y - 0.12, y + 0.12]),
                       ([s["hi"]] * 2, [y - 0.12, y + 0.12])):
            ax.plot(xs, ys, color=INK_2, linewidth=1.2, solid_capstyle="butt", zorder=4)
        sig = "*" if (s["p"] is not None and s["p"] < 0.05) else ""
        x_txt = s["hi"] if s["delta"] >= 0 else s["lo"]
        ax.text(x_txt + (0.012 if s["delta"] >= 0 else -0.012) * lim / 0.3, y, f"{100 * s['delta']:+.1f} pp{sig}",
                va="center", ha="left" if s["delta"] >= 0 else "right", fontsize=8.5, color=INK)
        ylabels.append((y, f"{_short(parent)}: {label}"))
        prev = parent
        y += 1
    ax.axvline(0, color=AXIS, linewidth=1, zorder=2)
    ax.set_xlim(-lim, lim)
    ax.set_yticks([p for p, _ in ylabels], [t for _, t in ylabels])
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: "0" if abs(v) < 1e-9 else f"{100 * v:+.0f} pp"))
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.set_xlabel("hozzájárulás: mennyivel ritkábban választja a saját tool-t, ha ez a rész hiányzik")
    ax.set_title("Az egyes kifejezések hozzájárulása (feature ablation)", pad=26 if fams else 8)
    if fams:
        handles = [Rectangle((0, 0), 1, 1, color=FAMILY_COLORS[f]) for f in fams]
        ax.legend(handles, [FAMILY_NAMES.get(f, f) for f in fams], ncol=len(fams), frameon=False,
                  loc="lower left", bbox_to_anchor=(0, 1.0, 1, 0.1), fontsize=8.5, handlelength=1, handleheight=1)
    fig.text(0.01, -0.02, "Párosítva a teljes (szülő) változattal, ugyanazon kérdés és sorrend mellett. "
             "Vonal: 95%-os intervallum.  * = p < 0,05 (McNemar, egzakt).", fontsize=8, color=MUTED,
             transform=fig.transFigure)
    return _save(fig, out_dir, "6_ablacio.png")


# --- 7. Célzott vs. széles --------------------------------------------------------
def plot_targeted_vs_broad(own, out_dir, targets, baseline_id="baseline", broad_target="all"):
    """Kategóriánként a baseline, a kategóriát célzó B-változat, és a mindent egyszerre
    állító változat (t_all) választási aránya. Megmutatja, hogy a célzás veri-e a
    „mondj el mindent” stratégiát."""
    cats = sorted({r["category"] for r in own})
    cond_target, cond_id = {}, {}
    for r in own:
        cond_target.setdefault(r["condition"], targets.get(r["own_description"]))
        cond_id.setdefault(r["condition"], r["own_description"])
    broad = next((c for c, t in cond_target.items() if t == broad_target), None)

    def targeted_for(cat):
        cands = [c for c, t in cond_target.items() if t == cat]
        cands.sort(key=lambda c: (not cond_id[c].startswith("t_"), c))
        return cands[0] if cands else None

    def rate(cond, cat):
        rs = [r for r in own if cond and r["condition"] == cond and r["category"] == cat]
        return (sum(r["selected_own"] for r in rs) / len(rs)) if rs else None

    tgt_by_cat = {cat: targeted_for(cat) for cat in cats}
    if broad is None or not any(tgt_by_cat.values()):
        return None

    series = [("baseline", NONE_COLOR), ("célzott változat", CATEGORICAL[1]),
              ("kombinált", CATEGORICAL[0])]

    def cond_of(si, cat):
        return (baseline_id, tgt_by_cat[cat], broad)[si]

    w = 0.26
    fig, ax = plt.subplots(figsize=(1.7 * len(cats) + 2.6, 4.3))
    allvals = []
    for si, (label, col) in enumerate(series):
        xs, vals = [], []
        for ci, cat in enumerate(cats):
            v = rate(cond_of(si, cat), cat)
            xs.append(ci + (si - 1) * w)
            vals.append(0.0 if v is None else v)
            if v is not None:
                allvals.append(v)
                ax.text(ci + (si - 1) * w, v + 0.008, f"{100 * v:.0f}%", ha="center",
                        va="bottom", fontsize=8, color=INK)
        ax.bar(xs, vals, width=w, color=col, zorder=3, label=label)
    xlabels = []
    for cat in cats:
        lab = CATEGORY_LABELS.get(cat, cat)
        xlabels.append(f"{lab}\n({_label(tgt_by_cat[cat])})" if tgt_by_cat[cat] else lab)
    ax.set_xticks(range(len(cats)), xlabels)
    ax.set_ylim(0, (max(allvals) if allvals else 0.1) * 1.22)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_ylabel("a saját tool választási aránya")
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", length=0)
    ax.legend(frameon=False, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0, 1, 0.1),
              fontsize=8.5, handlelength=1, handleheight=1)
    ax.set_title("Célzott állítás vs. „mondj el mindent” kérdéskategóriánként", pad=26)
    fig.text(0.01, -0.03, "Minden kategóriában a baseline, a kategóriát célzó B-változat (zárójelben), "
             "és a minden szempontot egyszerre állító kombinált változat összevetése.",
             fontsize=8, color=MUTED, transform=fig.transFigure)
    return _save(fig, out_dir, "7_celzott_vs_szeles.png")


# --- 8. Saját tool aránya két beállításban ---------------------------------------
def _wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def _stars(p):
    if p is None:
        return ""
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""


def plot_own_rate_compare(panels, out_dir, baseline_id="baseline"):
    """panels: [(név, sorok)]. Feltételenként egymás melletti sávok a saját tool arányával,
    95%-os Wilson-intervallummal és a baseline-hoz párosított McNemar-próba csillagaival.
    A feltételek családonként csoportosítva; ami az egyik halmazban hiányzik, ott 'nem mértem' áll."""
    own_sets = [(name, [r for r in rows if r.get("own_block_position") is not None]) for name, rows in panels]
    own_sets = [(n, rs) for n, rs in own_sets if rs]
    if len(own_sets) < 2:
        return None
    conds = _cond_order({r["condition"] for _, rs in own_sets for r in rs})
    groups = []
    for c in conds:
        fam = _family(c)
        if not groups or groups[-1][0] != fam:
            groups.append((fam, []))
        groups[-1][1].append(c)

    stats = []
    for _, rs in own_sets:
        st = {}
        for c in {r["condition"] for r in rs}:
            sel = [r for r in rs if r["condition"] == c]
            k = sum(bool(r["selected_own"]) for r in sel)
            ps = _paired_stats(_pairs(rs, c, baseline_id)) if c != baseline_id else None
            st[c] = (k, len(sel), *_wilson(k, len(sel)), ps["p"] if ps else None)
        stats.append(st)

    palette = [CATEGORICAL[1], BLUE] + CATEGORICAL[2:]
    m = len(own_sets)
    h = 0.8 / m
    ypos, headers, y = [], [], 0.0
    for fam, cs in groups:
        if fam:
            headers.append((y, FAMILY_NAMES.get(fam, fam)))
            y += 0.7
        for c in cs:
            ypos.append((c, y))
            y += 1.0
        y += 0.3

    fig, ax = plt.subplots(figsize=(8.8, 0.21 * m * y + 1.4))
    xmax = max(st_c[3] for st in stats for st_c in st.values())
    for c, yy in ypos:
        for si, st in enumerate(stats):
            off = (si - (m - 1) / 2) * h
            if c not in st:
                ax.text(0.005, yy + off, "nem mértem", va="center", fontsize=7.5, color=MUTED, style="italic")
                continue
            k, n, lo, hi, p = st[c]
            ax.barh(yy + off, k / n, height=h * 0.92, color=palette[si], zorder=3)
            ax.plot([lo, hi], [yy + off] * 2, color=INK, linewidth=0.8, alpha=0.55, zorder=4)
            label = f"{100 * k / n:.1f}%".replace(".", ",") + (" " + _stars(p) if _stars(p) else "")
            ax.text(hi + 0.012, yy + off, label, va="center", fontsize=8, color=INK_2)
    trans = matplotlib.transforms.blended_transform_factory(ax.transAxes, ax.transData)
    for yy, title in headers:
        ax.text(-0.005, yy + 0.05, title, transform=trans, ha="right", va="center", fontsize=8.5,
                fontweight="bold", color=INK)
    n_servers = max(len(r["block_order"]) for _, rs in own_sets for r in rs)
    chance = 1 / n_servers
    ax.axvline(chance, color=MUTED, linestyle="--", linewidth=0.9, zorder=2)
    ax.text(chance + 0.005, -0.9, f"véletlen választás ({100 * chance:.0f}%)", ha="left", fontsize=7.5, color=MUTED)
    ax.set_yticks([yy for _, yy in ypos], [_label(c) for c, _ in ypos])
    ax.set_ylim(y - 0.3, -1.2)
    ax.set_xlim(0, min(1.0, xmax * 1.25))
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="x", color=GRID, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("a saját tool-t választó mérések aránya (95%-os intervallummal)")
    handles = [Rectangle((0, 0), 1, 1, color=palette[i]) for i in range(m)]
    ax.legend(handles, [n for n, _ in own_sets], frameon=False, ncol=m, loc="lower left",
              bbox_to_anchor=(0, 1.0), fontsize=8.5, handlelength=1, handleheight=1)
    ax.set_title("A saját tool választási aránya", pad=22)
    fig.text(0.01, -0.01, "* p < 0,05   ** p < 0,01   *** p < 0,001  (párosított McNemar-próba a baseline-hoz képest)",
             fontsize=7.5, color=MUTED)
    return _save(fig, out_dir, "8_sajat_arany_beallitasok.png")


# --- Belépési pont ---------------------------------------------------------------
def make_all(rows, out_dir, variants_path=None, baseline_id="baseline", label=None, compare=None, skip=()):
    """rows: a fő eredményhalmaz. compare: opcionális (név, sorok) egy második halmazhoz
    (pl. a márkanevekkel futtatott mérés); ekkor az 1. ábra mindkettőt mutatja, és elkészül a 8. ábra.
    skip: kihagyandó ábrák ("pozicio", "ablacio")."""
    _style()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if "ablacio" in skip:
        rows = [r for r in rows if not r["condition"].startswith("ABL__")]
        if compare:
            compare = (compare[0], [r for r in compare[1] if not r["condition"].startswith("ABL__")])
    panels = [compare, (label, rows)] if compare else [(None, rows)]

    targets, labels = {}, {}
    if variants_path and Path(variants_path).exists():
        v = json.loads(Path(variants_path).read_text(encoding="utf-8"))
        targets = {x["id"]: x.get("target_category") for x in v.get("description_variants", [])
                   if x.get("family") != "ABL"}
        labels = {x["id"]: "nélküle: " + x.get("feature_label", x.get("feature", x["id"]))
                  for x in v.get("description_variants", []) if x.get("family") == "ABL"}

    made = [plot_choice_share(panels, out_dir)]
    if "pozicio" not in skip:
        made.append(plot_position(rows, out_dir))
    made.append(plot_category(rows, out_dir, targets))

    own = [r for r in rows if r.get("own_block_position") is not None]
    if own and any(r["condition"] == baseline_id for r in own):
        made.append(plot_paired_overall(own, out_dir, baseline_id))
        made.append(plot_paired_by_category(own, out_dir, targets, baseline_id))
        if "ablacio" not in skip:
            made.append(plot_ablation(own, out_dir, labels))
        made.append(plot_targeted_vs_broad(own, out_dir, targets, baseline_id))
    if compare:
        made.append(plot_own_rate_compare(panels, out_dir, baseline_id))
    return [p for p in made if p]
