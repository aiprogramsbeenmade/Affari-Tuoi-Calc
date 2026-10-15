"""
Script CLI per lanciare simulazioni Monte Carlo di Affari Tuoi.

Esempi d'uso:

    # Confronto standard su 10.000 partite
    python scripts/simula_locale.py

    # Simulazione più lunga
    python scripts/simula_locale.py --n 100_000

    # Filtra una policy specifica
    python scripts/simula_locale.py --policy prob

    # Salva i risultati in JSON
    python scripts/simula_locale.py --json data/report.json

    # Genera grafici (richiede matplotlib)
    python scripts/simula_locale.py --grafici data/grafici/

Lo script aggiunge automaticamente `src/` al sys.path, quindi funziona
anche senza aver installato il pacchetto.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Aggiungi src/ al path per funzionare da CLI senza installazione
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from affari_tuoi.core.cambio import (  # noqa: E402
    politica_benevola,
    politica_malevola,
    politica_neutrale,
)
from affari_tuoi.core.decisione import (  # noqa: E402
    DecisioneCRRA,
    DecisioneEV,
    DecisioneKelly,
    DecisioneProbabilistica,
    DecisioneSogliaAdattiva,
    DecisioneSogliaFissa,
)
from affari_tuoi.simulazione.monte_carlo import (  # noqa: E402
    ReportSimulazione,
    confronta_policy,
    formatta_tabella,
)
from affari_tuoi.simulazione.policy import Policy  # noqa: E402


# ---------------------------------------------------------------------------
# Policy predefinite
# ---------------------------------------------------------------------------

def policy_predefinite() -> list[Policy]:
    """
    Set standard di policy da confrontare.

    Copre le tre famiglie di criteri:
    - Classici economici (EV, Kelly, CRRA)
    - Probabilistici (Prob X%)
    - Adattivi (SogliaAd)
    - Baseline (Soglia fissa)
    """
    neutrale = politica_neutrale()
    return [
        Policy("EV puro", DecisioneEV(), neutrale),
        Policy("Kelly", DecisioneKelly(), neutrale),
        Policy("CRRA gamma=2", DecisioneCRRA(gamma=2.0), neutrale),
        Policy("Prob 20%", DecisioneProbabilistica(0.20), neutrale),
        Policy("Prob 30%", DecisioneProbabilistica(0.30), neutrale),
        Policy("Prob 40%", DecisioneProbabilistica(0.40), neutrale),
        Policy("SogliaAd 30->80", DecisioneSogliaAdattiva(0.3, 0.8), neutrale),
        Policy("SogliaAd 40->90", DecisioneSogliaAdattiva(0.4, 0.9), neutrale),
        Policy("SogliaAd 50->95", DecisioneSogliaAdattiva(0.5, 0.95), neutrale),
        Policy("Soglia 70% EV", DecisioneSogliaFissa(0.7), neutrale),
    ]


# ---------------------------------------------------------------------------
# Grafici (opzionali, richiedono matplotlib)
# ---------------------------------------------------------------------------

def genera_grafici(
    reports: list[ReportSimulazione],
    output_dir: Path,
) -> None:
    """
    Genera un grafico a dispersione media vs mediana per ciascuna policy.

    Utile per visualizzare la frontiera rischio/rendimento.

    Args:
        reports: lista di report da plottare.
        output_dir: cartella di output per i PNG.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "matplotlib non installato: salto i grafici. "
            "Installa con `pip install matplotlib`.",
            file=sys.stderr,
        )
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Grafico 1: media vs mediana ---
    fig, ax = plt.subplots(figsize=(10, 7))
    for r in reports:
        ax.scatter(r.payout_medio, r.payout_mediano, s=100)
        ax.annotate(
            r.policy,
            (r.payout_medio, r.payout_mediano),
            fontsize=8,
            xytext=(5, 5),
            textcoords="offset points",
        )
    ax.set_xlabel("Payout medio (EUR)")
    ax.set_ylabel("Payout mediano (EUR)")
    ax.set_title("Frontiera rischio/rendimento delle policy")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / "frontiera.png", dpi=120)
    plt.close(fig)

    # --- Grafico 2: barre di media con errore p5-p95 ---
    fig, ax = plt.subplots(figsize=(12, 6))
    nomi = [r.policy for r in reports]
    medie = [r.payout_medio for r in reports]
    p5 = [r.percentili[5] for r in reports]
    p95 = [r.percentili[95] for r in reports]

    x = range(len(nomi))
    ax.bar(x, medie, alpha=0.6, label="Media")
    ax.errorbar(
        x,
        medie,
        yerr=[
            [m - lo for m, lo in zip(medie, p5)],
            [hi - m for m, hi in zip(medie, p95)],
        ],
        fmt="none",
        ecolor="black",
        capsize=5,
        label="Range p5-p95",
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(nomi, rotation=30, ha="right")
    ax.set_ylabel("Payout (EUR)")
    ax.set_title("Payout medio con intervallo p5-p95")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / "payout_range.png", dpi=120)
    plt.close(fig)

    print(f"Grafici salvati in {output_dir}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulatore Monte Carlo di Affari Tuoi",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=10_000,
        help="numero di partite per policy (default: 10000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="seed del generatore casuale (default: 42)",
    )
    parser.add_argument(
        "--policy",
        type=str,
        default=None,
        help="filtra le policy per nome (substring case-insensitive)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="salva i report in un file JSON",
    )
    parser.add_argument(
        "--grafici",
        type=Path,
        default=None,
        help="genera grafici nella cartella indicata",
    )
    parser.add_argument(
        "--cambio",
        type=str,
        default="neutrale",
        choices=["neutrale", "malevola", "benevola"],
        help="politica del Dottore per il cambio (default: neutrale)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Validazione
    if args.n <= 0:
        print(f"Errore: --n deve essere > 0, ricevuto {args.n}", file=sys.stderr)
        return 1

    # Politica del cambio condivisa
    politiche_cambio = {
        "neutrale": politica_neutrale,
        "malevola": lambda: politica_malevola(2.0),
        "benevola": lambda: politica_benevola(2.0),
    }
    pol_cambio = politiche_cambio[args.cambio]()

    # Filtra policy
    policies = policy_predefinite()
    if args.policy:
        filtro = args.policy.lower()
        policies = [p for p in policies if filtro in p.nome.lower()]
        if not policies:
            print(
                f"Nessuna policy corrisponde a '{args.policy}'.",
                file=sys.stderr,
            )
            return 1

    # Applica politica cambio
    for p in policies:
        p.politica_cambio = pol_cambio

    # Esegui simulazioni
    print(f"Simulazione di {args.n:,} partite per {len(policies)} policy...")
    print(f"Seed: {args.seed} | Politica cambio: {args.cambio}\n")

    reports = confronta_policy(policies, args.n, seed=args.seed)

    # Stampa tabella
    print(formatta_tabella(reports))

    # Salva JSON
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                [r.to_dict() for r in reports],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nReport JSON salvato in {args.json}")

    # Genera grafici
    if args.grafici:
        genera_grafici(reports, args.grafici)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())