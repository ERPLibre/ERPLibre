// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

// erplibre_go_qemu_cache — miroir de téléchargement pour les VM QEMU locales.
//
// L'orchestrateur détourne le 80 et le 443 de ses VM vers cet outil, qui
// garde ce qui descend et sert la copie à la VM suivante. Deux VM de la même
// distribution ne tirent donc qu'une fois les mêmes paquets.
//
// Ce que l'outil NE fait pas, et qu'il faut savoir : il n'efface rien. Aucune
// éviction, aucun plafond de disque — « --status » dit ce qu'il occupe, la
// surveillance est manuelle et le cache vit sur le disque de l'orchestrateur.
package main

import (
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

const version = "0.1.0"

func main() {
	var (
		cacheDir = flag.String("cache-dir", "/var/cache/erplibre_go_qemu_cache",
			"répertoire des objets gardés")
		caDir = flag.String("ca-dir", "/var/lib/erplibre_go_qemu_cache",
			"répertoire de l'autorité de certification")
		httpPort = flag.Int("http-port", 8898, "écoute pour le 80 détourné")
		tlsPort  = flag.Int("tls-port", 8899, "écoute pour le 443 détourné")
		bridge   = flag.String("bridge", "virbr0", "pont libvirt des VM")
		subnet   = flag.String("subnet", "192.168.122.0/24", "sous-réseau des VM")
		logPath  = flag.String("access-log", "", "journal d'accès JSON par ligne")
		exclude  = flag.String("exclude", "",
			"hôtes à ne jamais déchiffrer, séparés par des virgules")
		verbose = flag.Bool("verbose", false, "dire chaque requête")
		status  = flag.Bool("status", false,
			"dire ce que le cache occupe, puis sortir")
		dryRun = flag.Bool("dry-run", false,
			"montrer les gestes privilégiés sans en faire un")
		initCA = flag.Bool("init-ca", false,
			"créer l'autorité si elle manque, puis sortir")
		printNft = flag.Bool("print-nft", false,
			"écrire les règles nft seules, à passer à « nft -f - »")
		printIptables = flag.Bool("print-iptables", false,
			"écrire les commandes iptables seules, une par ligne")
		showVersion = flag.Bool("version", false, "dire la version, puis sortir")
	)
	flag.Parse()

	if *showVersion {
		fmt.Printf("erplibre_go_qemu_cache %s\n", version)
		return
	}

	rules := RuleSet{
		Bridge: *bridge, Subnet: *subnet,
		HTTPPort: *httpPort, TLSPort: *tlsPort,
	}
	store := &Store{Dir: *cacheDir}

	// Les règles sortent d'ici et de nulle part ailleurs : le service les
	// pose en tubant cette sortie dans nft. Une seconde copie dans un script
	// d'installation dériverait de celle que les tests vérifient.
	if *printNft {
		for _, l := range rules.NftLines() {
			fmt.Println(l)
		}
		return
	}
	if *printIptables {
		for _, l := range rules.IptablesLines() {
			fmt.Println(l)
		}
		return
	}

	if *status {
		if err := printStatus(store, *caDir, rules); err != nil {
			fmt.Fprintf(os.Stderr, "état illisible : %v\n", err)
			os.Exit(1)
		}
		return
	}

	if *dryRun {
		printDryRun(store, *caDir, rules)
		return
	}

	if *initCA {
		ca, err := LoadOrCreateCA(*caDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "autorité : %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("autorité : %s\n", CertPath(*caDir))
		fmt.Printf("empreinte : %s\n", ca.Fingerprint())
		return
	}

	if err := serve(store, *caDir, rules, *logPath, *exclude, *verbose); err != nil {
		log.Fatalf("le cache s'arrête : %v", err)
	}
}

func serve(
	store *Store, caDir string, rules RuleSet,
	logPath, exclude string, verbose bool,
) error {
	if err := os.MkdirAll(store.Dir, 0o755); err != nil {
		return err
	}
	// Un objet à moitié écrit ne vaut rien et occupe : le démarrage est le
	// seul moment où un « .part » n'appartient à aucune écriture vivante.
	if n := store.SweepPartials(); n > 0 {
		log.Printf("%d écriture(s) interrompue(s) retirée(s)", n)
	}

	ca, err := LoadOrCreateCA(caDir)
	if err != nil {
		return err
	}
	alog, err := OpenAccessLog(logPath)
	if err != nil {
		return err
	}
	defer alog.Close()

	proxy := NewProxy(store, alog)
	proxy.Verbose = verbose

	refusals := NewRefusals(append(DefaultExclusions, splitList(exclude)...))
	front := &TLSFront{CA: ca, Proxy: proxy, Refusals: refusals}

	httpLn, err := net.Listen("tcp", fmt.Sprintf(":%d", rules.HTTPPort))
	if err != nil {
		return fmt.Errorf("écoute HTTP : %w", err)
	}
	tlsLn, err := net.Listen("tcp", fmt.Sprintf(":%d", rules.TLSPort))
	if err != nil {
		return fmt.Errorf("écoute TLS : %w", err)
	}

	log.Printf("cache : %s", store.Dir)
	log.Printf("autorité : %s (%s)", CertPath(caDir), ca.Fingerprint())
	log.Printf("écoutes : http %d, tls %d", rules.HTTPPort, rules.TLSPort)

	errc := make(chan error, 2)
	go func() {
		srv := &http.Server{
			Handler:           proxy.handler("http"),
			ReadHeaderTimeout: 30 * time.Second,
		}
		errc <- srv.Serve(httpLn)
	}()
	go func() { errc <- front.Serve(tlsLn) }()
	return <-errc
}

func printStatus(store *Store, caDir string, rules RuleSet) error {
	st, err := store.Stat()
	if err != nil {
		return err
	}
	fmt.Printf("répertoire  : %s\n", store.Dir)
	fmt.Printf("objets      : %d\n", st.Objects)
	fmt.Printf("occupation  : %s\n", HumanBytes(st.Bytes))
	if st.Oldest.IsZero() {
		fmt.Printf("plus ancien : aucun objet\n")
	} else {
		fmt.Printf("plus ancien : %s\n", st.Oldest.Format(time.RFC3339))
	}
	fmt.Printf("autorité    : %s\n", CertPath(caDir))
	if ca, err := LoadOrCreateCA(caDir); err == nil {
		fmt.Printf("empreinte   : %s\n", ca.Fingerprint())
	} else {
		fmt.Printf("empreinte   : autorité absente\n")
	}
	fmt.Printf("\nAucune éviction n'est écrite : ce cache ne diminue jamais\n")
	fmt.Printf("de lui-même, et il vit sur le disque de l'orchestrateur.\n")
	return nil
}

func printDryRun(store *Store, caDir string, rules RuleSet) {
	fmt.Printf("À blanc — rien n'est écrit, rien n'est posé.\n\n")
	fmt.Printf("Répertoire du cache, créé au démarrage :\n  %s\n\n", store.Dir)
	fmt.Printf("Autorité, créée si elle manque :\n  %s (clé en 0600)\n\n",
		CertPath(caDir))
	fmt.Printf("Règles nft à poser sur l'hôte :\n")
	for _, l := range rules.NftLines() {
		fmt.Printf("  %s\n", l)
	}
	fmt.Printf("\nÀ défaut de nft :\n")
	for _, l := range rules.IptablesLines() {
		fmt.Printf("  %s\n", l)
	}
	fmt.Printf("\nRetrait :\n  %s\n", rules.NftDeleteLine())
	fmt.Printf("\nDans chaque VM qui utilise le cache :\n")
	for _, f := range []string{"pacman", "apt", "dnf", "zypper"} {
		dir, cmd, bundle, _ := GuestTrustCommand(f)
		fmt.Printf("  %-7s %s/erplibre-cache.crt puis %s\n", f, dir, cmd)
		for _, l := range GuestEnvLines(bundle) {
			fmt.Printf("          %s\n", l)
		}
	}
}

func splitList(s string) []string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
