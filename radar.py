import requests
from PIL import Image, UnidentifiedImageError
import os
from datetime import datetime, timedelta, timezone
from time import sleep
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading
import schedule
import signal

# Nastavení pracovního adresáře
script_dir = os.path.dirname(os.path.abspath(__file__))
output_folder = os.path.join(script_dir, "output")
map_file = os.path.join(script_dir, "./assets/mapa-cr.png")  # Cesta k souboru s mapou
placeholder_file = os.path.join(
    script_dir, "./assets/placeholder.png"
)  # Cesta k souboru s placeholder obrázkem
max_gifs = 10  # Maximální počet uložených GIFů


class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
    def send_error(self, code, message=None):
        if code == 404:
            self.send_response(200)
            self.send_header("Content-type", "image/png")
            self.end_headers()
            with open(placeholder_file, "rb") as file:
                self.wfile.write(file.read())
        else:
            super().send_error(code, message)


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
            requests.get(f"http://{self.server_name}:{self.server_port}")
        except requests.RequestException:
            pass


def manage_gif_storage(output_folder, max_gifs):
    gif_files = sorted([f for f in os.listdir(output_folder) if f.endswith(".gif")])
    while len(gif_files) > max_gifs:
        file_to_remove = gif_files.pop(0)
        os.remove(os.path.join(output_folder, file_to_remove))
        print(f"Smazán starý GIF soubor: {file_to_remove}")


def create_gif():
    # Funkce pro stažení obrázku z URL s opakovanými pokusy
    def download_image(url, datum, retries=5):
        while retries > 0:
            datum_txt = datum.strftime("%Y%m%d.%H%M")[:-1] + "0"
            url = f"https://radar.bourky.cz/data/pacz2gmaps.z_max3d.{datum_txt}.0.png"
            print(f"Stahuji soubor: {url}")
            try:
                response = requests.get(url)
                response.raise_for_status()
                return True, response.content, datum_txt
            except requests.RequestException as e:
                print(
                    f"HTTP {response.status_code if response else 'Unknown'}: Nemohu stáhnout soubor ({e})"
                )
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

    # Vytvoření složky output, pokud neexistuje
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Stahování vrstev
    images = []
    for i, time in enumerate(layers):
        success, content, datum_txt = download_image("", time)
        file_path = os.path.join(output_folder, f"layer_{i}.png")
        if success:
            with open(file_path, "wb") as file:
                file.write(content)
            try:
                img = Image.open(file_path).convert("RGBA")
            except UnidentifiedImageError as e:
                print(
                    f"Nelze identifikovat obrazový soubor {file_path} ({e}), používám placeholder."
                )
                img = Image.open(placeholder_file).convert("RGBA")
            except Exception as e:
                print(
                    f"Chyba při otevírání obrázku {file_path} ({e}), používám placeholder."
                )
                img = Image.open(placeholder_file).convert("RGBA")
        else:
            print(
                f"Přeskakuji soubor pro čas {datum_txt} kvůli selhání stahování, používám placeholder."
            )
            img = Image.open(placeholder_file).convert("RGBA")

        images.append(img)

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
    timestamp = now.strftime("%Y%m%d%H%M%S")
    output_path = os.path.join(output_folder, f"radar_with_map_{timestamp}.gif")

    if overlay_images:
        overlay_images[0].save(
            output_path,
            save_all=True,
            append_images=overlay_images[1:],
            duration=500,
            loop=0,
        )
        print(f"GIF byl úspěšně vytvořen: {output_path}")

        # Uložení názvu posledního GIFu do souboru
        latest_gif_path = os.path.join(output_folder, "latest_gif.txt")
        with open(latest_gif_path, "w") as f:
            f.write(f"radar_with_map_{timestamp}.gif")

        # Správa úložiště GIFů
        manage_gif_storage(output_folder, max_gifs)
    else:
        print("Nebyl nalezen žádný platný obrázek pro vytvoření GIFu.")

    # Uklid souborů
    for i in range(len(layers)):
        layer_path = os.path.join(output_folder, f"layer_{i}.png")
        if os.path.exists(layer_path):
            os.remove(layer_path)


# Funkce pro spuštění jednoduchého HTTP serveru
def run_http_server():
    global server
    handler = CustomHTTPRequestHandler
    server = StoppableHTTPServer(
        ("0.0.0.0", 3005), handler
    )  # Upravte port podle potřeby
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
