package main

import (
	"os"
	"strings"
	"testing"
)

// La validation du numéro est le garde-fou qui empêche de composer chez
// quelqu'un qui n'a rien demandé. Elle est testée sur les formes qu'un
// humain tape réellement, pas seulement sur la forme canonique.
func TestNuméroValide(t *testing.T) {
	bons := map[string]string{
		"5145550142":      "15145550142",
		"514-555-0142":    "15145550142",
		"(514) 555-0142":  "15145550142",
		"+1 514 555 0142": "15145550142",
		"1.514.555.0142":  "15145550142",
	}
	for brut, attendu := range bons {
		got, err := NuméroValide(brut)
		if err != nil {
			t.Errorf("%q refusé à tort : %v", brut, err)
			continue
		}
		if got != attendu {
			t.Errorf("%q → %q, attendu %q", brut, got, attendu)
		}
	}

	// Un indicatif commençant par 0 ou 1 n'existe pas dans le plan
	// nord-américain : les accepter enverrait l'appel dans le vide, ou pire,
	// vers un service spécial.
	mauvais := []string{"", "12345", "0145550142", "1145550142",
		"514555014", "51455501421", "abc", "911"}
	for _, brut := range mauvais {
		if got, err := NuméroValide(brut); err == nil {
			t.Errorf("%q accepté à tort → %q", brut, got)
		}
	}
}

func TestChargerConfigRefuseIncomplet(t *testing.T) {
	for _, v := range []string{"VOIP_TRUNK", "VOIP_USER", "VOIP_PASSWORD",
		"VOIP_FROM", "VOIP_BIND"} {
		t.Setenv(v, "")
	}
	// Échouer au démarrage et non au premier appel : découvrir un secret
	// manquant quand quelqu'un attend une annonce est la pire façon de
	// l'apprendre.
	if _, err := ChargerConfig(); err == nil {
		t.Fatal("configuration vide acceptée")
	}
}

func TestChargerConfigDéfauts(t *testing.T) {
	t.Setenv("VOIP_TRUNK", "sip.exemple.ca")
	t.Setenv("VOIP_USER", "123456")
	t.Setenv("VOIP_PASSWORD", "secret")
	t.Setenv("VOIP_FROM", "")
	t.Setenv("VOIP_BIND", "")
	c, err := ChargerConfig()
	if err != nil {
		t.Fatalf("configuration complète refusée : %v", err)
	}
	// Boucle locale par défaut : un service SIP qui écoute sur toutes les
	// interfaces est scanné en continu. Ouvrir doit rester un geste explicite.
	if c.Bind != "127.0.0.1:5080" {
		t.Errorf("liaison par défaut = %q, attendu la boucle locale", c.Bind)
	}
	if c.From != c.User {
		t.Errorf("From vide devrait reprendre User, got %q", c.From)
	}
}

func TestSecretsJamaisSurLaLigneDeCommande(t *testing.T) {
	// Le mot de passe vient de l'environnement et jamais d'un drapeau : la
	// ligne de commande est visible dans la liste des processus de toute la
	// machine, pendant toute la durée de l'appel.
	for _, arg := range os.Args {
		if arg == "-password" || arg == "--password" {
			t.Fatal("un drapeau de mot de passe a été introduit")
		}
	}
}

func TestCarteModemTrouvée(t *testing.T) {
	// Test dépendant du matériel : on l'ignore proprement plutôt que de le
	// faire échouer sur une machine sans modem.
	if _, err := os.Stat("/proc/asound/cards"); err != nil {
		t.Skip("pas de sous-système ALSA")
	}
	carte, err := CarteModem()
	if err != nil {
		t.Skip("aucun modem Quectel branché : " + err.Error())
	}
	// hw:<index>,0 et rien d'autre : aplay refuse toute autre forme.
	if !strings.HasPrefix(carte, "hw:") || !strings.HasSuffix(carte, ",0") {
		t.Errorf("carte %q n'est pas de la forme hw:N,0", carte)
	}
}

func TestPortDéfautEstUnLienStable(t *testing.T) {
	// Un lien et non /dev/ttyUSB3 : le numéro change au rebranchement, et
	// viser un numéro finit par parler au mauvais port — ou au GPS.
	if !strings.HasPrefix(PortDéfaut, "/dev/") {
		t.Fatalf("port par défaut inattendu : %q", PortDéfaut)
	}
	if strings.Contains(PortDéfaut, "ttyUSB") {
		t.Errorf("le port par défaut vise un numéro de tty : %q", PortDéfaut)
	}
}
