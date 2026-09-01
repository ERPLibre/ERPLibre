package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"io"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// échantillons fabrique un bloc PCM 16 bits à partir de valeurs.
func échantillons(valeurs ...int16) []byte {
	b := make([]byte, len(valeurs)*2)
	for i, v := range valeurs {
		binary.LittleEndian.PutUint16(b[i*2:], uint16(v))
	}
	return b
}

// puits collecte ce qu'on lui écrit et arrête le contexte au bout de n blocs.
type puits struct {
	mutex   sync.Mutex
	reçu    bytes.Buffer
	blocs   int
	limite  int
	arrêter context.CancelFunc
}

func (p *puits) Write(b []byte) (int, error) {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	p.reçu.Write(b)
	p.blocs++
	if p.blocs >= p.limite {
		p.arrêter()
	}
	return len(b), nil
}

func (p *puits) Close() error { return nil }

func (p *puits) octets() []byte {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	return append([]byte(nil), p.reçu.Bytes()...)
}

// sourceSansFin rejoue le même bloc indéfiniment.
type sourceSansFin struct {
	motif []byte
	pos   int
}

func (s *sourceSansFin) Read(b []byte) (int, error) {
	for i := range b {
		b[i] = s.motif[s.pos%len(s.motif)]
		s.pos++
	}
	return len(b), nil
}

func (s *sourceSansFin) Close() error { return nil }

func pomperPourTest(t *testing.T, ouvert bool, gain int, ouvrir ouvreurCapture,
	blocs int, traiter func([]byte) int) *puits {
	t.Helper()
	ctx, arrêter := context.WithTimeout(context.Background(), 5*time.Second)
	defer arrêter()
	p := &puits{limite: blocs, arrêter: arrêter}

	c := NouveauCombiné("carte")
	c.micOuvert.Store(ouvert)
	c.gainMic.Store(int64(gain))
	c.pomper(ctx, p, ouvrir, &c.micOuvert, &c.périphMic, &c.gainMic,
		&c.niveauMic, "essai", traiter, true)
	return p
}

// Micro fermé : AUCUNE capture ne doit être ouverte. Couper en aval
// laisserait le micro allumé pour le système et pour le voyant du portable,
// et « fermé » serait un mensonge.
func TestMicroFerméNOuvreAucuneCapture(t *testing.T) {
	var ouvertures atomic.Int64
	ouvrir := func(ctx context.Context, d string) (io.ReadCloser, func(), error) {
		ouvertures.Add(1)
		return &sourceSansFin{motif: échantillons(9000, -9000)}, func() {}, nil
	}
	p := pomperPourTest(t, false, GainNeutre, ouvrir, 3, nil)

	if n := ouvertures.Load(); n != 0 {
		t.Fatalf("%d capture(s) ouverte(s) alors que le micro est fermé", n)
	}
	reçu := p.octets()
	if len(reçu) == 0 {
		t.Fatal("la carte doit recevoir du silence, pas rien")
	}
	for i, o := range reçu {
		if o != 0 {
			t.Fatalf("octet %d non nul (%d) : le micro fermé laisse passer", i, o)
		}
	}
}

// Micro ouvert : la capture est ouverte et les octets passent.
func TestMicroOuvertCaptureEtTransmet(t *testing.T) {
	motif := échantillons(1000, -1000)
	var ouvertures atomic.Int64
	ouvrir := func(ctx context.Context, d string) (io.ReadCloser, func(), error) {
		ouvertures.Add(1)
		return &sourceSansFin{motif: motif}, func() {}, nil
	}
	p := pomperPourTest(t, true, GainNeutre, ouvrir, 3, nil)

	if ouvertures.Load() != 1 {
		t.Fatalf("une seule ouverture attendue, %d obtenues", ouvertures.Load())
	}
	reçu := p.octets()
	if len(reçu) < TailleBloc {
		t.Fatalf("trop peu d'octets : %d", len(reçu))
	}
	if bytes.Equal(reçu[:TailleBloc], make([]byte, TailleBloc)) {
		t.Fatal("le micro ouvert ne doit pas transmettre du silence")
	}
}

