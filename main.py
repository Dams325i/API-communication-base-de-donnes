from fastapi import FastAPI, HTTPException, Body
import sqlite3
import os
import io
import json
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Autorise tous les appareils
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURATION ---
SCOPES = ['https://www.googleapis.com/auth/drive'] # Permission totale pour upload
FILE_ID = '1PmQ7Mud8HCGPgxXRngKLp4BcqpI4XhUM'
DB_PATH = "/tmp/temp_database.sqlite"

def get_drive_service():
    # Render place le "Secret File" à la racine du projet
    # On l'utilise donc directement comme sur ton ordinateur
    try:
        creds = service_account.Credentials.from_service_account_file(
            'credentials.json', 
            scopes=SCOPES
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Erreur de chargement des identifiants : {e}")
        return None

def download_db():
    service = get_drive_service()
    request = service.files().get_media(fileId=FILE_ID)
    fh = io.FileIO(DB_PATH, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    fh.close()

def upload_db():
    """Renvoie le fichier modifié sur Google Drive"""
    service = get_drive_service()
    media = MediaFileUpload(DB_PATH, mimetype='application/x-sqlite3', resumable=True)
    service.files().update(fileId=FILE_ID, media_body=media).execute()

# --- ROUTES DE LECTURE AVEC TRI ---

@app.get("/api/clients")
def get_clients():
    download_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Tri alphabétique sur le nom
    cursor.execute("SELECT * FROM Clients ORDER BY Nom_Prénom ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/api/factures")
def get_factures():
    download_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Tri décroissant sur l'ID (les plus récentes en premier)
    cursor.execute("SELECT * FROM Factures ORDER BY id_Facture DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/api/devis")
def get_devis():
    download_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Tri décroissant sur l'ID
    cursor.execute("SELECT * FROM Devis ORDER BY id_Devi DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# --- ROUTES D'ÉCRITURE CORRIGÉES ---

@app.patch("/api/{type_doc}/{id_doc}/statut")
def update_statut(type_doc: str, id_doc: int, data: dict = Body(...)):
    download_db()
    
    # On récupère la valeur et on force le nettoyage
    brut = data.get('statut') or data.get('Statut')
    nouveau_statut = str(brut).strip() # .strip() enlève les espaces invisibles autour
    
    print(f"--- DEBUG STATUT ---")
    print(f"Reçu: '{brut}'")
    print(f"Après nettoyage: '{nouveau_statut}'")
    
    table = "Factures" if type_doc == "factures" else "Devis"
    col_id = "id_Facture" if type_doc == "factures" else "id_Devi"
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # On fait l'update
        cursor.execute(f"UPDATE {table} SET Statut = ? WHERE {col_id} = ?", (nouveau_statut, id_doc))
        
        # Vérification immédiate : est-ce qu'une ligne a été modifiée ?
        if cursor.rowcount == 0:
            print(f"ATTENTION: Aucune ligne modifiée. L'ID {id_doc} existe-t-il ?")
            
        conn.commit()
        conn.close()
        upload_db()
        return {"status": "success", "modifie": nouveau_statut}
    except Exception as e:
        if conn: conn.close()
        print(f"ERREUR SQL: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/clients")
def add_client(client: dict = Body(...)):
    download_db()
    print(f"Données reçues pour nouveau client : {client}") # Pour debugger dans le terminal
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # On utilise des clés larges pour matcher avec Flutter
        nom = client.get('Nom_Prénom') or client.get('nom')
        adr = client.get('Adresse') or client.get('adresse')
        cp = client.get('CP') or client.get('cp')
        ville = client.get('Ville') or client.get('ville')
        mail = client.get('Mail') or client.get('email')
        tel1 = client.get('Tel1') or client.get('tel1')
        tel2 = client.get('Tel2') or client.get('tel2')

        query = "INSERT INTO Clients (Nom_Prénom, Adresse, CP, Ville, Mail, Tel1, Tel2) VALUES (?, ?, ?, ?, ?, ?, ?)"
        cursor.execute(query, (nom,  adr, cp, ville, mail, tel1, tel2))
        conn.commit()
        conn.close()
        upload_db()
        return {"status": "success"}
    except Exception as e:
        if conn: conn.close()
        print(f"Erreur lors de l'ajout client : {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.patch("/api/{type_doc}/{id_doc}/paiement")
def update_paiement(type_doc: str, id_doc: int, data: dict = Body(...)):
    download_db()
    table = "Factures" if type_doc == "factures" else "Devis"
    col_id = "id_Facture" if type_doc == "factures" else "id_Devi"
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # On met à jour le statut ET les infos de paiement
        # Vérifiez bien que ces colonnes (Date_Paiement, Type_Paiement, Num_Paiement) 
        # existent dans votre fichier Excel/SQLite
        query = f"""
            UPDATE {table} 
            SET Statut = ?, 
                Date_Paiement_total = ?, 
                Type_Paiement_total = ?, 
                Numéro_Paiement_total = ? 
            WHERE {col_id} = ?
        """
        cursor.execute(query, (
            data.get('statut'),
            data.get('date_paiement'),
            data.get('type_paiement'),
            data.get('numero_paiement'),
            id_doc
        ))
        
        conn.commit()
        conn.close()
        upload_db()
        return {"status": "success"}
    except Exception as e:
        if conn: conn.close()
        print(f"Erreur Paiement: {e}")

        raise HTTPException(status_code=500, detail=str(e))

