"""Solution figure for example_repo/unit3/circuits.xml: the RC step response.

Run from this folder:  python rc_figs.py   (writes rc_step_soln.png)
The circuit diagram is rc_circuit.tex; see the build lines at its top.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

V0, VS, TAU = 2.0, 5.0, 1.0  # initial voltage (V), source (V), RC (s)

t = np.linspace(0, 5 * TAU, 400)
v = VS - (VS - V0) * np.exp(-t / TAU)

fig, ax = plt.subplots(figsize=(6, 3.4))
ax.plot(t, v, linewidth=2, label=r"$v_C(t) = 5 - 3e^{-t/\tau}$ V")
ax.axhline(VS, linestyle="--", color="gray", linewidth=1)
ax.text(4.95 * TAU, VS - 0.12, "final value 5 V", ha="right", va="top", color="gray")

v_tau = VS - (VS - V0) * np.exp(-1)
ax.plot([TAU], [v_tau], "o", color="C1")
ax.annotate(
    rf"$t=\tau=1$ s: {v_tau:.2f} V" "\n(63% of the way from 2 V to 5 V)",
    xy=(TAU, v_tau), xytext=(1.6 * TAU, 2.6),
    arrowprops=dict(arrowstyle="->", color="C1"), color="C1",
)
ax.plot([0], [V0], "o", color="C2")
ax.annotate("initial value 2 V", xy=(0, V0), xytext=(0.25, 1.35), color="C2")

ax.set_xlim(0, 5 * TAU)
ax.set_ylim(0, 5.6)
ax.set_xlabel("t (s)")
ax.set_ylabel(r"$v_C(t)$ (V)")
ax.grid(alpha=0.3)
ax.legend(loc="lower right")
fig.tight_layout()
fig.savefig("rc_step_soln.png", dpi=150)