// Une capture qu'on ne peut pas ouvrir se RÉESSAIE, sans s'emballer.
//
// Abandonner laisserait le sens muet pour de bon, alors que la carte du
// modem s'absente quelques instants quand son canal voix se rouvre. Mais
// réessayer sans repos relancerait un processus par tour de boucle : entre
// les deux, un repos.
func TestCaptureImpossibleReessaieSansSEmballer(t *testing.T) {
	var essais atomic.Int64
	ouvrir := func(ctx context.Context, d string) (io.ReadCloser, func(), error) {
		essais.Add(1)
		return nil, nil, io.ErrUnexpectedEOF
	}
	p := pomperPourTest(t, true, GainNeutre, ouvrir, 1<<30, nil)

	n := essais.Load()
	if n < 2 {
		t.Fatalf("%d essai(s) : le sens abandonne au lieu de réessayer", n)
	}
	// Cinq secondes de contexte a un demi-seconde de repos : une dizaine de
	// tentatives au plus, avec de la marge pour l'ordonnancement.
	if n > 15 {
		t.Fatalf("%d essais : la boucle s'emballe", n)
	}
	for _, o := range p.octets() {
		if o != 0 {
			t.Fatal("sans capture, seul du silence doit sortir")
		}
	}
}

// La DESCENTE ne doit jamais changer de source. Sa carte est celle du
// modem : y substituer le périphérique du système ferait écouter le micro
// de la machine à la place de la ligne — un écho, pas une panne, donc bien
// plus difficile à comprendre.
func TestLaDescenteNeSubstituePasSaSource(t *testing.T) {
	ouvrir := func(ctx context.Context, d string) (io.ReadCloser, func(), error) {
		return nil, nil, io.ErrUnexpectedEOF
	}
	ctx, arrêter := context.WithTimeout(context.Background(), 2*time.Second)
	defer arrêter()

	c := NouveauCombiné("carte")
	source := &atomic.Value{}
	source.Store("hw:1,0")
	c.pomper(ctx, &puits{limite: 1 << 30, arrêter: arrêter}, ouvrir,
		&c.hpOuvert, source, &c.gainHP, &c.niveauHP, "descente", nil, false)

	if v, _ := source.Load().(string); v != "hw:1,0" {
		t.Fatalf("source devenue %q : la descente a change de carte", v)
	}
}

func TestTousLesRéglagesModemRétablissentLaVoix(t *testing.T) {
	cas := []struct {
		nom      string
		brancher func(*Combiné, *int)
		poser    func(*Combiné) error
	}{
		{"volume d'écoute",
			func(c *Combiné, n *int) { c.VolumeModem = func(int) error { *n++; return nil } },
			func(c *Combiné) error { return c.PoserVolumeModem(4) }},
		{"suppression de bruit",
			func(c *Combiné, n *int) { c.BruitModem = func(bool) error { *n++; return nil } },
			func(c *Combiné) error { return c.PoserBruitModem(true) }},
		{"gain de montée",
			func(c *Combiné, n *int) { c.GainMicroModem = func(int) error { *n++; return nil } },
			func(c *Combiné) error { return c.PoserGainMicroModem(20480) }},
	}
	for _, k := range cas {
		t.Run(k.nom, func(t *testing.T) {
			c := NouveauCombiné("carte")
			appliqué, rétabli := 0, 0
			k.brancher(c, &appliqué)
			c.RéaffirmerVoix = func() error { rétabli++; return nil }
			if err := k.poser(c); err != nil {
				t.Fatalf("refusé : %v", err)
			}
			if appliqué != 1 {
				t.Fatalf("réglage applique %d fois", appliqué)
			}
			if rétabli != 1 {
				t.Fatal("canal voix non rétabli : le son restera coupé")
			}
		})
	}
}

