import os
import subprocess
import sys

def add_client(client_name):
    """Ajoute un nouveau client OpenVPN."""
    command = f"easyrsa build-client-full {client_name} nopass"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Client {client_name} ajouté avec succès.")
    else:
        print(f"Erreur lors de l'ajout du client {client_name}: {result.stderr}")

def revoke_client(client_name):
    """Révoque un client OpenVPN."""
    command = f"easyrsa revoke {client_name} && easyrsa gen-crl"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Client {client_name} révoqué avec succès.")
    else:
        print(f"Erreur lors de la révocation du client {client_name}: {result.stderr}")

def list_clients():
    """Liste les clients connectés à OpenVPN."""
    status_file = "/var/log/openvpn-status.log"
    if not os.path.exists(status_file):
        print("Le fichier de statut OpenVPN n'existe pas.")
        return
    
    with open(status_file, "r") as f:
        lines = f.readlines()
        print("Clients connectés:")
        for line in lines:
            if "," in line and "CLIENT_LIST" in line:
                client_info = line.split(",")
                print(f"- {client_info[1]} (IP: {client_info[2]}, Connexion: {client_info[4]})")

def delete_client(client_name):
    """Supprime les fichiers d'un client OpenVPN."""
    paths = [
        f"/etc/openvpn/easy-rsa/pki/private/{client_name}.key",
        f"/etc/openvpn/easy-rsa/pki/issued/{client_name}.crt",
        f"/etc/openvpn/easy-rsa/pki/reqs/{client_name}.req",
    ]
    
    for path in paths:
        if os.path.exists(path):
            os.remove(path)
            print(f"Fichier supprimé: {path}")
        else:
            print(f"Fichier introuvable: {path}")

def check_server_status():
    """Vérifie si le serveur OpenVPN est en cours d'exécution."""
    result = subprocess.run("systemctl is-active openvpn", shell=True, capture_output=True, text=True)
    if "active" in result.stdout:
        print("Le serveur OpenVPN est actif.")
    else:
        print("Le serveur OpenVPN est inactif ou en erreur.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python openvpn_manager.py <commande> [arguments]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "add" and len(sys.argv) == 3:
        add_client(sys.argv[2])
    elif command == "revoke" and len(sys.argv) == 3:
        revoke_client(sys.argv[2])
    elif command == "list":
        list_clients()
    elif command == "delete" and len(sys.argv) == 3:
        delete_client(sys.argv[2])
    elif command == "status":
        check_server_status()
    else:
        print("Commande invalide.")

