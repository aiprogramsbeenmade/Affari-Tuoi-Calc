# Affari Tuoi Calc

Un **calcolatore interattivo** e **simulatore Monte Carlo** per il programma televisivo *Affari Tuoi*.

Il progetto ha due anime:

1. **Bot Telegram** — mentre guardi la puntata, apri i pacchi man mano che escono in TV e ricevi in tempo reale:
   - Valore Atteso (EV) del pacco del giocatore
   - Probabilità di battere un'offerta
   - Consigli su offerte e cambio
   - Report PDF commentato a fine partita

2. **Motore di simulazione** — per studiare le strategie in modo scientifico:
   - Simulazioni Monte Carlo su 100.000+ partite
   - Confronto tra criteri decisionali (EV puro, CRRA, Kelly, probabilistico)
   - Analisi bayesiana del cambio

## Perché

*Affari Tuoi* è un problema di **decisione in condizioni di incertezza**. Ogni offerta del Dottore è una scelta tra una cifra certa e una distribuzione di probabilità. Il progetto esplora:

- Qual è la scelta **razionale** in senso economico (EV, utilità attesa)
- Come la **propensione al rischio** cambia la decisione ottimale
- Perché la **matematica classica non basta** (asimmetria estrema dei premi)
- Come il **cambio** sia un segnale bayesiano, non solo una scommessa

## Caratteristiche

### Bot Telegram

- **`/new`** — inizia una partita, mostra la griglia dei 20 pacchi
- **Apri pacchi** — un tap per pacco, il bot ricalcola tutto
- **Offerte** — inserisci l'importo (`35000`, `35k`, `1.5k`) e ricevi un confronto tra criteri
- **Cambio finale** — analisi bayesiana in base alla politica del Dottore
- **Report PDF** — a fine partita, un PDF multipagina con grafico, timeline decisioni, statistiche e commento didattico
- **`/stats`** — statistiche aggregate delle tue partite
- **`/reset_db`** — cancella tutto (solo admin)

### Simulatore

Script CLI che confronta 10 strategie su N partite:

```bash
python scripts/simula_locale.py --n 100000
```

Output tipico (estratto):

```
Policy                       |       Media |     Mediana |          p5 |         p95 |   Acc.
------------------------------------------------------------------------------------------------------
EV puro                      |      58,303 |       5,000 |           1 |     250,000 |    3.3%
Prob 30%                     |      45,875 |      26,000 |         100 |     200,000 |   74.1%
SogliaAd 30->80              |      50,070 |      47,000 |       1,100 |     114,000 |   99.6%
Soglia 70% EV                |      44,729 |      43,500 |       6,300 |      88,000 |  100.0%
```

## Installazione

### Requisiti

