"""
Execution quotidienne (paper trading) de la strategie overnight drift sur SPY.

Contexte
--------
TWS n'est disponible que ~9h-18h heure de Paris (ordinateur de travail), jamais
24h/24. Un ordre MOC/MOO, une fois accepte par IB, reste en file chez le
courtier et s'execute automatiquement a l'auction meme si TWS ferme ensuite :
TWS n'a donc besoin d'etre ouvert qu'au moment de la SOUMISSION, jamais de
l'EXECUTION. Un seul passage quotidien (~15h45 Paris / ~9h45 ET, juste apres
l'ouverture NY) suffit donc a :

1. Confirmer que la sortie MOO de ce matin (soumise la veille) a bien ete
   executee, et logger le fill reel.
2. Soumettre l'ordre d'entree MOC (achat) pour la cloture du jour J.
3. Soumettre l'ordre de sortie MOO (vente) pour l'ouverture du jour J+1, des
   maintenant : sinon il n'aurait jamais le temps d'etre en file avant la
   prochaine ouverture, puisque le prochain passage n'a lieu qu'apres celle-ci.

Regle strategie (cf. overnight_backtest.py, config gagnante sur SPY/QQQ/IWM/MES) :
long overnight uniquement -- achat MOC en cloture, vente MOO a l'ouverture
suivante.

Usage
-----
    python place_overnight_order.py --dry-run
    python place_overnight_order.py --dry-run --skip-window-check
    python place_overnight_order.py                      # execution reelle (paper, port 7497)

CSV/logs ecrits dans logs/trading.log (texte) et logs/trades.csv (structure).
Kill switch : presence du fichier STOP_TRADING.flag (a cote de ce script) ->
bloque uniquement les nouvelles entrees, jamais les sorties.
"""
from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import dataclass
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

NY_TZ = "America/New_York"
SYMBOL = "SPY"
QUANTITY = 100  # taille de position paper trading (a ajuster manuellement, pas de sizing automatique)

# Fenetre du passage quotidien unique : peu apres l'ouverture NY (9h30 ET),
# assez large pour absorber un lancement manuel/tache planifiee un peu en retard,
# mais jamais avant l'ouverture (l'ordre de sortie du matin doit d'abord avoir eu
# une chance de s'executer) ni tard le soir (hors des heures de bureau Paris).
WINDOW_START = dtime(9, 35)
WINDOW_END = dtime(11, 0)

HERE = Path(__file__).parent
KILL_SWITCH_PATH = HERE / "STOP_TRADING.flag"
LOG_DIR = HERE / "logs"
TRADE_LOG_PATH = LOG_DIR / "trades.csv"
TRADE_LOG_COLS = ["timestamp_ny", "action", "symbol", "quantity", "order_type",
                  "tif", "status", "fill_price", "note"]


# --------------------------------------------------------------------------
# Fonctions pures (testees dans test_place_overnight_order.py, sans IB)
# --------------------------------------------------------------------------
def now_ny() -> datetime:
    return datetime.now(ZoneInfo(NY_TZ))


def is_within_window(ts: datetime, start: dtime = WINDOW_START, end: dtime = WINDOW_END) -> bool:
    """Fail-safe : hors semaine ou hors fenetre horaire ET -> False (on ne soumet rien)."""
    if ts.weekday() >= 5:  # samedi/dimanche
        return False
    return start <= ts.time() <= end


def kill_switch_active(path: Path = KILL_SWITCH_PATH) -> bool:
    return path.exists()


def should_skip_entry(kill_switch: bool, position_qty: float) -> bool:
    """Bloque une nouvelle entree si le kill switch est actif, ou si une
    position est deja ouverte (garde-fou anti-doublon)."""
    return kill_switch or position_qty != 0


def should_skip_exit(position_qty: float) -> bool:
    """No-op si deja flat : jamais bloque par le kill switch (une position
    ouverte doit toujours pouvoir etre fermee)."""
    return position_qty == 0


