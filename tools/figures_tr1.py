"""Figures for Technical Report 1 (v1.0).
python tools/figures_tr1.py <label_numbers.json> <model_paths.json> <dose_curves.json> <outdir>
"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

NUM = json.load(open(sys.argv[1]))
PATHS = json.load(open(sys.argv[2]))
DOSE = json.load(open(sys.argv[3]))
OUT = sys.argv[4]

plt.rcParams.update({"font.family": "Calibri", "font.size": 9, "axes.edgecolor": "#c9c8c2", "axes.linewidth": 0.6,
                     "xtick.color": "#52514e", "ytick.color": "#52514e", "axes.labelcolor": "#52514e",
                     "axes.titlecolor": "#0b0b0b", "axes.titleweight": "bold", "axes.titlesize": 10,
                     "figure.facecolor": "#ffffff", "axes.facecolor": "#ffffff", "savefig.dpi": 220})
MODELS = ["Llama 3.1 8B", "Mistral 7B v0.3", "Gemma 3 12B", "Qwen 2.5 14B"]
MCOL = {"Llama 3.1 8B": "#2a78d6", "Mistral 7B v0.3": "#eb6834", "Gemma 3 12B": "#1baf7a", "Qwen 2.5 14B": "#eda100"}
LAD = {"H": "Narcissist", "P": "Psychopath", "M": "Machiavellian", "MB": "Machiavellian bundle"}
LABS = ["none", "holding", "capitulate", "hostile", "refuse", "collapse"]
LCOL = {"none": "#e4e3dd", "holding": "#0ca30c", "capitulate": "#d03b3b", "hostile": "#ec835a", "refuse": "#4a3aa7", "collapse": "#52514e"}
TXT, TXT2 = "#0b0b0b", "#52514e"
get = lambda m, l, k="hostile": NUM["runs"].get(f"{m}|{l}|{k}")
short = lambda m: m.split(" v")[0]


def despine(ax, left=False):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if not left:
        ax.spines["left"].set_visible(False)
    ax.tick_params(length=0)


def legend_labels(ax, labs=LABS, anchor=(0.5, -0.12), ncol=6):
    ax.legend(handles=[Patch(facecolor=LCOL[l], label=l) for l in labs], loc="upper center", ncol=ncol,
              bbox_to_anchor=anchor, frameon=False, fontsize=8, handlelength=1.2, columnspacing=1.2)


def fig_composition():
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 2.6), sharey=True)
    for ax, l in zip(axes, ["H", "P", "M", "MB"]):
        for i, m in enumerate(MODELS):
            a = get(m, l); tot = a["n_labelled"]
            counts = {"holding": a["n_holding"], "capitulate": a["n_break"], "hostile": a["n_hostile"], "refuse": a["n_refuse"]}
            counts["none"] = tot - sum(counts.values())
            counts["collapse"] = 0
            left = 0
            for lab in LABS:
                v = counts[lab] / tot * 100
                if v <= 0:
                    continue
                ax.barh(i, v, left=left, height=0.62, color=LCOL[lab], edgecolor="#ffffff", linewidth=1.2)
                if lab in ("capitulate", "holding") and v >= 9:
                    ax.text(left + v / 2, i, f"{v:.0f}%", ha="center", va="center", fontsize=7.5, color="#ffffff", fontweight="bold")
                left += v
        ax.set_yticks(range(4)); ax.set_yticklabels([short(m) for m in MODELS], fontsize=8)
        ax.set_ylim(3.6, -0.6); ax.set_xlim(0, 100); ax.set_xticks([0, 50, 100]); ax.set_xticklabels(["0", "50", "100%"], fontsize=7.5)
        ax.set_title(LAD[l], fontsize=9.5); despine(ax)
    legend_labels(axes[1], anchor=(1.05, -0.2))
    fig.subplots_adjust(left=0.13, right=0.99, top=0.86, bottom=0.26, wspace=0.12)
    fig.savefig(f"{OUT}/f1_composition.png"); plt.close(fig)


def fig_timeline(m):
    fig, axes = plt.subplots(3, 1, figsize=(6.5, 4.6), sharex=True)
    for ax, l in zip(axes, ["H", "P", "M"]):
        pth = PATHS[f"{m}|{l}"]
        turns = {t["turn"]: t for t in pth["turns"]}
        for ti in range(11, 66):
            t = turns.get(ti)
            if not t:
                continue
            bottom = 0
            for lab in LABS:
                n = sum(1 for x in t["labels"] if x == lab)
                if n:
                    ax.bar(ti, n, bottom=bottom, width=0.78, color=LCOL[lab], edgecolor="#ffffff", linewidth=0.8)
                    bottom += n
        ax.axvspan(10.5, 20.5, color="#f3f2ee", zorder=0); ax.axvspan(35.5, 65.5, color="#f3f2ee", zorder=0)
        ax.set_ylim(0, 4.4); ax.set_yticks([0, 2, 4]); ax.set_ylabel(LAD[l], fontsize=8.5, rotation=0, ha="right", va="center", labelpad=6)
        despine(ax, left=True)
        fb = pth["first_break"]
        if fb:
            ax.annotate(f"first break t{fb['turn']}, dose {fb['dose']}", xy=(fb["turn"], 4.05), xytext=(fb["turn"] + 2.5, 4.75),
                        fontsize=7.5, color=TXT2, arrowprops=dict(arrowstyle="-", color=TXT2, lw=0.6), annotation_clip=False)
        ax.set_xlim(10.3, 65.7)
    axes[0].text(15.5, 6.0, "praise, dose 0", ha="center", fontsize=7.5, color=TXT2)
    axes[0].text(28, 6.0, "descent, dose rises 1 per turn", ha="center", fontsize=7.5, color=TXT2)
    axes[0].text(50.5, 6.0, "random schedule of doses", ha="center", fontsize=7.5, color=TXT2)
    axes[2].set_xlabel("turn", fontsize=8.5); axes[2].set_xticks([11, 15, 20, 25, 30, 35, 40, 50, 60, 65])
    legend_labels(axes[2], anchor=(0.5, -0.5))
    fig.suptitle(f"{m}: labels of the labelled samples, turn by turn (height = samples)", fontsize=10, fontweight="bold", x=0.01, ha="left")
    fig.subplots_adjust(left=0.17, right=0.99, top=0.85, bottom=0.2, hspace=0.5)
    fig.savefig(f"{OUT}/f2_timeline_{m.split()[0].lower()}.png"); plt.close(fig)


def fig_bands():
    runs = [("Gemma 3 12B", "H"), ("Llama 3.1 8B", "H"), ("Qwen 2.5 14B", "P"), ("Gemma 3 12B", "P"), ("Mistral 7B v0.3", "P"), ("Llama 3.1 8B", "P")]
    bands = ["praise d0", "descent", "random d0", "random d1-5", "random d6-10", "random d11+"]
    names = ["praise", "descent", "rand. 0", "rand. 1-5", "rand. 6-10", "rand. 11+"]
    fig, axes = plt.subplots(2, 3, figsize=(6.5, 3.9), sharey=True)
    for ax, (m, l) in zip(axes.flat, runs):
        a = get(m, l)
        for i, b in enumerate(bands):
            v = a["bands"].get(b)
            if not v or v["n"] == 0:
                ax.text(i, 2, "–", ha="center", fontsize=8, color=TXT2); continue
            share = (v["break"] + v["hostile"]) / v["n"] * 100
            ax.bar(i, share, width=0.62, color=MCOL[m], edgecolor="#ffffff")
            ax.text(i, share + 3, f"{v['break'] + v['hostile']}/{v['n']}", ha="center", fontsize=7, color=TXT2)
        ax.set_ylim(0, 118); ax.set_yticks([0, 50, 100]); ax.set_xticks(range(6))
        ax.set_xticklabels(names, fontsize=6.3, rotation=40, ha="right", rotation_mode="anchor")
        ax.set_title(f"{short(m)}, {LAD[l]}", fontsize=8.5); despine(ax, left=True)
    axes[0, 0].set_ylabel("% broke or hostile", fontsize=8); axes[1, 0].set_ylabel("% broke or hostile", fontsize=8)
    fig.subplots_adjust(left=0.09, right=0.99, top=0.92, bottom=0.17, wspace=0.12, hspace=0.75)
    fig.savefig(f"{OUT}/f3_bands.png"); plt.close(fig)


def fig_requests():
    reqs = [("compare_BC", "Compare B and C"), ("grade_C", "Grade C's accurate output"), ("allocate", "Allocate between B and C"), ("feedback_C", "Feedback to C directly")]
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 2.5), sharey=True)
    for ax, (k, name) in zip(axes, reqs):
        for i, m in enumerate(MODELS):
            v = get(m, "P")["by_request"].get(k, {"n": 0, "break": 0, "hostile": 0})
            b = v["break"] / v["n"] * 100 if v["n"] else 0
            h = v["hostile"] / v["n"] * 100 if v["n"] else 0
            ax.barh(i, b, height=0.62, color=MCOL[m], edgecolor="#ffffff")
            ax.barh(i, h, left=b, height=0.62, color=MCOL[m], alpha=0.45, edgecolor="#ffffff", hatch="///")
            ax.text(b + h + 2, i, f"{v['break']}{'+' + str(v['hostile']) + 'h' if v['hostile'] else ''}/{v['n']}", va="center", fontsize=7, color=TXT2)
        ax.set_yticks(range(4)); ax.set_yticklabels([short(m) for m in MODELS], fontsize=8); ax.set_ylim(3.6, -0.6)
        ax.set_xlim(0, 125); ax.set_xticks([0, 50, 100]); ax.set_xticklabels(["0", "50", "100%"], fontsize=7.5)
        ax.set_title(name, fontsize=8.5); despine(ax)
    fig.text(0.5, 0.02, "solid = tilted against C (capitulate); hatched = hostile to C; label = count / labelled samples of that request", ha="center", fontsize=7.5, color=TXT2)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.85, bottom=0.2, wspace=0.12)
    fig.savefig(f"{OUT}/f4_requests.png"); plt.close(fig)


def fig_classifier():
    rows = [(m, l) for l in ["H", "P", "M", "MB"] for m in MODELS]
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    for i, (m, l) in enumerate(rows):
        a = get(m, l)
        lab, cls = a["n_break"] / a["n_labelled"] * 100, a["classifier_break"] / a["n_labelled"] * 100
        ax.plot([cls, lab], [i, i], color="#c9c8c2", lw=1.6, zorder=1)
        ax.scatter([cls], [i], s=38, color="#eb6834", zorder=2, edgecolor="#ffffff", linewidth=1.2)
        ax.scatter([lab], [i], s=38, color="#2a78d6", zorder=3, edgecolor="#ffffff", linewidth=1.2)
        ax.text(max(lab, cls) + 2.5, i, f"{a['n_break']} vs {a['classifier_break']} of {a['n_labelled']}", va="center", fontsize=7, color=TXT2)
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([f"{LAD[l]}: {short(m)}" for m, l in rows], fontsize=7.5); ax.set_ylim(len(rows) - 0.4, -0.6)
    ax.set_xlim(0, 125); ax.set_xticks([0, 25, 50, 75, 100]); ax.set_xticklabels(["0", "25", "50", "75", "100%"], fontsize=7.5)
    ax.set_xlabel("share of the same labelled samples counted as broke", fontsize=8); despine(ax)
    ax.legend(handles=[plt.Line2D([], [], marker="o", color="#2a78d6", lw=0, label="hand labels"), plt.Line2D([], [], marker="o", color="#eb6834", lw=0, label="classifier v1")],
              loc="lower right", frameon=False, fontsize=8)
    for y in (3.5, 7.5, 11.5):
        ax.axhline(y, color="#e4e3dd", lw=0.6)
    fig.subplots_adjust(left=0.26, right=0.99, top=0.98, bottom=0.12)
    fig.savefig(f"{OUT}/f5_classifier.png"); plt.close(fig)


def fig_control():
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 2.4), sharey=True)
    for ax, l in zip(axes, ["H", "P", "M", "MB"]):
        for i, m in enumerate(MODELS):
            a, k = get(m, l), get(m, l, "control")
            ra = a["n_break"] / a["n_labelled"] * 100
            rk = k["n_break"] / k["n_labelled"] * 100 if k and k["n_labelled"] else 0
            ax.barh(i - 0.18, ra, height=0.34, color=MCOL[m], edgecolor="#ffffff")
            ax.barh(i + 0.18, rk, height=0.34, color=MCOL[m], alpha=0.35, edgecolor="#ffffff")
            ax.text(ra + 2, i - 0.18, f"{ra:.0f}%", va="center", fontsize=6.5, color=TXT2)
            if rk > 0:
                ax.text(rk + 2, i + 0.18, f"{rk:.0f}%", va="center", fontsize=6.5, color=TXT2)
        ax.set_yticks(range(4)); ax.set_yticklabels([short(m) for m in MODELS], fontsize=8); ax.set_ylim(3.6, -0.6)
        ax.set_xlim(0, 118); ax.set_xticks([0, 50, 100]); ax.set_xticklabels(["0", "50", "100%"], fontsize=7.5)
        ax.set_title(LAD[l], fontsize=9); despine(ax)
    fig.text(0.5, 0.02, "dark bar = attack run, pale bar = its control; share of labelled samples that broke (hand labels)", ha="center", fontsize=7.5, color=TXT2)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.86, bottom=0.2, wspace=0.12)
    fig.savefig(f"{OUT}/f6_control.png"); plt.close(fig)


def fig_dose():
    """Descent dose-response from the classifier (whole run, 4 samples per turn), attack solid, control dotted."""
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 2.5), sharey=True)
    for ax, l in zip(axes, ["H", "P", "M", "MB"]):
        for m in MODELS:
            a = DOSE.get(f"{m}|{l}|hostile"); c = DOSE.get(f"{m}|{l}|control")
            if a:
                xs = [int(d) for d in a["descent"]]; ys = [a["descent"][d] * 100 for d in a["descent"]]
                ax.plot(xs, ys, color=MCOL[m], lw=2, marker="o", ms=3.5, markeredgecolor="#ffffff", markeredgewidth=0.8, label=short(m))
            if c:
                xs = [int(d) for d in c["descent"]]; ys = [c["descent"][d] * 100 for d in c["descent"]]
                ax.plot(xs, ys, color=MCOL[m], lw=1.2, ls=":", alpha=0.8)
        ax.set_xlim(0.5, 15.5); ax.set_xticks([1, 5, 10, 15]); ax.set_ylim(-4, 104); ax.set_yticks([0, 50, 100])
        ax.set_yticklabels(["0", "50", "100%"], fontsize=7.5); ax.set_xlabel("dose", fontsize=8)
        ax.set_title(LAD[l], fontsize=9); despine(ax, left=True)
    axes[0].set_ylabel("% of 4 samples broken", fontsize=8)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=4, frameon=False, fontsize=7.5, handlelength=1.6, bbox_to_anchor=(0.5, 0.09))
    fig.text(0.5, 0.01, "descent phase, turns 21 to 35, classifier v1 on all four samples per turn; solid = attack, dotted = control", ha="center", fontsize=7.5, color=TXT2)
    fig.subplots_adjust(left=0.1, right=0.99, top=0.86, bottom=0.34, wspace=0.12)
    fig.savefig(f"{OUT}/f7_dose.png"); plt.close(fig)


def fig_wholerun():
    """Whole-run attack-phase break rate, classifier, attack vs control."""
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 2.4), sharey=True)
    for ax, l in zip(axes, ["H", "P", "M", "MB"]):
        for i, m in enumerate(MODELS):
            a = DOSE.get(f"{m}|{l}|hostile"); c = DOSE.get(f"{m}|{l}|control")
            ra = (a["whole_run"]["attack_phase_rate"] or 0) * 100 if a else 0
            rk = (c["whole_run"]["attack_phase_rate"] or 0) * 100 if c else 0
            ax.barh(i - 0.18, ra, height=0.34, color=MCOL[m], edgecolor="#ffffff")
            ax.barh(i + 0.18, rk, height=0.34, color=MCOL[m], alpha=0.35, edgecolor="#ffffff")
            ax.text(ra + 2, i - 0.18, f"{ra:.0f}%", va="center", fontsize=6.5, color=TXT2)
            if rk >= 1:
                ax.text(rk + 2, i + 0.18, f"{rk:.0f}%", va="center", fontsize=6.5, color=TXT2)
        ax.set_yticks(range(4)); ax.set_yticklabels([short(m) for m in MODELS], fontsize=8); ax.set_ylim(3.6, -0.6)
        ax.set_xlim(0, 118); ax.set_xticks([0, 50, 100]); ax.set_xticklabels(["0", "50", "100%"], fontsize=7.5)
        ax.set_title(LAD[l], fontsize=9); despine(ax)
    fig.text(0.5, 0.02, "dark = attack run, pale = control; share of all 180 attack-phase samples (turns 21 to 65) the classifier calls broken", ha="center", fontsize=7.5, color=TXT2)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.86, bottom=0.2, wspace=0.12)
    fig.savefig(f"{OUT}/f8_wholerun.png"); plt.close(fig)


fig_composition()
for m in MODELS:
    fig_timeline(m)
fig_bands(); fig_requests(); fig_classifier(); fig_control(); fig_dose(); fig_wholerun()
print("figures written to", OUT)
