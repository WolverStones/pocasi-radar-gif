import requests
from PIL import Image, UnidentifiedImageError
import os
from datetime import datetime, timedelta, timezone
from time import sleep
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading
import schedule
import signal

output_folder = "output"
map_file = "../assets/mapa-cr.png"  # Cesta k souboru s mapou

class StoppableHTTPServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keep_running = True

    def serve_forever(self):
        while self.keep_running:
            self.handle_request()

    def shutdown(self):
        self.keep_running = False
        # Probuzení serveru, pokud je v nečinnosti
        try:
            requests.get(f'http://{self.server_name}:{self.server_port}')
        except requests.RequestException:
            pass

def create_gif():
    # Funkce pro stažení obrázku z URL s opakovanými pokusy
    def download_image(url, datum, retries=5):
        while retries > 0:
            datum_txt = datum.strftime("%Y%m%d.%H%M")[:-1] + "0"
            url = f"https://radar.bourky.cz/data/pacz2gmaps.z_max3d.{datum_txt}.0.png"
            print(f"Stahuji soubor: {url}")
            response = requests.get(url)
            if response.status_code == 200:
                return True, response.content, datum_txt
            else:
                print(f"HTTP {response.status_code}: Nemohu stáhnout soubor")
                print("Pokusím se stáhnout o 10 minut starší soubor")
                datum -= timedelta(minutes=10)
                retries -= 1
                sleep(0.5)
        return False, None, datum_txt

    # Získání aktuálního času
    now = datetime.now(timezone.utc)

    # Seznam vrstev k stažení (například posledních 6 snímků po 10 minutách)
    layers = []
    for i in range(6):
        time = now - timedelta(minutes=10 * i)
        layers.append(time)

    # Stahování vrstev
    images = []
    for i, time in enumerate(layers):
        success, content, datum_txt = download_image("", time)
        if success:
            file_path = f"layer_{i}.png"
            with open(file_path, 'wb') as file:
                file.write(content)
            try:
                img = Image.open(file_path).convert("RGBA")
                images.append(img)
            except UnidentifiedImageError:
                print(f"Nelze identifikovat obrazový soubor {file_path}")
        else:
            print(f"Přeskakuji soubor pro čas {datum_txt} kvůli selhání stahování.")

    # Obrácení pořadí obrázků
    images.reverse()

    # Načtení mapy České republiky ze souboru
    if not os.path.exists(map_file):
        print(f"Soubor s mapou {map_file} nenalezen.")
        return

    base_map = Image.open(map_file).convert("RGBA")

    # Posun radarových snímků mírně doleva
    x_offset = -50  # Posun o 50 pixelů doleva

    # Překrytí radarových snímků na mapu
    overlay_images = []
    for img in images:
        overlay = base_map.copy()
        overlay.paste(img, (x_offset, 0), img)
        overlay_images.append(overlay)

    # Pokud máme nějaké platné obrázky, vytvoříme GIF s unikátním názvem
    os.makedirs(output_folder, exist_ok=True)
    timestamp = now.strftime("%Y%m%d%H%M%S")
    output_path = os.path.join(output_folder, f'radar_with_map_{timestamp}.gif')

    if overlay_images:
        overlay_images[0].save(output_path, save_all=True, append_images=overlay_images[1:], duration=500, loop=0)
        print(f"GIF byl úspěšně vytvořen: {output_path}")
        
        # Uložení názvu posledního GIFu do souboru
        with open(os.path.join(output_folder, 'latest_gif.txt'), 'w') as f:
            f.write(f'radar_with_map_{timestamp}.gif')
    else:
        print("Nebyl nalezen žádný platný obrázek pro vytvoření GIFu.")

    # Uklid souborů
    for i in range(len(layers)):
        if os.path.exists(f"layer_{i}.png"):
            os.remove(f"layer_{i}.png")

# Funkce pro spuštění jednoduchého HTTP serveru
def run_http_server():
    global server
    os.chdir(output_folder)
    handler = SimpleHTTPRequestHandler
    server = StoppableHTTPServer(("0.0.0.0", 3005), handler)  # Upravte port podle potřeby
    print("Server běží na portu 3005")
    server.serve_forever()

# Spuštění HTTP serveru v samostatném vlákně
thread = threading.Thread(target=run_http_server)
thread.daemon = True
thread.start()

# Plánování úlohy pro pravidelnou aktualizaci GIFu
schedule.every(10).minutes.do(create_gif)  # Aktualizace každých 10 minut

# Vytvoření počátečního GIFu
create_gif()

# Funkce pro správné ukončení skriptu
def graceful_shutdown(signum, frame):
    print("Vypínám server...")
    server.shutdown()
    exit(0)

# Zachytávání signálů ukončení
signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

# Držet hlavní vlákno spuštěné a spouštět naplánované úlohy
try:
    while True:
        schedule.run_pending()
        sleep(1)
except KeyboardInterrupt:
    graceful_shutdown(None, None)
