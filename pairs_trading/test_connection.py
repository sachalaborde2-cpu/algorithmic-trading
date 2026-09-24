"""
test_connection.py

Test rapide et isolé de la connexion IBKR avant de lancer le screening complet.
Vérifie: la connexion socket à TWS, la qualification du contrat AAPL, et la
récupération de 30 jours de données historiques ajustées.

Lance-le avec: python3 test_connection.py
TWS doit être ouvert, connecté à ton compte paper trading, avec l'API activée.
"""

from ib_async import IB, Stock, util

ib = IB()

try:
    ib.connect("127.0.0.1", 7497, clientId=1, timeout=10)
    print(f"Connecté: {ib.isConnected()}")
    print(f"Comptes disponibles: {ib.managedAccounts()}")

    contract = Stock("AAPL", "SMART", "USD")
    ib.qualifyContracts(contract)
    print(f"Contrat qualifié: {contract}")

    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr="30 D",
        barSizeSetting="1 day",
        whatToShow="ADJUSTED_LAST",
        useRTH=True,
    )

    if not bars:
        print("ÉCHEC: aucune barre reçue. Vérifie les permissions de données de marché sur ton compte.")
    else:
        df = util.df(bars)
        print(f"\n{len(df)} barres reçues. Dernières lignes:")
        print(df[["date", "open", "high", "low", "close", "volume"]].tail())
        print("\nTout fonctionne, tu peux passer à run_screening.py.")

except Exception as e:
    print(f"ÉCHEC DE CONNEXION: {e}")
    print("Vérifie: TWS est ouvert et connecté, l'API est activée (Enable ActiveX and")
    print("Socket Clients), le port est bien 7497, et 127.0.0.1 est dans Trusted IPs.")

finally:
    if ib.isConnected():
        ib.disconnect()
        print("\nDéconnecté proprement.")
