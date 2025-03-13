from flask import Flask, request, render_template_string, redirect, url_for, send_file, flash, has_request_context, jsonify, session, make_response
import os, sys, platform, json, uuid, hashlib, re, pandas as pd, subprocess, io, base64, socket, requests, copy
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A5, A4
from reportlab.lib.units import inch
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, PageBreak, ListFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import PyPDF2
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_JUSTIFY

# Détermination de l'adresse IP locale (pour affichage dans la page trial_expired)
LOCAL_IP = socket.gethostbyname(socket.gethostname())

app = Flask(__name__)
app.secret_key = 'votre_cle_secrete'

# ---------------------------
# Répertoires de travail
# ---------------------------
BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MEDICSAS_FILES")
os.makedirs(BASE_DIR, exist_ok=True)
EXCEL_FOLDER = os.path.join(BASE_DIR, "Excel")
os.makedirs(EXCEL_FOLDER, exist_ok=True)
PDF_FOLDER = os.path.join(BASE_DIR, "PDF")
os.makedirs(PDF_FOLDER, exist_ok=True)
CONFIG_FOLDER = os.path.join(BASE_DIR, "Config")
os.makedirs(CONFIG_FOLDER, exist_ok=True)
BACKGROUND_FOLDER = os.path.join(BASE_DIR, "Background")
os.makedirs(BACKGROUND_FOLDER, exist_ok=True)

CONFIG_FILE = os.path.join(CONFIG_FOLDER, "config.json")
EXCEL_FILE_PATH = os.path.join(EXCEL_FOLDER, "ConsultationData.xlsx")

# ---------------------------
# Nouvelle partie : Activation et Gestion des Licences
# ---------------------------
# --- Paramètres d'activation ---
SECRET_SALT = "S2!eUrltaMnSecet25lrao"  # Remplacez par votre sel secret unique

def get_hardware_id():
    hardware_id = str(uuid.getnode())
    return hashlib.sha256(hardware_id.encode()).hexdigest()[:16]

def generate_activation_key_for_user(user_hardware_id, plan):
    normalized_plan = plan.strip().lower()
    if normalized_plan == "1 an":
        now = datetime.now()
        # Pour le plan 1 an, on se base uniquement sur le mois et l'année actuels
        plan_data = now.strftime("%m%Y")
    elif normalized_plan == "illimité":
        # Pour illimité, on n'utilise que l'ID et le sel secret
        plan_data = ""
    else:
        plan_data = plan  # Pour les autres cas, on conserve le plan tel quel si besoin
    hash_val = hashlib.sha256((user_hardware_id + SECRET_SALT + plan_data).encode()).hexdigest().upper()
    code = hash_val[:16]
    # Formater en 4 blocs de 4 caractères séparés par des tirets (ex: XXXX-XXXX-XXXX-XXXX)
    formatted_code = '-'.join([code[i:i+4] for i in range(0, 16, 4)])
    return formatted_code

# Gestion de l'activation (plans : essai 7 jours, 1 an, illimité)
if platform.system() == "Windows":
    ACTIVATION_DIR = os.path.join(os.environ.get('APPDATA'), 'SystemData')
else:
    ACTIVATION_DIR = os.path.join(os.path.expanduser('~'), '.systemdata')
os.makedirs(ACTIVATION_DIR, exist_ok=True)
ACTIVATION_FILE = os.path.join(ACTIVATION_DIR, 'activation32x32.json')

