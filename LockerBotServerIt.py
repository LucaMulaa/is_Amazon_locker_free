from playwright.sync_api import sync_playwright 
import re
import aiohttp
import asyncio
import json
from datetime import datetime, timedelta

# Configurazione modificabile
# INTERVALLO DI CONTROLLO: tempo di attesa fra un ciclo di monitoraggio e l'altro.
CHECK_INTERVAL = timedelta(hours=2)

# ID del locker da monitorare (identificativo univoco)
LOCKER_ID = ""

# Credenziali Amazon per l'autenticazione
AMAZON_EMAIL = ""
AMAZON_PASSWORD = ""

# Coordinate geografiche da utilizzare per il controllo della disponibilità del locker
LATITUDE = 44.4444  # Latitudine
LONGITUDE = 44.444   # Longitudine

def get_purchase_id(email: str, password: str) -> str:
    """
    Esegue il login su Amazon e naviga fino alla pagina di checkout per ottenere l'ID dell'acquisto.
    
    Parametri:
        email (str): L'indirizzo email per l'autenticazione su Amazon.
        password (str): La password associata all'account Amazon.
    
    Ritorna:
        str: L'ID dell'acquisto estratto dalla URL di checkout oppure None in caso di errore.
    
    Funzionamento:
        - Utilizza Playwright per l'automazione del browser.
        - Avvia il browser in modalità headless (senza interfaccia grafica).
        - Esegue il login su Amazon inserendo le credenziali.
        - Naviga verso il carrello e il checkout.
        - Estrae l'ID dell'acquisto dalla URL tramite espressione regolare.
    """
    with sync_playwright() as p:
        # Avvio del browser Chromium in modalità headless (senza interfaccia grafica)
        browser = p.chromium.launch(headless=True)
        try:
            # Apertura di una nuova pagina nel browser
            page = browser.new_page()
            
            # Naviga alla pagina di login di Amazon
            page.goto("https://www.amazon.it/gp/sign-in.html")
            
            # Inserisce l'email e procede al passaggio successivo
            page.fill("#ap_email", email)
            page.click("#continue")
            
            # Inserisce la password e invia il modulo di login
            page.fill("#ap_password", password)
            page.click("#signInSubmit")
            
            # Attende che il selettore dell'header di navigazione sia presente, confermando il login
            page.wait_for_selector("#nav-tools")

            # Naviga al carrello e procede al checkout
            page.click("#nav-cart")
            page.click("input[data-feature-id=proceed-to-checkout-action]")
            
            # Attende che l'URL cambi, verificando che la pagina di checkout sia stata raggiunta
            page.wait_for_url(re.compile(r"/checkout/p/"), timeout=60000)

            # Utilizza una espressione regolare per estrarre l'ID dell'acquisto dalla URL
            match = re.search(r"/p/p-(\d+-\d+-\d+)", page.url)
            return match.group(1) if match else None
            
        except Exception as e:
            # Gestisce eventuali errori e li stampa su console
            print(f"Errore durante l'ottenimento dell'ID: {str(e)}")
            return None
        finally:
            # Chiude il browser indipendentemente dall'esito dell'operazione
            browser.close()