// Un réglage refusé ne doit pas être retenu comme s'il avait pris.
func TestUnRéglageRefuséNEstPasRetenu(t *testing.T) {
	c := NouveauCombiné("carte")
	c.GainMicroModem = func(int) error { return io.ErrUnexpectedEOF }
	c.RéaffirmerVoix = func() error { return nil }
	if err := c.PoserGainMicroModem(20480); err == nil {
		t.Fatal("l'erreur du modem doit remonter")
	}
	if c.GainMicroModemPosé() != VolumeModemInconnu {
		t.Fatalf("gain retenu (%d) alors qu'il a été refusé",
			c.GainMicroModemPosé())
	}
}

func TestBasculesDuTraitement(t *testing.T) {
	c := NouveauCombiné("carte")
	// Allumés par défaut tous les deux : sans casque, les haut-parleurs
	// repartent dans le micro, et un micro de portable envoie son
	// ventilateur en continu. Le demi-duplex se remarque moins.
	if !c.AntiÉcho() {
		t.Fatal("l'anti-écho doit démarrer allumé")
	}
	if !c.FiltreMicro() {
		t.Fatal("le nettoyage du micro doit démarrer allumé")
	}
	if c.BasculerAntiÉcho() || c.AntiÉcho() {
		t.Fatal("la bascule doit éteindre l'anti-écho")
	}
	if c.BasculerFiltreMicro() || c.FiltreMicro() {
		t.Fatal("la bascule doit éteindre le nettoyage")
	}
}

// sourceMorte s'ouvre puis rend la main aussitôt, comme un périphérique
// que le système ne relâche pas : le processus démarre et meurt à la
// première lecture.
type sourceMorte struct{}

func (sourceMorte) Read([]byte) (int, error) { return 0, io.EOF }
func (sourceMorte) Close() error             { return nil }

// Un périphérique choisi que le système refuse doit ramener à celui du
// système, et non laisser un micro muet.
//
// L'échec n'apparaît PAS à l'ouverture : la commande démarre, puis rend la
// main. Sans garde-fou, la boucle la relance indéfiniment et rien ne dit
// pourquoi plus rien ne passe.
func TestPériphériqueRefuséRamèneAuSystème(t *testing.T) {
	ctx, arrêter := context.WithTimeout(context.Background(), 2*time.Second)
	defer arrêter()

	c := NouveauCombiné("carte")
	c.micOuvert.Store(true)
	c.périphMic.Store("hw:9,9")

	var ouvertures atomic.Int64
	ouvrir := func(context.Context, string) (io.ReadCloser, func(), error) {
		ouvertures.Add(1)
		return sourceMorte{}, func() {}, nil
	}
	c.pomper(ctx, &puits{limite: 1 << 30, arrêter: arrêter}, ouvrir,
		&c.micOuvert, &c.périphMic, &c.gainMic, &c.niveauMic, "essai", nil,
		true)

	if choisi, _ := c.Périphériques(); choisi != "" {
		t.Fatalf("périphérique resté à %q : le micro reste muet", choisi)
	}
	// Et la boucle ne doit pas avoir tourné à vide : un repos sépare les
	// tentatives une fois revenu au périphérique du système.
	if n := ouvertures.Load(); n > 10 {
		t.Fatalf("%d ouvertures en deux secondes : la boucle s'emballe", n)
	}
}

// TOUS les flux doivent borner leur tampon ALSA.
//
// Par defaut, arecord et aplay se donnent un demi-seconde chacun. Il suffit
// qu'UN seul sens l'oublie pour ramener a lui seul le delai qu'on cherche a
// supprimer — d'ou une source unique d'arguments, et ce test qui la garde.
func TestTousLesFluxBornentLeurTampon(t *testing.T) {
	for _, périphérique := range []string{"", "hw:1,0"} {
		args := argsALSA(périphérique)
		joint := strings.Join(args, " ")
		for _, exigé := range []string{
			"--period-size " + PériodeVoix,
			"--buffer-size " + TamponVoix,
			"-r " + TauxVoix,
			"-f " + FormatVoix,
		} {
			if !strings.Contains(joint, exigé) {
				t.Errorf("%q absent de %q", exigé, joint)
			}
		}
		if périphérique != "" && !strings.HasPrefix(joint, "-D "+périphérique) {
			t.Errorf("le peripherique doit venir en tete : %q", joint)
		}
	}
	// Le tampon doit rester un multiple de la periode : ALSA arrondit
	// sinon, et le reglage ne vaut plus ce qu'il annonce.
	p, _ := strconv.Atoi(PériodeVoix)
	b, _ := strconv.Atoi(TamponVoix)
	if p <= 0 || b%p != 0 {
		t.Fatalf("tampon %d n'est pas un multiple de la periode %d", b, p)
	}
	// Et la latence annoncee doit rester sous le dixieme de seconde : au
	// dela, on se coupe la parole.
	if ms := 1000 * b / int(TauxVoixHz); ms > 100 {
		t.Fatalf("tampon de %d ms : trop long pour une conversation", ms)
	}
}