def build_trade_record(timestamp_ny: datetime, action: str, symbol: str, quantity: float,
                        order_type: str, tif: str, status: str,
                        fill_price: float | None, note: str) -> dict:
    return {
        "timestamp_ny": timestamp_ny.isoformat(),
        "action": action,
        "symbol": symbol,
        "quantity": quantity,
        "order_type": order_type,
        "tif": tif,
        "status": status,
        "fill_price": fill_price,
        "note": note,
    }


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("overnight_drift")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_DIR / "trading.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    return logger


def append_trade_record(record: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    is_new = not TRADE_LOG_PATH.exists()
    with open(TRADE_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_LOG_COLS)
        if is_new:
            w.writeheader()
        w.writerow(record)


# --------------------------------------------------------------------------
# Integration IB (non testee unitairement : necessite TWS ; validee
# manuellement en dry-run puis en reel sur le compte paper)
# --------------------------------------------------------------------------
@dataclass
class IBConfig:
    host: str = "127.0.0.1"
    port: int = 7497  # paper trading
    client_id: int = 42


def connect_ib(cfg: IBConfig, logger: logging.Logger):
    from ib_async import IB
    ib = IB()
    try:
        ib.connect(cfg.host, cfg.port, clientId=cfg.client_id, timeout=10)
    except Exception as e:
        logger.error("Connexion IB impossible (TWS lance ? port %s ouvert ?) : %s", cfg.port, e)
        raise
    return ib


def get_position_qty(ib, symbol: str = SYMBOL) -> float:
    for pos in ib.positions():
        if pos.contract.symbol == symbol:
            return pos.position
    return 0.0


def submit_moc_buy(ib, logger: logging.Logger, symbol: str, quantity: int, dry_run: bool) -> dict:
    """Ordre d'entree : achat Market-On-Close pour la cloture du jour meme."""
    from ib_async import MarketOrder, Stock
    ts = now_ny()
    if dry_run:
        logger.info("[DRY-RUN] soumettrait BUY %s x%s MOC (cloture du jour)", symbol, quantity)
        return build_trade_record(ts, "BUY", symbol, quantity, "MOC", "DAY", "DryRun", None,
                                   "entree overnight (dry-run)")

    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)
    order = MarketOrder("BUY", quantity)
    order.orderType = "MOC"
    trade = ib.placeOrder(contract, order)
    ib.sleep(1)
    logger.info("Ordre BUY %s x%s MOC soumis, statut=%s", symbol, quantity, trade.orderStatus.status)
    return build_trade_record(ts, "BUY", symbol, quantity, "MOC", "DAY", trade.orderStatus.status,
                               None, "entree overnight")


def submit_moo_sell(ib, logger: logging.Logger, symbol: str, quantity: int, dry_run: bool) -> dict:
    """Ordre de sortie : vente Market-On-Open pour l'ouverture du lendemain.
    Soumis des aujourd'hui (le prochain passage n'aura lieu qu'apres cette
    ouverture)."""
    from ib_async import MarketOrder, Stock
    ts = now_ny()
    if dry_run:
        logger.info("[DRY-RUN] soumettrait SELL %s x%s MOO (ouverture du lendemain)", symbol, quantity)
        return build_trade_record(ts, "SELL", symbol, quantity, "MKT", "OPG", "DryRun", None,
                                   "sortie overnight J+1 (dry-run)")

    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)
    order = MarketOrder("SELL", quantity)
    order.tif = "OPG"
    trade = ib.placeOrder(contract, order)
    ib.sleep(1)
    logger.info("Ordre SELL %s x%s MOO (OPG) soumis, statut=%s", symbol, quantity, trade.orderStatus.status)
    return build_trade_record(ts, "SELL", symbol, quantity, "MKT", "OPG", trade.orderStatus.status,
                               None, "sortie overnight J+1")