def check_activation():
    if not os.path.exists(ACTIVATION_FILE):
        activation_data = {
            "plan": "essai_7jours",
            "activation_date": date.today().isoformat()
        }
        with open(ACTIVATION_FILE, "w", encoding="utf-8") as f:
            json.dump(activation_data, f)
        return True
    else:
        with open(ACTIVATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        plan = data.get("plan")
        try:
            activation_date = date.fromisoformat(data.get("activation_date"))
        except Exception:
            return False
        if plan.lower() == "essai_7jours":
            # Utilisation de timedelta
            return date.today() <= activation_date + timedelta(days=7)
        elif plan.lower() == "1 an":
            expected = generate_activation_key_for_user(get_hardware_id(), plan)
            if data.get("activation_code") == expected:
                try:
                    anniversary = activation_date.replace(year=activation_date.year + 1)
                except ValueError:
                    anniversary = activation_date + timedelta(days=365)
                return date.today() <= anniversary
            else:
                return False
        elif plan.lower() == "illimité":
            expected = generate_activation_key_for_user(get_hardware_id(), plan)
            return data.get("activation_code") == expected
        else:
            return False

def update_activation_after_payment(plan):
    data = {
        "plan": plan,
        "activation_date": date.today().isoformat(),
        "activation_code": generate_activation_key_for_user(get_hardware_id(), plan)
    }
    with open(ACTIVATION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

# Contrôle de la période d'essai
def check_trial_period():
    # Si le fichier d'activation existe et que le plan n'est pas "essai_7jours", l'application est considérée activée.
    if os.path.exists(ACTIVATION_FILE):
        try:
            with open(ACTIVATION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("plan") != "essai_7jours":
                return True
        except Exception:
            pass

    if platform.system() == "Windows":
        hidden_folder = os.path.join(os.environ.get('APPDATA'), 'SystemData')
        os.makedirs(hidden_folder, exist_ok=True)
        file_path = os.path.join(hidden_folder, 'windows32x32')
    else:
        hidden_folder = os.path.join(os.path.expanduser('~'), '.systemdata')
        os.makedirs(hidden_folder, exist_ok=True)
        file_path = os.path.join(hidden_folder, 'windows3')
    from datetime import datetime as dt
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding="utf-8") as f:
                stored_date_str = f.read().strip()
            stored_date = dt.strptime(stored_date_str, '%Y-%m-%d')
        except Exception as e:
            flash("Le fichier de licence est corrompu. Veuillez contacter le support.", "error")
            return False
        if stored_date > dt.now():
            flash("Le fichier de licence est corrompu ou la date système a été modifiée.", "error")
            return False
        days_passed = (dt.now() - stored_date).days
        if days_passed > 7:
            flash("La période d'essai de 7 jours est terminée.<br>Contactez sastoukadigital@gmail.com ou Whatsapp au +212652084735.", "error")
            return False
        return True
    else:
        current_date_str = dt.now().strftime('%Y-%m-%d')
        try:
            with open(file_path, 'w', encoding="utf-8") as f:
                f.write(current_date_str)
            if platform.system() == "Windows":
                import ctypes
                FILE_ATTRIBUTE_HIDDEN = 0x02
                FILE_ATTRIBUTE_SYSTEM = 0x04
                attrs = FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
                ctypes.windll.kernel32.SetFileAttributesW(file_path, attrs)
            else:
                os.chmod(file_path, 0)
        except Exception as e:
            flash("Impossible de créer le fichier de licence.", "error")
            return False
        return True

@app.before_request
def enforce_trial_period():
    if request.endpoint not in ("activation", "activate", "purchase_plan", "paypal_success", "paypal_cancel", "change_theme", "trial_expired", "static", "activation_choice"):
        if not check_trial_period():
            return redirect(url_for("trial_expired"))

@app.route("/trial_expired")
def trial_expired():
    # Désactiver le plan d'essai de 7 jours en modifiant le fichier d'activation
    if os.path.exists(ACTIVATION_FILE):
        try:
            with open(ACTIVATION_FILE, "r+", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("plan") == "essai_7jours":
                    data["plan"] = "essai_expire"
                    f.seek(0)
                    json.dump(data, f)
                    f.truncate()
        except Exception:
            pass
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
      <meta charset="UTF-8"/>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Période d'essai expirée</title>
      <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
      <script>
         setTimeout(function(){
            window.location.href = "{{ url_for('activation') }}";
         }, 3000);
      </script>
    </head>
    <body class="bg-light">
      <div class="container my-5">
        <div class="alert alert-danger" role="alert">
          La période d'essai de 7 jours est terminée.<br>
          Veuillez contacter <a href="mailto:sastoukadigital@gmail.com">sastoukadigital@gmail.com</a> ou Whatsapp au +212652084735.
        </div>
      </div>
      <footer class="text-center mt-4">
        <small>Accès via réseau local : http://{{ local_ip }}:4000</small>
      </footer>
    </body>
    </html>
    """, local_ip=LOCAL_IP)

# ---------------------------
# Partie PayPal et Achat de Plans (mise à jour pour autoriser le paiement par carte bancaire)
# ---------------------------
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID") or "AYPizBBNq1vp8WyvzvTHITGq9KoUUTXmzE0DBA7D_lWl5Ir6wEwVCB-gorvd1jgyX35ZqyURK6SMvps5"
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET") or "EKSvwa_yK7ZYTuq45VP60dbRMzChbrko90EnhQsRzrMNZhqU2mHLti4_UTYV60ytY9uVZiAg7BoBlNno"

PAYPAL_OAUTH_URL = "https://api-m.paypal.com/v1/oauth2/token"
PAYPAL_ORDER_API = "https://api-m.paypal.com/v2/checkout/orders"

def get_paypal_access_token():
    response = requests.post(
        PAYPAL_OAUTH_URL,
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        data={"grant_type": "client_credentials"},
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET)
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        raise Exception(f"Erreur obtention token PayPal: {response.status_code} {response.text}")

def create_paypal_order(amount, currency="USD"):
    token = get_paypal_access_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    # Ajout du paramètre "landing_page": "BILLING" dans application_context pour permettre le paiement par carte
    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": currency,
                    "value": amount
                }
            }
        ],
        "application_context": {
            "return_url": url_for("paypal_success", _external=True),
            "cancel_url": url_for("paypal_cancel", _external=True),
            "landing_page": "BILLING"  # Force l'affichage du paiement par carte
        }
    }
    response = requests.post(PAYPAL_ORDER_API, json=body, headers=headers)
    if response.status_code in (200, 201):
        data = response.json()
        order_id = data["id"]
        approval_url = None
        for link in data["links"]:
            if link["rel"] in ("approve", "payer-action"):
                approval_url = link["href"]
                break
        return order_id, approval_url
    else:
        raise Exception(f"Erreur création ordre PayPal: {response.status_code} {response.text}")

def capture_paypal_order(order_id):
    token = get_paypal_access_token()
    url = f"{PAYPAL_ORDER_API}/{order_id}/capture"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    response = requests.post(url, headers=headers)
    if response.status_code in (200, 201):
        data = response.json()
        if data.get("status") == "COMPLETED":
            return True
        return False
    return False

purchase_orders = {}

@app.route("/purchase_plan/<plan>")
def purchase_plan(plan):
    if plan not in ["1 an", "illimité"]:
        return "Plan non valide", 400
    amount = "50.00" if plan == "1 an" else "120.00"
    try:
        order_id, approval_url = create_paypal_order(amount, "USD")
        purchase_orders[order_id] = plan
        return redirect(approval_url)
    except Exception as e:
        return f"Erreur: {e}"

@app.route("/paypal_success")
def paypal_success():
    order_id = request.args.get("token", None)
    if not order_id:
        return "Paramètre 'token' manquant dans l'URL."
    success = capture_paypal_order(order_id)
    if success:
        plan = purchase_orders.get(order_id)
        if plan:
            update_activation_after_payment(plan)
            flash(f"Paiement validé pour le plan {plan} !", "success")
        else:
            flash("Paiement validé, mais plan inconnu.", "error")
        return redirect(url_for("index"))
    else:
        flash("Paiement non complété.", "error")
        return redirect(url_for("index"))

@app.route("/paypal_cancel")
def paypal_cancel():
    flash("Paiement annulé par l'utilisateur.", "error")
    return redirect(url_for("index"))

# -----------------------------------------------------------------------------
# Nouvelle Page d'Activation mise à jour
# -----------------------------------------------------------------------------
activation_template = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Activation de l'Application</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script>
    function copyMachineID() {
      var copyText = document.getElementById("machineID");
      copyText.select();
      copyText.setSelectionRange(0, 99999);
      document.execCommand("copy");
      alert("ID de l'utilisateur copié : " + copyText.value);
    }
  </script>
</head>
<body>
  <div class="container mt-5">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <h2 class="text-center mb-4">Activation de l'Application</h2>
    <div class="row justify-content-center">
      <div class="col-12 col-md-8 col-lg-6">
        <div class="card">
          <div class="card-body">
            <p><strong>ID de l'utilisateur :</strong></p>
            <div class="input-group mb-3">
              <input type="text" class="form-control" id="machineID" value="{{ machine_id }}" readonly>
              <button class="btn btn-outline-secondary" type="button" onclick="copyMachineID()">Copier</button>
            </div>
            <form method="POST" action="{{ url_for('activation') }}">
              <div class="mb-3">
                <label for="activation_code" class="form-label">Code d'activation (optionnel) :</label>
                <input type="text" class="form-control" id="activation_code" name="activation_code" placeholder="Entrez votre code ici">
              </div>
              <div class="mb-3">
                <p>Si vous ne disposez pas d'un code, choisissez l'activation par paiement PayPal :</p>
                <div class="d-flex flex-column flex-sm-row gap-2">
                  <button type="submit" name="choix" value="1 an" class="btn btn-success flex-fill">Activer 1 an (50.00 USD)</button>
                  <button type="submit" name="choix" value="Illimité" class="btn btn-success flex-fill">Activer Illimité (120.00 USD)</button>
                </div>
              </div>
              <div class="text-center mb-3">
                <button type="submit" name="choix" value="essai" class="btn btn-primary">Activer Essai Gratuit 7 jours</button>
              </div>
              <div class="alert alert-info">
                Si vous avez un code d'activation, saisissez-le ci-dessus et validez. Sinon, choisissez l'option de paiement.
                Pour toute information, contactez notre support technique à l'adresse sastoukadigital@gmail.com ou via WhatsApp au +212652084735.
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
@app.route("/activation", methods=["GET", "POST"])
def activation():
    machine_id = get_hardware_id()
    if request.method == "POST":
        choix = request.form.get("choix")
        activation_code = request.form.get("activation_code", "").strip()
        if choix == "essai":
            data = {
                "plan": "essai_7jours",
                "activation_date": date.today().isoformat()
            }
            with open(ACTIVATION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            flash("Essai de 7 jours activé.", "success")
            return redirect(url_for("index"))
        elif choix in ["Illimité", "1 an"]:
            if activation_code:
                expected_code = generate_activation_key_for_user(get_hardware_id(), choix)
                if activation_code == expected_code:
                    update_activation_after_payment(choix)
                    flash(f"Plan {choix} activé avec succès via code.", "success")
                    return redirect(url_for("index"))
                else:
                    flash("Code d'activation invalide.", "error")
            else:
                try:
                    amount = "50.00" if choix == "1 an" else "120.00"
                    order_id, approval_url = create_paypal_order(amount, "USD")
                    purchase_orders[order_id] = choix
                    return redirect(approval_url)
                except Exception as e:
                    flash(f"Erreur lors de la création de la commande PayPal: {e}", "error")
    return render_template_string(activation_template, machine_id=machine_id)

# -----------------------------------------------------------------------------
# Données et Fonctions Utilitaires (Consultations, PDF, etc.)
# -----------------------------------------------------------------------------
def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {}
    return config

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding="utf-8") as f:
        json.dump(config, f)

def extract_rest_duration(text):
    placeholders = ["[Nom du Médecin]", "[Nom du Patient]", "[Lieu]", "[Date]", "[X]"]
    for placeholder in placeholders:
        text = text.replace(placeholder, "")
    match = re.search(r"durée de\s*(\d+)\s*jours", text, re.IGNORECASE)
    if match:
        return match.group(1)
    else:
        return ""

default_medications_options = [
    "Paracétamol (500 mg, 3 fois/jour, durant 5 jours)",
    "Ibuprofène (200 mg, 3 fois/jour, durant 1 semaine)",
    "Amoxicilline (500 mg, 3 fois/jour, durant 10 jours)",
    "Azithromycine (500 mg, 1 fois/jour, durant 3 jours)",
    "Oméprazole (20 mg, 1 fois/jour, durant 4 semaines)",
    "Salbutamol inhalé (2 bouffées, 3 fois/jour, au besoin)",
    "Metformine (500 mg, 2 fois/jour, en continu)",
    "Lisinopril (10 mg, 1 fois/jour, en continu)",
    "Simvastatine (20 mg, 1 fois/jour, le soir)",
    "Furosémide (40 mg, 1 fois/jour, au besoin)",
    "Acide acétylsalicylique (100 mg, 1 fois/jour, en continu)",
    "Warfarine (selon INR, en continu)",
    "Insuline rapide (doses variables, avant les repas)",
    "Levothyroxine (50 µg, 1 fois/jour, le matin)",
    "Diclofénac (50 mg, 3 fois/jour, durant 5 jours)"
]
default_analyses_options = [
    "Glycémie à jeun",
    "Hémogramme complet",
    "Bilan hépatique",
    "Bilan rénal",
    "TSH",
    "CRP",
    "Ionogramme sanguin",
    "Analyse d'urine",
    "Profil lipidique",
    "Test de grossesse",
    "Hémoglobine glyquée (HbA1c)",
    "Temps de prothrombine (TP/INR)",
    "Bilan martial (fer sérique, ferritine)",
    "Groupage sanguin ABO et Rh",
    "Sérologie hépatite B et C"
]
default_radiologies_options = [
    "Radiographie thoracique",
    "Échographie abdominale",
    "IRM cérébrale",
    "Scanner thoracique",
    "Échographie cardiaque",
    "Radiographie du genou",
    "IRM de la colonne vertébrale",
    "Scanner abdominal",
    "Mammographie",
    "Échographie pelvienne",
    "Radiographie du poignet",
    "Échographie thyroïdienne",
    "IRM du genou",
    "Scanner cérébral",
    "Radiographie du rachis cervical"
]

certificate_categories = {
            "Attestation de bonne santé": "Je soussigné(e) [Nom du Médecin], Docteur en médecine, atteste par la présente que [Nom du Patient], âgé(e) de [Âge], est en bonne santé générale. Après examen clinique, aucune condition médicale ne contre-indique sa participation à [activité]. Ce certificat est délivré à la demande du patient pour servir et valoir ce que de droit.",
            "Certificat de maladie": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], présente des symptômes compatibles avec [diagnostic]. En conséquence, il/elle nécessite un repos médical et est dispensé(e) de toute activité professionnelle ou scolaire pour une durée de [X] jours à compter du [Date].",
            "Certificat de grossesse": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgée de [Âge], est actuellement enceinte de [X] semaines. Cet état de grossesse a été confirmé par un examen médical réalisé le [Date], et le suivi se poursuit normalement.",
            "Certificat de vaccination": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], a reçu les vaccins suivants conformément aux recommandations de santé publique : [Liste des vaccins avec dates]. Ce certificat est délivré pour attester de l'état vaccinal du patient.",
            "Certificat d'inaptitude sportive": "Je soussigné(e) [Nom du Médecin], après avoir examiné [Nom du Patient], atteste que celui/celle-ci est temporairement inapte à pratiquer des activités sportives en raison de [raison médicale]. La durée de cette inaptitude est estimée à [X] semaines, sous réserve de réévaluation médicale.",
            "Certificat d'aptitude au sport": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], après un examen physique complet, est en bonne condition physique et apte à pratiquer le sport suivant : [sport]. Aucun signe de contre-indication médicale n'a été détecté lors de la consultation.",
            "Certificat médical pour voyage": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], âgé(e) de [Âge], est médicalement apte à entreprendre un voyage prévu du [Date de début] au [Date de fin]. Aucun problème de santé majeur n'a été identifié pouvant contre-indiquer le déplacement.",
            "Certificat d'arrêt de travail": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], après consultation le [Date], nécessite un arrêt de travail d'une durée de [X] jours en raison de [motif médical]. Cet arrêt est nécessaire pour permettre au patient de récupérer de manière optimale.",
            "Certificat de reprise du travail": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], ayant été en arrêt de travail pour [motif], est désormais apte à reprendre son activité professionnelle à compter du [Date]. Le patient ne présente plus de signes d'incapacité liés à la condition précédemment diagnostiquée.",
            "Certificat pour soins prolongés": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] nécessite des soins médicaux prolongés pour le motif suivant : [raison]. Ces soins incluent [description des soins] et sont requis pour une période estimée de [X] semaines/mois.",
            "Certificat de visite médicale": "Je soussigné(e) [Nom du Médecin], atteste avoir examiné [Nom du Patient] lors d'une visite médicale effectuée le [Date]. Aucun problème de santé particulier n'a été détecté lors de cet examen, sauf mention contraire ci-dessous : [Observations supplémentaires].",
            "Certificat d'éducation physique": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient] est médicalement apte à participer aux activités d'éducation physique organisées par [Institution scolaire]. Aucun risque pour la santé n'a été identifié à ce jour.",
            "Certificat pour les assurances": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], après un examen médical effectué le [Date], est en état de [décrire état de santé pertinent]. Ce certificat est délivré pour répondre à la demande de l'assureur concernant [motif].",
            "Certificat pour permis de conduire": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient] a subi un examen médical complet et est jugé(e) apte à conduire un véhicule. Aucun signe de trouble de la vision, de coordination ou de toute autre condition pouvant entraver la conduite n'a été détecté.",
            "Certificat de non-contagion": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] ne présente aucun signe de maladie contagieuse à ce jour. Cet état de santé a été confirmé par un examen clinique et, le cas échéant, des tests complémentaires.",
            "Certificat pour compétition sportive": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], après examen physique réalisé le [Date], est médicalement apte à participer à la compétition suivante : [compétition]. Aucun signe de contre-indication n'a été observé lors de l'évaluation.",
            "Certificat de consultation": "Je soussigné(e) [Nom du Médecin], atteste avoir consulté [Nom du Patient] le [Date] pour le motif suivant : [raison]. Un examen complet a été effectué et les recommandations nécessaires ont été fournies au patient.",
            "Certificat pour institutions scolaires": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient] est médicalement apte à reprendre les activités scolaires à compter du [Date]. Aucun problème de santé susceptible de gêner la participation aux cours n'a été relevé.",
            "Certificat de suivi médical": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient] est actuellement sous suivi médical régulier pour la gestion de [motif]. Le suivi inclut [décrire brièvement le type de suivi ou de traitement] et se poursuivra jusqu'à amélioration de la condition.",
            "Certificat de confirmation de traitement": "Je soussigné(e) [Nom du Médecin], confirme que [Nom du Patient] est actuellement sous traitement pour [diagnostic]. Le traitement a débuté le [Date] et comprend [détails du traitement], visant à [objectif du traitement].",
            "Certificat d'incapacité partielle": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], âgé(e) de [Âge], présente une incapacité partielle en raison de [condition médicale], nécessitant des aménagements au travail ou à l'école pendant [durée].",
            "Certificat de soins palliatifs": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], bénéficie de soins palliatifs pour [motif]. Ces soins ont pour objectif de soulager les symptômes et d'améliorer la qualité de vie.",
            "Certificat de guérison": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] est guéri(e) de [condition] et est désormais en mesure de reprendre ses activités sans restriction médicale.",
            "Certificat de non-contraindication au jeûne": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], ne présente aucune contre-indication médicale au jeûne durant [période ou événement spécifique].",
            "Certificat de non-consommation d'alcool": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient] a été examiné(e) et ne présente aucun signe de consommation d'alcool récent. Ce certificat est délivré pour [motif].",
            "Certificat de handicap": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] présente un handicap lié à [type de handicap] nécessitant des aménagements spécifiques dans son environnement de travail ou scolaire.",
            "Certificat de non-fumeur": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] est non-fumeur et ne présente aucun signe de consommation récente de tabac. Ce certificat est délivré pour des raisons administratives ou de sécurité.",
            "Certificat d'aptitude pour adoption": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], âgé(e) de [Âge], présente les conditions physiques et psychologiques favorables pour entamer une démarche d'adoption.",
            "Certificat d'aptitude au travail en hauteur": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], est médicalement apte à travailler en hauteur. Aucun signe de vertige, trouble de l'équilibre ou autre condition médicale contre-indiquant ce type d'activité n'a été observé lors de l'examen.",
            "Certificat pour greffe d'organe": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] est en état de recevoir un organe pour une greffe. Ce certificat est délivré pour la validation médicale du processus de transplantation pour [type d'organe].",
            "Certificat de fin de traitement": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], ayant suivi un traitement pour [diagnostic], a terminé le processus de soins et ne nécessite plus d'interventions médicales pour cette condition.",
            "Certificat de restriction alimentaire": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], en raison de [diagnostic], doit suivre une restriction alimentaire spécifique incluant : [détails des restrictions].",
            "Certificat d'aptitude pour la plongée sous-marine": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], est apte à pratiquer la plongée sous-marine après évaluation médicale. Aucun signe de contre-indication n'a été détecté pour cette activité.",
            "Certificat de transport sanitaire": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], âgé(e) de [Âge], nécessite un transport sanitaire pour des raisons de santé spécifiques. Ce transport est nécessaire pour des déplacements vers [destination] à des fins de suivi médical.",
            "Certificat d'aptitude au travail de nuit": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], après examen, est apte à travailler de nuit sans contre-indications médicales détectées.",
            "Certificat de non-allergie": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], après examen, ne présente aucune allergie connue aux substances suivantes : [liste des substances]. Ce certificat est délivré pour des raisons administratives ou de sécurité.",
            "Certificat d'aptitude pour opérations chirurgicales": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], est médicalement apte pour subir une opération chirurgicale pour [type d'opération]. Un bilan pré-opératoire a été réalisé pour valider cette aptitude.",
            "Certificat d'aptitude pour formation militaire": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], après un examen médical, est en condition physique pour participer à une formation militaire et ne présente aucun trouble incompatible avec ce type d'entraînement.",
            "Certificat d'aptitude pour sports extrêmes": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], après un examen approfondi, est apte à pratiquer les sports extrêmes suivants : [liste des sports]. Aucun problème de santé n'a été détecté pour interdire cette pratique.",
            "Certificat d'invalidité temporaire": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] est temporairement en situation d'invalidité due à [motif médical] et requiert une assistance pour ses activités quotidiennes pour une durée de [durée].",
            "Certificat de soins dentaires": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] suit actuellement des soins dentaires pour [motif], comprenant [détails des soins]. Un suivi est recommandé jusqu'à la résolution complète de la condition.",
            "Certificat de soins orthopédiques": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] est en cours de traitement orthopédique pour [condition], incluant des séances de rééducation pour une période estimée de [durée].",
            "Certificat de non-consommation de stupéfiants": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] ne présente aucun signe de consommation récente de substances stupéfiantes, sur la base d'un examen clinique et de tests.",
            "Certificat pour activités à risque": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient], âgé(e) de [Âge], est médicalement apte à participer aux activités suivantes à risque : [liste des activités]. Aucun signe de contre-indication n'a été détecté.",
            "Certificat pour maternité à risque": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], enceinte de [X] semaines, présente un risque médical nécessitant des soins supplémentaires et des restrictions spécifiques pour le bon déroulement de sa grossesse.",
            "Certificat pour soins psychiatriques": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient] est actuellement en traitement psychiatrique pour [diagnostic]. Le suivi inclut [description du traitement] et est prévu pour [durée estimée].",
            "Certificat de décès": "Je soussigné(e) [Nom du Médecin], certifie que [Nom du Patient] est décédé(e) le [Date de décès]. Ce certificat est délivré à des fins légales pour l'enregistrement du décès auprès des autorités compétentes.",
            "Certificat de non-aptitude à la baignade": "Je soussigné(e) [Nom du Médecin], atteste que [Nom du Patient], âgé(e) de [Âge], ne peut pas pratiquer la baignade en raison de [raison médicale]. Cette restriction est valable jusqu'à nouvel ordre médical."
        }

default_certificate_text = """Je soussigné(e) [Nom du Médecin], certifie que le patient [Nom du Patient], né(e) le [Date de naissance], présente un état de santé nécessitant un arrêt de travail et un repos médical d'une durée de [X] jours à compter du [Date]. Ce repos est nécessaire pour permettre au patient de récupérer pleinement de [préciser la nature de l'affection ou des symptômes].

Fait à [Lieu], le [Date]."""

patient_ids = []
patient_names = []
patient_id_to_name = {}
patient_name_to_id = {}
patient_name_to_age = {}
patient_id_to_age = {}
patient_name_to_phone = {}
patient_id_to_phone = {}
patient_name_to_antecedents = {}
patient_id_to_antecedents = {}
patient_name_to_dob = {}
patient_id_to_dob = {}
patient_name_to_gender = {}
patient_id_to_gender = {}

def load_patient_data():
    global patient_ids, patient_names, patient_id_to_name, patient_name_to_id
    global patient_name_to_age, patient_id_to_age, patient_name_to_phone, patient_id_to_phone
    global patient_name_to_antecedents, patient_id_to_antecedents
    global patient_name_to_dob, patient_id_to_dob, patient_name_to_gender, patient_id_to_gender
    if os.path.exists(EXCEL_FILE_PATH):
        df_patients = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
        required_columns = {'patient_id', 'patient_name', 'age', 'patient_phone', 'antecedents', 'date_of_birth', 'gender'}
        if required_columns.issubset(set(df_patients.columns)):
            df_patients['patient_id'] = df_patients['patient_id'].astype(str)
            df_patients['patient_name'] = df_patients['patient_name'].astype(str)
            df_patients['date_of_birth'] = df_patients['date_of_birth'].astype(str)
            df_patients['gender'] = df_patients['gender'].astype(str)
            patient_ids = sorted(df_patients['patient_id'].unique().tolist(), key=str.lower)
            patient_names = sorted(df_patients['patient_name'].unique().tolist(), key=str.lower)
            patient_id_to_name = dict(zip(df_patients['patient_id'], df_patients['patient_name']))
            patient_name_to_id = dict(zip(df_patients['patient_name'], df_patients['patient_id']))
            patient_name_to_age = dict(zip(df_patients['patient_name'], df_patients['age']))
            patient_id_to_age = dict(zip(df_patients['patient_id'], df_patients['age']))
            patient_name_to_phone = dict(zip(df_patients['patient_name'], df_patients['patient_phone']))
            patient_id_to_phone = dict(zip(df_patients['patient_id'], df_patients['patient_phone']))
            patient_name_to_antecedents = dict(zip(df_patients['patient_name'], df_patients['antecedents']))
            patient_id_to_antecedents = dict(zip(df_patients['patient_id'], df_patients['antecedents']))
            patient_name_to_dob = dict(zip(df_patients['patient_name'], df_patients['date_of_birth']))
            patient_id_to_dob = dict(zip(df_patients['patient_id'], df_patients['date_of_birth']))
            patient_name_to_gender = dict(zip(df_patients['patient_name'], df_patients['gender']))
            patient_id_to_gender = dict(zip(df_patients['patient_id'], df_patients['gender']))
        else:
            if has_request_context():
                flash("Le fichier Excel ne contient pas les colonnes requises.", "error")
            else:
                print("Erreur: Le fichier Excel ne contient pas les colonnes requises.")
    else:
        patient_ids.clear()
        patient_names.clear()
        patient_id_to_name.clear()
        patient_name_to_id.clear()
        patient_name_to_age.clear()
        patient_id_to_age.clear()
        patient_name_to_phone.clear()
        patient_id_to_phone.clear()
        patient_name_to_antecedents.clear()
        patient_id_to_antecedents.clear()
        patient_name_to_dob.clear()
        patient_id_to_dob.clear()
        patient_name_to_gender.clear()
        patient_id_to_gender.clear()

load_patient_data()

@app.route("/get_last_consultation")
def get_last_consultation():
    patient_id = request.args.get("patient_id", "").strip()
    if patient_id and os.path.exists(EXCEL_FILE_PATH):
        df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
        df = df[df['patient_id'].astype(str) == patient_id]
        if not df.empty:
            last_row = df.iloc[-1].to_dict()
            return json.dumps(last_row)
    return json.dumps({})

@app.route("/get_consultations")
def get_consultations():
    patient_id = request.args.get("patient_id", "").strip()
    if patient_id and os.path.exists(EXCEL_FILE_PATH):
        df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
        df = df[df['patient_id'].astype(str) == patient_id]
        return df.to_json(orient="records")
    return "[]"

@app.route("/delete_consultation", methods=["POST"])
def delete_consultation():
    consultation_id = request.form.get("consultation_id", "").strip()
    if consultation_id:
        try:
            df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
            df = df[df["consultation_id"] != consultation_id]
            df.to_excel(EXCEL_FILE_PATH, index=False)
            return "OK", 200
        except Exception as e:
            return str(e), 500
    return "Missing parameters", 400

def apply_background(pdf_canvas, width, height):
    if background_file and os.path.exists(background_file):
        if background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            try:
                pdf_canvas.drawImage(background_file, 0, 0, width=width, height=height)
            except Exception as e:
                print(f"Erreur lors de l'importation de l'arrière-plan : {str(e)}")

# --- Fonction de génération du PDF de consultation ---
def generate_pdf_file(save_path, form_data, medication_list, analyses_list, radiologies_list):
    doctor_name = form_data.get("doctor_name", "").strip()
    patient_name = form_data.get("patient_name", "").strip()
    age = form_data.get("patient_age", "").strip()
    location = form_data.get("location", "").strip()
    date_of_birth = form_data.get("date_of_birth", "").strip()
    gender = form_data.get("gender", "").strip()
    computed_age = age
    if date_of_birth:
        try:
            birth = datetime.strptime(date_of_birth, '%Y-%m-%d')
            now = datetime.now()
            years = now.year - birth.year - ((now.month, now.day) < (birth.month, birth.day))
            months = (now.month - birth.month) % 12
            computed_age = f"{years} ans {months} mois" if years > 0 else f"{months} mois"
        except Exception as e:
            computed_age = age

    clinical_signs = form_data.get("clinical_signs", "").strip()
    bp = form_data.get("bp", "").strip()
    temperature = form_data.get("temperature", "").strip()
    heart_rate = form_data.get("heart_rate", "").strip()
    respiratory_rate = form_data.get("respiratory_rate", "").strip()
    diagnosis = form_data.get("diagnosis", "").strip()

    certificate_content = form_data.get("certificate_content", "").strip()
    date_str = datetime.now().strftime('%d/%m/%Y')

    c = canvas.Canvas(save_path, pagesize=A5)
    width, height = A5
    left_margin = 56.7
    header_margin = 130
    footer_margin = 56.7
    max_line_width = width - left_margin * 2

    # Première page : si l'arrière-plan est une image, on l'applique
    if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
        apply_background(c, width, height)

    def draw_header(pdf_canvas, title):
        pdf_canvas.setFont("Helvetica", 10)
        location_date_str = f"{location}, le {date_str}"
        pdf_canvas.drawCentredString(width / 2, height - header_margin, location_date_str)
        pdf_canvas.setFont("Helvetica-Bold", 16)
        pdf_canvas.drawCentredString(width / 2, height - header_margin - 25, title)
        pdf_canvas.setFont("Helvetica-Bold", 10)
        pdf_canvas.drawString(left_margin, height - header_margin - 50, "Médecin :")
        pdf_canvas.setFont("Helvetica", 10)
        pdf_canvas.drawString(left_margin + 50, height - header_margin - 50, doctor_name)
        pdf_canvas.setFont("Helvetica-Bold", 10)
        pdf_canvas.drawString(left_margin, height - header_margin - 70, "Patient :")
        pdf_canvas.setFont("Helvetica", 10)
        pdf_canvas.drawString(left_margin + 50, height - header_margin - 70, patient_name)
        pdf_canvas.setFont("Helvetica-Bold", 10)
        pdf_canvas.drawString(left_margin, height - header_margin - 90, "Sexe :")
        pdf_canvas.setFont("Helvetica", 10)
        pdf_canvas.drawString(left_margin + 50, height - header_margin - 90, gender)
        pdf_canvas.setFont("Helvetica-Bold", 10)
        pdf_canvas.drawString(left_margin, height - header_margin - 110, "Âge :")
        pdf_canvas.setFont("Helvetica", 10)
        pdf_canvas.drawString(left_margin + 50, height - header_margin - 110, computed_age)

    def justify_text(pdf_canvas, text, max_width, y_position, left_margin, footer_margin, height):
        paragraphs = text.splitlines()
        for paragraph in paragraphs:
            lines = []
            current_line = ""
            for word in paragraph.split():
                test_line = f"{current_line} {word}".strip()
                if pdf_canvas.stringWidth(test_line, "Helvetica", 10) <= max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            lines.append(current_line)
            for line in lines:
                line_width = pdf_canvas.stringWidth(line, "Helvetica", 10)
                centered_x = (max_width - line_width) / 2 + left_margin
                pdf_canvas.drawString(centered_x, y_position, line)
                y_position -= 15  # Vous pouvez ajuster cet interligne si besoin
                if y_position < footer_margin:
                    pdf_canvas.showPage()
                    # Réappliquer l'arrière-plan si nécessaire
                    if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        apply_background(pdf_canvas, width, height)
                    # Réafficher l'en-tête et réinitialiser y_position
                    draw_header(pdf_canvas, "Certificat Médical")
                    pdf_canvas.setFont("Helvetica", 10)
                    y_position = height - header_margin - 130  # Valeur réinitialisée, à ajuster selon votre design
        return y_position

    def draw_signature(pdf_canvas, y_position):
        y_position -= 30
        pdf_canvas.setFont("Helvetica", 12)
        pdf_canvas.drawCentredString(width / 2, y_position, "Signature")
        return y_position

    def draw_list(title, items, y_position, pdf_canvas, left_margin, footer_margin, height):
        pdf_canvas.setFont("Helvetica-Bold", 12)
        pdf_canvas.drawString(left_margin, y_position, title)
        y_position -= 20
        pdf_canvas.setFont("Helvetica", 10)
        max_width = 300
        for index, item in enumerate(items, start=1):
            words = item.split()
            current_line = f"{index}. "
            for word in words:
                test_line = f"{current_line} {word}".strip()
                if pdf_canvas.stringWidth(test_line, "Helvetica", 10) <= max_width:
                    current_line = test_line
                else:
                    pdf_canvas.drawString(left_margin, y_position, current_line)
                    y_position -= 20
                    # Vérification du bas de page et réinitialisation
                    if y_position < footer_margin:
                        pdf_canvas.showPage()
                        if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                            apply_background(pdf_canvas, width, height)
                        draw_header(pdf_canvas, title)
                        pdf_canvas.setFont("Helvetica", 10)
                        y_position = height - header_margin - 130
                    current_line = word
            if current_line:
                pdf_canvas.drawString(left_margin, y_position, current_line)
                y_position -= 20
                if y_position < footer_margin:
                    pdf_canvas.showPage()
                    if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        apply_background(pdf_canvas, width, height)
                    draw_header(pdf_canvas, title)
                    pdf_canvas.setFont("Helvetica", 10)
                    y_position = height - header_margin - 130
        return y_position

    def draw_multiline_text(pdf_canvas, text, left_margin, y_position, max_width, footer_margin, height):
        lines = text.split('\n')
        for line in lines:
            if y_position < footer_margin:
                pdf_canvas.showPage()
                if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    apply_background(pdf_canvas, width, height)
                draw_header(pdf_canvas, "Consultation")
                y_position = height - header_margin - 130
            pdf_canvas.drawString(left_margin, y_position, line)
            y_position -= 15
        return y_position

    has_content = False

    def add_section(section_title, items, canvas_obj):
        nonlocal has_content
        if items and any(item.strip() for item in items):
            if has_content:
                canvas_obj.showPage()
                if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    apply_background(canvas_obj, width, height)
            draw_header(canvas_obj, section_title)
            y_pos = height - header_margin - 130
            y_pos = draw_list(section_title, items, y_pos, canvas_obj, left_margin, footer_margin, height)
            y_pos = draw_signature(canvas_obj, y_pos)
            has_content = True

    if medication_list and any(m.strip() for m in medication_list):
        add_section("Ordonnance Médicale", medication_list, c)
    if analyses_list and any(a.strip() for a in analyses_list):
        add_section("Analyses", analyses_list, c)
    if radiologies_list and any(r.strip() for r in radiologies_list):
        add_section("Radiologies", radiologies_list, c)

    if clinical_signs or bp or temperature or heart_rate or respiratory_rate or diagnosis:
        if has_content:
            c.showPage()
            if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                apply_background(c, width, height)
        draw_header(c, "Consultation")
        y_pos = height - header_margin - 130
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left_margin, y_pos, "Signes Cliniques / Motifs de Consultation :")
        y_pos -= 20
        c.setFont("Helvetica", 10)
        y_pos = draw_multiline_text(c, clinical_signs, left_margin, y_pos, max_line_width, footer_margin, height)
        if bp or temperature or heart_rate or respiratory_rate:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left_margin, y_pos, "Paramètres Vitaux :")
            y_pos -= 20
            c.setFont("Helvetica", 10)
            if bp:
                c.drawString(left_margin + 20, y_pos, f"Tension Artérielle : {bp} mmHg")
                y_pos -= 15
            if temperature:
                c.drawString(left_margin + 20, y_pos, f"Température : {temperature} °C")
                y_pos -= 15
            if heart_rate:
                c.drawString(left_margin + 20, y_pos, f"Fréquence Cardiaque : {heart_rate} bpm")
                y_pos -= 15
            if respiratory_rate:
                c.drawString(left_margin + 20, y_pos, f"Fréquence Respiratoire : {respiratory_rate} rpm")
                y_pos -= 15
        if diagnosis:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left_margin, y_pos, "Diagnostic :")
            y_pos -= 20
            c.setFont("Helvetica", 10)
            y_pos = draw_multiline_text(c, diagnosis, left_margin, y_pos, max_line_width, footer_margin, height)
        y_pos = draw_signature(c, y_pos)
        has_content = True

    if form_data.get("include_certificate", "off") == "on" and certificate_content:
        if has_content:
            c.showPage()
            if background_file and os.path.exists(background_file) and background_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                apply_background(c, width, height)
        draw_header(c, "Certificat Médical")
        y_pos = height - header_margin - 130
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left_margin, y_pos, "Certificat Médical :")
        y_pos -= 20
        c.setFont("Helvetica", 10)
        certificate_text = certificate_content.replace("[Nom du Médecin]", doctor_name)\
                                        .replace("[Nom du Patient]", patient_name)\
                                        .replace("[Lieu]", location)\
                                        .replace("[Date]", date_str)\
                                        .replace("[Âge]", computed_age)\
                                        .replace("[Date de naissance]", date_of_birth)
        rest_duration = extract_rest_duration(certificate_text)
        certificate_text = certificate_text.replace("[X]", rest_duration)
        y_pos = justify_text(c, certificate_text, max_line_width, y_pos, left_margin, footer_margin, height)
        y_pos = draw_signature(c, y_pos)
        has_content = True

    c.save()

    # Fusion post-génération de l'arrière-plan PDF si nécessaire (pour arrière-plan PDF)
    if background_file and os.path.exists(background_file) and background_file.lower().endswith('.pdf'):
        try:
            merge_with_background_pdf(save_path)
        except Exception as e:
            print(f"Erreur lors de la fusion avec l'arrière-plan PDF : {str(e)}")

@app.route("/", methods=["GET", "POST"])
def index():
    config = load_config()
    global background_file
    if config.get("background_file_path"):
        background_file = config["background_file_path"]
    else:
        background_file = None

    saved_medications = []
    saved_analyses = []
    saved_radiologies = []

    if request.method == "POST":
        form_data = request.form.to_dict()
        medication_list = request.form.getlist("medications_list")
        analyses_list = request.form.getlist("analyses_list")
        radiologies_list = request.form.getlist("radiologies_list")
        consultation_date = datetime.now().strftime('%Y-%m-%d')
        patient_id = form_data.get("patient_id", "").strip()
        patient_name = form_data.get("patient_name", "").strip()
        date_of_birth = form_data.get("date_of_birth", "").strip()
        gender = form_data.get("gender", "").strip()
        age = form_data.get("patient_age", "").strip()
        location = form_data.get("location", "").strip()
        patient_phone = form_data.get("patient_phone", "").strip()
        antecedents = form_data.get("antecedents", "").strip()
        clinical_signs = form_data.get("clinical_signs", "").strip()
        bp = form_data.get("bp", "").strip()
        temperature = form_data.get("temperature", "").strip()
        heart_rate = form_data.get("heart_rate", "").strip()
        respiratory_rate = form_data.get("respiratory_rate", "").strip()
        diagnosis = form_data.get("diagnosis", "").strip()
        medications = '; '.join(medication_list)
        analyses = '; '.join(analyses_list)
        radiologies = '; '.join(radiologies_list)
        certificate_category = form_data.get("certificate_category", "").strip()
        rest_duration = extract_rest_duration(form_data.get("certificate_content", ""))
        doctor_comment = form_data.get("doctor_comment", "").strip()

        saved_medications = medication_list
        saved_analyses = analyses_list
        saved_radiologies = radiologies_list

        if not patient_id:
            return render_template_string(alert_template, alert_type="warning", alert_title="Attention", alert_text="Veuillez entrer l'ID du patient.", redirect_url=url_for("index"))

        # Vérification de l'unicité de l'ID pour un même patient
        if os.path.exists(EXCEL_FILE_PATH):
            df_existing = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
            if patient_id in df_existing["patient_id"].astype(str).tolist():
                existing_name = df_existing.loc[df_existing["patient_id"].astype(str) == patient_id, "patient_name"].iloc[0]
                if existing_name.strip().lower() != patient_name.strip().lower():
                    flash("L'ID existe déjà et est associé à un autre patient.", "error")
                    return render_template_string(alert_template, alert_type="error", alert_title="Erreur", alert_text="L'ID existe déjà et est associé à un autre patient.", redirect_url=url_for("index"))

        if os.path.exists(EXCEL_FILE_PATH):
            df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
        else:
            df = pd.DataFrame(columns=[
                "consultation_date", "patient_id", "patient_name", "date_of_birth", "gender", "age", "patient_phone", "antecedents",
                "clinical_signs", "bp", "temperature", "heart_rate", "respiratory_rate", "diagnosis",
                "medications", "analyses", "radiologies", "certificate_category", "certificate_content",
                "rest_duration", "doctor_comment", "consultation_id"
            ])
        new_row = {
            "consultation_date": consultation_date,
            "patient_id": patient_id,
            "patient_name": patient_name,
            "date_of_birth": date_of_birth,
            "gender": gender,
            "age": age,
            "patient_phone": patient_phone,
            "antecedents": antecedents,
            "clinical_signs": clinical_signs,
            "bp": bp,
            "temperature": temperature,
            "heart_rate": heart_rate,
            "respiratory_rate": respiratory_rate,
            "diagnosis": diagnosis,
            "medications": medications,
            "analyses": analyses,
            "radiologies": radiologies,
            "certificate_category": certificate_category,
            "certificate_content": "",
            "rest_duration": rest_duration,
            "doctor_comment": doctor_comment,
            "consultation_id": str(uuid.uuid4())
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_excel(EXCEL_FILE_PATH, index=False)
        load_patient_data()
        flash("Les données du patient ont été enregistrées avec succès.", "success")
    patient_data = {}
    for pid in patient_ids:
        patient_data[pid] = {
            "name": patient_id_to_name.get(pid, ""),
            "age": patient_id_to_age.get(pid, ""),
            "phone": patient_id_to_phone.get(pid, ""),
            "antecedents": patient_id_to_antecedents.get(pid, ""),
            "date_of_birth": patient_id_to_dob.get(pid, ""),
            "gender": patient_id_to_gender.get(pid, "")
        }
    return render_template_string(main_template,
                                  config=config,
                                  current_date=datetime.now().strftime("%d/%m/%Y"),
                                  medications_options=default_medications_options,
                                  analyses_options=default_analyses_options,
                                  radiologies_options=default_radiologies_options,
                                  certificate_categories=certificate_categories,
                                  default_certificate_text=default_certificate_text,
                                  patient_ids=patient_ids,
                                  patient_names=patient_names,
                                  host_address=f"http://{LOCAL_IP}:3000",
                                  patient_data=patient_data,
                                  saved_medications=saved_medications,
                                  saved_analyses=saved_analyses,
                                  saved_radiologies=saved_radiologies)

@app.route("/generate_pdf_route")
def generate_pdf_route():
    form_data = {
        "doctor_name": request.args.get("doctor_name", "Dr. Exemple"),
        "patient_name": request.args.get("patient_name", "Patient Exemple"),
        "patient_age": request.args.get("patient_age", "30"),
        "date_of_birth": request.args.get("date_of_birth", ""),
        "gender": request.args.get("gender", ""),
        "location": request.args.get("location", "Ville Exemple"),
        "clinical_signs": request.args.get("clinical_signs", "Signes cliniques..."),
        "bp": request.args.get("bp", "120/80"),
        "temperature": request.args.get("temperature", "37"),
        "heart_rate": request.args.get("heart_rate", "70"),
        "respiratory_rate": request.args.get("respiratory_rate", "16"),
        "diagnosis": request.args.get("diagnosis", "Diagnostic exemple"),
        "certificate_content": request.args.get("certificate_content", default_certificate_text),
        "include_certificate": request.args.get("include_certificate", "off")
    }
    medication_list = request.args.get("medications_list", "").split("\n") or ["Médicament Exemple"]
    analyses_list = request.args.get("analyses_list", "").split("\n") or ["Analyse Exemple"]
    radiologies_list = request.args.get("radiologies_list", "").split("\n") or ["Radiologie Exemple"]

    pdf_path = os.path.join(PDF_FOLDER, f"Ordonnance_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
    generate_pdf_file(pdf_path, form_data, medication_list, analyses_list, radiologies_list)
    return send_file(pdf_path, as_attachment=True)

def add_background_platypus(canvas_obj, doc):
    bg_path = background_file if background_file and os.path.exists(background_file) else None
    if bg_path:
        if bg_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            try:
                canvas_obj.drawImage(bg_path, 0, 0, width=doc.pagesize[0], height=doc.pagesize[1])
            except Exception as e:
                print(f"Erreur lors de l'ajout de l'arrière-plan image : {str(e)}")

from reportlab.lib.enums import TA_JUSTIFY

import copy
from PyPDF2 import PdfReader, PdfWriter

def merge_with_background_pdf(foreground_path):
    if not (background_file and os.path.exists(background_file) and background_file.lower().endswith('.pdf')):
        return

    bg_reader = PdfReader(background_file)
    fg_reader = PdfReader(foreground_path)
    writer = PdfWriter()

    num_bg_pages = len(bg_reader.pages)
    for i in range(len(fg_reader.pages)):
        fg_page = fg_reader.pages[i]
        # Créer une copie indépendante de la page d'arrière‑plan pour éviter la réutilisation
        if i < num_bg_pages:
            bg_page = copy.deepcopy(bg_reader.pages[i])
        else:
            bg_page = copy.deepcopy(bg_reader.pages[-1])
        # Fusionner le contenu généré sur le fond
        bg_page.merge_page(fg_page)
        writer.add_page(bg_page)

    with open(foreground_path, "wb") as f_out:
        writer.write(f_out)
  
def generate_history_pdf_file(pdf_path, df_filtered):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import A5
    import pandas as pd

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A5,
        rightMargin=56.7, leftMargin=56.7,
        topMargin=130, bottomMargin=56.7
    )
    elements = []
    styles = getSampleStyleSheet()
    style_heading = ParagraphStyle(
        'CustomHeading',
        parent=styles["Heading1"],
        fontSize=styles["Heading1"].fontSize - 2,
        alignment=TA_JUSTIFY,
        leading=styles["Heading1"].leading - 2
    )
    style_normal = ParagraphStyle(
        'JustifiedNormal',
        parent=styles["Normal"],
        fontSize=styles["Normal"].fontSize - 2,
        alignment=TA_JUSTIFY
    )
    style_subheading = styles["Heading2"]

    if not df_filtered.empty:
        patient_row = df_filtered.iloc[0]
        patient_name = str(patient_row.get('patient_name', ''))
        patient_id = str(patient_row.get('patient_id', ''))
        patient_age = str(patient_row.get('age', ''))
        patient_gender = str(patient_row.get('gender', ''))
        patient_phone = str(patient_row.get('patient_phone', ''))
        patient_antecedents = str(patient_row.get('antecedents', ''))
        
        title = (
            f"Historique des Consultations de {patient_name} "
            f"(ID: {patient_id}, Age: {patient_age}, Sexe: {patient_gender}, "
            f"Téléphone: {patient_phone}, Antécédents: {patient_antecedents})"
        )
        elements.append(Paragraph(title, style_heading))
        elements.append(Spacer(1, 12))

        for index, row in df_filtered.iterrows():
            consultation_date = str(row['consultation_date'])
            clinical_signs = str(row.get('clinical_signs', '')) if pd.notnull(row.get('clinical_signs', '')) else ''
            bp = str(row.get('bp', '')) if pd.notnull(row.get('bp', '')) else ''
            temperature = str(row.get('temperature', '')) if pd.notnull(row.get('temperature', '')) else ''
            heart_rate = str(row.get('heart_rate', '')) if pd.notnull(row.get('heart_rate', '')) else ''
            respiratory_rate = str(row.get('respiratory_rate', '')) if pd.notnull(row.get('respiratory_rate', '')) else ''
            diagnosis = str(row.get('diagnosis', '')) if pd.notnull(row.get('diagnosis', '')) else ''
            medications = str(row.get('medications', '')) if pd.notnull(row.get('medications', '')) else ''
            analyses = str(row.get('analyses', '')) if pd.notnull(row.get('analyses', '')) else ''
            radiologies = str(row.get('radiologies', '')) if pd.notnull(row.get('radiologies', '')) else ''
            certificate_category = str(row.get('certificate_category', '')) if pd.notnull(row.get('certificate_category', '')) else ''
            rest_duration = str(row.get('rest_duration', '')) if pd.notnull(row.get('rest_duration', '')) else ''
            doctor_comment = str(row.get('doctor_comment', '')) if pd.notnull(row.get('doctor_comment', '')) else ''

            elements.append(Paragraph(f"Date de consultation : {consultation_date}", style_subheading))
            elements.append(Spacer(1, 6))

            if clinical_signs:
                elements.append(Paragraph("<b>Signes Cliniques / Motifs de Consultation :</b>", style_normal))
                elements.append(Paragraph(clinical_signs, style_normal))

            if bp or temperature or heart_rate or respiratory_rate:
                elements.append(Paragraph("<b>Paramètres Vitaux :</b>", style_normal))
                vitals = []
                if bp:
                    vitals.append(f"Tension Artérielle : {bp} mmHg")
                if temperature:
                    vitals.append(f"Température : {temperature} °C")
                if heart_rate:
                    vitals.append(f"Fréquence Cardiaque : {heart_rate} bpm")
                if respiratory_rate:
                    vitals.append(f"Fréquence Respiratoire : {respiratory_rate} rpm")
                vitals_text = '; '.join(vitals)
                elements.append(Paragraph(vitals_text, style_normal))

            if diagnosis:
                elements.append(Paragraph(f"<b>Diagnostic :</b> {diagnosis}", style_normal))

            if medications:
                elements.append(Paragraph("<b>Médicaments prescrits :</b>", style_normal))
                meds_list = medications.split('; ')
                for med in meds_list:
                    elements.append(Paragraph(f"- {med}", style_normal))

            if analyses:
                elements.append(Paragraph("<b>Analyses demandées :</b>", style_normal))
                analyses_list = analyses.split('; ')
                for analysis in analyses_list:
                    elements.append(Paragraph(f"- {analysis}", style_normal))

            if radiologies:
                elements.append(Paragraph("<b>Radiologies demandées :</b>", style_normal))
                radiologies_list = radiologies.split('; ')
                for radiology in radiologies_list:
                    elements.append(Paragraph(f"- {radiology}", style_normal))

            if certificate_category:
                elements.append(Paragraph(f"<b>Certificat médical :</b> {certificate_category}", style_normal))

            if rest_duration:
                elements.append(Paragraph(f"<b>Durée du repos :</b> {rest_duration} jours", style_normal))

            if doctor_comment.strip():
                elements.append(Paragraph("<b>Commentaire du médecin :</b>", style_normal))
                elements.append(Paragraph(doctor_comment, style_normal))

            elements.append(Spacer(1, 12))

    doc.build(elements, onFirstPage=add_background_platypus, onLaterPages=add_background_platypus)
    if background_file and background_file.lower().endswith('.pdf'):
        try:
            merge_with_background_pdf(pdf_path)
        except Exception as e:
            print(f"Erreur lors de la fusion avec l'arrière-plan PDF : {str(e)}")
    return

@app.route("/generate_history_pdf")
def generate_history_pdf():
    patient_id_filter = request.args.get("patient_id_filter", "").strip()
    patient_name_filter = request.args.get("patient_name_filter", "").strip()
    if not os.path.exists(EXCEL_FILE_PATH):
        flash("Aucune donnée de consultation n'a été trouvée.", "warning")
        return redirect(url_for("index"))
    df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
    if patient_id_filter:
        df_filtered = df[df['patient_id'].astype(str) == patient_id_filter]
    elif patient_name_filter:
        df_filtered = df[df['patient_name'].astype(str).str.contains(patient_name_filter, case=False, na=False)]
    else:
        flash("Veuillez sélectionner l'ID ou le nom du patient.", "warning")
        return redirect(url_for("index"))
    if df_filtered.empty:
        flash("Aucune consultation trouvée pour ce patient.", "info")
        return redirect(url_for("index"))
    pdf_path = os.path.join(PDF_FOLDER, f"Historique_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
    generate_history_pdf_file(pdf_path, df_filtered)
    return send_file(pdf_path, as_attachment=True)

# --- Modification pour les importations via AJAX ---
@app.route("/import_excel", methods=["POST"])
def import_excel():
    if 'excel_file' not in request.files:
        return jsonify({"status": "warning", "message": "Aucun fichier sélectionné."})
    file = request.files["excel_file"]
    if file.filename == "":
        return jsonify({"status": "warning", "message": "Aucun fichier sélectionné."})
    filename = secure_filename(file.filename)
    file_path = os.path.join(EXCEL_FOLDER, filename)
    file.save(file_path)
    try:
        df = pd.read_excel(file_path)
        df.columns = [col.lower() for col in df.columns]
        global default_medications_options, default_analyses_options, default_radiologies_options
        if 'medications' in df.columns:
            default_medications_options.extend(df['medications'].dropna().tolist())
        if 'analyses' in df.columns:
            default_analyses_options.extend(df['analyses'].dropna().tolist())
        if 'radiologies' in df.columns:
            default_radiologies_options.extend(df['radiologies'].dropna().tolist())
        if all(x in df.columns for x in ['patient_name', 'patient_id', 'age', 'patient_phone', 'antecedents', 'date_of_birth', 'gender']):
            global patient_ids, patient_names, patient_id_to_name, patient_name_to_id, patient_name_to_age, patient_id_to_age, patient_name_to_phone, patient_id_to_phone, patient_name_to_antecedents, patient_id_to_antecedents, patient_name_to_dob, patient_id_to_dob, patient_name_to_gender, patient_id_to_gender
            patient_ids.extend(df['patient_id'].astype(str).tolist())
            patient_names.extend(df['patient_name'].astype(str).tolist())
            patient_ids = sorted(set(patient_ids), key=str.lower)
            patient_names = sorted(set(patient_names), key=str.lower)
            patient_id_to_name.update(dict(zip(df['patient_id'].astype(str), df['patient_name'].astype(str))))
            patient_name_to_id.update(dict(zip(df['patient_name'].astype(str), df['patient_id'].astype(str))))
            patient_name_to_age.update(dict(zip(df['patient_name'], df['age'])))
            patient_id_to_age.update(dict(zip(df['patient_id'], df['age'])))
            patient_name_to_phone.update(dict(zip(df['patient_name'], df['patient_phone'])))
            patient_id_to_phone.update(dict(zip(df['patient_id'], df['patient_phone'])))
            patient_name_to_antecedents.update(dict(zip(df['patient_name'], df['antecedents'])))
            patient_id_to_antecedents.update(dict(zip(df['patient_id'], df['antecedents'])))
            patient_name_to_dob.update(dict(zip(df['patient_name'], df['date_of_birth'].astype(str))))
            patient_id_to_dob.update(dict(zip(df['patient_id'], df['date_of_birth'].astype(str))))
            patient_name_to_gender.update(dict(zip(df['patient_name'], df['gender'].astype(str))))
            patient_id_to_gender.update(dict(zip(df['patient_id'], df['gender'].astype(str))))
        default_medications_options = list(set(default_medications_options))
        default_analyses_options = list(set(default_analyses_options))
        default_radiologies_options = list(set(default_radiologies_options))
        current_config = load_config()
        current_config['medications_options'] = default_medications_options
        current_config['analyses_options'] = default_analyses_options
        current_config['radiologies_options'] = default_radiologies_options
        save_config(current_config)
        return jsonify({"status": "success", "message": "Les données ont été importées avec succès."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Erreur lors de l'importation des données : {str(e)}"})

@app.route("/import_background", methods=["POST"])
def import_background():
    if 'background_file' not in request.files:
        return jsonify({"status": "warning", "message": "Aucun fichier sélectionné."})
    file = request.files["background_file"]
    if file.filename == "":
        return jsonify({"status": "warning", "message": "Aucun fichier sélectionné."})
    filename = secure_filename(file.filename)
    file_path = os.path.join(BACKGROUND_FOLDER, filename)
    file.save(file_path)
    if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
        bg_type = 'image'
    elif filename.lower().endswith('.pdf'):
        bg_type = 'pdf'
    else:
        bg_type = None
    if bg_type:
        global background_file
        background_file = file_path
        current_config = load_config()
        current_config['background_file_path'] = background_file
        save_config(current_config)
        return jsonify({"status": "success", "message": f"L'arrière-plan a été importé depuis : {file_path}"})
    else:
        return jsonify({"status": "warning", "message": "Format de fichier non supporté. Veuillez sélectionner une image ou un PDF."})

@app.route("/update_comment", methods=["POST"])
def update_comment():
    patient_id = request.form.get("suivi_patient_id", "").strip()
    new_comment = request.form.get("new_doctor_comment", "").strip()
    if not patient_id:
         flash("Veuillez entrer l'ID du patient.", "warning")
         return redirect(url_for("index"))
    if os.path.exists(EXCEL_FILE_PATH):
         df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=0)
         df.loc[df['patient_id'].astype(str)==patient_id, 'doctor_comment'] = new_comment
         df.to_excel(EXCEL_FILE_PATH, index=False)
         flash("Commentaire mis à jour.", "success")
    else:
         flash("Fichier de données non trouvé.", "error")
    return redirect(url_for("index"))

@app.route("/settings", methods=["GET", "POST"])
def settings():
    global default_medications_options, default_analyses_options, default_radiologies_options
    current_config = load_config()
    if request.method == "POST":
        current_config['nom_clinique'] = request.form.get("nom_clinique", "")
        current_config['cabinet'] = request.form.get("cabinet", "")
        current_config['centre_medical'] = request.form.get("centre_medecin", "")
        current_config['doctor_name'] = request.form.get("nom_medecin", "")
        current_config['location'] = request.form.get("lieu", "")
        current_config['theme'] = request.form.get("theme", current_config.get("theme", "Default"))
        current_config['background_file_path'] = request.form.get("arriere_plan", "")
        # Nouveau champ pour le chemin de stockage personnalisé
        storage_path = request.form.get("storage_path", "").strip()
        if storage_path:
            current_config['storage_path'] = storage_path
            # Mise à jour globale du chemin de stockage et des dossiers associés
            global BASE_DIR, EXCEL_FOLDER, PDF_FOLDER, CONFIG_FOLDER, BACKGROUND_FOLDER, CONFIG_FILE, EXCEL_FILE_PATH
            BASE_DIR = storage_path
            os.makedirs(BASE_DIR, exist_ok=True)
            EXCEL_FOLDER = os.path.join(BASE_DIR, "Excel")
            os.makedirs(EXCEL_FOLDER, exist_ok=True)
            PDF_FOLDER = os.path.join(BASE_DIR, "PDF")
            os.makedirs(PDF_FOLDER, exist_ok=True)
            CONFIG_FOLDER = os.path.join(BASE_DIR, "Config")
            os.makedirs(CONFIG_FOLDER, exist_ok=True)
            BACKGROUND_FOLDER = os.path.join(BASE_DIR, "Background")
            os.makedirs(BACKGROUND_FOLDER, exist_ok=True)
            CONFIG_FILE = os.path.join(CONFIG_FOLDER, "config.json")
            EXCEL_FILE_PATH = os.path.join(EXCEL_FOLDER, "ConsultationData.xlsx")
            # Sauvegarde dans le fichier de configuration de stockage
            try:
                with open(STORAGE_CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump({"storage_path": storage_path}, f)
            except Exception as e:
                flash(f"Erreur lors de la sauvegarde du chemin de stockage : {str(e)}", "error")
        meds = request.form.get("liste_medicaments", "")
        current_config['medications_options'] = meds.splitlines() if meds else default_medications_options
        analyses = request.form.get("liste_analyses", "")
        current_config['analyses_options'] = analyses.splitlines() if analyses else default_analyses_options
        radios = request.form.get("liste_radiologies", "")
        current_config['radiologies_options'] = radios.splitlines() if radios else default_radiologies_options
        save_config(current_config)
        flash("Paramètres mis à jour avec succès.", "success")
        return redirect(url_for("index"))
    else:
        return render_template_string(settings_template, config=current_config)

# -----------------------------------------------------------------------------
# Templates HTML
# -----------------------------------------------------------------------------
main_template = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ config.nom_clinique or config.cabinet or 'MedicSastouka' }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
   <link href="https://fonts.googleapis.com/css2?family=Great+Vibes&display=swap" rel="stylesheet">
  <!-- DataTables CSS -->
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.1/css/dataTables.bootstrap5.min.css">
  <style>
  body {
      padding-top: 56px;
  }
</style>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
  <!-- jQuery et DataTables JS -->
  <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.1/js/jquery.dataTables.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.1/js/dataTables.bootstrap5.min.js"></script>
  <style>
    body { background: linear-gradient(to right, #74ABE2, #5563DE); }
    .card { background: rgba(255, 255, 255, 0.95); }
    /* Pour les onglets inactifs */
.nav-tabs .nav-link {
  background-color: #000080; /* Bleu foncé */
  color: #ffffff;            /* Texte blanc */
  border: 1px solid #ddd;    /* (optionnel) */
}

/* Pour l'onglet actif */
.nav-tabs .nav-link.active {
  background-color: #FFDC00; /* Jaune */
  color: #000000;            /* Texte noir */
  border: 1px solid #ddd;    /* (optionnel) */
}
    .footer { font-size: 0.9rem; color: #f8f9fa; }
  </style>
  <script>
    // Interception stricte de la touche "Entrée" sur les combobox pour éviter la soumission ou suppression involontaire
    document.addEventListener("DOMContentLoaded", function() {
      document.querySelectorAll("#medication_combobox, #analysis_combobox, #radiology_combobox").forEach(function(input) {
        input.addEventListener("keydown", function(e) {
          if (e.key === "Enter") {
            e.preventDefault();
            return false;
          }
        });
      });
    });

    // Conservation de l'onglet actif via localStorage
    document.addEventListener("DOMContentLoaded", function() {
      // Pour la combobox des médicaments
      var medCombo = document.getElementById("medication_combobox");
      if (medCombo) {
        medCombo.addEventListener("keydown", function(e) {
          if (e.key === "Enter") {
            e.preventDefault();
            addMedication();
          }
        });
      }

      // Pour la combobox des analyses
      var analysisCombo = document.getElementById("analysis_combobox");
      if (analysisCombo) {
        analysisCombo.addEventListener("keydown", function(e) {
          if (e.key === "Enter") {
            e.preventDefault();
            addAnalysis();
          }
        });
      }

      // Pour la combobox des radiologies
      var radCombo = document.getElementById("radiology_combobox");
      if (radCombo) {
        radCombo.addEventListener("keydown", function(e) {
          if (e.key === "Enter") {
            e.preventDefault();
            addRadiology();
          }
        });
      }
    });

    // Gestion AJAX pour les formulaires d'import
    function ajaxFileUpload(formId, endpoint) {
      var form = document.getElementById(formId);
      var formData = new FormData(form);
      fetch(endpoint, {
          method: "POST",
          body: formData
      })
      .then(response => response.json())
      .then(data => {
          Swal.fire({
              icon: data.status,
              title: data.status === "success" ? "Succès" : "Attention",
              text: data.message,
              timer: 2000,
              showConfirmButton: false
          });
          if (data.status === "success") {
              if (formId === "importExcelForm") {
                  $('#importExcelModal').modal('hide');
              } else if (formId === "importBackgroundForm") {
                  $('#importBackgroundModal').modal('hide');
              }
              setTimeout(function() {
                  $('.modal-backdrop').remove();
              }, 2100);
          }
      })
      .catch(error => {
          Swal.fire({
              icon: "error",
              title: "Erreur",
              text: error,
              timer: 2000,
              showConfirmButton: false
          });
      });
      return false;
    }

    // Autres fonctions de la page (gestion des listes, génération de PDF, etc.)
    document.querySelectorAll("#medication_combobox, #analysis_combobox, #radiology_combobox").forEach(function(input) {
      input.addEventListener("keydown", function(e) {
        if (e.key === "Enter") { e.preventDefault(); }
      });
    });
    document.addEventListener("DOMContentLoaded", function() {
      document.getElementById("mainForm").addEventListener("submit", function(e) {
        e.preventDefault();
        Swal.fire({
          title: 'Vérification des onglets',
          text: "Avez-vous parcouru tous les onglets (Consultation, Médicaments, Biologie, Radiologies, Certificats) ?",
          icon: 'warning',
          showCancelButton: true,
          confirmButtonText: 'Oui, je confirme',
          cancelButtonText: 'Non, vérifier'
        }).then((result) => {
          if (result.isConfirmed) {
            document.querySelectorAll("#medications_listbox option").forEach(function(option) { option.selected = true; });
            document.querySelectorAll("#analyses_listbox option").forEach(function(option) { option.selected = true; });
            document.querySelectorAll("#radiologies_listbox option").forEach(function(option) { option.selected = true; });
            e.target.submit();
          }
        });
      });
    });
    var certificateTemplates = {{ certificate_categories|tojson }};
    window.addEventListener("DOMContentLoaded", function() {
      document.getElementById("certificate_category").addEventListener("change", function() {
        var cat = this.value;
        if(certificateTemplates[cat]) { document.getElementById("certificate_content").value = certificateTemplates[cat]; }
      });
      window.medicationCount = 1;
      window.analysisCount = 1;
      window.radiologyCount = 1;
      console.log("Patient data:", patientData);
    });
    function updateListNumbers(listboxId) {
      var listbox = document.getElementById(listboxId);
      for (var i = 0; i < listbox.options.length; i++) {
        var parts = listbox.options[i].value.split(". ");
        var text = (parts.length > 1) ? parts.slice(1).join(". ") : listbox.options[i].value;
        listbox.options[i].text = (i + 1) + ". " + text;
      }
    }
    function addMedication() {
      var combo = document.getElementById("medication_combobox");
      var listbox = document.getElementById("medications_listbox");
      var value = combo.value.trim();
      if (value !== "") {
        var option = document.createElement("option");
        option.text = window.medicationCount + ". " + value;
        option.value = value;
        listbox.add(option);
        window.medicationCount++;
        combo.value = "";
      }
    }
    function removeMedication() {
      var listbox = document.getElementById("medications_listbox");
      for (var i = listbox.options.length - 1; i >= 0; i--) { if (listbox.options[i].selected) { listbox.remove(i); } }
      updateListNumbers("medications_listbox");
      window.medicationCount = listbox.options.length + 1;
    }
    function addAnalysis() {
      var combo = document.getElementById("analysis_combobox");
      var listbox = document.getElementById("analyses_listbox");
      var value = combo.value.trim();
      if (value !== "") {
        var option = document.createElement("option");
        option.text = window.analysisCount + ". " + value;
        option.value = value;
        listbox.add(option);
        window.analysisCount++;
        combo.value = "";
      }
    }
    function removeAnalysis() {
      var listbox = document.getElementById("analyses_listbox");
      for (var i = listbox.options.length - 1; i >= 0; i--) { if (listbox.options[i].selected) { listbox.remove(i); } }
      updateListNumbers("analyses_listbox");
      window.analysisCount = listbox.options.length + 1;
    }
    function addRadiology() {
      var combo = document.getElementById("radiology_combobox");
      var listbox = document.getElementById("radiologies_listbox");
      var value = combo.value.trim();
      if (value !== "") {
        var option = document.createElement("option");
        option.text = window.radiologyCount + ". " + value;
        option.value = value;
        listbox.add(option);
        window.radiologyCount++;
        combo.value = "";
      }
    }
    function removeRadiology() {
      var listbox = document.getElementById("radiologies_listbox");
      for (var i = listbox.options.length - 1; i >= 0; i--) { if (listbox.options[i].selected) { listbox.remove(i); } }
      updateListNumbers("radiologies_listbox");
      window.radiologyCount = listbox.options.length + 1;
    }
    var patientData = {{ patient_data|tojson }};
    document.addEventListener("DOMContentLoaded", function(){
      document.getElementById("suivi_patient_id").addEventListener("change", function() {
         var id = this.value.trim();
         if(patientData[id]){
            document.getElementById("suivi_patient_name").value = patientData[id].name;
         } else {
            document.getElementById("suivi_patient_name").value = "";
         }
         $('#consultationsTable').DataTable().ajax.reload();
      });
    });
    document.addEventListener("DOMContentLoaded", function(){
      document.getElementById("patient_id").addEventListener("change", function() {
         var id = this.value.trim();
         console.log("Patient ID modifié:", id);
         if(patientData[id]){
            document.getElementById("patient_name").value = patientData[id].name;
            document.getElementById("patient_age").value = patientData[id].age;
            document.getElementById("patient_phone").value = patientData[id].phone;
            document.getElementById("antecedents").value = patientData[id].antecedents;
            document.getElementById("date_of_birth").value = patientData[id].date_of_birth;
            document.getElementById("gender").value = patientData[id].gender;
            document.getElementById("suivi_patient_id").value = id;
            document.getElementById("suivi_patient_name").value = patientData[id].name;
         } else { console.log("Aucune donnée trouvée pour cet ID:", id); }
         if(id){
              fetch("/get_last_consultation?patient_id=" + id)
              .then(response => response.json())
              .then(data => {
                  console.log("Données de la dernière consultation:", data);
                  if(Object.keys(data).length !== 0){
                        document.getElementById("clinical_signs").value = data.clinical_signs || "";
                        document.getElementById("bp").value = data.bp || "";
                        document.getElementById("temperature").value = data.temperature || "";
                        document.getElementById("heart_rate").value = data.heart_rate || "";
                        document.getElementById("respiratory_rate").value = data.respiratory_rate || "";
                        document.getElementById("diagnosis").value = data.diagnosis || "";
                        var medications_listbox = document.getElementById("medications_listbox");
                        medications_listbox.innerHTML = "";
                        if(data.medications){
                             data.medications.split("; ").forEach((item, index)=>{
                                  var option = document.createElement("option");
                                  option.text = (index+1) + ". " + item;
                                  option.value = item;
                                  medications_listbox.add(option);
                             });
                        }
                        var analyses_listbox = document.getElementById("analyses_listbox");
                        analyses_listbox.innerHTML = "";
                        if(data.analyses){
                             data.analyses.split("; ").forEach((item, index)=>{
                                  var option = document.createElement("option");
                                  option.text = (index+1) + ". " + item;
                                  option.value = item;
                                  analyses_listbox.add(option);
                             });
                        }
                        var radiologies_listbox = document.getElementById("radiologies_listbox");
                        radiologies_listbox.innerHTML = "";
                        if(data.radiologies){
                             data.radiologies.split("; ").forEach((item, index)=>{
                                  var option = document.createElement("option");
                                  option.text = (index+1) + ". " + item;
                                  option.value = item;
                                  radiologies_listbox.add(option);
                             });
                        }
                        document.getElementById("certificate_category").value = data.certificate_category || "";
                        document.getElementById("certificate_content").value = data.certificate_content || "";
                  }
              })
              .catch(error => { console.error("Erreur lors de la récupération de la dernière consultation :", error); });
         }
      });
    });
    document.addEventListener("DOMContentLoaded", function(){
      document.getElementById("date_of_birth").addEventListener("change", function() {
        var dob = this.value;
        if (dob) {
          var birthDate = new Date(dob);
          var today = new Date();
          var ageYears = today.getFullYear() - birthDate.getFullYear();
          var m = today.getMonth() - birthDate.getMonth();
          if (m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) {
            ageYears--;
          }
          var ageMonths = today.getMonth() - birthDate.getMonth();
          if (today.getDate() < birthDate.getDate()) {
            ageMonths--;
          }
          ageMonths = (ageMonths + 12) % 12;
          var ageString = ageYears > 0 ? ageYears + " ans " + ageMonths + " mois" : ageMonths + " mois";
          document.getElementById("patient_age").value = ageString;
        }
      });
    });
    function filterConsultations() {
      var id = document.getElementById("suivi_patient_id").value.trim();
      var name = document.getElementById("suivi_patient_name").value.trim();
      var params = new URLSearchParams(window.location.search);
      if (id) { params.set("patient_id_filter", id); }
      if (name) { params.set("patient_name_filter", name); }
      document.getElementById("historyPdfBtn").href = "{{ url_for('generate_history_pdf') }}?" + params.toString();
      window.location.href = "?" + params.toString();
    }
    function generateHistoryPDF() {
       var id = document.getElementById("suivi_patient_id").value.trim();
       var name = document.getElementById("suivi_patient_name").value.trim();
       if (!id && !name) {
           Swal.fire({
               icon: 'warning',
               title: 'Attention',
               text: "Veuillez renseigner l'ID ou le nom du patient."
           });
           return;
       }
       var params = new URLSearchParams();
       if (id) { params.set("patient_id_filter", id); }
       if (name) { params.set("patient_name_filter", name); }
       var url = "{{ url_for('generate_history_pdf') }}" + "?" + params.toString();
       window.open(url, "_blank");
    }
    function generatePDF() {
      const doctor_name = document.getElementById("doctor_name").value;
      const patient_name = document.getElementById("patient_name").value;
      const patient_age = document.getElementById("patient_age").value;
      const date_of_birth = document.getElementById("date_of_birth").value;
      const gender = document.getElementById("gender").value;
      const location = document.getElementById("location").value;
      const clinical_signs = document.getElementById("clinical_signs").value;
      const bp = document.getElementById("bp").value;
      const temperature = document.getElementById("temperature").value;
      const heart_rate = document.getElementById("heart_rate").value;
      const respiratory_rate = document.getElementById("respiratory_rate").value;
      const diagnosis = document.getElementById("diagnosis").value;
      const certificate_content = document.getElementById("certificate_content").value;
      const include_certificate = document.getElementById("include_certificate").checked ? "on" : "off";
      
      let medications = [];
      const medications_listbox = document.getElementById("medications_listbox");
      for (let option of medications_listbox.options) { medications.push(option.value); }
      let analyses = [];
      const analyses_listbox = document.getElementById("analyses_listbox");
      for (let option of analyses_listbox.options) { analyses.push(option.value); }
      let radiologies = [];
      const radiologies_listbox = document.getElementById("radiologies_listbox");
      for (let option of radiologies_listbox.options) { radiologies.push(option.value); }
      
      const params = new URLSearchParams();
      params.set("doctor_name", doctor_name);
      params.set("patient_name", patient_name);
      params.set("patient_age", patient_age);
      params.set("date_of_birth", date_of_birth);
      params.set("gender", gender);
      params.set("location", location);
      params.set("clinical_signs", clinical_signs);
      params.set("bp", bp);
      params.set("temperature", temperature);
      params.set("heart_rate", heart_rate);
      params.set("respiratory_rate", respiratory_rate);
      params.set("diagnosis", diagnosis);
      params.set("certificate_content", certificate_content);
      params.set("include_certificate", include_certificate);
      params.set("medications_list", medications.join("\\n"));
      params.set("analyses_list", analyses.join("\\n"));
      params.set("radiologies_list", radiologies.join("\\n"));
      
      const url = "{{ url_for('generate_pdf_route') }}" + "?" + params.toString();
      window.open(url, "_blank");
    }
    $(document).ready(function(){
      var table = $('#consultationsTable').DataTable({
         ajax: {
           url: "/get_consultations",
           data: function(d) {
             d.patient_id = $('#suivi_patient_id').val();
           },
           dataSrc: ''
         },
         columns: [
           { data: "consultation_date" },
           { data: "patient_id" },
           { data: "patient_name" },
           { data: "date_of_birth" },
           { data: "gender" },
           { data: "age" },
           { data: "patient_phone" },
           { data: "antecedents" },
           { data: "clinical_signs" },
           { data: "bp" },
           { data: "temperature" },
           { data: "heart_rate" },
           { data: "respiratory_rate" },
           { data: "diagnosis" },
           { data: "medications" },
           { data: "analyses" },
           { data: "radiologies" },
           { data: "certificate_category" },
           { data: "certificate_content" },
           { data: "rest_duration" },
           { data: "doctor_comment" },
           { 
             data: "consultation_id",
             render: function(data, type, row, meta) {
                return '<button class="btn btn-sm btn-danger delete-btn" data-id="'+data+'">Supprimer</button>';
             }
           }
         ]
      });
      $('#consultationsTable tbody').on('click', '.delete-btn', function(e){
         e.preventDefault();
         var consultationId = $(this).data('id');
         if(confirm("Voulez-vous vraiment supprimer cette consultation ?")){
           $.ajax({
             url: '/delete_consultation',
             method: 'POST',
             data: { consultation_id: consultationId },
             success: function(response){
                table.ajax.reload();
             },
             error: function(err){
                alert("Erreur lors de la suppression");
             }
           });
         }
      });
      $('#refreshTableBtn').click(function(){
         table.ajax.reload();
      });
    });
  </script>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</head>
<body class="min-h-screen flex flex-col">
<nav class="navbar navbar-dark fixed-top" style="background-color: #000080;">
  <div class="container-fluid d-flex align-items-center">
    <button class="navbar-toggler" style="transform: scale(0.75);" type="button" data-bs-toggle="offcanvas" data-bs-target="#settingsOffcanvas" aria-controls="settingsOffcanvas">
      <span class="navbar-toggler-icon"></span>
    </button>
    <a class="navbar-brand ms-auto" href="#" style="font-family: 'Great Vibes', cursive; font-size: 2rem;">
      MedicSastouka
    </a>
  </div>
</nav>
<div class="offcanvas offcanvas-start" tabindex="-1" id="settingsOffcanvas" aria-labelledby="settingsOffcanvasLabel">
  <div class="offcanvas-header bg-dark text-white">
    <h5 id="settingsOffcanvasLabel">Paramètres de l'application</h5>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="offcanvas" aria-label="Fermer"></button>
  </div>
  <div class="offcanvas-body">
    <a href="{{ url_for('activation') }}" class="btn btn-outline-primary w-100 mb-2">Activation</a>
    <form action="{{ url_for('settings') }}" method="POST">
      <div class="mb-3">
        <label for="nom_clinique" class="form-label">Nom Clinique / Cabinet :</label>
        <input type="text" class="form-control" name="nom_clinique" id="nom_clinique" value="{{ request.form.get('nom_clinique', config.nom_clinique if config.nom_clinique is defined else '') }}">
      </div>
      <div class="mb-3">
        <label for="centre_medecin" class="form-label">Centre Médical :</label>
        <input type="text" class="form-control" name="centre_medecin" id="centre_medecin" value="{{ request.form.get('centre_medecin', config.centre_medical if config.centre_medical is defined else '') }}">
      </div>
      <div class="mb-3">
        <label for="nom_medecin" class="form-label">Nom du Médecin :</label>
        <input type="text" class="form-control" name="nom_medecin" id="nom_medecin" value="{{ request.form.get('nom_medecin', config.doctor_name if config.doctor_name is defined else '') }}">
      </div>
      <div class="mb-3">
        <label for="lieu" class="form-label">Lieu :</label>
        <input type="text" class="form-control" name="lieu" id="lieu" value="{{ request.form.get('lieu', config.location if config.location is defined else '') }}">
      </div>
      <div class="mb-3">
        <label for="theme" class="form-label">Thème :</label>
        <select class="form-select" name="theme" id="theme">
          <option value="Default" {% if config.theme == 'Default' %}selected{% endif %}>Default</option>
          <option value="Dark" {% if config.theme == 'Dark' %}selected{% endif %}>Dark</option>
          <option value="Blue" {% if config.theme == 'Blue' %}selected{% endif %}>Blue</option>
        </select>
      </div>
      <div class="mb-3">
        <label for="arriere_plan" class="form-label">Arrière-plan (URL ou chemin) :</label>
        <input type="text" class="form-control" name="arriere_plan" id="arriere_plan" value="{{ request.form.get('arriere_plan', config.background_file_path if config.background_file_path is defined else '') }}">
      </div>
      <!-- Nouveau champ pour le chemin de stockage personnalisé -->
      <div class="mb-3">
        <label for="storage_path" class="form-label">Chemin de stockage personnalisé :</label>
        <input type="text" class="form-control" name="storage_path" id="storage_path" placeholder="Ex: D:\MesDocs\MedicSastouka" value="{{ config.storage_path if config.storage_path is defined else '' }}">
      </div>
      <div class="mb-3">
        <label for="liste_medicaments" class="form-label">Liste des Médicaments :</label>
        <textarea class="form-control" name="liste_medicaments" id="liste_medicaments" rows="5">{% if config.medications_options is defined %}{{ config.medications_options | join('\n') }}{% endif %}</textarea>
      </div>
      <div class="mb-3">
        <label for="liste_analyses" class="form-label">Liste des Analyses :</label>
        <textarea class="form-control" name="liste_analyses" id="liste_analyses" rows="5">{% if config.analyses_options is defined %}{{ config.analyses_options | join('\n') }}{% endif %}</textarea>
      </div>
      <div class="mb-3">
        <label for="liste_radiologies" class="form-label">Liste des Radiologies :</label>
        <textarea class="form-control" name="liste_radiologies" id="liste_radiologies" rows="5">{% if config.radiologies_options is defined %}{{ config.radiologies_options | join('\n') }}{% endif %}</textarea>
      </div>
      <button type="submit" class="btn btn-success w-100">Enregistrer Paramètres</button>
    </form>
  </div>
</div>
<div class="container my-4">
  <div class="card shadow-lg">
<div class="card-header bg-gradient-to-r from-indigo-600 to-blue-500 text-white text-center">
  <h1 class="font-bold">{{ config.nom_clinique or config.cabinet or 'MedicSastouka' }}</h1>
  <h2 class="font-bold">{{ config.doctor_name or 'Nom du Médecin' }} - {{ config.location or 'Lieu' }}</h2>
  <p class="font-bold">Date : {{ current_date }}</p>
</div>
    <div class="card-body">
      <form method="POST" enctype="multipart/form-data" id="mainForm">
        <ul class="nav nav-tabs" id="myTab" role="tablist">
          <li class="nav-item" role="presentation">
            <button class="nav-link active" id="basic-info-tab" data-bs-toggle="tab" data-bs-target="#basic-info" type="button" role="tab">Informations de Base</button>
          </li>
          <li class="nav-item" role="presentation">
            <button class="nav-link" id="consultation-tab" data-bs-toggle="tab" data-bs-target="#consultation" type="button" role="tab">Consultation</button>
          </li>
          <li class="nav-item" role="presentation">
            <button class="nav-link" id="medicaments-tab" data-bs-toggle="tab" data-bs-target="#medicaments" type="button" role="tab">Médicaments</button>
          </li>
          <li class="nav-item" role="presentation">
            <button class="nav-link" id="biologie-tab" data-bs-toggle="tab" data-bs-target="#biologie" type="button" role="tab">Biologie</button>
          </li>
          <li class="nav-item" role="presentation">
            <button class="nav-link" id="radiologies-tab" data-bs-toggle="tab" data-bs-target="#radiologies" type="button" role="tab">Radiologies</button>
          </li>
          <li class="nav-item" role="presentation">
            <button class="nav-link" id="certificat-tab" data-bs-toggle="tab" data-bs-target="#certificat" type="button" role="tab">Certificat Médical</button>
          </li>
          <li class="nav-item" role="presentation">
            <button class="nav-link" id="suivi-tab" data-bs-toggle="tab" data-bs-target="#suivi" type="button" role="tab">Suivi patient</button>
          </li>
        </ul>
        <div class="tab-content py-3">
          <!-- Onglet Informations de Base -->
          <div class="tab-pane fade show active" id="basic-info" role="tabpanel">
            <div class="mb-3 row">
              <label for="doctor_name" class="col-sm-3 col-form-label">Nom du Médecin :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" name="doctor_name" id="doctor_name" value="{{ request.form.get('doctor_name', config.doctor_name if config.doctor_name is defined else '') }}">
              </div>
            </div>
            <div class="mb-3 row">
              <label for="location" class="col-sm-3 col-form-label">Lieu :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" name="location" id="location" value="{{ request.form.get('location', config.location if config.location is defined else '') }}">
              </div>
            </div>
            <div class="mb-3 row">
              <label for="patient_id" class="col-sm-3 col-form-label">ID du Patient :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" name="patient_id" id="patient_id" list="patient_ids" value="{{ request.form.get('patient_id', request.args.get('patient_id_filter', '')) }}">
                <datalist id="patient_ids">
                  {% for pid in patient_ids %}
                  <option value="{{ pid }}"></option>
                  {% endfor %}
                </datalist>
              </div>
            </div>
            <div class="mb-3 row">
              <label for="patient_name" class="col-sm-3 col-form-label">Nom du Patient :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" name="patient_name" id="patient_name" list="patient_names" value="{{ request.form.get('patient_name', '') }}">
                <datalist id="patient_names">
                  {% for pname in patient_names %}
                  <option value="{{ pname }}"></option>
                  {% endfor %}
                </datalist>
              </div>
            </div>
            <div class="mb-3 row">
              <label for="date_of_birth" class="col-sm-3 col-form-label">Date de Naissance :</label>
              <div class="col-sm-9">
                <input type="date" class="form-control" name="date_of_birth" id="date_of_birth" value="{{ request.form.get('date_of_birth', '') }}">
              </div>
            </div>
            <div class="mb-3 row">
              <label for="gender" class="col-sm-3 col-form-label">Sexe :</label>
              <div class="col-sm-9">
                <select class="form-select" name="gender" id="gender">
                  <option value="Masculin" {% if request.form.get('gender','') == 'Masculin' %}selected{% endif %}>Masculin</option>
                  <option value="Féminin" {% if request.form.get('gender','') == 'Féminin' %}selected{% endif %}>Féminin</option>
                  <option value="Autre" {% if request.form.get('gender','') == 'Autre' %}selected{% endif %}>Autre</option>
                </select>
              </div>
            </div>
            <div class="mb-3 row">
              <label for="patient_age" class="col-sm-3 col-form-label">Âge du Patient :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" name="patient_age" id="patient_age" value="{{ request.form.get('patient_age', '') }}">
              </div>
            </div>
            <div class="mb-3 row">
              <label for="antecedents" class="col-sm-3 col-form-label">Antécédents :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" name="antecedents" id="antecedents" value="{{ request.form.get('antecedents', '') }}">
              </div>
            </div>
            <div class="mb-3 row">
              <label for="patient_phone" class="col-sm-3 col-form-label">Téléphone :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" name="patient_phone" id="patient_phone" value="{{ request.form.get('patient_phone', '') }}">
              </div>
            </div>
          </div>
          <!-- Onglet Consultation -->
          <div class="tab-pane fade" id="consultation" role="tabpanel">
            <div class="mb-3">
              <label for="clinical_signs" class="form-label">Signes Cliniques / Motifs de Consultation :</label>
              <textarea class="form-control" name="clinical_signs" id="clinical_signs" rows="2">{{ request.form.get('clinical_signs', '') }}</textarea>
            </div>
            <div class="row mb-3">
              <div class="col-sm-6">
                <label for="bp" class="form-label">Tension Artérielle (mmHg) :</label>
                <input type="text" class="form-control" name="bp" id="bp" value="{{ request.form.get('bp', '') }}">
              </div>
              <div class="col-sm-6">
                <label for="temperature" class="form-label">Température (°C) :</label>
                <input type="text" class="form-control" name="temperature" id="temperature" value="{{ request.form.get('temperature', '') }}">
              </div>
            </div>
            <div class="row mb-3">
              <div class="col-sm-6">
                <label for="heart_rate" class="form-label">Fréquence Cardiaque (bpm) :</label>
                <input type="text" class="form-control" name="heart_rate" id="heart_rate" value="{{ request.form.get('heart_rate', '') }}">
              </div>
              <div class="col-sm-6">
                <label for="respiratory_rate" class="form-label">Fréquence Respiratoire (rpm) :</label>
                <input type="text" class="form-control" name="respiratory_rate" id="respiratory_rate" value="{{ request.form.get('respiratory_rate', '') }}">
              </div>
            </div>
            <div class="mb-3">
              <label for="diagnosis" class="form-label">Diagnostic :</label>
              <input type="text" class="form-control" name="diagnosis" id="diagnosis" value="{{ request.form.get('diagnosis', '') }}">
            </div>
            <div class="mb-3">
              <label for="doctor_comment" class="form-label">Commentaire du Médecin :</label>
              <textarea class="form-control" name="doctor_comment" id="doctor_comment" rows="3">{{ request.form.get('doctor_comment', '') }}</textarea>
            </div>
          </div>
          <!-- Onglet Médicaments -->
          <div class="tab-pane fade" id="medicaments" role="tabpanel">
            <div class="mb-3">
              <label for="medication_combobox" class="form-label">Médicament :</label>
              <input type="text" class="form-control" id="medication_combobox" placeholder="Sélectionnez un médicament" list="medications_options_list">
              <datalist id="medications_options_list">
                {% for m in medications_options %}
                <option value="{{ m }}"></option>
                {% endfor %}
              </datalist>
              <div class="mt-2">
                <button type="button" class="btn btn-primary" onclick="addMedication()">Ajouter</button>
                <button type="button" class="btn btn-secondary" onclick="removeMedication()">Supprimer</button>
              </div>
              <select id="medications_listbox" name="medications_list" multiple class="form-select mt-2" size="5">
                {% if saved_medications %}
                  {% for med in saved_medications %}
                    <option selected value="{{ med }}">{{ loop.index }}. {{ med }}</option>
                  {% endfor %}
                {% endif %}
              </select>
            </div>
          </div>
          <!-- Onglet Biologie -->
          <div class="tab-pane fade" id="biologie" role="tabpanel">
            <div class="mb-3">
              <label for="analysis_combobox" class="form-label">Analyse :</label>
              <input type="text" class="form-control" id="analysis_combobox" placeholder="Sélectionnez une analyse" list="analyses_options_list">
              <datalist id="analyses_options_list">
                {% for a in analyses_options %}
                <option value="{{ a }}"></option>
                {% endfor %}
              </datalist>
              <div class="mt-2">
                <button type="button" class="btn btn-primary" onclick="addAnalysis()">Ajouter</button>
                <button type="button" class="btn btn-secondary" onclick="removeAnalysis()">Supprimer</button>
              </div>
              <select id="analyses_listbox" name="analyses_list" multiple class="form-select mt-2" size="5">
                {% if saved_analyses %}
                  {% for a in saved_analyses %}
                    <option selected value="{{ a }}">{{ loop.index }}. {{ a }}</option>
                  {% endfor %}
                {% endif %}
              </select>
            </div>
          </div>
          <!-- Onglet Radiologies -->
          <div class="tab-pane fade" id="radiologies" role="tabpanel">
            <div class="mb-3">
              <label for="radiology_combobox" class="form-label">Radiologie :</label>
              <input type="text" class="form-control" id="radiology_combobox" placeholder="Sélectionnez une radiologie" list="radiologies_options_list">
              <datalist id="radiologies_options_list">
                {% for r in radiologies_options %}
                <option value="{{ r }}"></option>
                {% endfor %}
              </datalist>
              <div class="mt-2">
                <button type="button" class="btn btn-primary" onclick="addRadiology()">Ajouter</button>
                <button type="button" class="btn btn-secondary" onclick="removeRadiology()">Supprimer</button>
              </div>
              <select id="radiologies_listbox" name="radiologies_list" multiple class="form-select mt-2" size="5">
                {% if saved_radiologies %}
                  {% for r in saved_radiologies %}
                    <option selected value="{{ r }}">{{ loop.index }}. {{ r }}</option>
                  {% endfor %}
                {% endif %}
              </select>
            </div>
          </div>
          <!-- Onglet Certificat Médical -->
          <div class="tab-pane fade" id="certificat" role="tabpanel">
            <div class="mb-3">
              <label for="certificate_category" class="form-label">Catégorie du Certificat :</label>
              <select class="form-select" name="certificate_category" id="certificate_category">
                <option value="">-- Sélectionnez --</option>
                {% for key in certificate_categories.keys() %}
                <option value="{{ key }}" {% if request.form.get('certificate_category','') == key %}selected{% endif %}>{{ key }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="mb-3">
              <label for="certificate_content" class="form-label">Contenu du Certificat :</label>
              <textarea class="form-control" name="certificate_content" id="certificate_content" rows="5">{{ request.form.get('certificate_content', default_certificate_text) }}</textarea>
            </div>
            <div class="form-check">
              <input class="form-check-input" type="checkbox" name="include_certificate" id="include_certificate" {% if request.form.get('include_certificate','')=='on' %}checked{% endif %}>
              <label class="form-check-label" for="include_certificate">Inclure le certificat médical</label>
            </div>
          </div>
          <!-- Onglet Suivi patient -->
          <div class="tab-pane fade" id="suivi" role="tabpanel">
            <div class="mb-3 row">
              <label for="suivi_patient_id" class="col-sm-3 col-form-label">ID du Patient :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" id="suivi_patient_id" name="suivi_patient_id" list="patient_ids" value="{{ request.args.get('patient_id_filter', '') }}">
                <datalist id="patient_ids">
                  {% for pid in patient_ids %}
                  <option value="{{ pid }}"></option>
                  {% endfor %}
                </datalist>
              </div>
            </div>
            <div class="mb-3 row">
              <label for="suivi_patient_name" class="col-sm-3 col-form-label">Nom du Patient :</label>
              <div class="col-sm-9">
                <input type="text" class="form-control" id="suivi_patient_name" name="suivi_patient_name" list="patient_names" value="{{ request.args.get('patient_name_filter', '') }}">
                <datalist id="patient_names">
                  {% for pname in patient_names %}
                  <option value="{{ pname }}"></option>
                  {% endfor %}
                </datalist>
              </div>
            </div>
            <div class="table-responsive">
              <table id="consultationsTable" class="table table-striped">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>ID Patient</th>
                    <th>Nom du Patient</th>
                    <th>Date de Naissance</th>
                    <th>Sexe</th>
                    <th>Âge</th>
                    <th>Téléphone</th>
                    <th>Antécédents</th>
                    <th>Consultation</th>
                    <th>Tension</th>
                    <th>Température</th>
                    <th>FC</th>
                    <th>FR</th>
                    <th>Diagnostic</th>
                    <th>Médicaments</th>
                    <th>Analyses</th>
                    <th>Radiologies</th>
                    <th>Catégorie Certificat</th>
                    <th>Contenu Certificat</th>
                    <th>Durée Repos</th>
                    <th>Commentaire</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                </tbody>
              </table>
            </div>
            <div class="mb-3 d-flex flex-wrap justify-content-around gap-2">
              <button type="button" id="refreshTableBtn" class="btn btn-outline-secondary">Rafraîchir</button>
              <button type="button" class="btn btn-outline-success" onclick="generateHistoryPDF()">Afficher PDF Historique</button>
            </div>
          </div>
        </div>
        <div class="d-flex flex-wrap justify-content-around gap-2 mt-4">
          <button type="submit" class="btn btn-success">Enregistrer Consultation</button>
          <button type="button" class="btn btn-primary" onclick="generatePDF()">Générer PDF</button>
          <button type="reset" class="btn btn-danger">Réinitialiser</button>
          <button type="button" class="btn btn-primary" onclick="generatePDF()">Afficher PDF</button>
          <button type="button" class="btn btn-success" data-bs-toggle="modal" data-bs-target="#importExcelModal">
  Importer Listes Prédefinies
</button>
          <button type="button" class="btn btn-warning" data-bs-toggle="modal" data-bs-target="#importBackgroundModal">
  Importer Arrière‑plan
</button>
        </div>
      </form>
    </div>
<div class="card-footer text-center footer" style="color: #343a40;">
  SASTOUKA DIGITAL © 2025 sastoukadigital@gmail.com • Whatsapp +212652084735<br>
  Accès via réseau local : <span>{{ host_address }}</span>
  <div class="d-flex justify-content-center gap-2 mt-2">
    <a href="{{ url_for('download_app') }}" class="btn" style="background-color: #001f3f; color: #fff;">
      Télécharger MedicSastouka (Win)
    </a>
  </div>
</div>
  </div>
</div>
<!-- Modal Import Excel -->
<div class="modal fade" id="importExcelModal" tabindex="-1" aria-labelledby="importExcelModalLabel" aria-hidden="true">
  <div class="modal-dialog">
    <form id="importExcelForm" onsubmit="return ajaxFileUpload('importExcelForm','/import_excel')" class="modal-content">
      <div class="modal-header bg-warning text-dark">
        <h5 class="modal-title" id="importExcelModalLabel">Importer Listes Prédefinies (Excel)</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fermer"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label for="excel_file" class="form-label">Sélectionnez le fichier Excel :</label>
          <input type="file" class="form-control" name="excel_file" id="excel_file" required>
        </div>
      </div>
      <div class="modal-footer">
        <button type="submit" class="btn btn-warning">Importer</button>
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
      </div>
    </form>
  </div>
</div>
<!-- Modal Import Arrière‑plan -->
<div class="modal fade" id="importBackgroundModal" tabindex="-1" aria-labelledby="importBackgroundModalLabel" aria-hidden="true">
  <div class="modal-dialog">
    <form id="importBackgroundForm" onsubmit="return ajaxFileUpload('importBackgroundForm','/import_background')" class="modal-content">
      <div class="modal-header bg-danger text-white">
        <h5 class="modal-title" id="importBackgroundModalLabel">Importer Arrière‑plan (Image/PDF)</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fermer"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label for="background_file" class="form-label">Sélectionnez le fichier :</label>
          <input type="file" class="form-control" name="background_file" id="background_file" required>
        </div>
      </div>
      <div class="modal-footer">
        <button type="submit" class="btn btn-danger">Importer</button>
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
      </div>
    </form>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
  $('#importBackgroundModal').on('hidden.bs.modal', function () {
      $('body').css('overflow', 'auto');
  });
</script>
<script>
  $('#importExcelModal').on('hidden.bs.modal', function () {
    $('body').removeClass('modal-open').css('overflow', 'auto');
  });
</script>
</body>
</html>
"""

alert_template = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Alerte</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
</head>
<body>
<script>
  Swal.fire({
    icon: '{{ alert_type }}',
    title: '{{ alert_title }}',
    html: '{{ alert_text }} {% if extra_info %} <br><br> {{ extra_info }} {% endif %}',
    timer: 3000,
    timerProgressBar: true,
    didClose: () => { window.location.href = "{{ redirect_url }}"; }
  });
</script>
</body>
</html>
"""

admin_template = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Générateur de Clés d'Activation</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
</head>
<body class="bg-gray-100">
<div class="container my-5">
  <h2 class="text-center font-bold text-2xl">Générateur de Clés d'Activation</h2>
  <form method="POST">
    <div class="mb-3">
      <label class="form-label">ID Unique de l'utilisateur:</label>
      <input type="text" class="form-control" name="hardware_id" value="{{ hardware_id }}" readonly>
    </div>
    <div class="mb-3">
      <label class="form-label">Sélectionnez le Plan:</label>
      <select class="form-select" name="plan">
        <option value="Illimité">Illimité</option>
      </select>
    </div>
    <button type="submit" class="btn btn-primary">Générer Clé</button>
  </form>
  {% if activation_key %}
  <div class="alert alert-success mt-3">
    Clé d'Activation Générée: <strong>{{ activation_key }}</strong>
  </div>
  {% endif %}
  <a href="{{ url_for('index') }}" class="btn btn-secondary mt-3">Retour</a>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

settings_template = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Paramètres de l'application</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-light">
<div class="container my-5">
  <h2 class="text-center">Paramètres de l'application</h2>
  <form action="{{ url_for('settings') }}" method="POST">
    <div class="mb-3">
      <label for="nom_clinique" class="form-label">Nom Clinique / Cabinet :</label>
      <input type="text" class="form-control" name="nom_clinique" id="nom_clinique" value="{{ config.nom_clinique or '' }}">
    </div>
    <div class="mb-3">
      <label for="centre_medecin" class="form-label">Centre Médical :</label>
      <input type="text" class="form-control" name="centre_medecin" id="centre_medecin" value="{{ config.centre_medical or '' }}">
    </div>
    <div class="mb-3">
      <label for="nom_medecin" class="form-label">Nom du Médecin :</label>
      <input type="text" class="form-control" name="nom_medecin" id="nom_medecin" value="{{ config.doctor_name or '' }}">
    </div>
    <div class="mb-3">
      <label for="lieu" class="form-label">Lieu :</label>
      <input type="text" class="form-control" name="lieu" id="lieu" value="{{ config.location or '' }}">
    </div>
    <div class="mb-3">
      <label for="theme" class="form-label">Thème :</label>
      <select class="form-select" name="theme" id="theme">
        <option value="Default" {% if config.theme == 'Default' %}selected{% endif %}>Default</option>
        <option value="Dark" {% if config.theme == 'Dark' %}selected{% endif %}>Dark</option>
        <option value="Blue" {% if config.theme == 'Blue' %}selected{% endif %}>Blue</option>
      </select>
    </div>
    <div class="mb-3">
      <label for="arriere_plan" class="form-label">Arrière-plan (URL ou chemin) :</label>
      <input type="text" class="form-control" name="arriere_plan" id="arriere_plan" value="{{ config.background_file_path or '' }}">
    </div>
    <div class="mb-3">
      <label for="liste_medicaments" class="form-label">Liste des Médicaments :</label>
      <textarea class="form-control" name="liste_medicaments" id="liste_medicaments" rows="5">{% if config.medications_options %}{{ config.medications_options | join('\n') }}{% endif %}</textarea>
    </div>
    <div class="mb-3">
      <label for="liste_analyses" class="form-label">Liste des Analyses :</label>
      <textarea class="form-control" name="liste_analyses" id="liste_analyses" rows="5">{% if config.analyses_options %}{{ config.analyses_options | join('\n') }}{% endif %}</textarea>
    </div>
    <div class="mb-3">
      <label for="liste_radiologies" class="form-label">Liste des Radiologies :</label>
      <textarea class="form-control" name="liste_radiologies" id="liste_radiologies" rows="5">{% if config.radiologies_options %}{{ config.radiologies_options | join('\n') }}{% endif %}</textarea>
    </div>
    <button type="submit" class="btn btn-success w-100">Enregistrer Paramètres</button>
  </form>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
@app.route("/download_app")
def download_app():
    file_path = os.path.join(BASE_DIR, "MedicSastouka.rar")
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        flash("Le fichier n'existe pas.", "error")
        return redirect(url_for("index"))


if __name__ == "__main__":
    import webbrowser
    webbrowser.open("http://127.0.0.1:3000")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