func TestGainAmplifieEtSature(t *testing.T) {
	bloc := échantillons(1000, -1000)
	appliquerGain(bloc, 200)
	if got := int16(binary.LittleEndian.Uint16(bloc[0:])); got != 2000 {
		t.Fatalf("2000 attendu, %d obtenu", got)
	}

	// Un gain qui déborderait l'entier doit saturer, pas s'inverser : un son
	// fort deviendrait sinon un craquement, bien pire qu'une saturation.
	fort := échantillons(30000, -30000)
	appliquerGain(fort, 400)
	if got := int16(binary.LittleEndian.Uint16(fort[0:])); got != 32767 {
		t.Fatalf("saturation haute attendue, %d obtenu", got)
	}
	if got := int16(binary.LittleEndian.Uint16(fort[2:])); got != -32768 {
		t.Fatalf("saturation basse attendue, %d obtenu", got)
	}

	// Gain neutre : aucun échantillon ne bouge.
	intact := échantillons(1234, -4321)
	copie := append([]byte(nil), intact...)
	appliquerGain(intact, GainNeutre)
	if !bytes.Equal(intact, copie) {
		t.Fatal("le gain neutre ne doit rien changer")
	}
}

func TestBornerGain(t *testing.T) {
	for _, c := range []struct{ donné, veut int }{
		{-50, 0}, {0, 0}, {100, 100}, {GainMax, GainMax}, {GainMax + 1, GainMax},
	} {
		if got := bornerGain(c.donné); got != c.veut {
			t.Errorf("bornerGain(%d) = %d, attendu %d", c.donné, got, c.veut)
		}
	}
}

func TestValeurEfficace(t *testing.T) {
	if got := valeurEfficace(échantillons(0, 0, 0, 0)); got != 0 {
		t.Fatalf("silence : 0 attendu, %d obtenu", got)
	}
	// Quatre échantillons de même amplitude : la valeur efficace vaut
	// l'amplitude, au signe près.
	if got := valeurEfficace(échantillons(1000, -1000, 1000, -1000)); got != 1000 {
		t.Fatalf("1000 attendu, %d obtenu", got)
	}
	if got := valeurEfficace(nil); got != 0 {
		t.Fatalf("bloc vide : 0 attendu, %d obtenu", got)
	}
}

func TestBasculesEtRéglages(t *testing.T) {
	c := NouveauCombiné("carte")
	if c.MicOuvert() {
		t.Fatal("le micro doit démarrer fermé")
	}
	if !c.HPOuvert() {
		t.Fatal("l'écoute doit démarrer ouverte : couper le micro ne rend pas sourd")
	}
	if !c.BasculerMic() || !c.MicOuvert() {
		t.Fatal("la bascule doit ouvrir un micro fermé")
	}
	if c.BasculerMic() || c.MicOuvert() {
		t.Fatal("la bascule doit refermer un micro ouvert")
	}
	if c.BasculerHP() || c.HPOuvert() {
		t.Fatal("la bascule doit fermer une écoute ouverte")
	}
	if got := c.RéglerGainMic(250); got != 250 {
		t.Fatalf("gain 250 attendu, %d", got)
	}
	if got := c.RéglerGainHP(9999); got != GainMax {
		t.Fatalf("gain borné à %d attendu, %d", GainMax, got)
	}
	c.ChoisirMicro("hw:2,0")
	c.ChoisirSortie("hw:3,0")
	if m, h := c.Périphériques(); m != "hw:2,0" || h != "hw:3,0" {
		t.Fatalf("périphériques mal retenus : %q %q", m, h)
	}
}