def _log_confirmed_fill(ib, logger: logging.Logger, symbol: str, side: str,
                        action: str, order_type: str, tif: str, note: str) -> None:
    """Cherche le dernier fill du jour (heure NY) pour ce sens d'execution IB
    ('BOT'/'SLD') et l'ajoute a trades.csv s'il existe."""
    today = now_ny().date()
    fills = [f for f in ib.fills()
             if f.contract.symbol == symbol and f.execution.side == side
             and f.execution.time.astimezone(ZoneInfo(NY_TZ)).date() == today]
    if not fills:
        return
    last = fills[-1]
    record = build_trade_record(now_ny(), action, symbol, last.execution.shares, order_type, tif,
                                "Filled", last.execution.price, note)
    append_trade_record(record)
    logger.info("Fill confirme : %s %s x%s @ %.2f", action, symbol, last.execution.shares, last.execution.price)


def check_this_morning_exit(ib, logger: logging.Logger, symbol: str) -> None:
    """Confirme que l'achat MOC d'hier soir et la vente MOO de ce matin ont
    bien ete executes, et logge les fills reels dans trades.csv (utilise par
    compare_live_vs_backtest.py). No-op si deja flat (idempotent) ; ne bloque
    jamais rien -- purement informatif/logging."""
    _log_confirmed_fill(ib, logger, symbol, "BOT", "BUY", "MOC", "DAY", "confirmation entree overnight (hier soir)")

    qty = get_position_qty(ib, symbol)
    if not should_skip_exit(qty):
        logger.warning("Position %s encore ouverte (qty=%s) : la sortie MOO de ce matin n'a peut-etre pas ete executee "
                        "(jour ferie ? ordre rejete ?). Verifier manuellement dans TWS.", symbol, qty)
        return

    logger.info("Position %s deja a plat : sortie de ce matin confirmee (ou aucune position ouverte hier).", symbol)
    _log_confirmed_fill(ib, logger, symbol, "SLD", "SELL", "MKT", "OPG", "confirmation sortie overnight (ce matin)")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run(dry_run: bool, skip_window_check: bool, ib_config: IBConfig) -> int:
    logger = setup_logging()
    ts = now_ny()
    logger.info("=== Passage quotidien overnight_drift (%s) ===", ts.isoformat())

    if not skip_window_check and not is_within_window(ts):
        logger.error("Hors fenetre horaire attendue (%s-%s ET, jours ouvres) : heure actuelle %s. "
                      "Aucun ordre soumis.", WINDOW_START, WINDOW_END, ts.time())
        return 1

    kill_switch = kill_switch_active()
    if kill_switch:
        logger.warning("Kill switch actif (%s) : aucune nouvelle entree ne sera soumise.", KILL_SWITCH_PATH)

    try:
        ib = connect_ib(ib_config, logger)
    except Exception:
        return 1

    try:
        position_qty = get_position_qty(ib, SYMBOL)

        check_this_morning_exit(ib, logger, SYMBOL)

        if should_skip_entry(kill_switch, position_qty):
            reason = "kill switch actif" if kill_switch else f"position deja ouverte (qty={position_qty})"
            logger.info("Entree du soir non soumise : %s.", reason)
        else:
            record = submit_moc_buy(ib, logger, SYMBOL, QUANTITY, dry_run)
            append_trade_record(record)

            exit_record = submit_moo_sell(ib, logger, SYMBOL, QUANTITY, dry_run)
            append_trade_record(exit_record)
    finally:
        ib.disconnect()

    logger.info("=== Fin du passage ===")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="n'appelle jamais placeOrder, logge ce qui aurait ete soumis")
    ap.add_argument("--skip-window-check", action="store_true", help="reserve au --dry-run pour tester hors heures de marche")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497, help="7497=paper, 7496=live")
    ap.add_argument("--client-id", type=int, default=42)
    a = ap.parse_args()

    if a.skip_window_check and not a.dry_run:
        raise SystemExit("--skip-window-check n'est autorise qu'avec --dry-run (securite anti-execution reelle hors fenetre).")

    cfg = IBConfig(host=a.host, port=a.port, client_id=a.client_id)
    raise SystemExit(run(a.dry_run, a.skip_window_check, cfg))


if __name__ == "__main__":
    main()