- Python 3.11+
- Un bot Telegram creato con [@BotFather](https://t.me/BotFather)

### Setup

```bash
git clone https://github.com/aiprogramsbeenmade/Affari-Tuoi-Calc.git
cd affari-tuoi-bot

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

### Configurazione

Crea un file `.env` nella root:

```
TELEGRAM_BOT_TOKEN=il_tuo_token_qui
ADMIN_USER_ID=il_tuo_user_id
DB_PATH=data/partite.db
LOG_LEVEL=INFO
```

Per trovare il tuo `user_id`, usa [@userinfobot](https://t.me/userinfobot).

## Uso

### Bot Telegram

```bash
python scripts/run_bot.py
```

Poi su Telegram: cerca il tuo bot, premi `/start`, e inizia con `/new`.

### Simulatore

```bash
# Confronto standard su 10.000 partite
python scripts/simula_locale.py

# Simulazione su 100.000 partite, salva JSON e grafici
python scripts/simula_locale.py --n 100000 --json data/report.json --grafici data/grafici/

# Filtra solo le policy probabilistiche
python scripts/simula_locale.py --policy prob
```

## Struttura del progetto

```
affari_tuoi_bot/
├── src/affari_tuoi/
│   ├── core/              # Motore matematico (puro, no dipendenze da Telegram)
│   │   ├── premi.py       # Configurazione dei 20 premi
│   │   ├── partita.py     # Stato della partita (Pacco, Partita, FasePartita)
│   │   ├── statistiche.py # EV, probabilità, entropia, soglie
│   │   ├── offerte.py     # Modelli di offerta del Dottore
│   │   ├── decisione.py   # 7 criteri di decisione (EV, CRRA, Kelly, Prob, Soglia)
│   │   ├── cambio.py      # Analisi bayesiana del cambio
│   │   └── consulente.py  # Logica per stati parziali (uso in tempo reale)
│   ├── simulazione/       # Monte Carlo e policy
│   ├── storage/           # SQLite + ricostruzione timeline per report
│   ├── grafici/           # Grafici matplotlib e PDF multipagina
│   ├── bot/               # Layer Telegram (handlers, keyboards, formatters)
│   └── utils/             # Config, logger, parsing
├── scripts/
│   ├── run_bot.py         # Avvia il bot
│   └── simula_locale.py   # CLI per simulazioni
├── tests/                 # Test pytest
└── data/                  # DB SQLite, configurazione premi, output
```

## Modelli matematici

### Valore atteso (EV)

Con `n` pacchi chiusi di valore `v_1, ..., v_n`:

```
EV = (1/n) * sum(v_i)
```

Il Dottore offre tipicamente una frazione dell'EV che **cresce** man mano che la partita avanza (dal 25% al primo turno al 90% con 2 pacchi).

### Certainty Equivalent (CRRA)

Con avversione al rischio `gamma` e sussistenza `c`:

```
u(x) = ((x + c) / scala)^(1 - gamma) / (1 - gamma)    (gamma != 1)
u(x) = log((x + c) / scala)                          (gamma == 1)

CE = u^{-1}(E[u(X)])
```

Il CE è il valore certo che rende indifferente il decisore. Con `gamma = 0`, `CE = EV`.

### Decisione probabilistica

Accetta se:

```
P(pacco >= offerta) < soglia
```

Il criterio più intuitivo: "accetto solo se ho meno del 30% di probabilità di fare meglio rifiutando".

### Analisi bayesiana del cambio

Con 2 pacchi chiusi, il Dottore può proporre il cambio. Poiché conosce i valori, l'offerta è un segnale. Modelliamo la sua politica come:

```
L(r) = sigmoid(alpha + beta * t)
```

dove `t` misura la posizione del pacco (0 = più basso, 1 = più alto). Con `beta > 0` il Dottore è "malevolo" (offre il cambio più spesso quando hai il pacco alto), con `beta < 0` è "benevolo". Il posterior aggiornato via Bayes ci dice se accettare o rifiutare.

## Simulazioni: risultati chiave

Su 100.000 partite per policy, con Dottore neutrale:

| Policy | Media | Mediana | Note |
|---|---|---|---|
| EV puro | 58k | **5k** | Lotteria: media alta, mediana bassissima |
| Prob 30% | 46k | 26k | Bilanciata |
| **SogliaAd 30→80** | **50k** | **47k** | Miglior compromesso media/mediana |
| Soglia 70% EV | 45k | 44k | Prudente pura |

**Non esiste una strategia dominante**: ogni policy è un punto su una frontiera rischio/rendimento.

## Limitazioni note

- Il **modello di offerta** del Dottore è una semplificazione. Le offerte reali hanno componenti psicologiche e televisive non modellate.
- La **CRRA** fatica con distribuzioni molto asimmetriche come quella di *Affari Tuoi*. Per questo abbiamo introdotto criteri alternativi (Prob, SogliaAd).
- Il **confronto strategie** nel PDF non è ancora implementato (richiede di rigiocare la partita con policy alternative).
- Il **parsing** degli importi non gestisce `35 000` con spazio (usa `35000`, `35.000`, o `35k`).

## Sviluppo

### Test

```bash
pytest
```

### Lint e type checking

```bash
ruff check src/
mypy src/
```

## Licenza

MIT License

Copyright (c) 2026 Matteo Proietti Micozzi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Ringraziamenti

- Basato sul format televisivo *Affari Tuoi* (Rai 1) e sul format originale *Deal or No Deal* (Endemol).
- Il progetto è a scopo **didattico e di ricerca personale**. Non è affiliato a Rai, Endemol o altre entità del programma.

---

**Disclaimer**: I consigli del bot sono calcoli probabilistici. Non esiste una strategia "giusta" in assoluto — dipende dalla propensione al rischio di chi gioca. Una singola partita è dominata dalla fortuna.