func TestBarreDeNiveau(t *testing.T) {
	cas := []struct {
		niveau int
		veut   string
	}{
		{0, "[..........]"},
		{ÉchelleNiveau / 2, "[#####.....]"},
		{ÉchelleNiveau, "[##########]"},
		// Au-delà de l'échelle la barre sature au lieu de déborder.
		{ÉchelleNiveau * 9, "[##########]"},
		{-5, "[..........]"},
	}
	for _, c := range cas {
		if got := barre(c.niveau); got != c.veut {
			t.Errorf("barre(%d) = %q, attendu %q", c.niveau, got, c.veut)
		}
	}
}

// Le tuyau du système retient soixante-cinq mille octets par défaut, soit
// QUATRE SECONDES de voix. Ce n'est pas un tampon mais un retard : une fois
// rempli il ne se vide plus, et aucun réglage d'ALSA ne le rattrape,
// puisqu'il est en amont.
func TestLesTuyauxSontBornés(t *testing.T) {
	lecture, écriture, err := os.Pipe()
	if err != nil {
		t.Skip("pas de tuyau disponible")
	}
	defer lecture.Close()
	defer écriture.Close()

	avant, err := unix.FcntlInt(écriture.Fd(), unix.F_GETPIPE_SZ, 0)
	if err != nil {
		t.Skip("taille de tuyau non lisible sur ce système")
	}
	bornerTuyau(écriture)
	après, err := unix.FcntlInt(écriture.Fd(), unix.F_GETPIPE_SZ, 0)
	if err != nil {
		t.Fatalf("relecture impossible : %v", err)
	}
	if après != TailleTuyau {
		t.Fatalf("tuyau de %d octets, %d attendus (avant : %d)",
			après, TailleTuyau, avant)
	}
	// Et la borne doit valoir moins d'une demi-seconde de voix, sans quoi
	// elle ne sert à rien.
	if ms := 1000 * après / (int(TauxVoixHz) * 2); ms > 500 {
		t.Fatalf("%d ms de retard possible : la borne est trop large", ms)
	}
	t.Logf("  tuyau : %d -> %d octets (%d ms de voix)", avant, après,
		1000*après/(int(TauxVoixHz)*2))
}

// La borne doit etre posee sur les tuyaux REELS, pas seulement disponible.
// L'oublier sur un seul sens y laisse quatre secondes de retard.
func TestLesFluxPosentLaBorne(t *testing.T) {
	ctx, arrêter := context.WithCancel(context.Background())
	defer arrêter()

	c := NouveauCombiné("null")
	_, entrée, err := c.démarrerLecture(ctx, "null", "essai")
	if err != nil {
		t.Skip("aplay indisponible")
	}
	f, ok := entrée.(*os.File)
	if !ok {
		t.Fatal("le bout d'ecriture devrait etre un fichier")
	}
	taille, err := unix.FcntlInt(f.Fd(), unix.F_GETPIPE_SZ, 0)
	if err != nil {
		t.Skip("taille de tuyau non lisible")
	}
	if taille != TailleTuyau {
		t.Fatalf("lecture : tuyau de %d octets, %d attendus", taille,
			TailleTuyau)
	}

	source, arrêt, err := captureALSA(ctx, "null")
	if err != nil {
		t.Skip("arecord indisponible")
	}
	defer arrêt()
	g, ok := source.(*os.File)
	if !ok {
		t.Fatal("le bout de lecture devrait etre un fichier")
	}
	if taille, err := unix.FcntlInt(g.Fd(), unix.F_GETPIPE_SZ, 0); err == nil {
		if taille != TailleTuyau {
			t.Fatalf("capture : tuyau de %d octets, %d attendus", taille,
				TailleTuyau)
		}
	}
}