class LockerMonitor:
    """
    Classe contenente metodi per il controllo della disponibilità del locker.
    """
    
    @staticmethod
    async def check_availability(purchase_id: str, lat: float, lng: float) -> bool:
        """
        Verifica la disponibilità di un determinato locker attraverso una chiamata API.
        
        Parametri:
            purchase_id (str): L'ID dell'acquisto ottenuto precedentemente, necessario per l'autenticazione API.
            lat (float): Latitudine per la ricerca di locker nelle vicinanze.
            lng (float): Longitudine per la ricerca di locker nelle vicinanze.
        
        Ritorna:
            bool: True se il locker è disponibile (eligible), False altrimenti.
        
        Funzionamento:
            - Crea una sessione asincrona HTTP utilizzando aiohttp.
            - Costruisce l'URL della richiesta con i parametri richiesti.
            - Esegue una richiesta GET e attende la risposta in formato JSON.
            - Controlla la struttura dei dati e cerca all'interno della lista dei locker il locker con l'ID specificato.
            - Ritorna il valore booleano associato al campo "isEligible" se il locker viene trovato.
        """
        async with aiohttp.ClientSession() as session:
            try:
                # Costruzione dell'URL con i parametri per la richiesta
                url = (
                    f"https://www.amazon.it/location_selector/fetch_locations?"
                    f"longitude={lng}&latitude={lat}"
                    f"&clientId=amazon_it_checkout_generic_tspc_desktop"
                    f"&purchaseId={purchase_id}"
                    "&countryCode=IT&lowerSlotPreference=false"
                    "&sortType=RECOMMENDED&userBenefit=true"
                    "&showFreeShippingLabel=true&showPromotionDetail=false"
                    "&showAvailableLocations=false&pipelineType=Chewbacca"
                )
                
                # Esegue la richiesta GET all'URL definito con un header personalizzato
                async with session.get(
                    url=url,
                    headers={"User-Agent": "LockerMonitor/2.0"}
                ) as response:
                    
                    # Converte la risposta in formato JSON
                    data = await response.json()
                    
                    # Verifica che la risposta sia un dizionario, altrimenti segnala un errore
                    if not isinstance(data, dict):
                        print("Formato risposta API non valido")
                        return False
                        
                    # Estrae la lista dei locker, assicurandosi che sia sempre una lista
                    location_list = data.get("locationList", []) if isinstance(data, dict) else []
                    if not isinstance(location_list, list):
                        location_list = []
                    
                    # Scorre la lista dei locker per cercare quello con l'ID specificato
                    for location in location_list:
                        if isinstance(location, dict) and location.get("id") == LOCKER_ID:
                            # Ritorna il valore booleano del campo "isEligible"
                            return bool(location.get("isEligible", False))
                    
                    # Se il locker non viene trovato nella lista, viene stampato un messaggio e si ritorna False
                    print("Locker non trovato nella risposta")
                    return False
                    
            except json.JSONDecodeError:
                # Gestione degli errori relativi al parsing della risposta JSON
                print("Errore nel parsing della risposta JSON")
                return False
            except Exception as e:
                # Gestione generica degli errori durante la richiesta
                print(f"Errore durante il check del locker: {str(e)}")
                return False
                
async def monitoring_cycle():
    """
    Ciclo di monitoraggio principale.
    
    Funzionamento:
        - Esegue ciclicamente (ogni CHECK_INTERVAL) le seguenti operazioni:
            1. Ottiene un nuovo purchase ID eseguendo il login su Amazon.
            2. Utilizza il purchase ID per verificare la disponibilità del locker.
            3. Stampa lo stato del locker (DISPONIBILE o PIENO).
            4. Calcola il tempo residuo fino al prossimo ciclo e attende quel tempo.
    """
    while True:
        start_time = datetime.now()
        print(f"\n=== Nuovo ciclo alle {start_time} ===")
        
        # Ottiene il purchase ID eseguendo la funzione in un thread separato per non bloccare l'evento asyncio
        purchase_id = await asyncio.to_thread(
            get_purchase_id, 
            AMAZON_EMAIL, 
            AMAZON_PASSWORD
        )
        
        if purchase_id:
            # Se il purchase ID è stato ottenuto, procede al controllo della disponibilità del locker
            status = await LockerMonitor.check_availability(
                purchase_id=purchase_id,
                lat=LATITUDE,
                lng=LONGITUDE
            )
            
            # Stampa lo stato attuale del locker
            print(f"Stato locker {LOCKER_ID}: {'DISPONIBILE' if status else 'PIENO'}")
            
        # Calcola il tempo trascorso in questo ciclo e determina quanto attendere prima del prossimo controllo
        elapsed = datetime.now() - start_time
        wait_seconds = CHECK_INTERVAL.total_seconds() - elapsed.total_seconds()
        if wait_seconds > 0:
            print(f"Prossimo controllo tra {wait_seconds/60:.1f} minuti")
            await asyncio.sleep(wait_seconds)

if __name__ == "__main__":
    """
    Punto di ingresso dello script.
    
    Utilizza asyncio.run per avviare il ciclo di monitoraggio asincrono.
    Intercetta l'eventuale interruzione tramite KeyboardInterrupt per terminare il programma in modo ordinato.
    """
    try:
        asyncio.run(monitoring_cycle())
    except KeyboardInterrupt:
        print("\nMonitoraggio interrotto")
